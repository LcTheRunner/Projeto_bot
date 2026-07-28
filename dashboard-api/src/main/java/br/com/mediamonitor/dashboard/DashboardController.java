package br.com.mediamonitor.dashboard;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import java.util.Map;

@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {
    private final DashboardService service;
    private final AuthService auth;

    public DashboardController(DashboardService service, AuthService auth) {
        this.service = service;
        this.auth = auth;
    }

    @GetMapping("/overview")
    public Map<String, Object> overview(
            @RequestParam(defaultValue = "7") int days,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String source,
            @RequestParam(required = false) Integer risk,
            @RequestParam(required = false) String tone,
            @RequestParam(required = false) java.util.List<String> location,
            @RequestParam(defaultValue = "false") boolean includeAll,
            HttpServletRequest request) {
        long userId = auth.requireUser(request).id();
        return service.overview(Math.max(1, Math.min(days, 365)), keyword, source, risk, tone, location, includeAll, userId);
    }

    @GetMapping("/filters")
    public Map<String, Object> filters(HttpServletRequest request) {
        return service.filters(auth.requireUser(request).id());
    }
}
