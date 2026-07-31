package br.com.mediamonitor.dashboard;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/dashboard/alerts")
public class McsAlertController {
    private final McsAlertService alerts;
    private final AuthService auth;

    public McsAlertController(McsAlertService alerts, AuthService auth) {
        this.alerts = alerts;
        this.auth = auth;
    }

    @GetMapping
    public Map<String, Object> alerts(
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(required = false) Long beforeId,
            HttpServletRequest request
    ) {
        long userId = auth.requireUser(request).id();
        return alerts.alerts(userId, limit, beforeId);
    }

    @GetMapping("/unread-count")
    public Map<String, Integer> unreadCount(HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        return Map.of("unreadCount", alerts.unreadCount(userId));
    }

    @PutMapping("/{id}/read")
    public Map<String, Integer> markRead(@PathVariable long id, HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        return Map.of("unreadCount", alerts.markRead(userId, id));
    }

    @PutMapping("/read-all")
    public Map<String, Integer> markAllRead(HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        return Map.of("unreadCount", alerts.markAllRead(userId));
    }
}
