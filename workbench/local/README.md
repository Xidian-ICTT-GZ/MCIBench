# local/ — MCIBench 本地判题系统（LeetCode 在线判题的离线替代）

大模型生成代码后，本地调用 8 语言编译器（Docker 沙箱、断网可跑）编译运行测试用例，
判定 AC/WA/CE/RE/TLE，输出与历史 LeetCode 判题结果**同构**的 JSON。下游
pass@k 计算（`SFT/scripts/compute_passk.py`）、CSV（`clean_results.py`）、数据库导入、
仪表盘**零改动**。历史 LeetCode 结果保留；仅新评测走本地口径。

## 目录结构

```
local/
  docs/               对拍工作流.md（审计方法与全部结论）、调研结论.md、评测方法综述.md
  common.py           路径/语言常量
  judge.py            drop-in 判题器（核心入口）
  harness/
    typespec.py       签名类型系统（Python3 签名 → TypeSpec）
    render.py         8 语言测试驱动渲染器（裁判程序生成器）
    runner.py         编译+运行执行器（host / docker 双后端）
    dataio.py         编码输入通路（突破源码字面量的规模上限，见下）
  gen_testcases/
    extract_lcd.py     LeetCodeDataset 用例提取（93 题，Apache-2.0）
    extract_examples.py 题目描述官方示例提取（96 题）
    design_cases.py   设计题 op 序列示例提取（4 题）
    llm_expand.py     LLM 生成补充输入（7 缺失题/设计题/低覆盖题）
    differential.py   8 语言参考解差分校验（投票定期望输出）
    validate.py       语料装配 + 金标准自检
    scale_expand.py   按题生成约束内的大规模用例（修复规模不足类缺口）
    clean_oob.py      清理超出题面约束的用例（逐参数解析值域）
  audit/              覆盖度审计：用历史 LeetCode 判定反查语料覆盖度
    pairing.py        结果↔代码配对
    wide_cases.py     全量用例集（窄 vs 宽的对照）
    coverage_audit.py Phase 0：窄/宽两遍重判，找判定翻转
    historical_audit.py Phase 1：与历史判定对拍，按方向分类
    report.py         差异报告（Markdown + CSV）
    scale_gap.py      规模缺口与值域越界诊断
  docker/
    Dockerfile        judge 镜像（ubuntu + 8 工具链 + uthash + sortedcontainers + 离线 NuGet）
    judge_exec.sh     容器内编译/运行入口
  testcases/
    _seed/            原始种子（lcd_/examples_/design_/llm_）
    <qid>/cases.json  最终语料（判题器直接使用）
```

审计工具用法与全部实测结论见 `docs/对拍工作流.md`。

## 使用流程

### 1. 构建判题镜像（在线一次，离线部署用 docker save/load）

```bash
cd local/docker && docker build -t local-judge:1 .
docker save local-judge:1 | gzip > local-judge-1.tar.gz   # 拷到离线机
docker load < local-judge-1.tar.gz
```

### 2. 构建测试语料（在线一次，语料本身可离线分发）

```bash
# 已有：93 题 LeetCodeDataset 种子 + 96 题官方示例 + 4 题设计示例（在 testcases/_seed/）
# 补充：LLM 生成 7 个缺失题 + 设计题 + 低覆盖题的输入（需要 LLM_API_KEY）
python -m local.gen_testcases.llm_expand \
    --qids 1146,1472,2080,2241,1323,1969,2580,2575 --n_per_problem 12

# 差分校验：Python 参考解为 pivot，≥2 语言投票 → local/results/differential.json
python -m local.gen_testcases.differential --max_cases 30 --max_workers 4

# 装配语料 + 金标准自检（参考解在最终语料上必须全 AC）
python -m local.gen_testcases.validate --max_workers 4
```

### 3. 判题（新评测产物 → 同构结果 JSON）

