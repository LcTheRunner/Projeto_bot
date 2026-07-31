package br.com.mediamonitor.dashboard;

import jakarta.annotation.PostConstruct;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.MailException;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.Base64;
import java.util.List;
import java.util.Map;

@Service
public class AuthService {
    public record User(long id, String username, String displayName, String email, boolean admin,
                       boolean externalEmailAllowed) {
        public User(long id, String username, String displayName, String email, boolean admin) {
            this(id, username, displayName, email, admin, false);
        }
    }
    private static final Logger LOGGER = LoggerFactory.getLogger(AuthService.class);
    private static final List<String> DEFAULT_KEYWORDS = List.of(
            "Instituto Carioca", "esporte e lazer", "corrupção", "emenda parlamentar",
            "emendas parlamentares", "político corrupto", "políticos corruptos",
            "empresa que investe em ONG", "empresas que investem em ONG",
            "empresa que investe no meio ambiente", "empresas que investem no meio ambiente",
            "empresa que investe em esporte", "empresas que investem em esporte",
            "Lei Rouanet", "Lei Rounet", "lei de incentivo ao esporte", "Prefeitura de Maricá",
            "Movimento Cultural Social"
    );

    private final JdbcTemplate jdbc;
    private final JavaMailSender mailSender;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(12);
    private final SecureRandom random = new SecureRandom();

    @Value("${dashboard.admin-user:equipe}") private String adminUser;
    @Value("${dashboard.admin-password:}") private String adminPassword;
    @Value("${dashboard.owner-username:}") private String ownerUsername;
    @Value("${dashboard.owner-email:}") private String ownerEmail;
    @Value("${dashboard.additional-admin-usernames:}") private String additionalAdminUsernames;
    @Value("${dashboard.session-days:7}") private int sessionDays;
    @Value("${dashboard.public-url:http://localhost:4200}") private String publicUrl;
    @Value("${dashboard.mail-from:}") private String mailFrom;
    @Value("${spring.mail.host:}") private String mailHost;

    public AuthService(JdbcTemplate jdbc, JavaMailSender mailSender) {
        this.jdbc = jdbc;
        this.mailSender = mailSender;
    }

