# MCIBench：大语言模型多语言代码智能基准

[English](README.en.md) | [中文](README.zh.md)

MCIBench 是一个面向大语言模型的多语言代码智能基准，用于评估同题代码生成和有向代码互译能力。该基准强调同题多语言评测：模型需要在多种主流编程语言上解决同一批编程题，并可进一步分析 Accepted 程序的功能正确性、运行时间和内存占用。

## 数据集概览

| 项目 | 数量 |
|---|---:|
| 题目数 | 1,489 |
| 语言数 | 8 |
| 生成任务题目-语言槽位 | 11,912 |
| 有向互译语言对 | 56 |
| 互译任务题目 | 100 |
| 原始参考解覆盖 8 种语言的题目 | 332 |
| 合并实验 Accepted 解后覆盖 8 种语言的题目 | 1,466 |

8 种语言为 `C`、`C++`、`C#`、`Java`、`JavaScript`、`Python3`、`Golang`、`Rust`。

## 任务和指标

MCIBench 包含两个任务：

1. 多语言代码生成：为每道题生成目标语言解法。
2. 有向代码互译：将一种语言的正确解法翻译为另一种目标语言。

主要评价指标包括功能正确性、`pass@k`、失败类型、运行时间和内存占用。

## 评测模型

本基准评测的模型包括：

- Advanced LLMs：GPT-4o、GLM-4、DeepSeek-v3.2、Claude-3-5-haiku、Qwen3-coder-480B-a35b-instruct
- Qwen3 Scaling Series：Qwen3-1.7B、Qwen3-4B、Qwen3-8B、Qwen3-14B、Qwen3-32B

## 仓库结构

```text
MCIBench/
  data/
    raw/
      descriptions/             # 按题号组织的 LeetCode 题面
      reference_solutions/      # 按题号和语言组织的参考题解
      snippets/                 # 每题每语言的函数或类接口片段
    metadata/                   # 任务题号、语言、语言对、标签、URL、题号映射
    indexes/                    # 任务索引和覆盖索引

  artifacts/
    derived_data/               # 聚合 CSV 文件和覆盖统计
    tables/                     # 分析和论文表格使用的 CSV 表

  experiments/
    generation/
      submissions.tgz           # 压缩后的代码生成原始提交结果
    translation/
      submissions.tgz           # 压缩后的代码互译原始提交结果

  Scripts/

  README.md
  README.en.md
  README.zh.md
  .gitignore
```

## 关键索引文件

| 文件 | 含义 |
|---|---|
| `data/indexes/generation_task_qids.txt` | 1,489 道生成任务题号 |
| `data/indexes/translation_task_qids.txt` | 100 道互译任务题号 |
| `data/indexes/translation_task_qids.csv` | 互译任务题号及难度、标签、URL |
| `data/indexes/complete_reference_qids.txt` | 原始参考解覆盖 8 种语言的 332 道题 |
| `data/indexes/complete_reference_qids.csv` | 原始 8 语言全参考解题号及元数据 |
| `data/indexes/complete_augmented_qids.txt` | 合并实验 Accepted 解后覆盖 8 种语言的 1,466 道题 |
| `data/indexes/complete_augmented_qids.csv` | 增强后 8 语言全覆盖题号及元数据 |
| `data/indexes/incomplete_augmented_qids.csv` | 增强后仍缺语言的题号和缺失语言 |

## 核心数据产物

| 文件 | 内容 |
|---|---|
| `artifacts/derived_data/generation_passk.csv` | 生成任务按模型、题号、语言统计的 pass@1 到 pass@5 |
| `artifacts/derived_data/translation_passk.csv` | 互译任务按模型、题号、源语言、目标语言统计的 pass@1 到 pass@5 |
| `artifacts/derived_data/dataset_quality_summary.csv` | 原始参考解和增强后数据集语言覆盖总览 |
| `artifacts/derived_data/dataset_quality_problem_detail.csv` | 每题语言覆盖明细和缺失语言 |
| `artifacts/tables/table_dataset_quality_comparison.csv` | 数据集覆盖对比表 |


## 覆盖口径

LeetCode 提交 JSON 中的 `Accepted` 表示功能正确。增强覆盖统计将原始参考解和实验 Accepted 解合并为一个题解池。单模型能力通过 `generation_passk.csv` 和 `translation_passk.csv` 分析。
