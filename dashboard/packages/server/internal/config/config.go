package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

// Config 应用全局配置结构体
type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Database DatabaseConfig `mapstructure:"database"`
	Web      WebConfig      `mapstructure:"web"`
}

// ServerConfig 服务器配置
type ServerConfig struct {
	Port int    `mapstructure:"port"`
	Mode string `mapstructure:"mode"`
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
	v.SetDefault("server.mode", "debug")
	v.SetDefault("database.path", "./data/mcibench.db")
	v.SetDefault("web.dist_path", "")

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
