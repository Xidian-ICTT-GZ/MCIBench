# MCIBench Project Structure

Updated: 2026-06-05

## Top-Level Layout

| Path | Content |
|---|---|
| `metadata/` | Problems, tags, difficulty labels, language lists, language pairs, templates, indexes |
| `solutions/` | Reference solutions and execution-validated solution placeholders |
| `generation/` | Code generation outputs, submissions archive, execution records |
| `translation/` | Code translation outputs, submissions archive, execution records |
| `scripts/` | Evaluation, reproduction, analysis, and archive synchronization scripts |
| `dashboard/` | Go + Vue online interface implementation |
| `docs/` | Documentation, derived data, figures, and tables |

## Metadata

| Path | Content |
|---|---|
| `metadata/GenCode_ids.txt` | Generation task qids |
| `metadata/TransCode_ids.txt` | Translation candidate qids |
| `metadata/TransCode_targ_ids.txt` | Translation task qids |
| `metadata/language.txt` | Benchmark languages |
| `metadata/language_pairs.txt` | Directed language pairs |
| `metadata/question_tags.json` | Difficulty labels and tags |
| `metadata/question_urls.json` | Problem URLs |
| `metadata/problems/descriptions/` | Chinese and English problem statements |
| `metadata/templates/snippets/` | Function/class templates by qid and language |
| `metadata/indexes/` | Published task and coverage indexes |

## Solutions

| Path | Content |
|---|---|
| `solutions/reference/` | Reference solutions grouped by qid |
| `solutions/execution_validated/` | Placeholder for validated solution exports |

## Generation And Translation

| Path | Content |
|---|---|
| `generation/submissions.tgz` | Compressed generation submission JSON records |
| `translation/submissions.tgz` | Compressed translation submission JSON records |
| `generation/records/generation_results.csv.tgz` | Compressed generation execution CSV |
| `translation/records/translation_results.csv.tgz` | Compressed translation execution CSV |
| `generation/code/`, `translation/code/` | Local generated code output directories |
| `generation/submissions/`, `translation/submissions/` | Local expanded submission directories |

Run `python scripts/sync_archives.py` to restore tracked archives into local expanded folders.

## Dashboard

| Path | Content |
|---|---|
| `dashboard/packages/server/` | Go API server |
| `dashboard/packages/web/` | Vue + Vite frontend |
| `dashboard/database/` | Split compressed SQLite database archive |
| `dashboard/scripts/restore_database.py` | Restores dashboard SQLite from archive parts |
| `dashboard/scripts/import_experiment_results.py` | Rebuilds dashboard SQLite from repository data |
| `dashboard/deploy/` | Linux deployment scripts |
