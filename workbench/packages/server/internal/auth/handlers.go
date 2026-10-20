package auth

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

type loginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type userRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
	Enabled  *bool  `json:"enabled"`
}

// Register mounts the authentication surface. The engine-level middleware in
// Middleware() already guards everything except login.
func (s *Store) Register(r *gin.Engine) {
	group := r.Group("/api/v1/auth")
	group.POST("/login", s.handleLogin)
	group.POST("/logout", s.handleLogout)
	group.GET("/me", s.handleMe)
	group.GET("/users", s.handleListUsers)
	group.POST("/users", s.handleCreateUser)
	group.PATCH("/users/:id", s.handlePatchUser)
	group.GET("/audit", s.handleAudit)
}

func (s *Store) setCookie(c *gin.Context, token string, expires time.Time) {
	seconds := int(time.Until(expires).Seconds())
	if seconds <= 0 {
		seconds = 60
	}
	// HttpOnly keeps the token away from scripts; Lax blocks cross-site POSTs
	// that would otherwise ride the cookie. Secure stays off for local HTTP and
	// must be turned on (config auth.secure_cookie) behind TLS.
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(CookieName, token, seconds, "/", "", s.SecureCookie, true)
}

func (s *Store) clearCookie(c *gin.Context) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(CookieName, "", -1, "/", "", s.SecureCookie, true)
}

func (s *Store) handleLogin(c *gin.Context) {
	var body loginRequest
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}
	username := strings.TrimSpace(body.Username)
	user, err := s.Authenticate(username, body.Password, c.ClientIP())
	if err != nil {
		switch err {
		case ErrRateLimited:
			s.Audit(User{}, "login", username, "rate_limited")
			c.JSON(http.StatusTooManyRequests, gin.H{"error": "too many failed attempts"})
		case ErrDisabled:
			s.Audit(User{}, "login", username, "disabled")
			c.JSON(http.StatusForbidden, gin.H{"error": "account disabled"})
		default:
			s.Audit(User{}, "login", username, "invalid")
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid credentials"})
		}
		return
	}
	token, expires, err := s.IssueSession(user.ID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot create session"})
		return
	}
	s.setCookie(c, token, expires)
	s.Audit(user, "login", "", "ok")
	c.JSON(http.StatusOK, gin.H{"user": user, "expires_at": expires.UTC().Format(time.RFC3339)})
}

func (s *Store) handleLogout(c *gin.Context) {
	user, _ := CurrentUser(c)
	token, _ := c.Cookie(CookieName)
	if err := s.RevokeSession(token); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot revoke session"})
		return
	}
	s.clearCookie(c)
	s.Audit(user, "logout", "", "ok")
	c.JSON(http.StatusOK, gin.H{"logged_out": true})
}

func (s *Store) handleMe(c *gin.Context) {
	user, ok := CurrentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "login required"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"user": user})
}

func (s *Store) handleListUsers(c *gin.Context) {
	users, err := s.List()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot list accounts"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": users})
}

func (s *Store) handleCreateUser(c *gin.Context) {
	operator, _ := CurrentUser(c)
	var body userRequest
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}
	if body.Role == "" {
		body.Role = RoleEvaluator
	}
	user, err := s.CreateUser(body.Username, body.Password, body.Role)
	if err != nil {
		s.Audit(operator, "user.create", body.Username, err.Error())
		switch err {
		case ErrUserExists:
			c.JSON(http.StatusConflict, gin.H{"error": "account already exists"})
		case ErrWeakPassword:
			c.JSON(http.StatusBadRequest, gin.H{"error": "password must be at least 12 characters"})
		default:
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		}
		return
	}
	s.Audit(operator, "user.create", user.Username, "ok")
	c.JSON(http.StatusCreated, gin.H{"user": user})
}

func (s *Store) handlePatchUser(c *gin.Context) {
	operator, _ := CurrentUser(c)
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid account id"})
		return
	}
	target, err := s.UserByID(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "account not found"})
		return
	}
	var body userRequest
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request"})
		return
	}
	if body.Password != "" {
		if err := s.SetPassword(id, body.Password); err != nil {
			s.Audit(operator, "user.password", target.Username, err.Error())
			c.JSON(http.StatusBadRequest, gin.H{"error": "password must be at least 12 characters"})
			return
		}
		s.Audit(operator, "user.password", target.Username, "ok")
	}
	if body.Enabled != nil {
		if !*body.Enabled && target.Role == RoleAdmin {
			// Never let the last enabled administrator lock everyone out.
			users, lerr := s.List()
			if lerr == nil {
				others := 0
				for _, candidate := range users {
					if candidate.Role == RoleAdmin && candidate.Enabled && candidate.ID != target.ID {
						others++
					}
				}
				if others == 0 {
					c.JSON(http.StatusConflict, gin.H{"error": "cannot disable the last enabled administrator"})
					return
				}
			}
		}
		if err := s.SetEnabled(id, *body.Enabled); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot update account"})
			return
		}
		s.Audit(operator, "user.enabled", target.Username, strconv.FormatBool(*body.Enabled))
	}
	updated, err := s.UserByID(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot read account"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"user": updated})
}

func (s *Store) handleAudit(c *gin.Context) {
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "100"))
	entries, err := s.AuditLog(limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "cannot read audit log"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": entries})
}
