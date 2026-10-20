package auth

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
)

func newTestServer(t *testing.T) (*gin.Engine, *Store) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	store, err := Open(filepath.Join(t.TempDir(), "auth.sqlite3"), 8)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	r := gin.New()
	r.Use(StripIdentityHeaders())
	r.Use(store.Middleware())
	store.Register(r)
	// Public routes exist here only so the middleware policy can be asserted.
	r.GET("/api/v1/version", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"build_id": "test"}) })
	r.GET("/api/v1/lab/health", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ready"}) })
	// A protected route that echoes a would-be identity header.
	r.GET("/api/v1/probe", func(c *gin.Context) {
		user, _ := CurrentUser(c)
		c.JSON(http.StatusOK, gin.H{"user": user.Username, "injected": c.GetHeader("X-User"),
			"operator": c.GetHeader("X-Operator")})
	})
	return r, store
}

func login(t *testing.T, r *gin.Engine, username, password string) *http.Cookie {
	t.Helper()
	body, _ := json.Marshal(map[string]string{"username": username, "password": password})
	request := httptest.NewRequest(http.MethodPost, "/api/v1/auth/login", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("login %s: %d %s", username, response.Code, response.Body.String())
	}
	for _, cookie := range response.Result().Cookies() {
		if cookie.Name == CookieName {
			return cookie
		}
	}
	t.Fatal("no session cookie")
	return nil
}

func call(r *gin.Engine, method, path string, body []byte, cookie *http.Cookie) *httptest.ResponseRecorder {
	var reader *bytes.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	} else {
		reader = bytes.NewReader(nil)
	}
	request := httptest.NewRequest(method, path, reader)
	request.Header.Set("Content-Type", "application/json")
	if cookie != nil {
		request.AddCookie(cookie)
	}
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)
	return response
}

func TestSessionCookieIsHardenedAndPublicRoutesStayOpen(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatalf("create admin: %v", err)
	}
	cookie := login(t, r, "admin", "correct-horse-battery")
	if !cookie.HttpOnly {
		t.Fatal("session cookie must be HttpOnly")
	}
	if cookie.SameSite != http.SameSiteLaxMode {
		t.Fatalf("session cookie SameSite = %v, want Lax", cookie.SameSite)
	}
	for _, path := range []string{"/api/v1/version", "/api/v1/lab/health"} {
		if code := call(r, http.MethodGet, path, nil, nil).Code; code != http.StatusOK {
			t.Fatalf("%s should be public, got %d", path, code)
		}
	}
}

func TestUnauthenticatedIsRejected(t *testing.T) {
	r, _ := newTestServer(t)
	for _, path := range []string{"/api/v1/probe", "/api/v1/auth/me", "/api/v1/auth/users", "/api/v1/slots"} {
		if code := call(r, http.MethodGet, path, nil, nil).Code; code != http.StatusUnauthorized {
			t.Fatalf("%s without session = %d, want 401", path, code)
		}
	}
}

func TestEvaluatorCannotReachAdminSurface(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CreateUser("eva", "correct-horse-battery", RoleEvaluator); err != nil {
		t.Fatal(err)
	}
	evaluator := login(t, r, "eva", "correct-horse-battery")
	if code := call(r, http.MethodGet, "/api/v1/auth/users", nil, evaluator).Code; code != http.StatusForbidden {
		t.Fatalf("evaluator listing accounts = %d, want 403", code)
	}
	body, _ := json.Marshal(map[string]string{"name": "x", "model_name": "m", "api_url": "https://example.test"})
	if code := call(r, http.MethodPost, "/api/v1/lab/models", body, evaluator).Code; code != http.StatusForbidden {
		t.Fatalf("evaluator writing a model config = %d, want 403", code)
	}
	if code := call(r, http.MethodGet, "/api/v1/lab/models", nil, evaluator).Code; code == http.StatusForbidden {
		t.Fatal("evaluator must still be able to read public model info")
	}
	admin := login(t, r, "admin", "correct-horse-battery")
	if code := call(r, http.MethodGet, "/api/v1/auth/users", nil, admin).Code; code != http.StatusOK {
		t.Fatalf("admin listing accounts = %d, want 200", code)
	}
}

func TestIdentityHeaderIsNotTrusted(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("eva", "correct-horse-battery", RoleEvaluator); err != nil {
		t.Fatal(err)
	}
	cookie := login(t, r, "eva", "correct-horse-battery")
	request := httptest.NewRequest(http.MethodGet, "/api/v1/probe", nil)
	request.AddCookie(cookie)
	request.Header.Set("X-User", "admin")
	request.Header.Set("X-Operator", "admin")
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("probe = %d", response.Code)
	}
	var payload map[string]any
	_ = json.Unmarshal(response.Body.Bytes(), &payload)
	if payload["injected"] != "" {
		t.Fatalf("browser supplied identity header survived: %v", payload["injected"])
	}
	if payload["user"] != "eva" {
		t.Fatalf("identity must come from the session, got %v", payload["user"])
	}
}

