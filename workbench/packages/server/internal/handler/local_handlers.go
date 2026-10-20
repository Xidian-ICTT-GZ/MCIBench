package handler

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/config"
	"github.com/m1inato/mcibench-board/internal/model"
	"gorm.io/gorm"
)

// Handler 本地判题仪表盘的处理器。
type Handler struct {
	db  *gorm.DB
	cfg *config.Config
}

func NewHandler(db *gorm.DB, cfg *config.Config) *Handler {
	return &Handler{db: db, cfg: cfg}
}

// klassDoc 分类口径，与 local/audit/report.py 的 KLASS_DOC 保持一致。
var klassDoc = map[string]string{
	"agrees":    "本地与 LeetCode 判定一致",
	"same_neg":  "双方都判不通过（类型可能不同；多为环境/编译差异）",
	"false_ac":  "本地 AC、LeetCode 非 AC —— 本地用例太弱（覆盖不足）",
	"false_wa":  "本地非 AC、LeetCode AC —— 本地用例太严，或判题器有缺陷",
	"no_corpus": "该题不在本地评测集内，无法对拍",
	"pending":   "有 LeetCode 判定，但本地还没判过 —— 跑 judge_all_models 即可补上",
	// 主库里有 20 个槽位的 LeetCode 判定为空（提交没被 LC 记录）。
	// 没有对照就没有一致性可言，所以**不参与**统计——此前它们被算成
	// false_ac（本地 AC + LC 空），等于把"不知道"当成了"不过"。
	"no_lc": "LeetCode 侧没有判定记录 —— 无对照，不参与一致性统计",
}

// metricsBlock 一组"一致率"指标。**两个一致率定义必须分开命名**：
//
//	comparable_slots / exact_agree_rate  —— 精确状态一致率（agrees / 可比）
//	binary_agree_rate                    —— 把 same_neg 也算一致（AC/非AC 二元）
//
// 二者差别很大（95.6% vs 97.4%），混用会让人以为在说同一件事。
// 另外报两个方向性指标，它们比一致率更有诊断价值：
//
//	miss_rate    漏检率 = FP/(FP+TN)
//	             LC 判失败的槽位里，我们放过了多少（本地用例太弱，false_ac）
//	false_reject_rate 误拒率 = FN/(TP+FN)
//	             我们判失败的槽位里，有多少是 LC 接受的（本地太严或判题器有缺陷）
//
// **口径修正（审查发现 C-001 / P1）**：此前这两个"方向性指标"用的是
// `false_ac/(false_ac+same_neg)` 与 `false_wa/(false_wa+same_neg)`，
// 即把 `same_neg` 当成了全部 TN。但按规范 7.3 的 2×2，**TN 是「LC 非 AC 且本地非 AC」**，
// 而 `classify()` 把**双方状态字符串相同**（含 `Wrong Answer == Wrong Answer`、
// `Compile Error == Compile Error`）都归入 `agrees` —— 所以 TN 远大于 `same_neg`：
//
//	N=7148  TP=4180  FN=59  FP=104  TN=2805
//	agrees 6855 里有 **2675** 条是双方同类型失败（WA 1633/CE 824/RE 170/TLE 47/MLE 1）
//
// 后果：漏检率被放大约 **12 倍**（3.575% 被报成 44.44%），
// 误拒率约 **22 倍**（1.392% 被报成 31.22%）。交接文档据此写出的整表失真。
//
// 现在按 2×2 真算：TP/FN/FP/TN 直接从原始状态构建，不靠 klass 的标签猜分母。
type metricsBlock struct {
	Comparable      int     `json:"comparable_slots"`
	Agrees          int     `json:"agrees"`
	SameNeg         int     `json:"same_neg"`
	FalseAC         int     `json:"false_ac"`
	FalseWA         int     `json:"false_wa"`
	NoLC            int     `json:"no_lc"`
	TP              int     `json:"tp"`
	FN              int     `json:"fn"`
	FP              int     `json:"fp"`
	TN              int     `json:"tn"`
	ExactAgreeRate  float64 `json:"exact_agree_rate"`
	BinaryAgreeRate float64 `json:"binary_agree_rate"`
	MissRate        float64 `json:"miss_rate"`
	FalseRejectRate float64 `json:"false_reject_rate"`
	// 本地拒绝中 LC 接受的比例 —— 规范 7.3 明确要求**不得与漏检率/误拒率混名**
	RejectedButLCAccepted float64 `json:"rejected_but_lc_accepted_rate"`
	// 分母为 0 时不该渲染成 0.0%（规范 7.3）：用这个标记让前端显示"不适用"
	MissRateApplicable        bool `json:"miss_rate_applicable"`
	FalseRejectRateApplicable bool `json:"false_reject_rate_applicable"`
}

