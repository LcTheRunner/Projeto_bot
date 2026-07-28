package br.com.mediamonitor.dashboard;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.ResultSet;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

@Service
public class DashboardService {
    private static final List<String> RJ_LOCATIONS = List.of(
            "rio de janeiro", "estado do rio", "governo do rio", "alerj",
            "angra dos reis", "aperibé", "araruama", "areal", "armação dos búzios", "arraial do cabo",
            "barra do piraí", "barra mansa", "belford roxo", "bom jardim", "bom jesus do itabapoana",
            "cabo frio", "cachoeiras de macacu", "cambuci", "campos dos goytacazes", "cantagalo",
            "carapebus", "cardoso moreira", "carmo", "casimiro de abreu", "comendador levy gasparian",
            "conceição de macabu", "cordeiro", "duas barras", "duque de caxias", "engenheiro paulo de frontin",
            "guapimirim", "iguaba grande", "itaboraí", "itaguaí", "italva", "itaocara", "itaperuna",
            "itatiaia", "japeri", "laje do muriaé", "macaé", "macuco", "magé", "mangaratiba",
            "maricá", "mendes", "mesquita", "miguel pereira", "miracema", "natividade", "nilópolis",
            "niterói", "nova friburgo", "nova iguaçu", "paracambi", "paraíba do sul", "paraty",
            "paty do alferes", "petrópolis", "pinheiral", "piraí", "porciúncula", "porto real",
            "quatis", "queimados", "quissamã", "resende", "rio bonito", "rio claro", "rio das flores",
            "rio das ostras", "santa maria madalena", "santo antônio de pádua", "são fidélis",
            "são francisco de itabapoana", "são gonçalo", "são joão da barra", "são joão de meriti",
            "são josé de ubá", "são josé do vale do rio preto", "são pedro da aldeia", "são sebastião do alto",
            "sapucaia", "saquarema", "seropédica", "silva jardim", "sumidouro", "tanguá",
            "teresópolis", "trajano de moraes", "três rios", "valença", "varre-sai", "vassouras",
            "volta redonda"
    );
    private static final List<String> RJ_MUNICIPALITIES = java.util.stream.Stream.concat(
            java.util.stream.Stream.of("Rio de Janeiro (capital)"),
            RJ_LOCATIONS.subList(4, RJ_LOCATIONS.size()).stream()
    ).toList();
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public DashboardService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public Map<String, Object> filters(long userId) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("sources", jdbc.queryForList("SELECT DISTINCT source FROM articles ORDER BY source", String.class));
        result.put("sections", jdbc.queryForList("SELECT DISTINCT section FROM articles ORDER BY section", String.class));
        result.put("risks", List.of(0, 5, 10));
        result.put("tones", jdbc.queryForList("SELECT DISTINCT tone FROM classifications ORDER BY tone", String.class));
        result.put("keywords", jdbc.queryForList(
                "SELECT keyword FROM user_keywords WHERE user_id = ? ORDER BY keyword", String.class, userId));
        result.put("municipalities", RJ_MUNICIPALITIES.stream().map(this::municipalityLabel).toList());
        return result;
    }

    public Map<String, Object> overview(int days, String keyword, String source, Integer risk, String tone, List<String> locations, boolean includeAll, long userId) {
        LocalDateTime since = LocalDateTime.now().minusDays(days);
        List<ArticleRow> rows = jdbc.query("""
                SELECT a.id, a.title, a.url, a.body, a.source, a.section, a.journalist, a.published_at,
                       c.risk_score, c.tone, c.impact_score, c.matched_keywords, c.evidence
                FROM articles a JOIN classifications c ON c.article_id = a.id
                WHERE a.published_at >= ? ORDER BY a.published_at DESC
                """, (rs, index) -> row(rs), since);

        List<String> userKeywords = jdbc.queryForList(
                "SELECT keyword FROM user_keywords WHERE user_id = ?", String.class, userId);
        rows = rows.stream()
                .filter(row -> userKeywords.stream().anyMatch(term -> contains(row.title + " " + row.body, term)))
                .toList();
        String wantedKeyword = clean(keyword);
        String wantedSource = clean(source);
        String wantedTone = clean(tone);
        rows = rows.stream()
                .filter(r -> wantedKeyword == null || r.keywords.stream().anyMatch(k -> k.equalsIgnoreCase(wantedKeyword)))
                .filter(r -> wantedSource == null || r.source.equalsIgnoreCase(wantedSource))
                .filter(r -> risk == null || r.risk == risk)
                .filter(r -> wantedTone == null || r.tone.equalsIgnoreCase(wantedTone))
                .filter(r -> locations == null || locations.isEmpty() || matchesLocations(r, locations))
                .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        double averageImpact = rows.stream().mapToDouble(r -> r.impact).average().orElse(0);
        result.put("periodDays", days);
        result.put("generatedAt", LocalDateTime.now());
        result.put("kpis", Map.of(
                "articles", rows.size(),
                "sources", rows.stream().map(r -> r.source).distinct().count(),
                "risk10", rows.stream().filter(r -> r.risk == 10).count(),
                "risk5", rows.stream().filter(r -> r.risk == 5).count(),
                "averageImpact", Math.round(averageImpact * 100.0) / 100.0,
                "instagram", rows.stream().filter(r -> r.source.startsWith("Instagram/")).count()
        ));
        result.put("byRisk", count(rows, r -> "Risco " + r.risk));
        result.put("byTone", count(rows, r -> label(r.tone)));
        result.put("bySource", count(rows, r -> r.source));
        result.put("bySection", count(rows, r -> label(r.section)));
        result.put("byKeyword", keywordCount(rows, userKeywords));
        result.put("timeline", timeline(rows, days));
        result.put("articles", (includeAll ? rows.stream() : rows.stream().limit(100)).map(ArticleRow::toMap).toList());
        return result;
    }

    private ArticleRow row(ResultSet rs) throws java.sql.SQLException {
        return new ArticleRow(
                rs.getLong("id"), rs.getString("title"), rs.getString("url"), rs.getString("body"), rs.getString("source"),
                rs.getString("section"), rs.getString("journalist"), rs.getTimestamp("published_at").toLocalDateTime(),
                rs.getInt("risk_score"), rs.getString("tone"), rs.getDouble("impact_score"),
                jsonList(rs.getString("matched_keywords")), jsonList(rs.getString("evidence"))
        );
    }

    private List<String> jsonList(String json) {
        try { return mapper.readValue(json, new TypeReference<>() {}); }
        catch (Exception ignored) { return List.of(); }
    }

    private List<Map<String, Object>> count(List<ArticleRow> rows, java.util.function.Function<ArticleRow, String> key) {
        Map<String, Long> counts = rows.stream().collect(Collectors.groupingBy(key, Collectors.counting()));
        return ranked(counts, 12);
    }

    private List<Map<String, Object>> keywordCount(List<ArticleRow> rows, List<String> userKeywords) {
        Map<String, Long> counts = new LinkedHashMap<>();
        for (String term : userKeywords) {
            long total = rows.stream().filter(row -> contains(row.title + " " + row.body, term)).count();
            if (total > 0) counts.put(term, total);
        }
        return ranked(counts, 20);
    }

    private List<Map<String, Object>> timeline(List<ArticleRow> rows, int days) {
        Map<LocalDate, Long> counts = rows.stream().collect(Collectors.groupingBy(r -> r.publishedAt.toLocalDate(), TreeMap::new, Collectors.counting()));
        LocalDate start = LocalDate.now().minusDays(days - 1L);
        List<Map<String, Object>> result = new ArrayList<>();
        for (int i = 0; i < days; i++) {
            LocalDate day = start.plusDays(i);
            result.add(Map.of("label", day.toString(), "value", counts.getOrDefault(day, 0L)));
        }
        return result;
    }

    private List<Map<String, Object>> ranked(Map<String, Long> values, int limit) {
        return values.entrySet().stream().sorted(Map.Entry.<String, Long>comparingByValue().reversed()).limit(limit)
                .map(e -> Map.<String, Object>of("label", e.getKey(), "value", e.getValue())).toList();
    }

    private String clean(String value) { return value == null || value.isBlank() ? null : value.trim(); }
    private boolean contains(String text, String term) {
        if (text == null || term == null) return false;
        String normalizedText = java.text.Normalizer.normalize(text, java.text.Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").toLowerCase(Locale.ROOT);
        String normalizedTerm = java.text.Normalizer.normalize(term, java.text.Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").toLowerCase(Locale.ROOT);
        return normalizedText.contains(normalizedTerm);
    }
    private boolean isRioDeJaneiro(ArticleRow row) {
        String text = normalize(row.title + " " + row.body + " " + row.source);
        return java.util.regex.Pattern.compile("(^|\\W)rj($|\\W)").matcher(text).find()
                || RJ_LOCATIONS.stream().map(this::normalize).anyMatch(text::contains);
    }
    private boolean matchesMunicipality(ArticleRow row, String municipality) {
        String wanted = municipality == null ? "" : municipality.replace(" (capital)", "");
        return contains(row.title + " " + row.body + " " + row.source, wanted);
    }
    private boolean matchesLocations(ArticleRow row, List<String> locations) {
        if (locations.stream().anyMatch("estado_rj"::equalsIgnoreCase)) return isRioDeJaneiro(row);
        return locations.stream().anyMatch(location -> matchesMunicipality(row, location));
    }
    private String normalize(String value) {
        return java.text.Normalizer.normalize(value == null ? "" : value, java.text.Normalizer.Form.NFD)
                .replaceAll("\\p{M}", "").toLowerCase(Locale.ROOT);
    }
    private String municipalityLabel(String value) {
        if (value.contains("(capital)")) return value;
        Set<String> lowercase = Set.of("da", "das", "de", "do", "dos");
        return Arrays.stream(value.split(" "))
                .map(word -> lowercase.contains(word) ? word
                        : Character.toUpperCase(word.charAt(0)) + word.substring(1))
                .collect(Collectors.joining(" "));
    }
    private String label(String value) {
        if (value == null || value.isBlank()) return "Não identificado";
        String text = value.replace('_', ' ');
        return Character.toUpperCase(text.charAt(0)) + text.substring(1);
    }

    private record ArticleRow(long id, String title, String url, String body, String source, String section, String journalist,
                              LocalDateTime publishedAt, int risk, String tone, double impact,
                              List<String> keywords, List<String> evidence) {
        Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("id", id); map.put("title", title); map.put("url", url); map.put("source", source);
            map.put("section", section); map.put("journalist", journalist); map.put("publishedAt", publishedAt);
            map.put("risk", risk); map.put("tone", tone); map.put("impact", impact);
            map.put("keywords", keywords); map.put("evidence", evidence);
            return map;
        }
    }
}
