package br.com.mediamonitor.dashboard;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.text.Normalizer;
import java.util.*;

@RestController
@RequestMapping("/api/dashboard/keywords")
public class KeywordController {
    private final JdbcTemplate jdbc;
    private final AuthService auth;

    public KeywordController(JdbcTemplate jdbc, AuthService auth) {
        this.jdbc = jdbc;
        this.auth = auth;
    }

    public record KeywordRequest(String keyword) {}
    public record BatchRequest(String text, List<Long> ids) {}
    private record ParsedKeywords(List<String> terms, int received) {}

    @GetMapping
    public List<Map<String, Object>> list(HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        return jdbc.queryForList("SELECT id, keyword FROM user_keywords WHERE user_id = ? ORDER BY keyword", userId);
    }

    @PostMapping
    public Map<String, Object> add(@RequestBody KeywordRequest body, HttpServletRequest request) {
        List<String> terms = parse(body.keyword()).terms();
        if (terms.size() != 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Digite uma palavra-chave ou use a inclusão em lote");
        }
        long userId = auth.requireUser(request).id();
        insert(userId, terms);
        return jdbc.queryForMap("SELECT id, keyword FROM user_keywords WHERE user_id = ? AND keyword = ?", userId, terms.getFirst());
    }

    @PostMapping("/batch")
    public Map<String, Object> addBatch(@RequestBody BatchRequest body, HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        ParsedKeywords parsed = parse(body.text());
        List<String> terms = parsed.terms();
        if (terms.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Nenhuma palavra-chave válida foi encontrada");
        int before = jdbc.queryForObject("SELECT COUNT(*) FROM user_keywords WHERE user_id = ?", Integer.class, userId);
        insert(userId, terms);
        int after = jdbc.queryForObject("SELECT COUNT(*) FROM user_keywords WHERE user_id = ?", Integer.class, userId);
        return Map.of("received", parsed.received(), "added", after - before, "ignored", parsed.received() - (after - before));
    }

    @DeleteMapping("/{id}")
    public Map<String, Boolean> delete(@PathVariable long id, HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        int changed = jdbc.update("DELETE FROM user_keywords WHERE id = ? AND user_id = ?", id, userId);
        if (changed == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Palavra-chave não encontrada");
        return Map.of("deleted", true);
    }

    @PostMapping("/delete-batch")
    public Map<String, Integer> deleteBatch(@RequestBody BatchRequest body, HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        List<Long> ids = body.ids() == null ? List.of() : body.ids().stream().filter(Objects::nonNull).distinct().limit(500).toList();
        if (ids.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Selecione ao menos uma palavra-chave");
        String placeholders = String.join(",", Collections.nCopies(ids.size(), "?"));
        List<Object> args = new ArrayList<>();
        args.add(userId);
        args.addAll(ids);
        int removed = jdbc.update("DELETE FROM user_keywords WHERE user_id = ? AND id IN (" + placeholders + ")", args.toArray());
        return Map.of("removed", removed);
    }

    private void insert(long userId, List<String> terms) {
        terms.forEach(term -> jdbc.update("INSERT IGNORE INTO user_keywords(user_id, keyword) VALUES (?, ?)", userId, term));
    }

    private ParsedKeywords parse(String input) {
        if (input == null || input.isBlank()) return new ParsedKeywords(List.of(), 0);
        Map<String, String> unique = new LinkedHashMap<>();
        int received = 0;
        for (String part : input.split("[\\r\\n,;:.\"'“”‘’]+")) {
            String term = part.replaceAll("\\s+", " ").trim();
            if (term.length() < 2 || term.length() > 255) continue;
            received++;
            String key = Normalizer.normalize(term, Normalizer.Form.NFD)
                    .replaceAll("\\p{M}", "").toLowerCase(Locale.ROOT);
            unique.putIfAbsent(key, term);
        }
        return new ParsedKeywords(new ArrayList<>(unique.values()), received);
    }
}
