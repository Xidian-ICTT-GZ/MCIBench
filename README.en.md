# MCIBench: Benchmarking Multilingual Code Intelligence

[Main README](README.md) | [中文](README.zh.md)

MCIBench evaluates large language models on multilingual code generation and directed code translation. The artifact keeps problem metadata, reference solutions, generated code, submissions, execution records, runtime and memory metrics, and pass@k summaries.

## Structure

```text
MCIBench/
  metadata/       # problems, tags, difficulty labels, templates, indexes
  solutions/      # reference and execution-validated solutions
  generation/     # generation outputs, submissions archive, execution records
  translation/    # translation outputs, submissions archive, execution records
  scripts/        # evaluation, reproduction, analysis, archive sync scripts
  dashboard/      # online interface implementation
  docs/           # README material, tutorial notes, figures, tables, schemas
```

## Restore Data

```bash
python scripts/sync_archives.py
```

This restores compressed execution records and submission folders. The dashboard database is stored as split archive parts:

```bash
cd dashboard
python scripts/restore_database.py
```

## Start Dashboard

Docker:

```bash
cd dashboard
docker compose -f docker-compose.prod.yml up -d --build
```

Local development:

```bash
cd dashboard/packages/server
cp config/config.example.yaml config/config.yaml
go run cmd/server/main.go
```

```bash
cd dashboard/packages/web
npm install
npm run dev
```

See [dashboard/README.md](dashboard/README.md) for database rebuild and deployment details.