    @PostConstruct
    void initialize() {
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_users (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  username VARCHAR(100) NOT NULL UNIQUE,
                  display_name VARCHAR(150) NOT NULL,
                  email VARCHAR(254) NULL UNIQUE,
                  password_hash VARCHAR(100) NOT NULL,
                  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                  can_send_external_email BOOLEAN NOT NULL DEFAULT FALSE,
                  active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """);
        addColumnIfMissing("dashboard_users", "email",
                "ALTER TABLE dashboard_users ADD COLUMN email VARCHAR(254) NULL UNIQUE AFTER display_name");
        addColumnIfMissing("dashboard_users", "email_verified",
                "ALTER TABLE dashboard_users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE AFTER email");
        addColumnIfMissing("dashboard_users", "can_send_external_email",
                "ALTER TABLE dashboard_users ADD COLUMN can_send_external_email BOOLEAN NOT NULL DEFAULT FALSE AFTER is_admin");
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_sessions (
                  token_hash CHAR(64) PRIMARY KEY,
                  user_id BIGINT NOT NULL,
                  expires_at DATETIME NOT NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS user_keywords (
                  id BIGINT PRIMARY KEY AUTO_INCREMENT,
                  user_id BIGINT NOT NULL,
                  keyword VARCHAR(255) NOT NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_keyword_user FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE,
                  UNIQUE KEY uq_user_keyword (user_id, keyword)
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                  token_hash CHAR(64) PRIMARY KEY,
                  user_id BIGINT NOT NULL,
                  expires_at DATETIME NOT NULL,
                  used_at DATETIME NULL,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_reset_user FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_codes (
                  user_id BIGINT PRIMARY KEY,
                  code_hash CHAR(64) NOT NULL,
                  expires_at DATETIME NOT NULL,
                  attempts INT NOT NULL DEFAULT 0,
                  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  CONSTRAINT fk_verification_user FOREIGN KEY (user_id) REFERENCES dashboard_users(id) ON DELETE CASCADE
                )
                """);
        jdbc.execute("""
                CREATE TABLE IF NOT EXISTS system_migrations (
                  migration_key VARCHAR(100) PRIMARY KEY,
                  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """);
        Integer users = jdbc.queryForObject("SELECT COUNT(*) FROM dashboard_users", Integer.class);
        if (users != null && users == 0 && adminPassword != null && !adminPassword.isBlank()) {
            jdbc.update("""
                    INSERT INTO dashboard_users(username, display_name, password_hash, is_admin)
                    VALUES (?, ?, ?, TRUE)
                    """, cleanUsername(adminUser), "Administrador MCS", encoder.encode(adminPassword));
            Long userId = jdbc.queryForObject("SELECT id FROM dashboard_users WHERE username = ?", Long.class, cleanUsername(adminUser));
            seedKeywords(userId);
        }
        jdbc.update("DELETE FROM dashboard_sessions WHERE expires_at < NOW()");
        jdbc.update("DELETE FROM password_reset_tokens WHERE expires_at < NOW() OR used_at IS NOT NULL");
        Integer defaultsApplied = jdbc.queryForObject(
                "SELECT COUNT(*) FROM system_migrations WHERE migration_key = 'default_keywords_v2'", Integer.class);
        if (defaultsApplied != null && defaultsApplied == 0) {
            jdbc.queryForList("SELECT id FROM dashboard_users", Long.class).forEach(this::seedKeywords);
            jdbc.update("INSERT INTO system_migrations(migration_key) VALUES ('default_keywords_v2')");
        }
        Integer alertKeywordsApplied = jdbc.queryForObject(
                "SELECT COUNT(*) FROM system_migrations WHERE migration_key = 'institutional_alert_keywords_v2'", Integer.class);
        if (alertKeywordsApplied != null && alertKeywordsApplied == 0) {
            jdbc.update("DELETE FROM user_keywords WHERE LOWER(TRIM(keyword)) = 'mcs'");
            jdbc.update("""
                    INSERT IGNORE INTO user_keywords(user_id, keyword)
                    SELECT id, 'Instituto Carioca' FROM dashboard_users
                    """);
            jdbc.update("INSERT IGNORE INTO system_migrations(migration_key) VALUES ('institutional_alert_keywords_v2')");
        }
        enforceConfiguredOwnerExclusivity();
    }

