// Package lab manages the Python execution service and same-origin proxy.
package lab

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/m1inato/mcibench-board/internal/auth"
	"github.com/m1inato/mcibench-board/internal/config"
)

type Service struct {
	cmd   *exec.Cmd
	url   string
	token string
	done  chan error
}

func Start(cfg *config.Config) (*Service, error) {
	root, err := filepath.Abs(cfg.Lab.WorkspaceRoot)
	if err != nil {
		return nil, err
	}
	if _, err := os.Stat(filepath.Join(root, "local", "lab", "server.py")); err != nil {
		return nil, fmt.Errorf("lab.workspace_root 未指向 MCIBench 仓库: %w", err)
	}
	db, err := filepath.Abs(cfg.Database.Path)
	if err != nil {
		return nil, err
	}
	data, err := filepath.Abs(cfg.Lab.DataPath)
	if err != nil {
		return nil, err
	}
	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		return nil, err
	}
	s := &Service{token: hex.EncodeToString(secret), done: make(chan error, 1)}
	s.cmd = exec.Command(cfg.Lab.PythonPath, "-u", "-X", "utf8", "-m", "local.lab.server", "--port", "0", "--data", data, "--benchmark-db", db)
	s.cmd.Dir = root
	s.cmd.Env = append(os.Environ(), "MCIBENCH_LAB_TOKEN="+s.token)
	s.cmd.Stderr = os.Stderr
	stdout, err := s.cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err := s.cmd.Start(); err != nil {
		return nil, err
	}
	go func() { s.done <- s.cmd.Wait() }()
	ready := make(chan string, 1)
	go func() {
		reader := bufio.NewReader(stdout)
		line, _ := reader.ReadString('\n')
		ready <- line
		io.Copy(io.Discard, reader)
	}()
	select {
	case line := <-ready:
		var data struct {
			Port int `json:"port"`
		}
		if err := json.Unmarshal([]byte(line), &data); err != nil || data.Port < 1 {
			s.cmd.Process.Kill()
			return nil, fmt.Errorf("Python 实验服务未启动；请检查 Python 路径和 numpy 依赖")
		}
		s.url = fmt.Sprintf("http://127.0.0.1:%d", data.Port)
	case <-time.After(15 * time.Second):
		s.cmd.Process.Kill()
		return nil, fmt.Errorf("Python 实验服务启动超时")
	}
	log.Printf("[信息] 代码评测实验服务已就绪")
	return s, nil
}

func (s *Service) Close() {
	req, _ := http.NewRequest(http.MethodPost, s.url+"/api/v1/lab/shutdown", nil)
	req.Header.Set("X-Lab-Token", s.token)
	client := &http.Client{Timeout: 3 * time.Second}
	if res, err := client.Do(req); err == nil {
		res.Body.Close()
	}
	select {
	case <-s.done:
	case <-time.After(30 * time.Second):
		s.cmd.Process.Kill()
	}
}

func AllowedOrigin(origin, host string) bool {
	if origin == "" {
		return true
	}
	u, err := url.Parse(origin)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return false
	}
	if u.Host == host {
		return true
	}
	return u.Scheme == "http" && (u.Host == "localhost:5199" || u.Host == "127.0.0.1:5199")
}

// labAuditObject extracts the addressed entity so an audit row names its target.
func labAuditObject(path string) string {
	segments := strings.Split(strings.Trim(path, "/"), "/")
	if len(segments) >= 2 && (segments[0] == "jobs" || segments[0] == "models") {
		return segments[0] + "/" + segments[1]
	}
	if len(segments) >= 1 && segments[0] != "" {
		return segments[0]
	}
	return ""
}

func (s *Service) Register(r *gin.Engine) {
	target, _ := url.Parse(s.url)
	proxy := httputil.NewSingleHostReverseProxy(target)
	original := proxy.Director
	proxy.Director = func(req *http.Request) {
		original(req)
		req.Header.Set("X-Lab-Token", s.token)
		req.Header.Del("Authorization")
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		io.WriteString(w, `{"error":"实验服务暂不可用，请重启仪表盘"}`)
	}
	r.Any("/api/v1/lab/*path", func(c *gin.Context) {
		host := strings.Split(c.Request.Host, ":")[0]
		if host != "localhost" && host != "127.0.0.1" || !AllowedOrigin(c.GetHeader("Origin"), c.Request.Host) {
			c.JSON(http.StatusForbidden, gin.H{"error": "实验管理仅允许本地仪表盘访问"})
			return
		}
		if c.Param("path") == "/shutdown" {
			c.Status(http.StatusNotFound)
			return
		}
		needsJSON := c.Request.Method == http.MethodPost || c.Request.Method == http.MethodPut || c.Request.Method == http.MethodPatch
		if needsJSON && !strings.HasPrefix(c.GetHeader("Content-Type"), "application/json") {
			c.JSON(http.StatusUnsupportedMediaType, gin.H{"error": "请使用 JSON 请求"})
			return
		}
		c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1024*1024)
		proxy.ServeHTTP(c.Writer, c.Request)
		// Task-level audit: only mutations, and only for an authenticated operator.
		// The Python worker cannot record this because it never sees the identity.
		if method := c.Request.Method; method != http.MethodGet && method != http.MethodHead {
			if user, ok := auth.CurrentUser(c); ok {
				auth.Record(user, method+" /api/v1/lab"+c.Param("path"),
					labAuditObject(c.Param("path")), "http:"+strconv.Itoa(c.Writer.Status()))
			}
		}
	})
}
