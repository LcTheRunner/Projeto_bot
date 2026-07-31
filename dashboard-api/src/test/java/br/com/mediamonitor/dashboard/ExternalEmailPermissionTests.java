package br.com.mediamonitor.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.server.ResponseStatusException;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ExternalEmailPermissionTests {
    @Test
    void onlyTheConfiguredOwnerCanGrantThePermission() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        AuthService auth = new AuthService(jdbc, org.mockito.Mockito.mock(JavaMailSender.class));
        ReflectionTestUtils.setField(auth, "ownerUsername", "lucas");
        ReflectionTestUtils.setField(auth, "ownerEmail", "lucas@example.com");
        when(jdbc.queryForList(
                contains("id = ? AND active = TRUE AND is_admin = TRUE"),
                eq(Long.class),
                eq(9L)
        )).thenReturn(List.of(9L));
        when(jdbc.update(contains("SET can_send_external_email = ?"), eq(true), eq(12L))).thenReturn(1);

        auth.updateExternalEmailPermission(
                new AuthService.User(9L, "lucas", "Lucas", "lucas@example.com", true),
                12L,
                true
        );

        verify(jdbc).update(contains("SET can_send_external_email = ?"), eq(true), eq(12L));
    }

    @Test
    void anotherAdministratorCannotGrantTheHiddenPermission() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        AuthService auth = new AuthService(jdbc, org.mockito.Mockito.mock(JavaMailSender.class));
        ReflectionTestUtils.setField(auth, "ownerUsername", "lucas");
        ReflectionTestUtils.setField(auth, "ownerEmail", "lucas@example.com");
        when(jdbc.queryForList(
                contains("id = ? AND active = TRUE AND is_admin = TRUE"),
                eq(Long.class),
                eq(8L)
        )).thenReturn(List.of(8L));

        assertThatThrownBy(() -> auth.updateExternalEmailPermission(
                new AuthService.User(8L, "outro", "Outro", "outro@example.com", true),
                12L,
                true
        )).isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode())
                        .isEqualTo(HttpStatus.FORBIDDEN));

        verify(jdbc, never()).update(contains("SET can_send_external_email = ?"), any(), any());
    }

    @Test
    void scheduleRejectsAnExternalRecipientWithoutCurrentDatabasePermission() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        EmailScheduleService schedules = new EmailScheduleService(jdbc, new ObjectMapper());
        when(jdbc.queryForObject(
                contains("SELECT can_send_external_email"),
                eq(Boolean.class),
                eq(7L)
        )).thenReturn(false);

        assertThatThrownBy(() -> schedules.create(
                new AuthService.User(7L, "pessoa", "Pessoa", "conta@example.com", false),
                LocalDateTime.now().plusHours(1),
                null,
                List.of("corrupção"),
                "destino@example.com"
        )).isInstanceOf(ResponseStatusException.class)
                .satisfies(error -> assertThat(((ResponseStatusException) error).getStatusCode())
                        .isEqualTo(HttpStatus.FORBIDDEN));
    }

    @Test
    void scheduleStoresTheExternalRecipientWhenPermissionIsActive() {
        JdbcTemplate jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        EmailScheduleService schedules = new EmailScheduleService(jdbc, new ObjectMapper());
        when(jdbc.queryForObject(
                contains("SELECT can_send_external_email"),
                eq(Boolean.class),
                eq(7L)
        )).thenReturn(true);
        when(jdbc.queryForObject(
                contains("COUNT(*) FROM email_schedules"),
                eq(Integer.class),
                eq(7L)
        )).thenReturn(0);
        when(jdbc.queryForList(
                "SELECT keyword FROM user_keywords WHERE user_id = ?",
                String.class,
                7L
        )).thenReturn(List.of("corrupção"));
        when(jdbc.queryForObject("SELECT LAST_INSERT_ID()", Long.class)).thenReturn(33L);

        long id = schedules.create(
                new AuthService.User(7L, "pessoa", "Pessoa", "conta@example.com", false, true),
                LocalDateTime.now().plusHours(1),
                null,
                List.of("corrupção"),
                "DESTINO@example.com"
        );

        assertThat(id).isEqualTo(33L);
        verify(jdbc).update(
                contains("INSERT INTO email_schedules"),
                eq(7L), any(Timestamp.class), isNull(), any(String.class), eq("destino@example.com")
        );
    }
}
