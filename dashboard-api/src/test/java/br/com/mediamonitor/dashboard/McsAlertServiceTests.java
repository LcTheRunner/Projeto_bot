package br.com.mediamonitor.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class McsAlertServiceTests {
    private JdbcTemplate jdbc;
    private McsAlertService service;

    @BeforeEach
    void setUp() {
        jdbc = org.mockito.Mockito.mock(JdbcTemplate.class);
        service = new McsAlertService(jdbc, new ObjectMapper());
    }

    @Test
    void marksAnAlertOnlyForTheAuthenticatedUser() {
        when(jdbc.update(
                contains("SELECT ?, a.id, NOW()"),
                eq(7L),
                eq(81L)
        )).thenReturn(1);
        when(jdbc.queryForObject(
                contains("WHERE r.alert_id IS NULL"),
                eq(Integer.class),
                eq(7L)
        )).thenReturn(0);

        assertThat(service.markRead(7L, 81L)).isZero();

        verify(jdbc).update(
                contains("SELECT ?, a.id, NOW()"),
                eq(7L),
                eq(81L)
        );
    }

    @Test
    void rejectsAnUnknownAlertWithoutCreatingAReadReceipt() {
        when(jdbc.update(
                contains("SELECT ?, a.id, NOW()"),
                eq(7L),
                eq(404L)
        )).thenReturn(0);
        when(jdbc.queryForObject(
                contains("FROM mcs_alerts WHERE id = ?"),
                eq(Integer.class),
                eq(404L)
        )).thenReturn(0);

        assertThatThrownBy(() -> service.markRead(7L, 404L))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(error ->
                        assertThat(((ResponseStatusException) error).getStatusCode().value()).isEqualTo(404)
                );
        verify(jdbc).update(
                contains("SELECT ?, a.id, NOW()"),
                eq(7L),
                eq(404L)
        );
    }

    @Test
    void markingAnAlreadyReadAlertRemainsIdempotent() {
        when(jdbc.update(
                contains("SELECT ?, a.id, NOW()"),
                eq(7L),
                eq(81L)
        )).thenReturn(0);
        when(jdbc.queryForObject(
                contains("FROM mcs_alerts WHERE id = ?"),
                eq(Integer.class),
                eq(81L)
        )).thenReturn(1);
        when(jdbc.queryForObject(
                contains("WHERE r.alert_id IS NULL"),
                eq(Integer.class),
                eq(7L)
        )).thenReturn(0);

        assertThat(service.markRead(7L, 81L)).isZero();
    }

    @Test
    void markAllUsesTheCurrentUserAndLeavesConcurrentFutureAlertsUnread() {
        when(jdbc.queryForObject(
                contains("WHERE r.alert_id IS NULL"),
                eq(Integer.class),
                eq(9L)
        )).thenReturn(2);

        assertThat(service.markAllRead(9L)).isEqualTo(2);

        verify(jdbc).update(
                contains("JOIN dashboard_users u ON u.id = ?"),
                eq(9L),
                eq(9L)
        );
    }
}