在包含 `Submit_Gen/`、`Submit_Trans/` 的目录（如 `SFT_Full/` 或 repo 根）下运行：

```bash
python local/judge.py -submit_gen   <run_name> --max_cases 30 --max_workers 4
python local/judge.py -submit_trans <run_name> --max_cases 30 --max_workers 4
# 分批并行（复用旧分片习惯）：-id_list "40,624,1014"
```

结果写入 `Submit_Result/Submit_Results[_Trans]_<run_name>/<qid>/<qid>_<lang>[_<src>_<tgt>]_<n>.json`，
与 CodeTest6 约定完全一致；断点续跑 = 结果文件存在即跳过。每个结果目录附
`judge_meta.json`（judge 版本、镜像、语料哈希、时间）。

## 判题语义

- 测试形式：**函数级测试**（BootTrans/HumanEvalPack 风格）——驱动构造语言原生参数
  直接调用、比对返回值，不经过文本序列化（见 docs/评测方法综述.md）。
- 判定 = 编译 + 全部用例通过（二值 oracle）；编译失败→CE、超时→TLE、OOM→MLE、
  崩溃→RE、输出不符→WA、全过→AC。
- 组合类输出（List[List[...]]）按行集合匹配（顺序不敏感、行为等价）。
- 每题默认最多 30 个用例（`--max_cases`），首个失败即停；每题目标 ≥8 个有效用例。
- 沙箱约束：`--network none`、**1536MB 内存**、单核、进程数限制、编译/运行分别限时。
  内存上限必须容得下**编译**：实测编译峰值 C 1.16GB、C++ 1.00GB，
  原先的 512MB 会让 gcc 被 OOM 杀死并误报成 Compile Error。
  代价是 512MB–1.5GB 的程序不再判 MLE（代价很小，换来的是不再误标正确代码）。
  **跑批量任务时并发数要相应下调**（1.5GB × 8 worker 会压垮主机）。

## 输入规模上限与编码通路

驱动原本把用例**以源码字面量嵌入**，这条路有硬上限（实测）：

| n | python3 | c | cpp | java | javascript | csharp | golang | rust |
|---|---|---|---|---|---|---|---|---|
| 5,000 | OK | OK | OK | OK | OK | OK | OK | OK |
| 10,000 | OK | OK | OK | **CE** | OK | OK | OK | OK |
| 20,000 | OK | OK | OK | CE | OK | OK | OK | **CE** |

Java 撞 64KB 单方法字节码上限、Rust 撞常量上限，而题面约束常达 1e5——
**这正是语料长期偏小的结构性原因**。`harness/dataio.py` 在用例超出阈值时改用
「编码 token 流 + 运行时解析」（收益不来自压缩，而来自不再逐元素生成代码），
实测 n=100000 在 8 种语言下全部通过。小语料仍走原字面量路径，历史结果不受影响。

## 与旧链路的对应

| 旧（LeetCode） | 新（本地） |
|---|---|
| `CodeTest6.py -submit_gen/-submit_trans` | `local/judge.py -submit_gen/-submit_trans` |
| cookie 池 / curl_cffi / CSRF / 分片脚本 | 全部不需要（旧脚本保留备用） |
| LeetCode 隐藏测试 | LeetCodeDataset 用例（93 题）+ 官方示例 + LLM 生成，全部经 8 语言差分校验 |
| 判题 JSON（9 字段，LeetCode 回传） | 本地生成同 schema JSON |

## 已知口径差异（记录在案）

1. 测试用例与 LeetCode 隐藏测试不同 → 与历史结果不可直接混比，报告中需注明
   judge 版本（见结果目录 judge_meta.json）。
2. 组合类输出采用顺序不敏感比较（LeetCode 精确比较）→ 行为等价语义，稍宽松。
3. runtime/memory 为本地容器实测（LeetCode 为服务器实测），percentile 置 0.0。
4. `submit_id` 置 0（下游只用文件名和 ac_status）。
