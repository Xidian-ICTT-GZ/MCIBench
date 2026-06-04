# MCIBench 服务器部署指南

## 包内容

```text
mcibench/
├── config/config.yaml
├── data/mcibench.db
├── mcibench-server            # 在服务器上构建生成
├── scripts/build.sh
├── scripts/start.sh
├── scripts/install-systemd.sh
├── server/                    # Go 后端源码
├── systemd/mcibench.service
└── web/                       # 已构建前端静态文件
```

当前统计口径：

- 代码生成任务固定按 1489 道题计算。
- 八种语言固定按 `C, C++, C#, Java, JavaScript, Python3, Rust, Golang` 计算。
- 代码互译任务固定按 100 道题、56 个有向语言对计算。
- 缺少结果的题目或方向按 0 分计入 Pass@k。
- Detail 页面中 Generated Codes 和 Translation Results 按模型、语言/互译方向分组，每组展示 ans1 到 ans5。

## 0. 服务器要求

- 系统：Ubuntu 20.04/22.04/24.04 或 Debian 11/12。
- 内存：建议 2GB 以上。
- 磁盘：建议预留 2GB 以上。
- 端口：默认使用 8080。
- 权限：需要 sudo 权限安装依赖、注册 systemd、开放端口。

下面假设部署目录为 `/opt/mcibench`，域名或 IP 用 `SERVER_IP` 表示。

## 1. 准备服务器依赖

以下命令适用于 Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y build-essential ca-certificates curl tar sqlite3
```

安装 Go 1.25 或更高版本。服务器已有 Go 时检查：

```bash
go version
```

Go 版本低于 1.25 时安装新版 Go：

```bash
cd /tmp
curl -LO https://go.dev/dl/go1.25.0.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.25.0.linux-amd64.tar.gz
echo 'export PATH=/usr/local/go/bin:$PATH' >> ~/.bashrc
export PATH=/usr/local/go/bin:$PATH
go version
```

确认 gcc 可用：

```bash
gcc --version
```

Go 后端使用 SQLite CGO 驱动，服务器必须有 gcc/build-essential。

## 2. 上传压缩包

在本地执行：

```bash
scp mcibench-deploy-20260603.tgz root@SERVER_IP:/opt/
```

使用普通用户部署时：

```bash
scp mcibench-deploy-20260603.tgz USER@SERVER_IP:/home/USER/
ssh USER@SERVER_IP
sudo mkdir -p /opt/mcibench
sudo tar -xzf /home/USER/mcibench-deploy-20260603.tgz -C /opt/mcibench --strip-components=1
sudo chown -R USER:USER /opt/mcibench
cd /opt/mcibench
```

使用 root 部署时：

```bash
ssh root@SERVER_IP
sudo mkdir -p /opt/mcibench
sudo tar -xzf /opt/mcibench-deploy-20260603.tgz -C /opt/mcibench --strip-components=1
cd /opt/mcibench
```

检查文件：

```bash
ls -lah
ls -lah data web server scripts config systemd
```

## 3. 构建后端

```bash
bash scripts/build.sh
```

构建成功后会生成：

```text
/opt/mcibench/mcibench-server
```

## 4. 配置端口和数据库

默认配置文件：

```bash
cat /opt/mcibench/config/config.yaml
```

默认内容：

```yaml
server:
  port: 8080
  mode: release

database:
  path: ./data/mcibench.db

web:
  dist_path: ./web