func (h *Handler) metrics(where string, wargs ...any) metricsBlock {
	var m metricsBlock
	// no_lc 计数必须在**过滤前**单独取：主查询带 `klass <> 'no_lc'`，
	// 在里面 SUM 恒为 0（那正是此前的死字段）。
	// **顺序很关键**：主查询的 `Scan(&m)` 会把整个结构体清零，
	// 所以 no_lc 必须在它**之后**赋值 —— 我第一版放在它之前，
	// 结果 no_lc 一直显示 0（查了半天）。
	var nNoLC int
	h.db.Model(&model.Slot{}).
		Select("COALESCE(SUM(CASE WHEN klass = 'no_lc' THEN 1 ELSE 0 END), 0)").
		Where(where, wargs...).Scan(&nNoLC)

	// 2×2 直接从原始状态算，不经过 klass 标签
	q := h.db.Model(&model.Slot{}).Select(`
		COUNT(*) AS comparable,
		SUM(CASE WHEN leetcode = 'Accepted' AND local = 'Accepted' THEN 1 ELSE 0 END) AS tp,
		SUM(CASE WHEN leetcode = 'Accepted' AND local <> 'Accepted' THEN 1 ELSE 0 END) AS fn,
		SUM(CASE WHEN leetcode <> 'Accepted' AND local = 'Accepted' THEN 1 ELSE 0 END) AS fp,
		SUM(CASE WHEN leetcode <> 'Accepted' AND local <> 'Accepted' THEN 1 ELSE 0 END) AS tn,
		SUM(CASE WHEN klass = 'agrees' THEN 1 ELSE 0 END) AS agrees,
		SUM(CASE WHEN klass = 'same_neg' THEN 1 ELSE 0 END) AS same_neg,
		SUM(CASE WHEN klass = 'false_ac' THEN 1 ELSE 0 END) AS false_ac,
		SUM(CASE WHEN klass = 'false_wa' THEN 1 ELSE 0 END) AS false_wa`).
		Where(where, wargs...)
	// no_lc 没有对照，不进分母
	q.Where(comparableWhere).Scan(&m)
	// **必须放在 Scan(&m) 之后**（Scan 会清零结构体）
	m.NoLC = nNoLC

	if m.Comparable > 0 {
		m.ExactAgreeRate = float64(m.Agrees) / float64(m.Comparable)
		m.BinaryAgreeRate = float64(m.TP+m.TN) / float64(m.Comparable)
	}
	if d := m.FP + m.TN; d > 0 {
		m.MissRate = float64(m.FP) / float64(d)
		m.MissRateApplicable = true
	}
	if d := m.TP + m.FN; d > 0 {
		m.FalseRejectRate = float64(m.FN) / float64(d)
		m.FalseRejectRateApplicable = true
	}
	if d := m.FN + m.TN; d > 0 {
		m.RejectedButLCAccepted = float64(m.FN) / float64(d)
	}
	return m
}

func pageParams(c *gin.Context) (page, size int) {
	page, _ = strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ = strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if page < 1 {
		page = 1
	}
	if size < 1 || size > 200 {
		size = 20
	}
	return
}

