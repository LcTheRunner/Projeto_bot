package br.com.mediamonitor.dashboard;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.when;

class AuthServiceKeywordDefaultsTests {
    private static final String INSERT_USER_KEYWORD =
            "INSERT IGNORE INTO user_keywords(user_id, keyword) VALUES (?, ?)";

    private JdbcTemplate jdbc;
    private AuthService service;

    @BeforeEach
    void setUp() {
        jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        service = new AuthService(jdbc, org.mockito.Mockito.mock(JavaMailSender.class));
        ReflectionTestUtils.setField(service, "adminPassword", "");
        ReflectionTestUtils.setField(service, "ownerUsername", "");
        ReflectionTestUtils.setField(service, "ownerEmail", "");
    }

    @Test
    void newAccountsReceiveTheInstitutionalAlertKeywordsWithoutTheMcsAcronym() {
        AuthService.User administrator =
                new AuthService.User(99L, "admin", "Admin", "admin@example.com", true);
        when(jdbc.queryForList(
                contains("id = ? AND active = TRUE AND is_admin = TRUE"),
                eq(Long.class),
                eq(99L)
        )).thenReturn(List.of(99L));
        when(jdbc.queryForObject(
                "SELECT id FROM dashboard_users WHERE username = ?",
                Long.class,
                "nova-conta"
        )).thenReturn(7L);

        long userId = service.createUser(
                administrator,
                "nova-conta",
                "",
                "nova@example.com",
                "123456",
                false
        );

        assertThat(userId).isEqualTo(7L);
        verify(jdbc).update(INSERT_USER_KEYWORD, 7L, "Movimento Cultural Social");
        verify(jdbc).update(INSERT_USER_KEYWORD, 7L, "Instituto Carioca");
        verify(jdbc, never()).update(INSERT_USER_KEYWORD, 7L, "MCS");
    }

    @Test
    void startupRemovesMcsAndKeepsInstitutoCariocaForExistingAccountsOnce() {
        when(jdbc.queryForObject(
                contains("information_schema.COLUMNS"),
                eq(Integer.class),
                any(),
                any()
        )).thenReturn(1);
        when(jdbc.queryForObject("SELECT COUNT(*) FROM dashboard_users", Integer.class)).thenReturn(2);
        when(jdbc.queryForObject(
                contains("migration_key = 'default_keywords_v2'"),
                eq(Integer.class)
        )).thenReturn(1);
        when(jdbc.queryForObject(
                contains("migration_key = 'institutional_alert_keywords_v2'"),
                eq(Integer.class)
        )).thenReturn(0);

        service.initialize();

        verify(jdbc).update("DELETE FROM user_keywords WHERE LOWER(TRIM(keyword)) = 'mcs'");
        verify(jdbc).update(contains("SELECT id, 'Instituto Carioca' FROM dashboard_users"));
        verify(jdbc).update(
                "INSERT IGNORE INTO system_migrations(migration_key) VALUES ('institutional_alert_keywords_v2')"
        );
    }
}
