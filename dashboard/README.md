# MCIBench Dashboard

This directory contains the online interface implementation for MCIBench.

## Layout

```text
dashboard/
  packages/server/          # Go API server
  packages/web/             # Vue + Vite frontend
  deploy/                   # Linux deployment scripts
  database/                 # Split compressed SQLite release database
  scripts/                  # Data restore and materialization scripts
  volumes/backend-data/     # Local Docker/runtime database mount
```

## Prerequisites

- Go 1.20+
- Node.js LTS and npm
- Python 3.10+
- Docker with Compose, for container deployment

## Restore The Release Database

The GitHub repository stores the dashboard database as split archive parts under `dashboard/database/`.

```bash
cd dashboard
python scripts/restore_database.py
```

The script restores:

```text
dashboard/volumes/backend-data/mcibench.db
dashboard/packages/server/data/mcibench.db
```

It also runs SQLite `integrity_check`.

## Run With Docker

```bash
cd dashboard
python scripts/restore_database.py
docker compose -f docker-compose.prod.yml up -d --build
```

Default URL:

```text
http://127.0.0.1/
```

## Run Locally

Backend:

```bash
cd dashboard/packages/server
cp config/config.example.yaml config/config.yaml
go run cmd/server/main.go
```

Frontend:

```bash
cd dashboard/packages/web
npm install
npm run dev
```

Single-port local run:

```bash
cd dashboard/packages/web
npm run build

cd ../server
MCIBENCH_WEB_DIST_PATH=../web/dist go run cmd/server/main.go
```

Default backend URL:

```text
http://127.0.0.1:8080/
```

## Rebuild The Database From Repository Data

Restore local archives first:

```bash
cd ..
python scripts/sync_archives.py
```

Then rebuild the dashboard SQLite database:

```bash
cd dashboard
python scripts/import_experiment_results.py
```

`import_experiment_results.py` reads:

- `metadata/`
- `solutions/reference/`
- `docs/derived_data/generation_passk.csv`
- `docs/derived_data/translation_passk.csv`
- `generation/code/`
- `generation/submissions/`
- `translation/code/`
- `translation/submissions/`

The expanded code and submission folders are local runtime data and are ignored by Git.