// scopeWhere 返回限定统计口径的 SQL 条件。
//
// 库里有两个**独立**的来源维度，此前被混成一个 `origin`：
//
//	lc_origin    —— 该槽位的 **LeetCode** 判定来自哪
//	local_origin —— 该槽位的 **本地** 判定来自哪
//
// 原来只有 `origin` 记 LeetCode 来源，本地判定却可能是从旧缓存补的，
// 前端据此判断"当前版本"就会把过期数据当成现役。
//
// 实测：`lc_origin='submissions'` 的 7946 个槽位里，有 778 个的本地判定
// 其实来自 `audit_cache`（全部属于 qwen3-1.7b-g-sft）——该模型在
// `results/all_models/` 下**根本没有结果**，本地判定只存在于旧缓存。
//
// 所以"当前口径"必须**同时**要求：
//
//	lc_origin='submissions' AND local_origin='all_models'
const comparableWhere = "slots.klass IN ('agrees','same_neg','false_ac','false_wa')"

func scopeWhere(scope string) (string, []any) {
	switch scope {
	case "audit":
		return "slots.lc_origin = ?", []any{"audit_cache"}
	case "stale":
		return "COALESCE(slots.identity_status, '') <> 'current'", nil
	case "all":
		return "1=1", nil
	default:
		return "slots.lc_origin = ? AND slots.local_origin = ? AND slots.identity_status = 'current' AND slots.qid IN (SELECT qid FROM problems WHERE in_ft_test=1)",
			[]any{"submissions", "all_models"}
	}
}

// Coverage has its own denominator, including missing and unverified results.
type identityCoverage struct {
	Planned      int `json:"planned"`
	Current      int `json:"current"`
	Stale        int `json:"stale"`
	Unverifiable int `json:"unverifiable"`
	Missing      int `json:"missing"`
}

func (h *Handler) coverage() identityCoverage {
	var out identityCoverage
	h.db.Model(&model.Slot{}).Select(`COUNT(*) AS planned,
        COALESCE(SUM(CASE WHEN identity_status='current' THEN 1 ELSE 0 END),0) AS current,
        COALESCE(SUM(CASE WHEN identity_status='stale' THEN 1 ELSE 0 END),0) AS stale,
        COALESCE(SUM(CASE WHEN identity_status='unverifiable' OR (COALESCE(identity_status,'')='' AND local<>'') THEN 1 ELSE 0 END),0) AS unverifiable,
        COALESCE(SUM(CASE WHEN identity_status='missing' OR (COALESCE(identity_status,'')='' AND COALESCE(local,'')='') THEN 1 ELSE 0 END),0) AS missing`).
		Where("lc_origin='submissions' AND qid IN (SELECT qid FROM problems WHERE in_ft_test=1)").Scan(&out)
	return out
}

// ---------------------------------------------------------------------------
// 总览
// ---------------------------------------------------------------------------

type modelStat struct {
	ModelName  string  `json:"model_name"`
	Total      int     `json:"total"`
	LocalAC    int     `json:"local_ac"`
	LeetcodeAC int     `json:"leetcode_ac"`
	Agrees     int     `json:"agrees"`
	FalseAC    int     `json:"false_ac"`
	FalseWA    int     `json:"false_wa"`
	AgreeRate  float64 `json:"agree_rate"`
}

