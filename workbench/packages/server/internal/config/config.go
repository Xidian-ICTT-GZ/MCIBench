package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

// Config 应用全局配置结构体
type Config struct {
	BuildID  string         `mapstructure:"-"`
	Server   ServerConfig   `mapstructure:"server"`
	Database DatabaseConfig `mapstructure:"database"`
	Web      WebConfig      `mapstructure:"web"`
	Lab      LabConfig      `mapstructure:"lab"`
	Auth     AuthConfig     `mapstructure:"auth"`
}

// AuthConfig 最小登录与权限。默认关闭，启用需要先创建首个管理员。
type AuthConfig struct {
	Enabled      bool   `mapstructure:"enabled"`
	DatabasePath string `mapstructure:"database_path"`
	SessionHours int    `mapstructure:"session_hours"`
	SecureCookie bool   `mapstructure:"secure_cookie"`
}

// ServerConfig 服务器配置
type ServerConfig struct {
	Host string `mapstructure:"host"`
	Port int    `mapstructure:"port"`
	Mode string `mapstructure:"mode"`
}

type LabConfig struct {
	Enabled       bool   `mapstructure:"enabled"`
	PythonPath    string `mapstructure:"python_path"`
	WorkspaceRoot string `mapstructure:"workspace_root"`
	DataPath      string `mapstructure:"data_path"`
}

// DatabaseConfig 数据库配置
type DatabaseConfig struct {
	Path string `mapstructure:"path"`
}

// WebConfig 前端静态资源配置
type WebConfig struct {
	DistPath string `mapstructure:"dist_path"`
}

// Load 从文件和环境变量中读取配置
func Load(cfgPath string) (*Config, error) {
	v := viper.New()

	// 默认值
	v.SetDefault("server.port", 8080)
	v.SetDefault("server.host", "127.0.0.1")
	v.SetDefault("server.mode", "debug")
	v.SetDefault("database.path", "./data/mcibench.db")
	v.SetDefault("web.dist_path", "")
	v.SetDefault("lab.enabled", false)
	v.SetDefault("lab.python_path", "python")
	v.SetDefault("lab.workspace_root", "../../../..")
	v.SetDefault("lab.data_path", "./data/lab.sqlite3")
	v.SetDefault("auth.enabled", false)
	v.SetDefault("auth.database_path", "./data/auth.sqlite3")
	v.SetDefault("auth.session_hours", 8)
	v.SetDefault("auth.secure_cookie", false)

	// 配置文件路径
	if cfgPath != "" {
		v.SetConfigFile(cfgPath)
	} else {
		v.SetConfigName("config")
		v.SetConfigType("yaml")
		v.AddConfigPath("./config")
		v.AddConfigPath(".")
	}

	// 环境变量覆盖（前缀 MCIBENCH，如 MCIBENCH_SERVER_PORT）
	v.SetEnvPrefix("MCIBENCH")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	// 读取配置文件
	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("读取配置文件失败: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("解析配置结构失败: %w", err)
	}

	return &cfg, nil
}
