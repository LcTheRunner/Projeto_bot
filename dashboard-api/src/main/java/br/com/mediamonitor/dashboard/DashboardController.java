package br.com.mediamonitor.dashboard;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import java.util.Map;

@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {
    private final DashboardService service;

    public DashboardController(DashboardService service) {
        this.service = service;
    }

    @GetMapping("/overview")
    public Map<String, Object> overview(
            @RequestParam(defaultValue = "7") int days,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String source,
            @RequestParam(required = false) Integer risk,
            @RequestParam(required = false) String tone) {
        return service.overview(Math.max(1, Math.min(days, 365)), keyword, source, risk, tone);
    }

    @GetMapping("/filters")
    public Map<String, Object> filters() {
        return service.filters();
    }
}
