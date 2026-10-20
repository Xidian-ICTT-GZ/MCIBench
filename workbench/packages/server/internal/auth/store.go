// Package auth implements the minimal local account, session and audit layer.
//
// It runs in the public Go ingress: the Python worker never sees a browser
// header it could trust, and every protected request is authorised here.
package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"golang.org/x/crypto/bcrypt"
)

// Roles. There is no self registration and no per-user job isolation.
const (
	RoleAdmin     = "admin"
	RoleEvaluator = "evaluator"
)

var (
	ErrInvalidCredentials = errors.New("auth: invalid credentials")
	ErrDisabled           = errors.New("auth: account disabled")
	ErrNoSession          = errors.New("auth: no session")
	ErrSessionExpired     = errors.New("auth: session expired")
	ErrUserExists         = errors.New("auth: user already exists")
	ErrWeakPassword       = errors.New("auth: password does not meet the minimum policy")
	ErrRateLimited        = errors.New("auth: too many failed attempts")
	ErrUserNotFound       = errors.New("auth: user not found")
)

// User is the public projection. Password material never leaves the store.
type User struct {
	ID        int64     `json:"id"`
	Username  string    `json:"username"`
	Role      string    `json:"role"`
	Enabled   bool      `json:"enabled"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// Store owns the authentication database. It is deliberately separate from the
// benchmark database: identity must never enter the historical statistics.
type Store struct {
	db           *sql.DB
	SessionHours int
	SecureCookie bool
	failures     *rateLimiter
	now          func() time.Time
}

// Open creates or opens the authentication database.
func Open(path string, sessionHours int) (*Store, error) {
	if sessionHours <= 0 {
		sessionHours = 8
	}
	if dir := filepath.Dir(path); dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, err
		}
	}
	db, err := sql.Open("sqlite3", path+"?_busy_timeout=5000&_journal_mode=WAL&_foreign_keys=on")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	store := &Store{db: db, SessionHours: sessionHours, failures: newRateLimiter(5, 10*time.Minute), now: time.Now}
	if err := store.migrate(); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (s *Store) migrate() error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT NOT NULL UNIQUE,
			password_hash TEXT NOT NULL,
			role TEXT NOT NULL,
			enabled INTEGER NOT NULL DEFAULT 1,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL)`,
		`CREATE TABLE IF NOT EXISTS sessions (
			token_hash TEXT PRIMARY KEY,
			user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			created_at TEXT NOT NULL,
			expires_at TEXT NOT NULL,
			revoked INTEGER NOT NULL DEFAULT 0)`,
		`CREATE TABLE IF NOT EXISTS audit_log (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			at TEXT NOT NULL,
			user_id INTEGER NOT NULL DEFAULT 0,
			username TEXT NOT NULL DEFAULT '',
			action TEXT NOT NULL,
			object TEXT NOT NULL DEFAULT '',
			result TEXT NOT NULL DEFAULT 'ok')`,
		`CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)`,
	}
	for _, statement := range statements {
		if _, err := s.db.Exec(statement); err != nil {
			return fmt.Errorf("auth migrate: %w", err)
		}
	}
	return nil
}

// Close releases the database handle.
func (s *Store) Close() error { return s.db.Close() }

func (s *Store) stamp() string { return s.now().UTC().Format(time.RFC3339) }

// ValidatePassword enforces the documented minimum: 12 characters.
func ValidatePassword(password string) error {
	if len(password) < 12 {
		return ErrWeakPassword
	}
	return nil
}

// CreateUser hashes the password and stores the account. It is the only writer
// of password material; the CLI and the admin handler both go through it.
func (s *Store) CreateUser(username, password, role string) (User, error) {
	username = strings.TrimSpace(username)
	if username == "" || len(username) > 64 {
		return User{}, errors.New("auth: username must be 1-64 characters")
	}
	if role != RoleAdmin && role != RoleEvaluator {
		return User{}, errors.New("auth: unknown role")
	}
	if err := ValidatePassword(password); err != nil {
		return User{}, err
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return User{}, err
	}
	now := s.stamp()
	result, err := s.db.Exec(`INSERT INTO users (username, password_hash, role, enabled, created_at, updated_at)
		VALUES (?, ?, ?, 1, ?, ?)`, username, string(hash), role, now, now)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			return User{}, ErrUserExists
		}
		return User{}, err
	}
	id, _ := result.LastInsertId()
	return s.UserByID(id)
}

// SetPassword replaces the hash and revokes existing sessions for that account.
func (s *Store) SetPassword(id int64, password string) error {
	if err := ValidatePassword(password); err != nil {
		return err
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	if _, err := s.db.Exec(`UPDATE users SET password_hash=?, updated_at=? WHERE id=?`,
		string(hash), s.stamp(), id); err != nil {
		return err
	}
	return s.RevokeUserSessions(id)
}

// SetEnabled toggles an account; disabling revokes its sessions immediately.
func (s *Store) SetEnabled(id int64, enabled bool) error {
	value := 0
	if enabled {
		value = 1
	}
	result, err := s.db.Exec(`UPDATE users SET enabled=?, updated_at=? WHERE id=?`, value, s.stamp(), id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return ErrUserNotFound
	}
	if !enabled {
		return s.RevokeUserSessions(id)
	}
	return nil
}

func (s *Store) scanUser(row *sql.Row) (User, error) {
	var user User
	var created, updated string
	var enabled int
	if err := row.Scan(&user.ID, &user.Username, &user.Role, &enabled, &created, &updated); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return User{}, ErrUserNotFound
		}
		return User{}, err
	}
	user.Enabled = enabled == 1
	user.CreatedAt, _ = time.Parse(time.RFC3339, created)
	user.UpdatedAt, _ = time.Parse(time.RFC3339, updated)
	return user, nil
}

