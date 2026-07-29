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
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@DependsOn("authService")
public class EmailScheduleService {
    private static final ZoneId LOCAL_TIME_ZONE = ZoneId.of("America/Sao_Paulo");
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public EmailScheduleService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    @PostConstruct
    void initialize() {
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS email_schedules (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  user_id BIGINT NOT NULL,
                  scheduled_at DATETIME NOT NULL,
                  risk_score INT NULL,
                  keywords_json TEXT NOT NULL,
                  status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                  prepared_at DATETIME NULL,
                  sent_at DATETIME NULL,
                  last_error VARCHAR(500) NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_email_schedule_user FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE,
                  INDEX idx_email_schedule_due (status, scheduled_at)
                )
                """);
    }

    public List<Map<String, Object>> list(AuthService.User user) {
        return jdbc.query("""
                SELECT id, scheduled_at, risk_score, keywords_json, status, prepared_at, sent_at, last_error, created_at
                FROM email_schedules WHERE user_id = ? ORDER BY scheduled_at
                """, (rs, row) -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", rs.getLong("id"));
            item.put("scheduledAt", rs.getTimestamp("scheduled_at").toLocalDateTime());
            item.put("risk", rs.getObject("risk_score"));
            item.put("keywords", parseKeywords(rs.getString("keywords_json")));
            item.put("status", rs.getString("status"));
            Timestamp prepared = rs.getTimestamp("prepared_at");
            Timestamp sent = rs.getTimestamp("sent_at");
            item.put("preparedAt", prepared == null ? null : prepared.toLocalDateTime());
            item.put("sentAt", sent == null ? null : sent.toLocalDateTime());
            item.put("lastError", rs.getString("last_error"));
            item.put("createdAt", rs.getTimestamp("created_at").toLocalDateTime());
            return item;
        }, user.id());
    }

    @Transactional
    public long create(AuthService.User user, LocalDateTime scheduledAt, Integer risk, List<String> keywords) {
        if (user.email() == null || user.email().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cadastre um e-mail na conta antes de programar o envio");
        }
        if (scheduledAt == null || !scheduledAt.isAfter(LocalDateTime.now(LOCAL_TIME_ZONE).plusMinutes(2))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Escolha um horário com pelo menos 2 minutos de antecedência");
        }
        if (risk != null && !List.of(0, 5, 10).contains(risk)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Selecione um risco válido");
        }
        Integer pending = jdbc.queryForObject("""
                SELECT COUNT(*) FROM email_schedules
                WHERE user_id = ? AND status IN ('PENDING', 'PREPARING')
                """, Integer.class, user.id());
        if (pending != null && pending >= 2) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Você já possui dois envios programados");
        }
        List<String> available = jdbc.queryForList(
                "SELECT keyword FROM user_keywords WHERE user_id = ?", String.class, user.id());
        List<String> selected = keywords == null || keywords.isEmpty()
                ? available
                : keywords.stream().map(String::trim).filter(term -> available.stream().anyMatch(term::equalsIgnoreCase)).distinct().toList();
        if (selected.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Selecione ao menos uma palavra-chave");
        }
        try {
            jdbc.update("""
                    INSERT INTO email_schedules(user_id, scheduled_at, risk_score, keywords_json)
                    VALUES (?, ?, ?, ?)
                    """, user.id(), Timestamp.valueOf(scheduledAt), risk, mapper.writeValueAsString(selected));
        } catch (Exception exception) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Não foi possível salvar o agendamento");
        }
        return jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class);
    }

    public void cancel(AuthService.User user, long id) {
        int changed = jdbc.update("""
                DELETE FROM email_schedules
                WHERE id = ? AND user_id = ? AND status IN ('PENDING', 'FAILED')
                """, id, user.id());
        if (changed == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Agendamento não encontrado ou já enviado");
    }

    private List<String> parseKeywords(String value) {
        try {
            return mapper.readValue(value, new TypeReference<>() {});
        } catch (Exception ignored) {
            return List.of();
        }
    }
}
