package auth

import (
	"net/http"
	"net/url"
	"strings"

	"github.com/gin-gonic/gin"
)

// CookieName is the only session carrier. No token is accepted from a header,
// so a stolen body cannot replay a session.
const CookieName = "mcibench_session"

// identityHeaders must never be trusted from the browser. The proxy chain sets
// them itself; anything arriving from outside is removed before routing.
var identityHeaders = []string{
	"X-User", "X-User-Id", "X-Username", "X-Operator", "X-Role",
	"X-Auth-User", "X-Forwarded-User", "X-Remote-User",
}

// StripIdentityHeaders removes browser-supplied identity claims.
func StripIdentityHeaders() gin.HandlerFunc {
	return func(c *gin.Context) {
		for _, header := range identityHeaders {
			c.Request.Header.Del(header)
		}
		c.Next()
	}
}

// Policy decides whether a request needs a session and which role it needs.
// Public surface is intentionally tiny: login, version, health and static files.
func Policy(method, path string) (public bool, role string) {
	if method == http.MethodOptions {
		return true, ""
	}
	switch path {
	case "/api/v1/auth/login":
		return method == http.MethodPost, ""
	case "/api/v1/version", "/api/v1/health", "/api/v1/lab/health":
		return true, ""
	}
	if !strings.HasPrefix(path, "/api/") {
		return true, "" // static shell and the public introduction page
	}
	switch {
	case strings.HasPrefix(path, "/api/v1/auth/users"), path == "/api/v1/auth/audit":
		return false, RoleAdmin
	case path == "/api/v1/lab/shutdown":
		return false, RoleAdmin
	case strings.HasPrefix(path, "/api/v1/lab/models") && method != http.MethodGet:
		return false, RoleAdmin
	}
	return false, ""
}

// sameOrigin rejects cross-site writes even when a cookie is present.
func sameOrigin(c *gin.Context) bool {
	origin := c.GetHeader("Origin")
	if origin == "" {
		origin = c.GetHeader("Referer")
	}
	if origin == "" {
		return true // non-browser clients cannot forge a cookie anyway
	}
	parsed, err := url.Parse(origin)
	if err != nil || parsed.Host == "" {
		return false
	}
	return strings.EqualFold(parsed.Host, c.Request.Host)
}

// Middleware is the engine-level gate. It resolves the session once, stores the
// account in the context, enforces the role and blocks cross-site writes.
func (s *Store) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		public, role := Policy(c.Request.Method, c.Request.URL.Path)
		if public {
			c.Next()
			return
		}
		if method := c.Request.Method; method != http.MethodGet && method != http.MethodHead {
			if !sameOrigin(c) {
				c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "cross-site request rejected"})
				return
			}
		}
		token, err := c.Cookie(CookieName)
		if err != nil || strings.TrimSpace(token) == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "login required"})
			return
		}
		user, err := s.SessionUser(token)
		if err != nil {
			c.SetCookie(CookieName, "", -1, "/", "", false, true)
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "session invalid or expired"})
			return
		}
		if role == RoleAdmin && user.Role != RoleAdmin {
			s.Audit(user, c.Request.Method+" "+c.Request.URL.Path, "", "forbidden")
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "administrator role required"})
			return
		}
		c.Set("auth.user", user)
		c.Set("auth.token", token)
		// The browser cannot forge this: StripIdentityHeaders ran first, and the
		// Python worker only accepts traffic carrying the private worker token.
		c.Request.Header.Set("X-Operator", user.Username)
		c.Next()
	}
}

// CurrentUser returns the authenticated account from the context.
func CurrentUser(c *gin.Context) (User, bool) {
	value, ok := c.Get("auth.user")
	if !ok {
		return User{}, false
	}
	user, ok := value.(User)
	return user, ok
}
