package router

import (
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/auth"
	"github.com/m1inato/mcibench-board/internal/config"
	"github.com/m1inato/mcibench-board/internal/handler"
	"github.com/m1inato/mcibench-board/internal/middleware"
	"gorm.io/gorm"
)

// Setup 创建 Gin 引擎并注册所有路由。
//
// 与主仪表盘的差异：路由面向「本地判题 + 对拍」而不是「LeetCode 提交」。
// 核心新增是 /stats/agreement —— 本地判与 LeetCode 判的一致性分类。
func Setup(db *gorm.DB, cfg *config.Config, authStore *auth.Store) *gin.Engine {
	r := gin.Default()
	r.Use(middleware.CORS())
	// The browser is never allowed to assert identity. Only this ingress may,
	// and it only does so after validating the session cookie.
	r.Use(auth.StripIdentityHeaders())
	if authStore != nil {
		authStore.SecureCookie = cfg.Auth.SecureCookie
		r.Use(authStore.Middleware())
		authStore.Register(r)
		auth.SetAuditSink(authStore.Audit)
	}

	h := handler.NewHandler(db, cfg)

	v1 := r.Group("/api/v1")
	{
		v1.GET("/version", func(c *gin.Context) {
			c.JSON(http.StatusOK, gin.H{"build_id": cfg.BuildID})
		})
		// 总览
		v1.GET("/stats/overview", h.GetOverview)
		// 一致性分析（本仪表盘的核心）
		v1.GET("/stats/agreement", h.GetAgreement)
		v1.GET("/stats/model/:model", h.GetModelStats)
		v1.GET("/stats/completion", h.GetCompletionStats)

		// 明细
		v1.GET("/slots", h.ListSlots)
		v1.GET("/problems", h.ListProblems)
		v1.GET("/problems/:qid", h.GetProblem)
		v1.GET("/local_results", h.ListLocalResults)
		v1.GET("/fixes", h.ListFixes)

		// 配置
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

	// serveFile 直接读文件返回，不走 c.File：
	// http.ServeFile 对以 /index.html 结尾的请求会 301 到目录路径，
	// 目录请求再落回 SPA 兜底，静态看板就会被首页外壳顶掉。
	serveFile := func(c *gin.Context, path string) bool {
		stat, err := os.Stat(path)
		if err == nil && stat.IsDir() {
			path = filepath.Join(path, "index.html")
			stat, err = os.Stat(path)
		}
		if err != nil || stat.IsDir() {
			return false
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return false
		}
		if strings.HasPrefix(c.Request.URL.Path, "/assets/") {
			c.Header("Cache-Control", "public, max-age=31536000, immutable")
		} else {
			c.Header("Cache-Control", "no-cache")
		}
		contentType := mime.TypeByExtension(filepath.Ext(path))
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		c.Data(http.StatusOK, contentType, data)
		return true
	}

	r.NoRoute(func(c *gin.Context) {
		if strings.HasPrefix(c.Request.URL.Path, "/api/") {
			c.JSON(http.StatusNotFound, gin.H{"error": "api route not found"})
			return
		}

		requestPath := strings.TrimPrefix(c.Request.URL.Path, "/")
		if requestPath != "" && serveFile(c, filepath.Join(distPath, requestPath)) {
			return
		}
		// 带扩展名的路径缺文件就是真缺，不能回退到 index.html：
		// 否则浏览器把 HTML 当模块解析，动态 import 失败却不报 404。
		if ext := filepath.Ext(requestPath); ext != "" {
			c.Status(http.StatusNotFound)
			return
		}

		c.Header("Cache-Control", "no-cache")
		serveFile(c, indexPath)
	})
}
