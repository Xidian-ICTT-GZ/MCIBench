package model

// Reference 参考题解模型
type Reference struct {
	ID         uint   `gorm:"primaryKey;autoIncrement" json:"id"`
	QID        int    `gorm:"column:qid;index:idx_ref_qid_lang" json:"qid,string"`
	Language   string `gorm:"column:language;index:idx_ref_qid_lang;size:20" json:"language"`
	AttemptNum int    `gorm:"column:attempt_num" json:"attempt_num"`
	Code       string `gorm:"column:code;type:text" json:"code"`
}
