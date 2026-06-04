package model

import "time"

// GenCode LLM 生成代码模型
type GenCode struct {
	ID         uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	QID        int       `gorm:"column:qid;index:idx_gen_qid_model_lang;uniqueIndex:idx_gen_unique" json:"qid,string"`
	ModelName  string    `gorm:"column:model_name;index:idx_gen_qid_model_lang;uniqueIndex:idx_gen_unique;size:50" json:"model_name"`
	Language   string    `gorm:"column:language;index:idx_gen_qid_model_lang;uniqueIndex:idx_gen_unique;size:20" json:"language"`
	AttemptNum int       `gorm:"column:attempt_num;uniqueIndex:idx_gen_unique" json:"attempt_num"`
	Code       string    `gorm:"column:code;type:text" json:"code"`
	FilePath   string    `gorm:"column:file_path;size:512" json:"file_path"`
	CreatedAt  time.Time `json:"created_at"`
}
