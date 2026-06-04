package model

import "time"

// Submission 提交结果模型
type Submission struct {
	ID                uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	QID               int       `gorm:"column:qid;index:idx_sub_qid_model_lang;uniqueIndex:idx_sub_unique" json:"qid,string"`
	ModelName         string    `gorm:"column:model_name;index:idx_sub_qid_model_lang;uniqueIndex:idx_sub_unique;size:50" json:"model_name"`
	Language          string    `gorm:"column:language;index:idx_sub_qid_model_lang;uniqueIndex:idx_sub_unique;size:20" json:"language"`
	SrcLang           string    `gorm:"column:src_lang;uniqueIndex:idx_sub_unique;size:20" json:"src_lang"`
	TgtLang           string    `gorm:"column:tgt_lang;uniqueIndex:idx_sub_unique;size:20" json:"tgt_lang"`
	AttemptNum        int       `gorm:"column:attempt_num;uniqueIndex:idx_sub_unique" json:"attempt_num"`
	SubmitID          int64     `gorm:"column:submit_id" json:"submit_id"`
	State             string    `gorm:"column:state;size:20" json:"state"`
	ACStatus          string    `gorm:"column:ac_status;size:50" json:"ac_status"`
	TotalTestcases    int       `gorm:"column:total_testcases" json:"total_testcases"`
	TotalCorrect      int       `gorm:"column:total_correct" json:"total_correct"`
	Runtime           string    `gorm:"column:runtime;size:50" json:"runtime"`
	RuntimePercentile float64   `gorm:"column:runtime_percentile" json:"runtime_percentile"`
	Memory            string    `gorm:"column:memory;size:50" json:"memory"`
	MemoryPercentile  float64   `gorm:"column:memory_percentile" json:"memory_percentile"`
	SourceType        string    `gorm:"column:source_type;index;uniqueIndex:idx_sub_unique;size:20" json:"source_type"`
	SourceDir         string    `gorm:"column:source_dir;size:100" json:"source_dir"`
	CreatedAt         time.Time `json:"created_at"`
}

// SubmissionJSON 对应 Submit_Results 目录下 JSON 文件的结构
type SubmissionJSON struct {
	SubmitID          int64   `json:"submit_id"`
	State             string  `json:"state"`
	ACStatus          string  `json:"ac_status"`
	TotalTestcases    int     `json:"total_testcases"`
	TotalCorrect      int     `json:"total_correct"`
	Runtime           string  `json:"runtime"`
	RuntimePercentile float64 `json:"runtime_percentile"`
	Memory            string  `json:"memory"`
	MemoryPercentile  float64 `json:"memory_percentile"`
}