// GetOverview 总览：题目/槽位/分类分布/模型列表。
func (h *Handler) GetOverview(c *gin.Context) {
	scope := c.DefaultQuery("scope", "ft_test")
	where, wargs := scopeWhere(scope)

	var problems, ftProblems, slots, runs, localResults, fixes int64
	h.db.Model(&model.Problem{}).Count(&problems)
	h.db.Model(&model.Problem{}).Where("in_ft_test = 1").Count(&ftProblems)
	q := h.db.Model(&model.Slot{})
	if where != "" {
		q = q.Where(where, wargs...)
	}
	q.Count(&slots)
	h.db.Model(&model.Run{}).Count(&runs)
	h.db.Model(&model.LocalResult{}).Count(&localResults)
	h.db.Model(&model.CorpusFix{}).Count(&fixes)

	klass := []gin.H{}
	kr := h.db.Model(&model.Slot{})
	if where != "" {
		kr = kr.Where(where, wargs...)
	}
	rows, _ := kr.Select("klass, COUNT(*) as n").Group("klass").Order("n DESC").Rows()
	if rows != nil {
		defer rows.Close()
		for rows.Next() {
			var k string
			var n int
			_ = rows.Scan(&k, &n)
			klass = append(klass, gin.H{"klass": k, "count": n, "doc": klassDoc[k]})
		}
	}

	// 只统计**两边都有判定**的槽位，"一致率"才有意义：
	// 既要排除 no_corpus（无法对拍），也要排除 pending（本地还没判）。
	var comparable, agreeing, pending int64
	base := func() *gorm.DB {
		b := h.db.Model(&model.Slot{})
		if where != "" {
			b = b.Where(where, wargs...)
		}
		return b
	}
	// **口径统一（审查发现 C-002 / P1）**：总览 KPI 此前用
	// `has_corpus = 1 AND klass <> 'pending'` 当分母（= 7168，**含 20 个 no_lc**），
	// 而 `metrics` 块用 `klass <> 'no_lc'`（= 7148）。同一个 scope 下两个分母、
	// 却都叫"一致率" —— 前端读的是前者，交接文档引用的是后者，读者无法对账。
	//
	// `no_lc` 是"本地有判定但 LC 无记录"的槽位，**没有对照就不可比**，
	// 规范 7.3 明确要求把它排除。所以统一到 `klass <> 'no_lc'`。
	base().Where(comparableWhere).Count(&comparable)
	base().Where("has_corpus = 1 AND klass = ?", "agrees").Count(&agreeing)
	base().Where("klass = 'pending'").Count(&pending)
	agreeRate := 0.0
	if comparable > 0 {
		agreeRate = float64(agreeing) / float64(comparable)
	}

	models := []string{}
	mq := h.db.Model(&model.Slot{})
	if where != "" {
		mq = mq.Where(where, wargs...)
	}
	mq.Distinct().Order("model").Pluck("model", &models)

	langs := []string{}
	lq := h.db.Model(&model.Slot{}).Where("lang <> ''")
	if where != "" {
		lq = lq.Where(where, wargs...)
	}
	lq.Distinct().Order("lang").Pluck("lang", &langs)

	// 被排除的模型——必须让前端显示出来，否则读数是"少了三块"而看不出来。
	excluded := []model.ExcludedModel{}
	h.db.Model(&model.ExcludedModel{}).Order("model").Find(&excluded)

	// 指标块：两个一致率定义 + 漏检率/误拒率（见 metricsBlock 的注释）。
	//
	// **这里不要预先拼 `klass <> 'no_lc'`**：`metrics()` 内部已经排除了 no_lc，
	// 而它还需要**看到** no_lc 才能统计 `no_lc` 字段。此前把过滤条件拼进 where
	// 传进去，导致 `no_lc` 恒为 0（死字段）。分块（dev/holdout）同理。
	// 另外注意：原注释称"只有 holdout 上的数字才是无偏的"—— 这句**站不住**，
	// 见 C-005：划分是按语料修改历史事后反推的，且 q922/q2610/q1304 的 checker
	// 都是被它们自身在 holdout 里的失败驱动的。措辞已降级为"描述性比较"。
	all := h.metrics(where, wargs...)
	dev := h.metrics(where+" AND qid IN (SELECT qid FROM problems WHERE split = ?)",
		append(append([]any{}, wargs...), "dev")...)
	hold := h.metrics(where+" AND qid IN (SELECT qid FROM problems WHERE split = ?)",
		append(append([]any{}, wargs...), "holdout")...)

	c.JSON(http.StatusOK, gin.H{
		"coverage":         h.coverage(),
		"problems":         problems,
		"ft_test_problems": ftProblems,
		"slots":            slots,
		"comparable_slots": comparable,
		"agreeing_slots":   agreeing,
		"agree_rate":       agreeRate,
		"pending_slots":    pending,
		"runs":             runs,
		"local_results":    localResults,
		"corpus_fixes":     fixes,
		"klass":            klass,
		"models":           models,
		"languages":        langs,
		"metrics":          all,
		"metrics_dev":      dev,
		"metrics_holdout":  hold,
		"scope":            scope,
		"excluded_models":  excluded,
	})
}

