package store

import (
	"fmt"
	"log"
	"os"
	"path/filepath"

	"github.com/m1inato/mcibench-board/internal/model"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// InitDB 初始化 SQLite 数据库连接，启用 WAL 模式并自动建表
func InitDB(dbPath string) (*gorm.DB, error) {
	// 确保数据库目录存在
	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("创建数据库目录失败: %w", err)
	}

	db, err := gorm.Open(sqlite.Open(dbPath+"?_journal_mode=WAL"), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		return nil, fmt.Errorf("连接 SQLite 失败: %w", err)
	}

	// 启用 WAL 模式以提升并发读性能
	sqlDB, err := db.DB()
	if err != nil {
		return nil, fmt.Errorf("获取底层 sql.DB 失败: %w", err)
	}
	if _, err := sqlDB.Exec("PRAGMA journal_mode=WAL"); err != nil {
		log.Printf("[警告] 设置 WAL 模式失败: %v", err)
	}
	if _, err := sqlDB.Exec("PRAGMA synchronous=NORMAL"); err != nil {
		log.Printf("[警告] 设置 synchronous 模式失败: %v", err)
	}

	// 自动迁移所有数据模型（建表/更新表结构）
	if err := db.AutoMigrate(
		&model.Problem{},
		&model.Submission{},
		&model.GenCode{},
		&model.Translation{},
		&model.GenerationPassK{},
		&model.TranslationPassK{},
		&model.Snippet{},
		&model.Reference{},
	); err != nil {
		return nil, fmt.Errorf("自动迁移失败: %w", err)
	}

	log.Println("[信息] SQLite 数据库初始化成功")
	return db, nil
}

// IsEmpty 检查数据库是否已填充数据
func IsEmpty(db *gorm.DB) bool {
	var count int64
	db.Model(&model.Problem{}).Count(&count)
	return count == 0
}
