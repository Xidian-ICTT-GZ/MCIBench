package model

import "time"

// Translation 代码翻译模型
type Translation struct {
	ID         uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	QID        int       `gorm:"column:qid;index:idx_trans_qid_model;uniqueIndex:idx_trans_unique" json:"qid,string"`
	ModelName  string    `gorm:"column:model_name;index:idx_trans_qid_model;uniqueIndex:idx_trans_unique;size:50" json:"model_name"`
	SrcLang    string    `gorm:"column:src_lang;uniqueIndex:idx_trans_unique;size:20" json:"src_lang"`
	TgtLang    string    `gorm:"column:tgt_lang;uniqueIndex:idx_trans_unique;size:20" json:"tgt_lang"`
	AttemptNum int       `gorm:"column:attempt_num;uniqueIndex:idx_trans_unique" json:"attempt_num"`
	Code       string    `gorm:"column:code;type:text" json:"code"`
	FilePath   string    `gorm:"column:file_path;size:512" json:"file_path"`
	CreatedAt  time.Time `json:"created_at"`
}
