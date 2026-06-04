package router

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/config"
	"github.com/m1inato/mcibench-board/internal/handler"
	"github.com/m1inato/mcibench-board/internal/middleware"
	"gorm.io/gorm"
)

// Setup 创建 Gin 引擎并注册所有路由
func Setup(db *gorm.DB, cfg *config.Config) *gin.Engine {
	r := gin.Default()

	// 全局中间件
	r.Use(middleware.CORS())

	// 初始化处理器
	h := handler.NewHandler(db, cfg)

	// API v1 路由组
	v1 := r.Group("/api/v1")
	{
		// 题目端点
		v1.GET("/problems", h.ListProblems)
		v1.GET("/problems/:qid", h.GetProblem)

		// 提交记录端点
		v1.GET("/submissions", h.ListSubmissions)

		// 生成代码与翻译端点
		v1.GET("/gencode/:qid", h.GetGenCode)
		v1.GET("/translations/:qid", h.GetTranslations)

		// 统计端点
		v1.GET("/stats/overview", h.GetStatsOverview)
		v1.GET("/stats/model/:model", h.GetModelStats)
		v1.GET("/stats/completion", h.GetCompletionStats)
		v1.GET("/stats/passk", h.GetPassKDashboard)

		// 配置端点
		v1.GET("/config/models", h.GetModels)
	}

	if cfg.Web.DistPath != "" {
		registerStaticFrontend(r, cfg.Web.DistPath)
	}

	return r
}

func registerStaticFrontend(r *gin.Engine, distPath string) {
	distPath = filepath.Clean(distPath)
	indexPath := filepath.Join(distPath, "index.html")

	r.NoRoute(func(c *gin.Context) {
		if strings.HasPrefix(c.Request.URL.Path, "/api/") {
			c.JSON(http.StatusNotFound, gin.H{"error": "api route not found"})
			return
		}

		requestPath := strings.TrimPrefix(c.Request.URL.Path, "/")
		if requestPath != "" {
			filePath := filepath.Join(distPath, requestPath)
			if stat, err := os.Stat(filePath); err == nil && !stat.IsDir() {
				c.File(filePath)
				return
			}
		}

		c.File(indexPath)
	})
}
