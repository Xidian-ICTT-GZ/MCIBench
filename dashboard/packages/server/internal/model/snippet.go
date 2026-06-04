package model

// Snippet 函数/类接口模板模型
type Snippet struct {
	ID       uint   `gorm:"primaryKey;autoIncrement" json:"id"`
	QID      int    `gorm:"column:qid;uniqueIndex:idx_snippet_qid_lang" json:"qid,string"`
	Language string `gorm:"column:language;uniqueIndex:idx_snippet_qid_lang;size:20" json:"language"`
	Code     string `gorm:"column:code;type:text" json:"code"`
}