func TestOperatorHeaderComesFromTheSession(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("eva", "correct-horse-battery", RoleEvaluator); err != nil {
		t.Fatal(err)
	}
	cookie := login(t, r, "eva", "correct-horse-battery")
	request := httptest.NewRequest(http.MethodGet, "/api/v1/probe", nil)
	request.AddCookie(cookie)
	request.Header.Set("X-Operator", "admin") // must be overwritten
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)
	var payload map[string]any
	_ = json.Unmarshal(response.Body.Bytes(), &payload)
	if payload["operator"] != "eva" {
		t.Fatalf("X-Operator = %v, want the authenticated user eva", payload["operator"])
	}
}

func TestAuditSinkReceivesActions(t *testing.T) {
	var captured []string
	SetAuditSink(func(user User, action, object, result string) {
		captured = append(captured, user.Username+"|"+action+"|"+object+"|"+result)
	})
	defer SetAuditSink(nil)
	Record(User{ID: 1, Username: "admin"}, "POST /api/v1/lab/jobs/x/run", "jobs/x", "http:202")
	if len(captured) != 1 || captured[0] != "admin|POST /api/v1/lab/jobs/x/run|jobs/x|http:202" {
		t.Fatalf("audit sink got %v", captured)
	}
}

func TestCrossSiteWriteIsRejected(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatal(err)
	}
	cookie := login(t, r, "admin", "correct-horse-battery")
	body, _ := json.Marshal(map[string]string{"username": "x", "password": "correct-horse-battery"})
	request := httptest.NewRequest(http.MethodPost, "/api/v1/auth/users", bytes.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Origin", "http://evil.example")
	request.AddCookie(cookie)
	response := httptest.NewRecorder()
	r.ServeHTTP(response, request)
	if response.Code != http.StatusForbidden {
		t.Fatalf("cross-site write = %d, want 403", response.Code)
	}
}

func TestLogoutAndDisableInvalidateSessions(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatal(err)
	}
	user, _ := store.CreateUser("eva", "correct-horse-battery", RoleEvaluator)

	cookie := login(t, r, "eva", "correct-horse-battery")
	if code := call(r, http.MethodPost, "/api/v1/auth/logout", nil, cookie).Code; code != http.StatusOK {
		t.Fatalf("logout = %d", code)
	}
	if code := call(r, http.MethodGet, "/api/v1/auth/me", nil, cookie).Code; code != http.StatusUnauthorized {
		t.Fatalf("session after logout = %d, want 401", code)
	}

	second := login(t, r, "eva", "correct-horse-battery")
	if err := store.SetEnabled(user.ID, false); err != nil {
		t.Fatal(err)
	}
	if code := call(r, http.MethodGet, "/api/v1/auth/me", nil, second).Code; code != http.StatusUnauthorized {
		t.Fatalf("session after disable = %d, want 401", code)
	}
	if code := call(r, http.MethodPost, "/api/v1/auth/login",
		mustJSON(map[string]string{"username": "eva", "password": "correct-horse-battery"}), nil).Code; code != http.StatusForbidden {
		t.Fatalf("disabled account login = %d, want 403", code)
	}
}

func TestLoginRateLimit(t *testing.T) {
	r, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatal(err)
	}
	var last int
	for i := 0; i < 6; i++ {
		last = call(r, http.MethodPost, "/api/v1/auth/login",
			mustJSON(map[string]string{"username": "admin", "password": "wrong-password-123"}), nil).Code
	}
	if last != http.StatusTooManyRequests {
		t.Fatalf("repeated failures = %d, want 429", last)
	}
}

func TestLastAdminCannotBeDisabled(t *testing.T) {
	r, store := newTestServer(t)
	admin, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin)
	if err != nil {
		t.Fatal(err)
	}
	cookie := login(t, r, "admin", "correct-horse-battery")
	path := "/api/v1/auth/users/" + itoa(admin.ID)
	if code := call(r, http.MethodPatch, path, mustJSON(map[string]any{"enabled": false}), cookie).Code; code != http.StatusConflict {
		t.Fatalf("disabling the last admin = %d, want 409", code)
	}
}

func TestWeakPasswordAndDuplicateAreRejected(t *testing.T) {
	_, store := newTestServer(t)
	if _, err := store.CreateUser("admin", "short", RoleAdmin); err != ErrWeakPassword {
		t.Fatalf("weak password accepted: %v", err)
	}
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != nil {
		t.Fatal(err)
	}
	if _, err := store.CreateUser("admin", "correct-horse-battery", RoleAdmin); err != ErrUserExists {
		t.Fatalf("duplicate account accepted: %v", err)
	}
}

func mustJSON(value any) []byte {
	body, _ := json.Marshal(value)
	return body
}

func itoa(value int64) string {
	if value == 0 {
		return "0"
	}
	digits := ""
	for value > 0 {
		digits = string(rune('0'+value%10)) + digits
		value /= 10
	}
	return digits
}
