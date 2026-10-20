package model

// 本文件是 local/dashboard 的数据模型，对应 `scripts/import_local_results.py`
// 建出的 local.db。表结构由那个脚本负责，这里的字段必须与之一致
// （AutoMigrate 在字段匹配时是空操作）。
//
// 与主仪表盘的关键差异：主库的 source_type 只有 generation/translation
// （任务维度）；本地库额外引入 klass ——「本地判 vs LeetCode 判」的分类，
// 这才是本地判题层要回答的问题。

// Problem 题目。corpus_cases 是本地语料条数，0 表示不在本地评测集内。
type Problem struct {
	QID                    int    `gorm:"column:qid;primaryKey" json:"qid"`
	Title                  string `gorm:"column:title" json:"title"`
	Slug                   string `gorm:"column:slug" json:"slug"`
	Difficulty             string `gorm:"column:difficulty" json:"difficulty"`
	URL                    string `gorm:"column:url" json:"url"`
	IsBenchmark            int    `gorm:"column:is_benchmark" json:"is_benchmark"`
	IsGenerationBenchmark  int    `gorm:"column:is_generation_benchmark" json:"is_generation_benchmark"`
	IsTranslationBenchmark int    `gorm:"column:is_translation_benchmark" json:"is_translation_benchmark"`
	CorpusCases            int    `gorm:"column:corpus_cases" json:"corpus_cases"`
	InFTTest               int    `gorm:"column:in_ft_test" json:"in_ft_test"`
}

func (Problem) TableName() string { return "problems" }

// Run 一次评测运行（一个模型的一个任务）。
type Run struct {
	Run        string `gorm:"column:run;primaryKey" json:"run"`
	Model      string `gorm:"column:model" json:"model"`
	Task       string `gorm:"column:task" json:"task"`
	SourceType string `gorm:"column:source_type" json:"source_type"`
	Slots      int    `gorm:"column:slots" json:"slots"`
	LocalAC    int    `gorm:"column:local_ac" json:"local_ac"`
	LeetcodeAC int    `gorm:"column:leetcode_ac" json:"leetcode_ac"`
}

func (Run) TableName() string { return "runs" }

// Slot 一个「本地判 vs LeetCode 判」的配对槽位。整个仪表盘的核心。
type Slot struct {
	ID             uint   `gorm:"column:id;primaryKey" json:"id"`
	Run            string `gorm:"column:run;index" json:"run"`
	Model          string `gorm:"column:model;index" json:"model"`
	Task           string `gorm:"column:task" json:"task"`
	SourceType     string `gorm:"column:source_type" json:"source_type"`
	QID            int    `gorm:"column:qid;index" json:"qid"`
	Lang           string `gorm:"column:lang" json:"lang"`
	SrcLang        string `gorm:"column:src_lang" json:"src_lang"`
	TgtLang        string `gorm:"column:tgt_lang" json:"tgt_lang"`
	Cand           int    `gorm:"column:cand" json:"cand"`
	Leetcode       string `gorm:"column:leetcode" json:"leetcode"`
	Local          string `gorm:"column:local" json:"local"`
	Klass          string `gorm:"column:klass;index" json:"klass"`
	LCOrigin       string `gorm:"column:lc_origin" json:"lc_origin"`
	LocalOrigin    string `gorm:"column:local_origin" json:"local_origin"`
	Stale          int    `gorm:"column:stale" json:"stale"`
	IdentityStatus string `gorm:"column:identity_status" json:"identity_status"`
	IdentityReason string `gorm:"column:identity_reason" json:"identity_reason"`
	HasCorpus      int    `gorm:"column:has_corpus" json:"has_corpus"`
}

func (Slot) TableName() string { return "slots" }

// LocalResult 本地判题器直接产出的 9 字段结果（与 LeetCode schema 同构）。
type LocalResult struct {
	IdentityStatus string `gorm:"column:identity_status" json:"identity_status"`
	IdentityReason string `gorm:"column:identity_reason" json:"identity_reason"`
	ID             uint   `gorm:"column:id;primaryKey" json:"id"`
	RunName        string `gorm:"column:run_name" json:"run_name"`
	Model          string `gorm:"column:model" json:"model"`
	Task           string `gorm:"column:task" json:"task"`
	SourceType     string `gorm:"column:source_type" json:"source_type"`
	QID            int    `gorm:"column:qid;index" json:"qid"`
	Lang           string `gorm:"column:lang" json:"lang"`
	SrcLang        string `gorm:"column:src_lang" json:"src_lang"`
	TgtLang        string `gorm:"column:tgt_lang" json:"tgt_lang"`
	Cand           int    `gorm:"column:cand" json:"cand"`
	State          string `gorm:"column:state" json:"state"`
	ACStatus       string `gorm:"column:ac_status" json:"ac_status"`
	TotalTestcases int    `gorm:"column:total_testcases" json:"total_testcases"`
	TotalCorrect   int    `gorm:"column:total_correct" json:"total_correct"`
	Runtime        string `gorm:"column:runtime" json:"runtime"`
	Memory         string `gorm:"column:memory" json:"memory"`
}

func (LocalResult) TableName() string { return "local_results" }

// CorpusFix 本次工作对语料的修复记录，供前端标注。
type CorpusFix struct {
	QID  int    `gorm:"column:qid" json:"qid"`
	Kind string `gorm:"column:kind" json:"kind"`
	Note string `gorm:"column:note" json:"note"`
}

func (CorpusFix) TableName() string { return "corpus_fixes" }

// ExcludedModel 被排除出统计的模型及原因。
//
// 排除不是删除——原始判题结果仍在 local/results/all_models/ 下。
// 但**必须把"排除了谁、为什么"显示出来**，否则看数的人不知道少了哪几块。
type ExcludedModel struct {
	Model  string `gorm:"column:model;primaryKey" json:"model"`
	Reason string `gorm:"column:reason" json:"reason"`
}

func (ExcludedModel) TableName() string { return "excluded_models" }
