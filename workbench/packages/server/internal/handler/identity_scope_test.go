package handler

import (
	"encoding/json"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/model"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestIdentityScopeAndCoverage(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db, err := gorm.Open(sqlite.Open(filepath.Join(t.TempDir(), "test.db")), &gorm.Config{})
	if err != nil {
		t.Fatal(err)
	}
	sqlDB, _ := db.DB()
	t.Cleanup(func() { sqlDB.Close() })
	if err := db.AutoMigrate(&model.Problem{}, &model.Slot{}, &model.Run{}, &model.LocalResult{}, &model.CorpusFix{}, &model.ExcludedModel{}); err != nil {
		t.Fatal(err)
	}
	db.Exec("ALTER TABLE problems ADD COLUMN split TEXT")
	db.Create(&model.Problem{QID: 2616, InFTTest: 1, CorpusCases: 1})
	db.Exec("INSERT INTO corpus_fixes(qid,kind,note) VALUES(2616,'first','first correction'),(2616,'second','second correction')")
	rows := []model.Slot{
		{Model: "m", QID: 2616, Lang: "python3", Cand: 1, Leetcode: "Accepted", Local: "Accepted", Klass: "agrees", IdentityStatus: "current"},
		{Model: "m", QID: 2616, Lang: "cpp", Cand: 1, Leetcode: "Accepted", Local: "Wrong Answer", Klass: "false_wa", IdentityStatus: "current"},
		{Model: "m", QID: 2616, Lang: "java", Cand: 1, Local: "Accepted", Klass: "no_lc", IdentityStatus: "current"},
		{Model: "m", QID: 2616, Lang: "rust", Cand: 1, Leetcode: "Accepted", Local: "Accepted", Klass: "agrees", IdentityStatus: "stale"},
		{Model: "m", QID: 2616, Lang: "c", Cand: 1, Leetcode: "Accepted", Local: "Accepted", Klass: "agrees", IdentityStatus: "unverifiable"},
		{Model: "m", QID: 2616, Lang: "golang", Cand: 1, Leetcode: "Accepted", Klass: "pending", IdentityStatus: "missing"},
	}
	for _, row := range rows {
		row.LCOrigin = "submissions"
		row.LocalOrigin = "all_models"
		row.HasCorpus = 1
		if err := db.Create(&row).Error; err != nil {
			t.Fatal(err)
		}
	}
	h := NewHandler(db, nil)
	r := gin.New()
	r.GET("/overview", h.GetOverview)
	r.GET("/model/:model", h.GetModelStats)
	r.GET("/problem/:qid", h.GetProblem)
	r.GET("/agreement", h.GetAgreement)
	get := func(url string) map[string]any {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("GET", url, nil))
		if w.Code != 200 {
			t.Fatalf("%s: %d %s", url, w.Code, w.Body.String())
		}
		var out map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
			t.Fatal(err)
		}
		return out
	}
	o := get("/overview")
	if o["comparable_slots"] != float64(2) || o["agree_rate"] != 0.5 {
		t.Fatalf("overview: %#v", o)
	}
	c := o["coverage"].(map[string]any)
	if c["planned"] != float64(6) || c["current"] != float64(3) || c["stale"] != float64(1) || c["unverifiable"] != float64(1) || c["missing"] != float64(1) {
		t.Fatalf("coverage: %#v", c)
	}
	m := get("/model/m")
	if m["total"] != float64(2) || m["agree_rate"] != 0.5 {
		t.Fatalf("model: %#v", m)
	}
	for _, entry := range m["languages"].([]any) {
		if entry.(map[string]any)["language"] == "" {
			t.Fatalf("model language missing: %#v", entry)
		}
	}
	p := get("/problem/2616?page_size=1&page=2")
	if p["total"] != float64(3) || len(p["slots"].([]any)) != 1 || p["metrics"].(map[string]any)["comparable_slots"] != float64(2) {
		t.Fatalf("problem: %#v", p)
	}
	a := get("/agreement")
	if a["by_model"].([]any)[0].(map[string]any)["total"] != float64(2) {
		t.Fatalf("agreement: %#v", a)
	}
	if a["by_problem"].([]any)[0].(map[string]any)["total"] != float64(2) {
		t.Fatalf("multiple correction notes multiplied problem denominator: %#v", a)
	}
	if get("/problem/2616?scope=all")["total"] != float64(6) {
		t.Fatal("history is inaccessible")
	}
	db.Model(&model.Slot{}).Where("1=1").Update("identity_status", "stale")
	o = get("/overview")
	if o["comparable_slots"] != float64(0) || o["coverage"].(map[string]any)["current"] != float64(0) {
		t.Fatalf("empty current scope: %#v", o)
	}
}
