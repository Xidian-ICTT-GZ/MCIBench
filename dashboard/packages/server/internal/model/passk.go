package model

// GenerationPassK stores per-model/per-problem/per-language generation pass@k.
type GenerationPassK struct {
	ID          uint    `gorm:"primaryKey;autoIncrement" json:"id"`
	ModelName   string  `gorm:"column:model_name;uniqueIndex:idx_gen_passk_unique;index;size:50" json:"model_name"`
	QID         int     `gorm:"column:qid;uniqueIndex:idx_gen_passk_unique;index" json:"qid,string"`
	Language    string  `gorm:"column:language;uniqueIndex:idx_gen_passk_unique;index;size:20" json:"language"`
	NCandidates int     `gorm:"column:n_candidates" json:"n_candidates"`
	PassAt1     float64 `gorm:"column:pass_at_1" json:"pass_at_1"`
	PassAt2     float64 `gorm:"column:pass_at_2" json:"pass_at_2"`
	PassAt3     float64 `gorm:"column:pass_at_3" json:"pass_at_3"`
	PassAt4     float64 `gorm:"column:pass_at_4" json:"pass_at_4"`
	PassAt5     float64 `gorm:"column:pass_at_5" json:"pass_at_5"`
}

// TranslationPassK stores per-model/per-problem/per-language-pair translation pass@k.
type TranslationPassK struct {
	ID          uint    `gorm:"primaryKey;autoIncrement" json:"id"`
	ModelName   string  `gorm:"column:model_name;uniqueIndex:idx_trans_passk_unique;index;size:50" json:"model_name"`
	QID         int     `gorm:"column:qid;uniqueIndex:idx_trans_passk_unique;index" json:"qid,string"`
	SrcLang     string  `gorm:"column:src_lang;uniqueIndex:idx_trans_passk_unique;index;size:20" json:"src_lang"`
	TgtLang     string  `gorm:"column:tgt_lang;uniqueIndex:idx_trans_passk_unique;index;size:20" json:"tgt_lang"`
	NCandidates int     `gorm:"column:n_candidates" json:"n_candidates"`
	PassAt1     float64 `gorm:"column:pass_at_1" json:"pass_at_1"`
	PassAt2     float64 `gorm:"column:pass_at_2" json:"pass_at_2"`
	PassAt3     float64 `gorm:"column:pass_at_3" json:"pass_at_3"`
	PassAt4     float64 `gorm:"column:pass_at_4" json:"pass_at_4"`
	PassAt5     float64 `gorm:"column:pass_at_5" json:"pass_at_5"`
}
