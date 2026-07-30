package br.com.mediamonitor.dashboard;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class AuthServiceOwnerBootstrapTests {
    private JdbcTemplate jdbc;
    private AuthService service;

    @BeforeEach
    void setUp() {
        jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        JavaMailSender mailSender = org.mockito.Mockito.mock(JavaMailSender.class);
        service = new AuthService(jdbc, mailSender);
        ReflectionTestUtils.setField(service, "ownerUsername", " Lucas ");
        ReflectionTestUtils.setField(service, "ownerEmail", " LUCAS@example.com ");
    }

    @Test
    void startupPromotesVerifiedMatchingAccountAndDemotesEveryOtherAdminAtomically() {
        when(jdbc.queryForObject(
                contains("information_schema.COLUMNS"),
                eq(Integer.class),
                any(),
                any()
        )).thenReturn(1);
        when(jdbc.queryForObject("SELECT COUNT(*) FROM dashboard_users", Integer.class)).thenReturn(1);
        when(jdbc.queryForObject(
                contains("migration_key = 'default_keywords_v2'"),
                eq(Integer.class)
        )).thenReturn(1);

        service.initialize();

        verify(jdbc).update(
                contains("SET candidate.is_admin = CASE WHEN candidate.id = owner.id THEN TRUE ELSE FALSE END"),
                eq("lucas"),
                eq("lucas@example.com")
        );
    }

    @Test
    void doesNothingWhenOwnerEmailIsNotConfigured() {
        ReflectionTestUtils.setField(service, "ownerEmail", "");

        service.enforceConfiguredOwnerExclusivity();

        verifyNoInteractions(jdbc);
    }

    @Test
    void doesNothingWhenOwnerEmailIsInvalid() {
        ReflectionTestUtils.setField(service, "ownerEmail", "email-invalido");

        service.enforceConfiguredOwnerExclusivity();

        verifyNoInteractions(jdbc);
    }

    @Test
    void marksOnlyTheExactUsernameAndEmailAsOwnerCandidate() {
        Map<String, Object> matching = new HashMap<>(Map.of(
                "id", 1L,
                "username", "lucas",
                "email", "lucas@example.com"
        ));
        Map<String, Object> wrongEmail = new HashMap<>(Map.of(
                "id", 2L,
                "username", "lucas",
                "email", "outra@example.com"
        ));
        when(jdbc.queryForList(contains("FROM dashboard_users ORDER BY created_at DESC")))
                .thenReturn(List.of(matching, wrongEmail));

        List<Map<String, Object>> users = service.users(
                new AuthService.User(99L, "admin", "Admin", "admin@example.com", true)
        );

        assertThat(users.get(0).get("ownerCandidate")).isEqualTo(true);
        assertThat(users.get(1).get("ownerCandidate")).isEqualTo(false);
    }

    @Test
    void revokedAdministratorCannotCreateAccountsWithAStaleSession() {
        AuthService.User revokedAdmin =
                new AuthService.User(99L, "antigo-admin", "Admin", "admin@example.com", true);
        when(jdbc.queryForList(
                contains("id = ? AND active = TRUE AND is_admin = TRUE"),
                eq(Long.class),
                eq(99L)
        )).thenReturn(List.of());

        assertThatThrownBy(() ->
                service.createUser(revokedAdmin, "novo-usuario", "", "novo@example.com", "senha", false)
        ).isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value()).isEqualTo(403));
    }

    @Test
    void ownershipTransferRejectsTheRightUsernameWithTheWrongEmail() {
        AuthService.User currentAdmin =
                new AuthService.User(99L, "admin", "Admin", "admin@example.com", true);
        when(jdbc.queryForList(
                contains("id = ? AND active = TRUE AND is_admin = TRUE"),
                eq(Long.class),
                eq(99L)
        )).thenReturn(List.of(99L));
        when(jdbc.queryForList(
                contains("SELECT id, username, email, active, email_verified"),
                eq(7L)
        )).thenReturn(List.of(Map.of(
                "id", 7L,
                "username", "lucas",
                "email", "outra@example.com",
                "active", true,
                "email_verified", true
        )));

        assertThatThrownBy(() -> service.transferOwnership(currentAdmin, 7L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode().value()).isEqualTo(400));
    }
}
