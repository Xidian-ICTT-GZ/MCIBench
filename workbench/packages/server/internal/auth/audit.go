package auth

import "sync"

// auditSink lets the ingress record mutating actions that are proxied to the
// Python worker. The worker never writes the audit log: only this process knows
// who the authenticated operator was.
var (
	auditMu   sync.RWMutex
	auditSink func(User, string, string, string)
)

// SetAuditSink wires the store's Audit method in at start-up.
func SetAuditSink(fn func(User, string, string, string)) {
	auditMu.Lock()
	defer auditMu.Unlock()
	auditSink = fn
}

// Record writes one audit entry. It never returns an error: auditing must not
// break the request it describes.
func Record(user User, action, object, result string) {
	auditMu.RLock()
	sink := auditSink
	auditMu.RUnlock()
	if sink != nil {
		sink(user, action, object, result)
	}
}
