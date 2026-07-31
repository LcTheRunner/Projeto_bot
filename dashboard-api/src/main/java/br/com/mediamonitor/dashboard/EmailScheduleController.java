package br.com.mediamonitor.dashboard;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/dashboard/email-schedules")
public class EmailScheduleController {
    private final EmailScheduleService schedules;
    private final AuthService auth;

    public EmailScheduleController(EmailScheduleService schedules, AuthService auth) {
        this.schedules = schedules;
        this.auth = auth;
    }

    public record ScheduleRequest(LocalDateTime scheduledAt, Integer risk, List<String> keywords,
                                  String recipientEmail) {}

    @GetMapping
    public List<Map<String, Object>> list(HttpServletRequest request) {
        return schedules.list(auth.requireUser(request));
    }

    @PostMapping
    public Map<String, Long> create(@RequestBody ScheduleRequest body, HttpServletRequest request) {
        long id = schedules.create(
                auth.requireUser(request), body.scheduledAt(), body.risk(), body.keywords(), body.recipientEmail()
        );
        return Map.of("id", id);
    }

    @DeleteMapping("/{id}")
    public Map<String, Boolean> cancel(@PathVariable long id, HttpServletRequest request) {
        schedules.cancel(auth.requireUser(request), id);
        return Map.of("deleted", true);
    }
}
