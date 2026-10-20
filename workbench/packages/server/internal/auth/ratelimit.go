package auth

import (
	"sync"
	"time"
)

type attempt struct {
	count int
	until time.Time
}

// rateLimiter bounds failed logins per identity (client address).
type rateLimiter struct {
	mu       sync.Mutex
	limit    int
	window   time.Duration
	attempts map[string]*attempt
	now      func() time.Time
}

func newRateLimiter(limit int, window time.Duration) *rateLimiter {
	if limit <= 0 {
		limit = 5
	}
	if window <= 0 {
		window = 10 * time.Minute
	}
	return &rateLimiter{limit: limit, window: window, attempts: map[string]*attempt{}, now: time.Now}
}

// Blocked reports whether the identity must wait before another attempt.
func (l *rateLimiter) Blocked(identity string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry, ok := l.attempts[identity]
	if !ok {
		return false
	}
	if l.now().After(entry.until) {
		delete(l.attempts, identity)
		return false
	}
	return entry.count >= l.limit
}

// Fail records one failed attempt.
func (l *rateLimiter) Fail(identity string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry, ok := l.attempts[identity]
	if !ok || l.now().After(entry.until) {
		entry = &attempt{until: l.now().Add(l.window)}
		l.attempts[identity] = entry
	}
	entry.count++
}

// Reset clears the counter after a successful login.
func (l *rateLimiter) Reset(identity string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.attempts, identity)
}
