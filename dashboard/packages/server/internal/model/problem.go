package model

import "time"

// Problem 题目模型，对应 LeetCode 编程题
type Problem struct {
	ID                     uint      `gorm:"primaryKey;autoIncrement" json:"id"`
	QID                    int       `gorm:"column:qid;uniqueIndex" json:"qid,string"`
	TID                    string    `gorm:"column:tid;index;size:20" json:"tid"`
	Title                  string    `gorm:"column:title;size:255" json:"title"`
	Slug                   string    `gorm:"column:slug;index;size:255" json:"slug"`
	URL                    string    `gorm:"column:url;size:512" json:"url"`
	Description            string    `gorm:"column:description;type:text" json:"description"`
	Difficulty             string    `gorm:"column:difficulty;size:20" json:"difficulty"`
	IsBenchmark            bool      `gorm:"column:is_benchmark;index" json:"is_benchmark"`
	IsGenerationBenchmark  bool      `gorm:"column:is_generation_benchmark;index" json:"is_generation_benchmark"`
	IsTranslationBenchmark bool      `gorm:"column:is_translation_benchmark;index" json:"is_translation_benchmark"`
	CreatedAt              time.Time `json:"created_at"`
	UpdatedAt              time.Time `json:"updated_at"`
}
