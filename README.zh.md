# MCIBench：多语言代码智能基准

[English](README.en.md) | [中文](README.zh.md)

MCIBench 用于评估大语言模型的多语言代码生成和定向代码互译能力。仓库保留题目元数据、参考解、模型输出、提交记录、执行状态、失败类型、运行时间、内存占用和 pass@k 汇总。

## 项目结构

```text
MCIBench/
  metadata/       # 题目、标签、难度、模板、索引
  solutions/      # 参考解和执行验证解
  generation/     # 生成任务输出、提交记录压缩包、执行记录
  translation/    # 互译任务输出、提交记录压缩包、执行记录
  scripts/        # 评测、复现、分析、归档同步脚本
  dashboard/      # 在线界面实现
  docs/           # README、教程说明、图表、schema 说明
```

## 数据恢复

展开提交记录和执行记录：

```bash
python scripts/sync_archives.py
```

该命令恢复：

```text
generation/submissions/
translation/submissions/
generation/records/generation_results.csv
translation/records/translation_results.csv
```

`generation/code/` 和 `translation/code/` 是本地模型输出目录。重建 dashboard 数据库时需要保留这些目录。

## 启动 Dashboard

恢复发布版 SQLite 数据库：

```bash
cd dashboard
python scripts/restore_database.py
```

Docker 启动：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

本地启动后端：

```bash
cd dashboard/packages/server
cp config/config.example.yaml config/config.yaml
go run cmd/server/main.go
```

本地启动前端：

```bash
cd dashboard/packages/web
npm install
npm run dev
```

更多部署和重建说明见 [dashboard/README.md](dashboard/README.md)。