// UserByID returns one account.
func (s *Store) UserByID(id int64) (User, error) {
	return s.scanUser(s.db.QueryRow(`SELECT id, username, role, enabled, created_at, updated_at
		FROM users WHERE id=?`, id))
}

// UserByName returns one account.
func (s *Store) UserByName(name string) (User, error) {
	return s.scanUser(s.db.QueryRow(`SELECT id, username, role, enabled, created_at, updated_at
		FROM users WHERE username=?`, strings.TrimSpace(name)))
}

// List returns every account, oldest first.
func (s *Store) List() ([]User, error) {
	rows, err := s.db.Query(`SELECT id, username, role, enabled, created_at, updated_at
		FROM users ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	users := []User{}
	for rows.Next() {
		var user User
		var created, updated string
		var enabled int
		if err := rows.Scan(&user.ID, &user.Username, &user.Role, &enabled, &created, &updated); err != nil {
			return nil, err
		}
		user.Enabled = enabled == 1
		user.CreatedAt, _ = time.Parse(time.RFC3339, created)
		user.UpdatedAt, _ = time.Parse(time.RFC3339, updated)
		users = append(users, user)
	}
	return users, rows.Err()
}

// Count reports how many accounts exist; the CLI refuses to create a first
// admin when the database is not empty.
func (s *Store) Count() (int, error) {
	var total int
	err := s.db.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&total)
	return total, err
}

func hashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// Authenticate verifies a password with per-identity rate limiting.
func (s *Store) Authenticate(username, password, identity string) (User, error) {
	if s.failures.Blocked(identity) {
		return User{}, ErrRateLimited
	}
	user, err := s.UserByName(username)
	if err != nil {
		s.failures.Fail(identity)
		return User{}, ErrInvalidCredentials
	}
	var hash string
	if err := s.db.QueryRow(`SELECT password_hash FROM users WHERE id=?`, user.ID).Scan(&hash); err != nil {
		return User{}, ErrInvalidCredentials
	}
	if bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) != nil {
		s.failures.Fail(identity)
		return User{}, ErrInvalidCredentials
	}
	if !user.Enabled {
		return User{}, ErrDisabled
	}
	s.failures.Reset(identity)
	return user, nil
}

// IssueSession creates a random bearer token and stores only its hash.
func (s *Store) IssueSession(userID int64) (string, time.Time, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", time.Time{}, err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	expires := s.now().Add(time.Duration(s.SessionHours) * time.Hour)
	if _, err := s.db.Exec(`INSERT INTO sessions (token_hash, user_id, created_at, expires_at, revoked)
		VALUES (?, ?, ?, ?, 0)`, hashToken(token), userID, s.stamp(), expires.UTC().Format(time.RFC3339)); err != nil {
		return "", time.Time{}, err
	}
	return token, expires, nil
}

// SessionUser resolves a token to an enabled account, rejecting expired sessions.
func (s *Store) SessionUser(token string) (User, error) {
	if strings.TrimSpace(token) == "" {
		return User{}, ErrNoSession
	}
	var userID int64
	var expires string
	var revoked int
	err := s.db.QueryRow(`SELECT user_id, expires_at, revoked FROM sessions WHERE token_hash=?`,
		hashToken(token)).Scan(&userID, &expires, &revoked)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, ErrNoSession
	}
	if err != nil {
		return User{}, err
	}
	if revoked == 1 {
		return User{}, ErrNoSession
	}
	if deadline, perr := time.Parse(time.RFC3339, expires); perr == nil && s.now().After(deadline) {
		return User{}, ErrSessionExpired
	}
	user, err := s.UserByID(userID)
	if err != nil {
		return User{}, ErrNoSession
	}
	if !user.Enabled {
		return User{}, ErrDisabled
	}
	return user, nil
}

// RevokeSession invalidates one token.
func (s *Store) RevokeSession(token string) error {
	if strings.TrimSpace(token) == "" {
		return nil
	}
	_, err := s.db.Exec(`UPDATE sessions SET revoked=1 WHERE token_hash=?`, hashToken(token))
	return err
}

// RevokeUserSessions invalidates every token of one account.
func (s *Store) RevokeUserSessions(userID int64) error {
	_, err := s.db.Exec(`UPDATE sessions SET revoked=1 WHERE user_id=? AND revoked=0`, userID)
	return err
}

// Audit records a mutating action. Secrets, tokens and bodies are never passed in.
func (s *Store) Audit(user User, action, object, result string) {
	if len(result) > 80 {
		result = result[:80]
	}
	_, _ = s.db.Exec(`INSERT INTO audit_log (at, user_id, username, action, object, result)
		VALUES (?, ?, ?, ?, ?, ?)`, s.stamp(), user.ID, user.Username, action, object, result)
}

// AuditLog returns the most recent entries, newest first.
func (s *Store) AuditLog(limit int) ([]map[string]any, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	rows, err := s.db.Query(`SELECT at, user_id, username, action, object, result
		FROM audit_log ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var at, username, action, object, result string
		var userID int64
		if err := rows.Scan(&at, &userID, &username, &action, &object, &result); err != nil {
			return nil, err
		}
		out = append(out, map[string]any{"at": at, "user_id": userID, "username": username,
			"action": action, "object": object, "result": result})
	}
	return out, rows.Err()
}