// ---------------------------------------------------------------------------
// 一致性分析（本地判 vs LeetCode 判）—— 本仪表盘的核心
// ---------------------------------------------------------------------------

// GetAgreement 按模型 × 分类的交叉表，以及按语言的分布。
func (h *Handler) GetAgreement(c *gin.Context) {
	task := c.Query("task")
	scope := c.DefaultQuery("scope", "ft_test")
	where, wargs := scopeWhere(scope)

	// 用局部 base() 而不是改 h.db —— Handler 是跨请求共享的，
	// 改它会把 scope 过滤泄漏到别的请求上。
	base := func() *gorm.DB {
		q := h.db.Model(&model.Slot{})
		if where != "" {
			q = q.Where(where, wargs...)
		}
		return q
	}

	byModel := []modelStat{}
	// C-002：模型页的分母也必须排除 no_lc，否则与总览/metrics 三个口径并存。
	// （此前是 `COUNT(*)`，含 no_lc 与 pending。）
	q := base().Where(comparableWhere).Select(`
		model AS model_name,
		COUNT(*) AS total,
		SUM(CASE WHEN local = 'Accepted' THEN 1 ELSE 0 END) AS local_ac,
		SUM(CASE WHEN leetcode = 'Accepted' THEN 1 ELSE 0 END) AS leetcode_ac,
		SUM(CASE WHEN klass = 'agrees' THEN 1 ELSE 0 END) AS agrees,
		SUM(CASE WHEN klass = 'false_ac' THEN 1 ELSE 0 END) AS false_ac,
		SUM(CASE WHEN klass = 'false_wa' THEN 1 ELSE 0 END) AS false_wa`)
	if task != "" {
		q = q.Where("task = ?", task)
	}
	if err := q.Group("model").Order("total DESC").Scan(&byModel).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	for i := range byModel {
		if byModel[i].Total > 0 {
			byModel[i].AgreeRate = float64(byModel[i].Agrees) / float64(byModel[i].Total)
		}
	}

	type langRow struct {
		Lang    string `json:"lang"`
		Total   int    `json:"total"`
		Agrees  int    `json:"agrees"`
		FalseAC int    `gorm:"column:false_ac" json:"false_ac"`
		FalseWA int    `gorm:"column:false_wa" json:"false_wa"`
	}
	byLang := []langRow{}
	lq := base().Where(comparableWhere).Select(`
		lang, COUNT(*) AS total,
		SUM(CASE WHEN klass = 'agrees' THEN 1 ELSE 0 END) AS agrees,
		SUM(CASE WHEN klass = 'false_ac' THEN 1 ELSE 0 END) AS false_ac,
		SUM(CASE WHEN klass = 'false_wa' THEN 1 ELSE 0 END) AS false_wa`).
		Where("lang <> ''")
	if task != "" {
		lq = lq.Where("task = ?", task)
	}
	lq.Group("lang").Order("total DESC").Scan(&byLang)

	// 按题目：差异最多的题排前面
	// 注意 QID 的 gorm tag：GORM 默认会把 "QID" 拆成列名 `q_id`，
	// 而 SQL 里输出的是 `qid`，不加 tag 会静默扫成 0。
	type probRow struct {
		QID         int    `gorm:"column:qid" json:"qid"`
		Title       string `json:"title"`
		CorpusCases int    `gorm:"column:corpus_cases" json:"corpus_cases"`
		Total       int    `json:"total"`
		Agrees      int    `json:"agrees"`
		FalseAC     int    `gorm:"column:false_ac" json:"false_ac"`
		FalseWA     int    `gorm:"column:false_wa" json:"false_wa"`
		Fixed       string `json:"fixed"`
	}
	byProblem := []probRow{}
	pq := h.db.Table("slots").
		Select(`slots.qid AS qid, MAX(problems.title) AS title,
			MAX(problems.corpus_cases) AS corpus_cases,
			COUNT(*) AS total,
			SUM(CASE WHEN slots.klass = 'agrees' THEN 1 ELSE 0 END) AS agrees,
			SUM(CASE WHEN slots.klass = 'false_ac' THEN 1 ELSE 0 END) AS false_ac,
			SUM(CASE WHEN slots.klass = 'false_wa' THEN 1 ELSE 0 END) AS false_wa,
			COALESCE(MAX(corpus_fixes.note), '') AS fixed`).
		Joins("LEFT JOIN problems ON problems.qid = slots.qid").
		Joins("LEFT JOIN (SELECT qid, GROUP_CONCAT(note, '; ') AS note FROM corpus_fixes GROUP BY qid) AS corpus_fixes ON corpus_fixes.qid = slots.qid").
		Where(comparableWhere)
	if where != "" {
		pq = pq.Where(where, wargs...)
	}
	if task != "" {
		pq = pq.Where("slots.task = ?", task)
	}
	pq.Group("slots.qid").Order("(false_ac + false_wa) DESC, total DESC").Limit(100).
		Scan(&byProblem)

	c.JSON(http.StatusOK, gin.H{
		"by_model":   byModel,
		"by_lang":    byLang,
		"by_problem": byProblem,
		"scope":      scope,
	})
}

