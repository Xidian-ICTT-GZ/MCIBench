# MCIBench: Benchmarking Multilingual Code Intelligence

[English](README.en.md) | [中文](README.zh.md)

MCIBench is a multilingual code intelligence benchmark for problem-aligned code generation and directed code translation. It preserves prompts, model outputs, executable submissions, execution status, failure type, runtime, memory usage, and derived pass@k artifacts.

## Repository Layout

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

## Core Data

| Path | Content |
|---|---|
| `metadata/GenCode_ids.txt` | 1,489 generation task qids |
| `metadata/TransCode_targ_ids.txt` | 100 translation task qids |
| `metadata/language.txt` | 8 benchmark languages |
| `metadata/language_pairs.txt` | 56 directed translation pairs |
| `metadata/problems/descriptions/` | Chinese and English problem statements |
| `metadata/templates/snippets/` | Per-problem, per-language interface templates |
| `solutions/reference/` | Reference solutions grouped by qid |
| `docs/derived_data/generation_passk.csv` | Generation pass@1 through pass@5 |
| `docs/derived_data/translation_passk.csv` | Translation pass@1 through pass@5 |
| `generation/records/generation_results.csv.tgz` | Compressed generation execution records |
| `translation/records/translation_results.csv.tgz` | Compressed translation execution records |

## Restore Local Archives

Expanded output folders are ignored by Git. Restore the local runtime folders from tracked archives:

```bash
python scripts/sync_archives.py
```

This extracts:

```text
generation/submissions/
translation/submissions/
generation/records/generation_results.csv
translation/records/translation_results.csv
```

The generated code folders `generation/code/` and `translation/code/` are local provenance folders. Keep them in place when rebuilding the dashboard database from raw outputs.

## Dashboard

Restore the released dashboard SQLite database:

```bash
cd dashboard
python scripts/restore_database.py
```

Run with Docker:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Run locally:

```bash
cd packages/server
cp config/config.example.yaml config/config.yaml
go run cmd/server/main.go
```

```bash
cd dashboard/packages/web
npm install
npm run dev
```

Dashboard details are in [dashboard/README.md](dashboard/README.md).

## Analysis Scripts

Use the repository root as the working directory:

```bash
python scripts/analyze_dataset_quality.py
python scripts/generate_paper_artifacts.py
python scripts/render_dataset_quality_table.py
```

The scripts resolve the new layout through `scripts/layout.py`.
