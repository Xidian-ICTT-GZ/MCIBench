package lab

import "testing"

func TestLabAuditObject(t *testing.T) {
	cases := map[string]string{
		"/jobs/abc123/run":        "jobs/abc123",
		"/jobs/abc123/rejudge":    "jobs/abc123",
		"/models/m1":              "models/m1",
		// A collection mutation names the collection, not a member.
		"/jobs":                   "jobs",
		"/models":                 "models",
		"/catalog":                "catalog",
	}
	for path, want := range cases {
		if got := labAuditObject(path); got != want {
			t.Fatalf("labAuditObject(%q) = %q, want %q", path, got, want)
		}
	}
}
