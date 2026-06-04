package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/config"
	"github.com/m1inato/mcibench-board/internal/router"
	"github.com/m1inato/mcibench-board/internal/store"
)

func main() {
	cfgPath := flag.String("config", "", "配置文件路径（默认: ./config/config.yaml）")
	flag.Parse()

	// 1. 加载配置
	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Fatalf("[致命] 加载配置失败: %v", err)
	}
	log.Printf("[信息] 配置加载成功（端口: %d，模式: %s）", cfg.Server.Port, cfg.Server.Mode)
	if err := validateWebDist(cfg.Web.DistPath); err != nil {
		log.Fatalf("[致命] 前端静态目录配置无效: %v", err)
	}

	// 2. 初始化 SQLite 数据库
	db, err := store.InitDB(cfg.Database.Path)
	if err != nil {
		log.Fatalf("[致命] 初始化数据库失败: %v", err)
	}
	log.Println("[信息] 数据库初始化成功")

	// 3. 数据库必须随部署包提供
	if store.IsEmpty(db) {
		log.Fatalf("[致命] 数据库为空，请先运行 scripts/import_experiment_results.py 生成 mcibench.db")
	}

	// 4. 设置 Gin 运行模式
	gin.SetMode(cfg.Server.Mode)

	// 5. 注册路由并启动服务
	r := router.Setup(db, cfg)
	addr := fmt.Sprintf(":%d", cfg.Server.Port)
	log.Printf("[信息] 服务启动于 %s", addr)
	if err := r.Run(addr); err != nil {
		log.Fatalf("[致命] 服务启动失败: %v", err)
	}
}

func validateWebDist(distPath string) error {
	if distPath == "" {
		return nil
	}

	stat, err := os.Stat(distPath)
	if err != nil {
		return err
	}
	if !stat.IsDir() {
		return fmt.Errorf("%s 不是目录", distPath)
	}

	indexPath := filepath.Join(distPath, "index.html")
	if _, err := os.Stat(indexPath); err != nil {
		return err
	}
	return nil
}
