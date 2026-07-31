package br.com.mediamonitor.dashboard;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PostConstruct;
import org.springframework.context.annotation.DependsOn;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@DependsOn("authService")
public class McsAlertService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public McsAlertService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    @PostConstruct
    void initialize() {
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS mcs_alerts (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  article_id BIGINT NULL,
                  url_hash CHAR(64) NOT NULL UNIQUE,
                  title VARCHAR(1000) NOT NULL,
                  url VARCHAR(1000) NOT NULL,
                  source VARCHAR(255) NOT NULL,
                  published_at DATETIME NULL,
                  detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  matched_terms_json TEXT NOT NULL,
                  match_excerpt VARCHAR(600) NULL,
                  risk_score INT NOT NULL DEFAULT 0,
                  impact_score DOUBLE NOT NULL DEFAULT 0,
                  UNIQUE KEY uq_mcs_alert_article (article_id),
                  INDEX idx_mcs_alert_detected (detected_at, id)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS user_mcs_alert_reads (
                  user_id BIGINT NOT NULL,
                  alert_id BIGINT NOT NULL,
                  read_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (user_id, alert_id),
                  INDEX idx_mcs_alert_read_alert (alert_id),
                  CONSTRAINT fk_mcs_alert_read_user
                    FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE,
                  CONSTRAINT fk_mcs_alert_read_alert
                    FOREIGN KEY (alert_id) REFERENCES mcs_alerts(id) ON DELETE CASCADE
                )
                """);
        Integer detectedDefault = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'mcs_alerts'
                  AND COLUMN_NAME = 'detected_at'
                  AND COLUMN_DEFAULT IS NOT NULL
                """, Integer.class);
        if (detectedDefault == null || detectedDefault == 0) {
            jdbc.execute("""
                    ALTER TABLE mcs_alerts
                    MODIFY detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    """);
        }
        Integer alertForeignKey = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'user_mcs_alert_reads'
                  AND COLUMN_NAME = 'alert_id'
                  AND REFERENCED_TABLE_NAME = 'mcs_alerts'
                """, Integer.class);
        if (alertForeignKey == null || alertForeignKey == 0) {
            jdbc.update("""
                    DELETE r FROM user_mcs_alert_reads r
                    LEFT JOIN mcs_alerts a ON a.id = r.alert_id
                    WHERE a.id IS NULL
                    """);
            jdbc.execute("""
                    ALTER TABLE user_mcs_alert_reads
                    ADD CONSTRAINT fk_mcs_alert_read_alert
                    FOREIGN KEY (alert_id) REFERENCES mcs_alerts(id) ON DELETE CASCADE
                    """);
        }
        jdbc.update("""
                DELETE FROM mcs_alerts
                WHERE detected_at < DATE_SUB(NOW(), INTERVAL 90 DAY)
                """);
    }

    public Map<String, Object> alerts(long userId, int limit, Long beforeId) {
        int boundedLimit = Math.max(1, Math.min(limit, 50));
        String select = """
                SELECT a.id, a.title, a.url, a.source, a.published_at, a.detected_at,
                       a.matched_terms_json, a.match_excerpt, a.risk_score, a.impact_score,
                       r.read_at,
                       (r.read_at IS NOT NULL OR a.detected_at < u.created_at) AS is_read
                FROM mcs_alerts a
                JOIN dashboard_users u ON u.id = ?
                LEFT JOIN user_mcs_alert_reads r
                  ON r.alert_id = a.id AND r.user_id = u.id
                WHERE a.detected_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                """;
        List<Map<String, Object>> items;
        if (beforeId == null) {
            items = jdbc.query(
                    select + " ORDER BY a.id DESC LIMIT ?",
                    (rs, row) -> alertMap(
                            rs.getLong("id"),
                            rs.getString("title"),
                            rs.getString("url"),
                            rs.getString("source"),
                            rs.getTimestamp("published_at"),
                            rs.getTimestamp("detected_at"),
                            rs.getString("matched_terms_json"),
                            rs.getString("match_excerpt"),
                            rs.getInt("risk_score"),
                            rs.getDouble("impact_score"),
                            rs.getBoolean("is_read"),
                            rs.getTimestamp("read_at")
                    ),
                    userId,
                    boundedLimit + 1
            );
        } else {
            items = jdbc.query(
                    select + " AND a.id < ? ORDER BY a.id DESC LIMIT ?",
                    (rs, row) -> alertMap(
                            rs.getLong("id"),
                            rs.getString("title"),
                            rs.getString("url"),
                            rs.getString("source"),
                            rs.getTimestamp("published_at"),
                            rs.getTimestamp("detected_at"),
                            rs.getString("matched_terms_json"),
                            rs.getString("match_excerpt"),
                            rs.getInt("risk_score"),
                            rs.getDouble("impact_score"),
                            rs.getBoolean("is_read"),
                            rs.getTimestamp("read_at")
                    ),
                    userId,
                    beforeId,
                    boundedLimit + 1
            );
        }
        boolean hasMore = items.size() > boundedLimit;
        if (hasMore) {
            items = new ArrayList<>(items.subList(0, boundedLimit));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("items", items);
        result.put("unreadCount", unreadCount(userId));
        result.put(
                "nextCursor",
                hasMore ? ((Number) items.getLast().get("id")).longValue() : null
        );
        return result;
    }

    public int unreadCount(long userId) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*)
                FROM mcs_alerts a
                JOIN dashboard_users u ON u.id = ?
                LEFT JOIN user_mcs_alert_reads r
                  ON r.alert_id = a.id AND r.user_id = u.id
                WHERE r.alert_id IS NULL
                  AND a.detected_at >= u.created_at
                  AND a.detected_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                """, Integer.class, userId);
        return count == null ? 0 : count;
    }

    @Transactional
    public int markRead(long userId, long alertId) {
        int inserted = jdbc.update("""
                INSERT IGNORE INTO user_mcs_alert_reads(user_id, alert_id, read_at)
                SELECT ?, a.id, NOW()
                FROM mcs_alerts a
                WHERE a.id = ?
                  AND a.detected_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                """, userId, alertId);
        if (inserted == 0) {
            Integer exists = jdbc.queryForObject(
                    """
                    SELECT COUNT(*) FROM mcs_alerts WHERE id = ?
                      AND detected_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                    """,
                    Integer.class,
                    alertId
            );
            if (exists == null || exists == 0) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Alerta não encontrado");
            }
        }
        return unreadCount(userId);
    }

    @Transactional
    public int markAllRead(long userId) {
        jdbc.update("""
                INSERT IGNORE INTO user_mcs_alert_reads(user_id, alert_id, read_at)
                SELECT ?, a.id, NOW()
                FROM mcs_alerts a
                JOIN dashboard_users u ON u.id = ?
                WHERE a.detected_at >= u.created_at
                  AND a.detected_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
                """, userId, userId);
        return unreadCount(userId);
    }

    private Map<String, Object> alertMap(
            long id,
            String title,
            String url,
            String source,
            Timestamp publishedAt,
            Timestamp detectedAt,
            String matchedTermsJson,
            String excerpt,
            int risk,
            double impact,
            boolean read,
            Timestamp readAt
    ) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", id);
        result.put("title", title);
        result.put("url", url);
        result.put("source", source);
        result.put("publishedAt", publishedAt == null ? null : publishedAt.toLocalDateTime());
        result.put("detectedAt", detectedAt == null ? null : detectedAt.toLocalDateTime());
        result.put("matchedTerms", matchedTerms(matchedTermsJson));
        result.put("excerpt", excerpt);
        result.put("risk", risk);
        result.put("impact", impact);
        result.put("read", read);
        result.put("readAt", readAt == null ? null : readAt.toLocalDateTime());
        return result;
    }

    private List<String> matchedTerms(String json) {
        try {
            return mapper.readValue(json, new TypeReference<>() {});
        } catch (Exception ignored) {
            return List.of();
        }
    }
}