// GetModelStats 单个模型的分语言明细。
func (h *Handler) GetModelStats(c *gin.Context) {
	name := c.Param("model")

	type langRow struct {
		Lang       string  `gorm:"column:language" json:"language"`
		Total      int     `json:"total"`
		Agrees     int     `json:"agrees"`
		FalseAC    int     `json:"false_ac"`
		FalseWA    int     `json:"false_wa"`
		LocalAC    int     `json:"local_ac"`
		LeetcodeAC int     `json:"leetcode_ac"`
		AgreeRate  float64 `json:"agree_rate"`
	}
	langs := []langRow{}
	// 必须与总览用**同一个**范围过滤。此前这里只有 `model = ?`，
	// 于是详情页把 audit_cache 的旧结果一起算进来——qwen3-1.7b 在总览是 94.8%，
	// 到详情页会变成 46% 左右（混入了旧口径的失败）。
	sw, sargs := scopeWhere(c.Query("scope"))
	where := "model = ? AND lang <> '' AND " + comparableWhere
	wargs := []any{name}
	if sw != "" {
		where += " AND " + sw
		wargs = append(wargs, sargs...)
	}
	h.db.Model(&model.Slot{}).Select(`
		lang AS language, COUNT(*) AS total,
		SUM(CASE WHEN klass = 'agrees' THEN 1 ELSE 0 END) AS agrees,
		SUM(CASE WHEN klass = 'false_ac' THEN 1 ELSE 0 END) AS false_ac,
		SUM(CASE WHEN klass = 'false_wa' THEN 1 ELSE 0 END) AS false_wa,
		SUM(CASE WHEN local = 'Accepted' THEN 1 ELSE 0 END) AS local_ac,
		SUM(CASE WHEN leetcode = 'Accepted' THEN 1 ELSE 0 END) AS leetcode_ac`).
		Where(where, wargs...).
		Group("lang").Order("total DESC").Scan(&langs)
	for i := range langs {
		if langs[i].Total > 0 {
			langs[i].AgreeRate = float64(langs[i].Agrees) / float64(langs[i].Total)
		}
	}

	var total, agrees int64
	h.db.Model(&model.Slot{}).Where(where, wargs...).Count(&total)
	h.db.Model(&model.Slot{}).Where(where+" AND klass = 'agrees'", wargs...).
		Count(&agrees)
	rate := 0.0
	if total > 0 {
		rate = float64(agrees) / float64(total)
	}

	c.JSON(http.StatusOK, gin.H{
		"model_name": name,
		"total":      total,
		"agrees":     agrees,
		"agree_rate": rate,
		"languages":  langs,
	})
}

