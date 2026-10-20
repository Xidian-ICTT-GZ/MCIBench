// Command admin bootstraps and maintains local accounts.
//
// Passwords are generated, never accepted: an operator-typed password ends up in
// shell history or a terminal scrollback. The generated value is printed once.
package main

import (
	"crypto/rand"
	"flag"
	"fmt"
	"math/big"
	"os"

	"github.com/m1inato/mcibench-board/internal/auth"
	"github.com/m1inato/mcibench-board/internal/config"
)

const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+"

func generatePassword(length int) (string, error) {
	out := make([]byte, length)
	limit := big.NewInt(int64(len(alphabet)))
	for i := range out {
		index, err := rand.Int(rand.Reader, limit)
		if err != nil {
			return "", err
		}
		out[i] = alphabet[index.Int64()]
	}
	return string(out), nil
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}

func main() {
	cfgPath := flag.String("config", "", "配置文件路径（默认: ./config/config.yaml）")
	command := flag.String("command", "bootstrap", "bootstrap | reset")
	username := flag.String("user", "admin", "账号名")
	// The bootstrap account is always an administrator: allowing an evaluator here
	// would produce an installation with no admin that can never be bootstrapped again.
	_ = flag.String("role", auth.RoleAdmin, "已固定为 admin；保留参数仅为兼容旧命令")
	length := flag.Int("length", 20, "生成密码长度（至少 12）")
	flag.Parse()

	if *length < 12 {
		fail("密码长度至少 12 位")
	}
	cfg, err := config.Load(*cfgPath)
	if err != nil {
		fail("加载配置失败: %v", err)
	}
	store, err := auth.Open(cfg.Auth.DatabasePath, cfg.Auth.SessionHours)
	if err != nil {
		fail("打开认证数据库失败: %v", err)
	}
	defer store.Close()

	switch *command {
	case "bootstrap":
		total, err := store.Count()
		if err != nil {
			fail("读取账号失败: %v", err)
		}
		if total > 0 {
			fail("数据库已有 %d 个账号，拒绝再创建引导管理员；请使用 -command reset -user <账号>", total)
		}
		password, err := generatePassword(*length)
		if err != nil {
			fail("生成密码失败: %v", err)
		}
		user, err := store.CreateUser(*username, password, auth.RoleAdmin)
		if err != nil {
			fail("创建账号失败: %v", err)
		}
		fmt.Printf("已创建账号 %s（%s），id=%d\n", user.Username, user.Role, user.ID)
		fmt.Printf("一次性初始密码：%s\n", password)
		fmt.Printf("请立即登录并修改密码；该密码不会再次显示，也不会写入日志。\n")
	case "reset":
		user, err := store.UserByName(*username)
		if err != nil {
			fail("账号不存在: %v", err)
		}
		password, err := generatePassword(*length)
		if err != nil {
			fail("生成密码失败: %v", err)
		}
		if err := store.SetPassword(user.ID, password); err != nil {
			fail("重置密码失败: %v", err)
		}
		fmt.Printf("已重置账号 %s 的密码，原有会话已失效\n", user.Username)
		fmt.Printf("一次性新密码：%s\n", password)
	default:
		fail("未知命令: %s（支持 bootstrap | reset）", *command)
	}
}
