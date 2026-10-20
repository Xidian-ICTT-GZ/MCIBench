package lab

import (
	"context"
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOriginGuard(t *testing.T) {
	for _, origin := range []string{"", "http://127.0.0.1:8090", "http://localhost:5199"} {
		if !AllowedOrigin(origin, "127.0.0.1:8090") {
			t.Fatalf("valid origin rejected: %s", origin)
		}
	}
	for _, origin := range []string{"https://evil.example", "http://127.0.0.1.evil.example:8090", "null", "file:///tmp/page"} {
		if AllowedOrigin(origin, "127.0.0.1:8090") {
			t.Fatalf("unsafe origin accepted: %s", origin)
		}
	}
}

func TestDeleteWithoutBodyAndOriginGuard(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Lab-Token") != "token" || r.Header.Get("Authorization") != "" {
			t.Error("proxy credential boundary failed")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()
	s := &Service{url: backend.URL, token: "token"}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	s.Register(r)
	request := httptest.NewRequest(http.MethodDelete, "http://127.0.0.1:8090/api/v1/lab/models/test", nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	request = request.WithContext(ctx)
	request.Header.Set("Authorization", "must-not-forward")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, request)
	if w.Code != http.StatusOK {
		t.Fatalf("DELETE without body rejected: %d", w.Code)
	}
	request = httptest.NewRequest(http.MethodPost, "http://127.0.0.1:8090/api/v1/lab/models", nil)
	request.Header.Set("Origin", "https://evil.example")
	request.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	r.ServeHTTP(w, request)
	if w.Code != http.StatusForbidden {
		t.Fatalf("foreign write origin accepted: %d", w.Code)
	}
}