// ---------------------------------------------------------------------------
// 槽位 / 题目 / 本地结果
// ---------------------------------------------------------------------------

// ListSlots 分页列出槽位，支持模型/语言/任务/分类/题号筛选。
func (h *Handler) ListSlots(c *gin.Context) {
	page, size := pageParams(c)
	q := h.db.Model(&model.Slot{})
	// 与总览用同一个范围过滤，否则槽位列表会出现总览里没有的旧口径记录。
	sw, sargs := scopeWhere(c.Query("scope"))
	if sw != "" {
		q = q.Where(sw, sargs...)
	}
	if v := c.Query("model"); v != "" {
		q = q.Where("model = ?", v)
	}
	if v := c.Query("lang"); v != "" {
		q = q.Where("lang = ?", v)
	}
	if v := c.Query("task"); v != "" {
		q = q.Where("task = ?", v)
	}
	if v := c.Query("klass"); v != "" {
		q = q.Where("klass = ?", v)
	}
	if v := c.Query("qid"); v != "" {
		q = q.Where("qid = ?", v)
	}
	// 只关心差异时用 mismatches=1
	if c.Query("mismatches") == "1" {
		q = q.Where("klass IN ('false_ac','false_wa')")
	}

	var total int64
	q.Count(&total)
	rows := []model.Slot{}
	if err := q.Order("id").Offset((page - 1) * size).Limit(size).
		Find(&rows).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": rows, "total": total,
		"page": page, "page_size": size})
}

// ListProblems 分页列出题目，支持搜索与"只看评测集/只看有修复"。
func (h *Handler) ListProblems(c *gin.Context) {
	page, size := pageParams(c)
	q := h.db.Model(&model.Problem{})
	if v := c.Query("q"); v != "" {
		like := "%" + v + "%"
		q = q.Where("CAST(qid AS TEXT) LIKE ? OR title LIKE ?", like, like)
	}
	if c.Query("ft_only") == "1" {
		q = q.Where("in_ft_test = 1")
	}
	if c.Query("fixed_only") == "1" {
		q = q.Where("qid IN (SELECT qid FROM corpus_fixes)")
	}
	var total int64
	q.Count(&total)
	rows := []model.Problem{}
	if err := q.Order("qid").Offset((page - 1) * size).Limit(size).
		Find(&rows).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": rows, "total": total,
		"page": page, "page_size": size})
}