```

修改端口示例：

```bash
sed -i 's/port: 8080/port: 9000/' /opt/mcibench/config/config.yaml
```

数据库文件路径保持 `./data/mcibench.db`，前端静态文件路径保持 `./web`。

## 5. 前台试运行

```bash
bash scripts/start.sh
```

看到服务启动后访问：

```text
http://SERVER_IP:8080/
```

检查接口：

```bash
curl http://127.0.0.1:8080/api/v1/stats/overview
curl http://127.0.0.1:8080/api/v1/stats/passk
```

接口应返回 JSON，浏览器应打开 Dashboard。

停止前台运行：按 `Ctrl+C`。

## 6. systemd 持续运行

```bash
sudo bash scripts/install-systemd.sh
```

常用命令：

```bash
sudo systemctl status mcibench
sudo systemctl restart mcibench
sudo journalctl -u mcibench -f
```

systemd 服务文件位置：

```text
/etc/systemd/system/mcibench.service
```

服务启动目录：

```text
/opt/mcibench
```

服务启动命令：

```text
/opt/mcibench/mcibench-server -config /opt/mcibench/config/config.yaml
```

## 7. 开放端口

服务默认监听 `8080`。

直接开放端口：

```bash
sudo ufw allow 8080/tcp
```

云服务器还需要在控制台安全组开放入站 TCP 8080：

- 阿里云：ECS 安全组入方向添加 TCP 8080。
- 腾讯云：CVM 安全组入站规则添加 TCP 8080。
- AWS：EC2 Security Group inbound rule 添加 TCP 8080。
- Azure：Network Security Group inbound rule 添加 TCP 8080。

检查监听：

```bash
ss -lntp | grep 8080
curl http://127.0.0.1:8080/
```

外网访问：

```text
http://SERVER_IP:8080/
```

## 8. Nginx 反向代理

安装 Nginx：

```bash
sudo apt install -y nginx
```

Nginx 反向代理示例：

```nginx
server {
    listen 80;
    server_name your.domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

保存为：

```text
/etc/nginx/sites-available/mcibench
```

启用配置：

```bash
sudo ln -sf /etc/nginx/sites-available/mcibench /etc/nginx/sites-enabled/mcibench
sudo nginx -t
sudo systemctl reload nginx
sudo ufw allow 80/tcp
```

此时访问：

```text
http://your.domain.com/
```

## 9. 数据校验

部署后应看到：

```text
problems = 2944
generation_benchmark_problems = 1489
translation_benchmark_problems = 100
generation Pass@k rows = 119120
translation Pass@k rows = 28000
```

SQLite 校验：

```bash
sqlite3 /opt/mcibench/data/mcibench.db 'pragma integrity_check;'
```

关键表数量：

```bash
sqlite3 /opt/mcibench/data/mcibench.db \
"select 'problems', count(*) from problems
 union all select 'generation_pass_ks', count(*) from generation_pass_ks
 union all select 'translation_pass_ks', count(*) from translation_pass_ks
 union all select 'gen_codes', count(*) from gen_codes
 union all select 'translations', count(*) from translations
 union all select 'submissions', count(*) from submissions;"
```

## 10. 更新部署包

上传新包后：

```bash
sudo systemctl stop mcibench
sudo rm -rf /opt/mcibench.new
sudo mkdir -p /opt/mcibench.new
sudo tar -xzf /opt/mcibench-deploy-20260603.tgz -C /opt/mcibench.new --strip-components=1
sudo cp -a /opt/mcibench/config/config.yaml /opt/mcibench.new/config/config.yaml
sudo mv /opt/mcibench /opt/mcibench.bak.$(date +%Y%m%d%H%M%S)
sudo mv /opt/mcibench.new /opt/mcibench
cd /opt/mcibench
bash scripts/build.sh
sudo bash scripts/install-systemd.sh
```

## 11. 常见问题

### 页面显示 No data

检查后端接口：

```bash
curl http://127.0.0.1:8080/api/v1/stats/passk
```

检查数据库：

```bash
sqlite3 /opt/mcibench/data/mcibench.db 'select count(*) from generation_pass_ks;'
sqlite3 /opt/mcibench/data/mcibench.db 'select count(*) from translation_pass_ks;'
```

### 端口无法访问

检查服务：

```bash
sudo systemctl status mcibench
ss -lntp | grep 8080
```

检查系统防火墙和云安全组，确保 TCP 8080 或 Nginx 的 TCP 80 已开放。

### 构建失败提示 gcc/CGO

安装编译依赖：

```bash
sudo apt install -y build-essential
```

重新构建：

```bash
cd /opt/mcibench
bash scripts/build.sh
```
