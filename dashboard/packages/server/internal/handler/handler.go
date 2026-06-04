package handler

import (
	"github.com/m1inato/mcibench-board/internal/config"
	"gorm.io/gorm"
)

// Handler 持有所有 HTTP 处理器的应用级依赖
type Handler struct {
	DB *gorm.DB
}

// NewHandler 创建新的 Handler 实例
func NewHandler(db *gorm.DB, cfg *config.Config) *Handler {
	return &Handler{DB: db}
}
