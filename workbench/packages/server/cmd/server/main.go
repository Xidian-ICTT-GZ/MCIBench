package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/auth"
	"github.com/m1inato/mcibench-board/internal/config"
	"github.com/m1inato/mcibench-board/internal/lab"
	"github.com/m1inato/mcibench-board/internal/router"
	"github.com/m1inato/mcibench-board/internal/store"
)

var buildID = "development"

func main() {
	cfgPath := flag.String("config", "", "配置文件路径（默认: ./config/config.yaml）")
	flag.Parse()

	// 1. 加载配置
	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Fatalf("[致命] 加载配置失败: %v", err)
	}
	cfg.BuildID = buildID
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
		log.Fatalf("[致命] 数据库为空，请先在仓库根目录运行：" +
			"python -m local.dashboard.scripts.import_local_results")
	}

	// 4. 设置 Gin 运行模式
	gin.SetMode(cfg.Server.Mode)

	// 5. 认证：默认关闭；启用前必须已有账号，避免把所有人挡在门外
	var authStore *auth.Store
	if cfg.Auth.Enabled {
		authStore, err = auth.Open(cfg.Auth.DatabasePath, cfg.Auth.SessionHours)
		if err != nil {
			log.Fatalf("[致命] 初始化认证数据库失败: %v", err)
		}
		defer authStore.Close()
		total, countErr := authStore.Count()
		if countErr != nil {
			log.Fatalf("[致命] 读取账号失败: %v", countErr)
		}
		if total == 0 {
			log.Fatalf("[致命] 认证已启用但没有账号；请先运行 " +
				"go run ./cmd/admin -command bootstrap -config ./config/config.yaml")
		}
		log.Printf("[信息] 认证已启用（会话 %d 小时，账号 %d 个）", authStore.SessionHours, total)
	}

	// 6. 注册路由并启动服务
	r := router.Setup(db, cfg, authStore)
	if cfg.Lab.Enabled {
		service, err := lab.Start(cfg)
		if err != nil {
			log.Fatalf("[致命] 启动实验服务失败: %v", err)
		}
		defer service.Close()
		service.Register(r)
	}
	addr := fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port)
	log.Printf("[信息] 服务启动于 %s", addr)
	server := &http.Server{Addr: addr, Handler: r, ReadHeaderTimeout: 10 * time.Second}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		server.Shutdown(ctx)
	}()
	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Printf("[错误] 服务启动失败: %v", err)
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
