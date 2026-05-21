# MCIBench: Benchmarking Multilingual Code Intelligence of Large Language Models

[English](README.en.md) | [中文](README.zh.md)

MCIBench is a multilingual code intelligence benchmark for evaluating large language models on problem-aligned code generation and directed code translation. It emphasizes same-problem multilingual evaluation: models are evaluated on the same programming problems across multiple mainstream programming languages, and accepted programs can be analyzed for functional correctness, runtime, and memory usage.

## Benchmark Overview

| Item | Count |
|---|---:|
| Problems | 1,489 |
| Languages | 8 |
| Generation qid-language slots | 11,912 |
| Directed translation language pairs | 56 |
| Translation task problems | 100 |
| Original reference-complete problems across all 8 languages | 332 |
| Augmented complete problems using accepted experimental solutions | 1,466 |

The 8 languages are `C`, `C++`, `C#`, `Java`, `JavaScript`, `Python3`, `Golang`, and `Rust`.

## Tasks and Metrics

MCIBench contains two tasks:

1. Multilingual code generation: generate a solution for each problem in each target language.
2. Directed code translation: translate a correct source-language solution into another target language.

The main evaluation metrics are functional correctness, `pass@k`, failure type, runtime, and memory usage.

## Supported Models

The benchmark was evaluated using:

- Advanced LLMs: GPT-4o, GLM-4, DeepSeek-v3.2, Claude-3-5-haiku, Qwen3-coder-480B-a35b-instruct
- Qwen3 scaling series: Qwen3-1.7B, Qwen3-4B, Qwen3-8B, Qwen3-14B, Qwen3-32B

## Repository Layout

```text
MCIBench/
  data/
    raw/
      descriptions/             # LeetCode problem statements organized by qid
      reference_solutions/      # Reference solutions organized by qid and language
      snippets/                 # Per-problem, per-language interface snippets
    metadata/                   # Task ids, languages, language pairs, tags, URLs, and qid mappings
    indexes/                    # Task indexes and coverage indexes

  artifacts/
    derived_data/               # Aggregated CSV files and coverage summaries
    tables/                     # CSV tables used in analysis and reporting

  experiments/
    generation/
      submissions.tgz           # Compressed raw generation submissions
    translation/
      submissions.tgz           # Compressed raw translation submissions

  Scripts/

  README.md
  README.en.md
  README.zh.md
  .gitignore
```

## Important Index Files

| File | Meaning |
|---|---|
| `data/indexes/generation_task_qids.txt` | 1,489 generation task qids |
| `data/indexes/translation_task_qids.txt` | 100 translation-task qids |
| `data/indexes/translation_task_qids.csv` | Translation qids with difficulty, tags, and URL |
| `data/indexes/complete_reference_qids.txt` | 332 qids with original reference solutions in all 8 languages |
| `data/indexes/complete_reference_qids.csv` | Complete original-reference qids with metadata |
| `data/indexes/complete_augmented_qids.txt` | 1,466 qids complete after adding accepted experimental solutions |
| `data/indexes/complete_augmented_qids.csv` | Augmented-complete qids with metadata |
| `data/indexes/incomplete_augmented_qids.csv` | Remaining qids and missing languages after augmentation |

## Core Data Products

| File | Content |
|---|---|
| `artifacts/derived_data/generation_passk.csv` | Generation pass@1 through pass@5 by model, qid, and language |
| `artifacts/derived_data/translation_passk.csv` | Translation pass@1 through pass@5 by model, qid, source language, and target language |
| `artifacts/derived_data/dataset_quality_summary.csv` | Reference and augmented language-coverage summary |
| `artifacts/derived_data/dataset_quality_problem_detail.csv` | Per-qid coverage details and missing languages |
| `artifacts/tables/table_dataset_quality_comparison.csv` | Dataset coverage comparison table |

## Coverage Interpretation

`Accepted` in LeetCode submission JSON is the functional correctness signal. The augmented coverage files combine original reference solutions and accepted experimental solutions into one solution pool. Single-model accuracy is reported through `generation_passk.csv` and `translation_passk.csv`.