// GetProblem 单题明细：元数据、语料规模、修复记录、各模型的判定分布。
func (h *Handler) GetProblem(c *gin.Context) {
	qid, err := strconv.Atoi(c.Param("qid"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "qid 必须是数字"})
		return
	}
	var p model.Problem
	if err := h.db.Where("qid = ?", qid).First(&p).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "题目不存在"})
		return
	}
	var fixes []model.CorpusFix
	h.db.Where("qid = ?", qid).Find(&fixes)

	type slotRow struct {
		Model    string `json:"model"`
		Lang     string `json:"lang"`
		Task     string `json:"task"`
		Cand     int    `json:"cand"`
		Leetcode string `json:"leetcode"`
		Local    string `json:"local"`
		Klass    string `json:"klass"`
	}
	slots := []slotRow{}
	sw, sargs := scopeWhere(c.Query("scope"))
	where := "slots.qid = ? AND " + sw
	args := append([]any{qid}, sargs...)
	var total int64
	h.db.Model(&model.Slot{}).Where(where, args...).Count(&total)
	page, size := pageParams(c)
	h.db.Model(&model.Slot{}).
		Select("model,lang,task,cand,leetcode,local,klass").
		Where(where, args...).Order("model,lang,task,cand").
		Offset((page - 1) * size).Limit(size).Scan(&slots)
	c.JSON(http.StatusOK, gin.H{
		"problem": p, "fixes": fixes, "slots": slots, "total": total,
		"page": page, "page_size": size, "metrics": h.metrics(where, args...),
	})
}

// ListLocalResults 分页列出本地判题器直接产出的结果。
func (h *Handler) ListLocalResults(c *gin.Context) {
	page, size := pageParams(c)
	q := h.db.Model(&model.LocalResult{})
	if v := c.Query("qid"); v != "" {
		q = q.Where("qid = ?", v)
	}
	if v := c.Query("lang"); v != "" {
		q = q.Where("lang = ?", v)
	}
	if v := c.Query("ac_status"); v != "" {
		q = q.Where("ac_status = ?", v)
	}
	var total int64
	q.Count(&total)
	rows := []model.LocalResult{}
	if err := q.Order("qid,lang").Offset((page - 1) * size).Limit(size).
		Find(&rows).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": rows, "total": total,
		"page": page, "page_size": size})
}

// ListFixes 本次工作对语料的修复清单。
func (h *Handler) ListFixes(c *gin.Context) {
	type fixRow struct {
		QID         int    `gorm:"column:qid" json:"qid"`
		Title       string `json:"title"`
		CorpusCases int    `gorm:"column:corpus_cases" json:"corpus_cases"`
		Kind        string `json:"kind"`
		Note        string `json:"note"`
	}
	rows := []fixRow{}
	h.db.Table("corpus_fixes").
		Select(`corpus_fixes.qid, COALESCE(problems.title,'') AS title,
			COALESCE(problems.corpus_cases,0) AS corpus_cases,
			corpus_fixes.kind, corpus_fixes.note`).
		Joins("LEFT JOIN problems ON problems.qid = corpus_fixes.qid").
		Order("corpus_fixes.qid").Scan(&rows)
	c.JSON(http.StatusOK, gin.H{"data": rows})
}

// GetCompletionStats 兼容原前端的占位：按模型×语言的槽位数。
func (h *Handler) GetCompletionStats(c *gin.Context) {
	type row struct {
		ModelName string `json:"model_name"`
		Language  string `json:"language"`
		Completed int    `json:"completed"`
	}
	rows := []row{}
	// 同样要限定范围：否则"完成度"会把旧口径的槽位也算成已完成。
	sw, sargs := scopeWhere(c.Query("scope"))
	q := h.db.Model(&model.Slot{}).
		Select("model AS model_name, lang AS language, COUNT(*) AS completed").
		Where("lang <> ''")
	if sw != "" {
		q = q.Where(sw, sargs...)
	}
	q.Group("model, lang").Order("model_name, language").Scan(&rows)
	var ft int64
	h.db.Model(&model.Problem{}).Where("in_ft_test = 1").Count(&ft)
	c.JSON(http.StatusOK, gin.H{
		"benchmark_total": ft,
		"rows":            rows,
		"note":            "本地仪表盘：completed 是已对拍的槽位数",
	})
}

// GetModels 模型列表。
func (h *Handler) GetModels(c *gin.Context) {
	models := []string{}
	h.db.Model(&model.Run{}).Distinct().Order("model").Pluck("model", &models)
	c.JSON(http.StatusOK, gin.H{"models": models})
}

var _ = strings.TrimSpace
