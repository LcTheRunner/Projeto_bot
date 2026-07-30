package br.com.mediamonitor.dashboard;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.ResponseCookie;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final AuthService auth;

    public AuthController(AuthService auth) {
        this.auth = auth;
    }

    public record LoginRequest(String username, String password) {}
    public record UserRequest(String username, String displayName, String email, String password, boolean admin) {}
    public record EmailRequest(String email) {}
    public record ResetRequest(String token, String password) {}
    public record VerificationRequest(String username, String code) {}

    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody LoginRequest body, HttpServletRequest request, HttpServletResponse response) {
        String token = auth.login(body.username(), body.password());
        response.addHeader("Set-Cookie", sessionCookie(token, request, Duration.ofDays(7)).toString());
        AuthService.User user = auth.requireUser(withCookie(request, token));
        return userMap(user);
    }

    @PostMapping("/logout")
    public Map<String, Boolean> logout(HttpServletRequest request, HttpServletResponse response) {
        auth.logout(request);
        response.addHeader("Set-Cookie", sessionCookie("", request, Duration.ZERO).toString());
        return Map.of("ok", true);
    }

    @PostMapping("/register")
    public Map<String, Long> register(@RequestBody UserRequest body) {
        return Map.of("id", auth.register(body.username(), body.displayName(), body.email(), body.password()));
    }

    @PostMapping("/verify-email")
    public Map<String, Boolean> verifyEmail(@RequestBody VerificationRequest body) {
        auth.verifyEmail(body.username(), body.code());
        return Map.of("ok", true);
    }

    @PostMapping("/resend-verification")
    public Map<String, Boolean> resendVerification(@RequestBody VerificationRequest body) {
        auth.resendVerification(body.username());
        return Map.of("ok", true);
    }

    @PostMapping("/forgot-password")
    public Map<String, Boolean> forgotPassword(@RequestBody EmailRequest body) {
        auth.requestPasswordReset(body.email());
        return Map.of("ok", true);
    }

    @PostMapping("/reset-password")
    public Map<String, Boolean> resetPassword(@RequestBody ResetRequest body) {
        auth.resetPassword(body.token(), body.password());
        return Map.of("ok", true);
    }

    @GetMapping("/me")
    public Map<String, Object> me(HttpServletRequest request) {
        return userMap(auth.requireUser(request));
    }

    @GetMapping("/users")
    public List<Map<String, Object>> users(HttpServletRequest request) {
        return auth.users(auth.requireUser(request));
    }

    @PostMapping("/users")
    public Map<String, Long> create(@RequestBody UserRequest body, HttpServletRequest request) {
        return Map.of("id", auth.createUser(auth.requireUser(request), body.username(), body.displayName(), body.email(), body.password(), body.admin()));
    }

    @PutMapping("/users/{id}/owner")
    public Map<String, Boolean> transferOwnership(@PathVariable long id, HttpServletRequest request) {
        auth.transferOwnership(auth.requireUser(request), id);
        return Map.of("updated", true);
    }

    @DeleteMapping("/users/{id}")
    public Map<String, Boolean> delete(@PathVariable long id, HttpServletRequest request) {
        auth.deleteUser(auth.requireUser(request), id);
        return Map.of("deleted", true);
    }

    private ResponseCookie sessionCookie(String token, HttpServletRequest request, Duration age) {
        boolean secure = request.isSecure() || "https".equalsIgnoreCase(request.getHeader("X-Forwarded-Proto"));
        return ResponseCookie.from("mcs_session", token).httpOnly(true).secure(secure).sameSite("Strict")
                .path("/").maxAge(age).build();
    }

    private Map<String, Object> userMap(AuthService.User user) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        result.put("id", user.id());
        result.put("username", user.username());
        result.put("displayName", user.displayName());
        result.put("email", user.email());
        result.put("admin", user.admin());
        return result;
    }

    private HttpServletRequest withCookie(HttpServletRequest request, String token) {
        return new jakarta.servlet.http.HttpServletRequestWrapper(request) {
            @Override public jakarta.servlet.http.Cookie[] getCookies() {
                return new jakarta.servlet.http.Cookie[]{new jakarta.servlet.http.Cookie("mcs_session", token)};
            }
        };
    }
}