    public String login(String username, String password) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT id, password_hash, email_verified FROM dashboard_users
                WHERE username = ? AND active = TRUE
                """, cleanUsername(username));
        if (rows.isEmpty() || !encoder.matches(password == null ? "" : password, (String) rows.getFirst().get("password_hash"))) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Usuário ou senha inválidos");
        }
        if (!Boolean.TRUE.equals(rows.getFirst().get("email_verified"))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Confirme o código enviado ao seu e-mail antes de entrar");
        }
        long userId = ((Number) rows.getFirst().get("id")).longValue();
        String token = randomToken();
        jdbc.update("INSERT INTO dashboard_sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                hash(token), userId, Timestamp.valueOf(LocalDateTime.now().plusDays(sessionDays)));
        return token;
    }

    public User requireUser(HttpServletRequest request) {
        String token = cookie(request, "mcs_session");
        if (token == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Autenticação necessária");
        List<User> rows = jdbc.query("""
                SELECT u.id, u.username, u.display_name, u.email, u.is_admin, u.can_send_external_email
                FROM dashboard_sessions s JOIN dashboard_users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > NOW() AND u.active = TRUE
                """, (rs, i) -> new User(
                        rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4),
                        rs.getBoolean(5), rs.getBoolean(6)
                ), hash(token));
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Sessão expirada");
        return rows.getFirst();
    }

    public void logout(HttpServletRequest request) {
        String token = cookie(request, "mcs_session");
        if (token != null) jdbc.update("DELETE FROM dashboard_sessions WHERE token_hash = ?", hash(token));
    }

    public List<Map<String, Object>> users(User actor) {
        requireAdmin(actor);
        List<Map<String, Object>> users = jdbc.queryForList("""
                SELECT id, username, display_name AS displayName, email,
                       email_verified AS emailVerified, is_admin AS admin,
                       can_send_external_email AS externalEmailAllowed,
                       active, created_at AS createdAt
                FROM dashboard_users ORDER BY created_at DESC
                """);
        users.forEach(user -> user.put(
                "ownerCandidate",
                isConfiguredOwner((String) user.get("username"), (String) user.get("email"))
        ));
        return users;
    }

    @Transactional
    public long createUser(User actor, String username, String displayName, String email, String password, boolean admin) {
        requireCurrentAdminForUpdate(actor);
        if (admin) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Novas contas são criadas como usuário comum. Use a transferência protegida para alterar o administrador"
            );
        }
        return createUserInternal(username, displayName, email, password, false);
    }

    @Transactional
    public void transferOwnership(User actor, long targetId) {
        requireCurrentAdminForUpdate(actor);
        List<Map<String, Object>> targetRows = jdbc.queryForList("""
                SELECT id, username, email, active, email_verified
                FROM dashboard_users WHERE id = ? FOR UPDATE
                """, targetId);
        if (targetRows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Conta não encontrada");
        }
        Map<String, Object> target = targetRows.getFirst();
        if (!isConfiguredOwner((String) target.get("username"), (String) target.get("email"))) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "A administração só pode ser transferida para a conta e o e-mail configurados como proprietários"
            );
        }
        if (!Boolean.TRUE.equals(target.get("active")) || !Boolean.TRUE.equals(target.get("email_verified"))) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "A conta proprietária precisa estar ativa e com o e-mail confirmado"
            );
        }
        jdbc.queryForList("""
                SELECT id FROM dashboard_users
                WHERE is_admin = TRUE AND active = TRUE FOR UPDATE
                """, Long.class);
        jdbc.update("""
                UPDATE dashboard_users
                SET is_admin = CASE WHEN id = ? THEN TRUE ELSE FALSE END
                """, targetId);
    }

    @Transactional
    public void updateExternalEmailPermission(User actor, long targetId, boolean enabled) {
        requireCurrentAdminForUpdate(actor);
        if (!isConfiguredOwner(actor.username(), actor.email())) {
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN,
                    "Somente a conta proprietária pode alterar destinos externos"
            );
        }
        int changed = jdbc.update("""
                UPDATE dashboard_users
                SET can_send_external_email = ?
                WHERE id = ? AND active = TRUE
                """, enabled, targetId);
        Integer existing = changed == 0
                ? jdbc.queryForObject(
                        "SELECT COUNT(*) FROM dashboard_users WHERE id = ? AND active = TRUE",
                        Integer.class,
                        targetId
                )
                : 1;
        if (existing == null || existing == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Conta não encontrada ou inativa");
        }
        if (!enabled) {
            jdbc.update("""
                    UPDATE email_schedules
                    SET status = 'FAILED',
                        last_error = 'Permissão para destino externo revogada'
                    WHERE user_id = ?
                      AND recipient_email IS NOT NULL
                      AND status IN ('PENDING', 'PREPARING')
                    """, targetId);
        }
    }

    @Transactional
    public void deleteUser(User actor, long targetId) {
        requireCurrentAdminForUpdate(actor);
        List<Map<String, Object>> targetRows = jdbc.queryForList("""
                SELECT id, username, is_admin, active
                FROM dashboard_users WHERE id = ? FOR UPDATE
                """, targetId);
        if (targetRows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Conta não encontrada");
        }
        if (actor.id() == targetId) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Você não pode excluir a própria conta");
        }
        Map<String, Object> target = targetRows.getFirst();
        if (Boolean.TRUE.equals(target.get("is_admin")) && Boolean.TRUE.equals(target.get("active"))) {
            List<Long> activeAdmins = jdbc.queryForList("""
                    SELECT id FROM dashboard_users
                    WHERE is_admin = TRUE AND active = TRUE FOR UPDATE
                    """, Long.class);
            if (activeAdmins.size() <= 1) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "O último administrador não pode ser excluído");
            }
        }
        List<String> scheduleStates = jdbc.queryForList("""
                SELECT status FROM email_schedules
                WHERE user_id = ? FOR UPDATE
                """, String.class, targetId);
        if (scheduleStates.stream().anyMatch("PREPARING"::equals)) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "Aguarde o envio de e-mail em preparação antes de excluir esta conta"
            );
        }
        jdbc.update("DELETE FROM dashboard_users WHERE id = ?", targetId);
    }

    public long register(String username, String displayName, String email, String password) {
        long userId = createUserInternal(username, username, email, password, false, false);
        sendVerificationCode(userId);
        return userId;
    }

    private long createUserInternal(String username, String displayName, String email, String password, boolean admin) {
        return createUserInternal(username, displayName, email, password, admin, true);
    }

    private long createUserInternal(String username, String displayName, String email, String password, boolean admin, boolean verified) {
        String cleanUser = cleanUsername(username);
        String cleanEmail = cleanEmail(email);
        if (!cleanUser.matches("[a-z0-9._-]{3,50}") || !cleanEmail.matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")
                || password == null || password.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Preencha um usuário válido, um e-mail válido e uma senha");
        }
        try {
            jdbc.update("""
                    INSERT INTO dashboard_users(username, display_name, email, email_verified, password_hash, is_admin)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """, cleanUser, cleanUser, cleanEmail, verified, encoder.encode(password), admin);
        } catch (DuplicateKeyException exception) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Usuário ou e-mail já cadastrado");
        }
        Long userId = jdbc.queryForObject("SELECT id FROM dashboard_users WHERE username = ?", Long.class, cleanUser);
        seedKeywords(userId);
        return userId;
    }

    public void resendVerification(String username) {
        List<Long> users = jdbc.query("""
                SELECT id FROM dashboard_users WHERE username = ? AND active = TRUE AND email_verified = FALSE
                """, (rs, row) -> rs.getLong(1), cleanUsername(username));
        if (!users.isEmpty()) sendVerificationCode(users.getFirst());
    }

    public void verifyEmail(String username, String code) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT v.user_id, v.code_hash, v.attempts
                FROM email_verification_codes v
                JOIN dashboard_users u ON u.id = v.user_id
                WHERE u.username = ? AND v.expires_at > NOW()
                """, cleanUsername(username));
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Código expirado. Solicite um novo código");
        Map<String, Object> row = rows.getFirst();
        long userId = ((Number) row.get("user_id")).longValue();
        if (((Number) row.get("attempts")).intValue() >= 5) {
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "Muitas tentativas. Solicite um novo código");
        }
        if (code == null || !hash(code.trim()).equals(row.get("code_hash"))) {
            jdbc.update("UPDATE email_verification_codes SET attempts = attempts + 1 WHERE user_id = ?", userId);
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Código incorreto");
        }
        jdbc.update("UPDATE dashboard_users SET email_verified = TRUE WHERE id = ?", userId);
        jdbc.update("DELETE FROM email_verification_codes WHERE user_id = ?", userId);
    }

    private void sendVerificationCode(long userId) {
        requireMailConfigured();
        Map<String, Object> user = jdbc.queryForMap("SELECT email FROM dashboard_users WHERE id = ?", userId);
        String code = String.format("%06d", random.nextInt(1_000_000));
        jdbc.update("""
                INSERT INTO email_verification_codes(user_id, code_hash, expires_at, attempts)
                VALUES (?, ?, ?, 0)
                ON DUPLICATE KEY UPDATE code_hash = VALUES(code_hash), expires_at = VALUES(expires_at), attempts = 0
                """, userId, hash(code), Timestamp.valueOf(LocalDateTime.now().plusMinutes(15)));
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(mailFrom);
        message.setTo((String) user.get("email"));
        message.setSubject("Código de validação — Central de Monitoramento do MCS");
        message.setText("""
                Seu código de validação é:

                %s

                O código expira em 15 minutos. Se você não criou esta conta, ignore este e-mail.
                """.formatted(code));
        sendMail(message);
    }

    public void requestPasswordReset(String email) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, email FROM dashboard_users WHERE email = ? AND active = TRUE", cleanEmail(email));
        if (rows.isEmpty()) return;
        requireMailConfigured();
        long userId = ((Number) rows.getFirst().get("id")).longValue();
        String token = randomToken();
        jdbc.update("DELETE FROM password_reset_tokens WHERE user_id = ?", userId);
        jdbc.update("INSERT INTO password_reset_tokens(token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                hash(token), userId, Timestamp.valueOf(LocalDateTime.now().plusMinutes(30)));
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(mailFrom);
        message.setTo((String) rows.getFirst().get("email"));
        message.setSubject("Redefinição de senha — Central de Monitoramento do MCS");
        message.setText("""
                Recebemos uma solicitação para redefinir sua senha.

                Acesse o link abaixo em até 30 minutos:
                %s/?reset=%s

                Se você não solicitou esta alteração, ignore este e-mail.
                """.formatted(publicUrl.replaceAll("/+$", ""), URLEncoder.encode(token, StandardCharsets.UTF_8)));
        sendMail(message);
    }

    public void resetPassword(String token, String password) {
        if (token == null || token.isBlank() || password == null || password.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Link ou senha inválidos");
        }
        List<Long> users = jdbc.query("""
                SELECT user_id FROM password_reset_tokens
                WHERE token_hash = ? AND expires_at > NOW() AND used_at IS NULL
                """, (rs, row) -> rs.getLong(1), hash(token));
        if (users.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Link inválido ou expirado");
        long userId = users.getFirst();
        jdbc.update("UPDATE dashboard_users SET password_hash = ? WHERE id = ?", encoder.encode(password), userId);
        jdbc.update("UPDATE password_reset_tokens SET used_at = NOW() WHERE token_hash = ?", hash(token));
        jdbc.update("DELETE FROM dashboard_sessions WHERE user_id = ?", userId);
    }

    private void requireAdmin(User user) {
        if (!user.admin()) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Acesso administrativo necessário");
    }

    private void requireCurrentAdminForUpdate(User user) {
        List<Long> currentAdmins = jdbc.queryForList("""
                SELECT id FROM dashboard_users
                WHERE id = ? AND active = TRUE AND is_admin = TRUE
                FOR UPDATE
                """, Long.class, user.id());
        if (currentAdmins.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Acesso administrativo necessário");
        }
    }

    private void requireMailConfigured() {
        if (mailHost == null || mailHost.isBlank() || mailFrom == null || mailFrom.isBlank()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "O envio de e-mail ainda não está configurado");
        }
    }

    private void sendMail(SimpleMailMessage message) {
        try {
            mailSender.send(message);
        } catch (MailException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Não conseguimos enviar o e-mail agora. Tente novamente");
        }
    }

    private void seedKeywords(Long userId) {
        if (userId == null) return;
        DEFAULT_KEYWORDS.forEach(keyword ->
                jdbc.update("INSERT IGNORE INTO user_keywords(user_id, keyword) VALUES (?, ?)", userId, keyword));
    }

    void enforceConfiguredOwnerExclusivity() {
        String configuredOwner = cleanUsername(ownerUsername);
        String configuredOwnerEmail = cleanEmail(ownerEmail);
        if (!isValidOwnerConfiguration(configuredOwner, configuredOwnerEmail)) {
            LOGGER.warn("Proprietário do dashboard não configurado; os papéis administrativos foram mantidos");
            return;
        }
        List<String> additionalAdmins = configuredAdditionalAdmins(configuredOwner);
        String configuredAdditionalAdmins = String.join(",", additionalAdmins);
        jdbc.update("""
                UPDATE dashboard_users candidate
                JOIN dashboard_users owner
                  ON owner.username = ?
                 AND owner.email = ?
                 AND owner.active = TRUE
                 AND owner.email_verified = TRUE
                SET candidate.is_admin = CASE
                  WHEN candidate.id = owner.id THEN TRUE
                  WHEN candidate.active = TRUE AND candidate.email_verified = TRUE
                       AND FIND_IN_SET(candidate.username, ?) > 0 THEN TRUE
                  ELSE FALSE
                END
                WHERE candidate.id = owner.id OR candidate.is_admin = TRUE
                   OR FIND_IN_SET(candidate.username, ?) > 0
                """, configuredOwner, configuredOwnerEmail,
                configuredAdditionalAdmins, configuredAdditionalAdmins);
        List<Map<String, Object>> state = jdbc.queryForList("""
                SELECT
                  SUM(active = TRUE AND email_verified = TRUE AND is_admin = TRUE
                      AND ((username = ? AND email = ?) OR FIND_IN_SET(username, ?) > 0)) AS configured_admins,
                  SUM(active = TRUE AND is_admin = TRUE) AS active_admins
                FROM dashboard_users
                """, configuredOwner, configuredOwnerEmail, configuredAdditionalAdmins);
        int expectedAdmins = 1 + additionalAdmins.size();
        if (!state.isEmpty()
                && number(state.getFirst().get("configured_admins")) == expectedAdmins
                && number(state.getFirst().get("active_admins")) == expectedAdmins) {
            LOGGER.info("Proprietário '{}' e {} administrador(es) adicional(is) confirmados",
                    configuredOwner, additionalAdmins.size());
        } else {
            LOGGER.warn(
                    "Não foi possível confirmar todos os administradores configurados para o proprietário '{}'",
                    configuredOwner
            );
        }
    }

    private List<String> configuredAdditionalAdmins(String configuredOwner) {
        return Arrays.stream(additionalAdminUsernames == null ? new String[0] : additionalAdminUsernames.split(","))
                .map(this::cleanUsername)
                .filter(username -> username.matches("[a-z0-9._-]{3,50}"))
                .filter(username -> !username.equals(configuredOwner))
                .distinct()
                .toList();
    }

    private boolean isConfiguredOwner(String username, String email) {
        String configuredOwner = cleanUsername(ownerUsername);
        String configuredOwnerEmail = cleanEmail(ownerEmail);
        return isValidOwnerConfiguration(configuredOwner, configuredOwnerEmail)
                && configuredOwner.equals(cleanUsername(username))
                && configuredOwnerEmail.equals(cleanEmail(email));
    }

    public boolean isOwner(User user) {
        return user != null && isConfiguredOwner(user.username(), user.email());
    }

    private boolean isValidOwnerConfiguration(String username, String email) {
        return username.matches("[a-z0-9._-]{3,50}")
                && email.matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    }

    private int number(Object value) {
        return value instanceof Number number ? number.intValue() : 0;
    }

    private void addColumnIfMissing(String table, String column, String ddl) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = ?
                """, Integer.class, table, column);
        if (count != null && count == 0) jdbc.execute(ddl);
    }

    private String cleanUsername(String value) { return value == null ? "" : value.trim().toLowerCase(); }
    private String cleanEmail(String value) { return value == null ? "" : value.trim().toLowerCase(); }

    private String randomToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String hash(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }

    private String cookie(HttpServletRequest request, String name) {
        if (request.getCookies() == null) return null;
        for (Cookie cookie : request.getCookies()) if (name.equals(cookie.getName())) return cookie.getValue();
        return null;
    }
}
