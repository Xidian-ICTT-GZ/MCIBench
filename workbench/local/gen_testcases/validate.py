# -*- coding: utf-8 -*-
r"""语料自检：**只读**。默认不对语料做任何改动。

为什么要拆成两个命令
--------------------
原来这个模块只有一条路径：从 `local/results/differential.json` 重建全部
`cases.json`，重建完顺手做自检。它把**破坏性重建**和**只读回归**混在一起，
而 `differential.json` 是**旧的**——实测直接跑会把 46 道题的语料覆盖掉
（q2140 从 30 条变 6 条、q1550 从 30 条变 45 条……），先用例增强出来的东西
全部丢失。而且没有任何提示。

现在：
    python -m local.gen_testcases.validate            # 只读自检（默认）
    python -m local.gen_testcases.validate rebuild --yes   # 显式重建

缓存也要有版本
--------------
原来自检结果按 (qid, lang) 判断"做过就跳过"，语料改了也照样复用旧结论
——于是**永远不会重新验证增强后的语料**。现在每条结果都带**指纹**
（语料内容 + 判题器源码 + 关键参数），只有指纹一致才复用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local.common import (LANGS, REPO_ROOT, TESTCASES_DIR,  # noqa: E402
                          load_ft_test_qids, load_json, load_reference,
                          load_snippet, save_json)
from local.gen_testcases.design_cases import DESIGN_QIDS  # noqa: E402
from local.harness.render import (extract_plain_entry,  # noqa: E402
                                  render_design_driver, render_plain_driver)
from local.harness.runner import run_submission  # noqa: E402
from local.harness.evidence import valid_measurement, load_evidence
from local.harness.typespec import DesignSig, PlainSig, parse_python_snippet  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "local" / "results" / "golden_check.json"

# 参与指纹的判题器源码 —— **闭包式**（A-101）。
#
# 原先这里是**手写的 6 个文件**清单，而它不等于判题依赖闭包：
# `local/common.py`（KEY_TO_LABEL / load_snippet / TESTCASES_DIR）与
# `local/gen_testcases/differential.py`（DRIVER_SIZE_BUDGET / chunk_indices）
# 都参与判定却**不在**清单里。审查代理 A 内存打补丁实测：把这两个加进去后
# 指纹 `ade36308a27e5fee` → `be9bbdd8163d28dc`（**变了**）。
# 现在改为从 `local/judge.py` 出发递归解析 import —— 新增被判题引用的模块
# 会**自动**进身份，不需要有人记得改清单。
#
# 实测闭包（10 个文件）：common.py / judge.py / harness{render,runner,validators,
# typespec,dataio}.py / gen_testcases{design_cases,differential,parse_io}.py

# C-003 的"覆盖面缺口"：即使语料与判题器源码一致，下面这些变了也会让
# **判定结果**变，所以必须进指纹：
#   - 被判定的**参考解本身**（交接文档 §五.2 明说改过 q2129/q2288 的 #include）
#   - 语言 snippet（驱动模板/签名来自它）
#   - FT_test.txt（决定 qid 集合）
#   - Docker 镜像（编译器版本）
#
# **A-102（P1）**：模板这一条此前是**假的** —— 模式写的是 `snippets/*`，
# 而模板在 `snippets/<qid>/<Label>.json`，**深一层**，`p.is_file()` 恒为假。
# 实测：`glob('…/snippets/*')` → **2944 个条目、0 个文件**；
# 改成 `snippets/*/*.json` 后指纹 `ade36308a27e5fee` → `ad3873f178abfd71`（变了）
# ⇒ 模板字节**从未**进入 800/800 指纹。
_FINGERPRINT_EXTRA_GLOBS = [
    "MCIBench-test/solutions/reference/*/*",
    # 必须到**文件**层；`snippets/*` 只到题号目录
    "MCIBench-test/metadata/templates/snippets/*/*.json",
]
_FINGERPRINT_EXTRA_FILES = [
    "SFT/data/datasets/FT_test.txt",
    "local/gen_testcases/design_cases.py",
]


REFERENCE_PROTOCOL = 3
REFERENCE_TIMEOUT_S = 30


def fingerprint(qids: list[int] | None = None, include_env: bool = True) -> str:
    """Bind the selected reference matrix, execution protocol and actual inputs."""
    from local.harness.identity import (judge_source_closure, code_sha,
        template_sha, corpus_content_sha, image_digest)
    from local.harness import runner
    qids = sorted(qids if qids is not None else load_ft_test_qids())
    payload = {
        "protocol": REFERENCE_PROTOCOL, "qids": qids, "languages": LANGS,
        "runner": dict(judge_source_closure()),
        "reference_entry": code_sha(Path(__file__).read_text(encoding="utf-8")),
        "run_timeout_s": REFERENCE_TIMEOUT_S, "memory_mb": runner.DOCKER_MEM_MB,
        "image": image_digest() if include_env else "diagnostic-without-environment",
        "cases": {str(q): corpus_content_sha(q, TESTCASES_DIR) for q in qids},
        "templates": {str(q): template_sha(q, "python3") for q in qids},
        "references": {f"{q}/{lang}": code_sha(load_reference(q, lang))
                       for q in qids for lang in LANGS},
    }
    if any(value is None for value in payload["cases"].values()):
        raise ValueError("Missing corpus in requested reference matrix")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def corpus_size() -> int:
    return sum(len(load_json(TESTCASES_DIR / str(q) / "cases.json") or [])
               for q in load_ft_test_qids()
               if (TESTCASES_DIR / str(q) / "cases.json").exists())


# --------------------------------------------------------------------------
# 破坏性重建（需显式指定）
# --------------------------------------------------------------------------

def would_drop_legal(old: list, new: list, qid: int, check_fn=None) -> list:
    """返回当前语料里有、候选里没有的**合法**用例。

    **B-101**：这段逻辑原来内联在 rebuild 里，而且判断是反的
    （if not _c_check(qid, c): continue 跳过了**合法**用例）。
    抽成模块级函数有两个好处：
      1. 可以被**行为测试直接调用**，包括**注入一个反向的 check_fn**
         来证明测试能发现方向错误（规范 8：验收不能是恒真断言）；
      2. 方向只写一处，不会被别的路径复制错。

    check_fn 默认取 constraints.check（返回违规列表，空 = 合法）。
    """
    if check_fn is None:
        from local.gen_testcases.constraints import check as check_fn  # noqa: N806
    def _key(c):
        return json.dumps(c.get("args"), sort_keys=True, ensure_ascii=False)
    new_args = {_key(c) for c in new}
    out = []
    for c in old:
        # 非法用例本来就允许被丢弃 → 跳过；合法的**一律不许丢**
        if check_fn(qid, c):
            continue
        if _key(c) not in new_args:
            out.append(c)
    return out


def rebuild(differential_file: Path, yes: bool, args=None) -> dict[int, list[dict]]:
    if args is None:
        from types import SimpleNamespace
        args = SimpleNamespace(allow_stale_source=False, allow_drop=False, backend="docker")
    results = load_json(differential_file)
    preimages = {}
    corpus: dict[int, list[dict]] = {}
    for r in results:
        if not r.get("ok") or not r.get("cases"):
            print(f"qid {r['qid']}: skipped ({r.get('reason', 'no cases')})")
            continue
        qid = int(r["qid"])
        corpus[qid] = r["cases"]
        path = TESTCASES_DIR / str(qid) / "cases.json"
        preimages[qid] = path.read_bytes() if path.exists() else None

    # 先算清楚会改什么，让"要不要覆盖"是个有依据的决定
    changes = []
    for qid, cases in sorted(corpus.items()):
        p = TESTCASES_DIR / str(qid) / "cases.json"
        old = len(load_json(p) or []) if p.exists() else 0
        if old != len(cases):
            changes.append((qid, old, len(cases)))
    if changes:
        print(f"\n** {len(changes)} 道题的语料会被改写 **")
        for qid, old, new in changes[:20]:
            print(f"    q{qid:<6} {old:>3} -> {new:>3}  ({new-old:+d})")
        if len(changes) > 20:
            print(f"    … 另 {len(changes)-20} 道")
    if not yes:
        print("\n这是破坏性操作（会覆盖 cases.json）。确认请加 --yes。")
        print("只想验证当前语料：直接跑不加参数（只读）。")
        sys.exit(2)

    # ---- 覆盖写盘前：约束闸门 + **源新鲜度闸门** + 备份 + 原子写 ----
    #
    # **这是我在会话里踩过的坑**：我以为 `rebuild` 重建的是 `golden_check.json`，
    # 实际它**重建语料**。当时它
    #   ① 直接 `save_json(d/"cases.json", cases)` —— **不备份**（B-012 类缺陷）
    #   ② **完全不检查约束** —— 实测重写后出 **117 条非法**（25 题），
    #      而重写前是 0 条（B-009 同类的又一条旁路）
    #   ③ 非原子写 —— 中断会留下半截语料
    # 结果 50 个语料文件被改坏，我花了很大力气才恢复。
    #
    # **B4-001（我第二次写错的措辞）**：我在这里写过"本命令只**减不增**，所以仍可
    # 写盘"—— **这是假的**。实测拿真实 `differential.json` 逐题比对，**30 题会被
    # 改写**，其中
    #   - `q1298 17 → 16`：会**删掉**刚补进去的合法触发用例（`would GAIN: []`）
    #   - `q1550 45 → 28`、`q1673 41 → 30`、`q2145/q2179 37 → 30`…：把
    #     `scale_expand` 的成果成批删掉
    #   - 同时又给别的题**加回旧用例**（`q2563 27 → 30`、`q120 29 → 30`）
    #
    # 所以它不是"只减"，而是"**用一份可能更旧的快照整体替换**"。据此加两道闸门：
    #   (a) **源新鲜度**：`differential.json` 必须比现有语料**新**，否则拒绝
    #       （源更旧意味着它会用旧数据覆盖新成果）
    #   (b) **不丢当前用例**：除非显式 `--allow-drop`，否则拒绝删掉**当前语料里
    #       已有的**合法用例（只允许新增 + 删非法）
    import os
    import time as _time
    from local.gen_testcases.constraints import check as _c_check
    from local.gen_testcases.constraints import parse as _c_parse
    from local.gen_testcases.corpus_io import atomic_save, sync_meta, unique_backup

    # (a) 源新鲜度
    diff_mtime = differential_file.stat().st_mtime if differential_file.exists() else 0
    newest_corpus = 0.0
    for qid in sorted(corpus):
        p = TESTCASES_DIR / str(qid) / "cases.json"
        if p.exists():
            newest_corpus = max(newest_corpus, p.stat().st_mtime)
    if diff_mtime and newest_corpus and diff_mtime < newest_corpus:
        print(f"\n** 拒绝：differential.json 比现有语料旧 **")
        print(f"    differential: {_time.strftime('%Y-%m-%d %H:%M', _time.localtime(diff_mtime))}")
        print(f"    最新语料    : {_time.strftime('%Y-%m-%d %H:%M', _time.localtime(newest_corpus))}")
        print(f"    用更旧的源覆盖会丢掉较新的成果（B4-001 实测会删掉 q1298 的触发用例、"
              f"以及 scale_expand 的成批成果）。")
        print(f"    确实要用旧源重建请加 --allow-stale-source。")
        if not getattr(args, "allow_stale_source", False):
            sys.exit(3)

    # (b) 不丢当前已有的合法用例（除非 --allow-drop）
    #
    # **B-101（P1）：这一段的判断原本是反的。** `_c_check` 返回的是**违规列表**
    # （空列表 = 合法），而原代码写的是
    #       if not _c_check(qid, c): continue
    # —— 于是它**跳过合法用例**，只收集非法用例，把"不许丢弃合法用例"
    # 反向成了"不许丢弃非法用例"。审查代理 B 端到端实测：
    #   ① 合法 `{"nums":[10,20],"p":1}` 被非法 `p=9` 替换 → **不拒绝、直接写盘**
    #   ② 旧非法 `p=9` 被新合法 `p=1` 替换 → exit 3，还打印
    #      "会删掉 1 条当前语料里**合法**的用例 / {…"p":9}"（把非法叫合法）
    # 主代理独立复现（`%TEMP%\lj_d1_repro.py`）：反向写法 would_drop=0、正确写法=1。
    would_drop: list[tuple[int, dict]] = []
    for qid in sorted(corpus):
        p = TESTCASES_DIR / str(qid) / "cases.json"
        if not p.exists():
            continue
        for c in would_drop_legal(load_json(p) or [], corpus[qid], qid,
                                  check_fn=_c_check):
            would_drop.append((qid, c))
    if would_drop:
        print(f"\n** 这次重建会删掉 {len(would_drop)} 条当前语料里**合法**的用例 **")
        for qid, c in would_drop[:8]:
            print(f"    q{qid}: {json.dumps(c.get('args'), ensure_ascii=False)[:76]}")
        if len(would_drop) > 8:
            print(f"    … 另 {len(would_drop)-8} 条")
        print(f"    这些用例可能是后续补进去的（例如 q1298 的合法触发用例、"
              f"scale_expand 的成果）。确实要删请加 --allow-drop。")
        if not getattr(args, "allow_drop", False):
            sys.exit(3)

    # ---------------------------------------------------------------
    # (c) 写盘前的整体校验 —— **对将要写入的每一份语料**
    #
    # B-103（P1）：原代码在写盘前**完全不校验**要写的内容（不跑 check()、
    # 不跑 unparsed()、也不看 expected），所以非法内容与错误 expected 都会静默入库。
    # B 的实测：变体 A 把非法 `p=9` 写进语料且同步 meta；变体 G 把同 args 的
    # expected 从 1 改成 999 也照写。
    #
    # B-113（P2）：如果"unparsed 非空就整批拒绝"，当前 **47/100** 题会被拦
    # → 保护会变成"每次都要绕过的旗标"（规范正是反对这种）。所以这里
    # 未核验约束默认拒绝；补齐人工规则和证据后才可重建。
    #
    # B-102（P1）：原代码 `:259` 引用了**从未赋值**的 `skipped_unparsed`，
    # 任何**条数变化**的重建都会在写盘前 NameError 崩掉（条数不变则绕过 →
    # 于是"条数变了就崩、条数不变就无校验地写"两个缺陷互补）。这里不再引用它。
    from local.gen_testcases.constraints import unparsed as _c_unparsed

    fatal: list[str] = []
    skipped_unverified: list[int] = []
    for qid in sorted(corpus):
        cases = corpus[qid]
        if not cases:
            fatal.append(f"q{qid}: 语料为空")
            continue
        bad = [(i, _c_check(qid, c)) for i, c in enumerate(cases)]
        bad = [(i, why) for i, why in bad if why]
        if bad:
            fatal.append(f"q{qid}: {len(bad)} 条候选违反题面约束，"
                         f"例如 idx{bad[0][0]} -> {bad[0][1][0]}")
        # expected 非空（B-103：原文完全不看 expected）
        miss_exp = [i for i, c in enumerate(cases) if c.get("expected") is None]
        if miss_exp:
            fatal.append(f"q{qid}: {len(miss_exp)} 条候选缺 expected")
        if _c_unparsed(qid):
            skipped_unverified.append(qid)
            fatal.append(f"q{qid}: 有 {len(_c_unparsed(qid))} 行未核验约束；补齐规则后再发布")
    if fatal:
        print(f"\n** 写盘前校验失败：{len(fatal)} 项 **")
        for f in fatal[:15]:
            print(f"    {f}")
        if len(fatal) > 15:
            print(f"    … 另 {len(fatal)-15} 项")
        print("** 未写入任何文件 **")
        sys.exit(3)
    # Nonempty expected is not evidence of correctness. Exercise every
    # supported reference/checker against exactly the proposed input/answer.
    expected_evidence = {}
    for qid, cases in sorted(corpus.items()):
        try:
            expected_evidence[str(qid)] = validate_expected(qid, cases, getattr(args, "backend", "docker"))
        except Exception as e:
            print(f"q{qid}: expected 校验失败，未写入任何文件：{e}")
            raise SystemExit(3) from e

    # ---------------------------------------------------------------
    # 两阶段写盘（B 的设计审查回答 1）：
    #   阶段一：把**意图**写成 plan.json（每题 old/new、备份目标名）——
    #           这样"清单说改了"与"实际改了"可以分开核对
    #   阶段二：逐题写，并**回写每题状态**到 outcome
    # 原先的问题是：逐题 atomic_save + 循环内 save_json(meta) 没有跨题原子性，
    # 任何一题 I/O 失败都会留下"部分题已换、部分没换、清单已写"的状态。
    # ---------------------------------------------------------------
    import datetime as _dt
    logdir = REPO_ROOT / "local" / "results" / "corpus_changes"
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = f"{_dt.datetime.now():%Y%m%d-%H%M%S}"

    plan = []
    for qid in sorted(corpus):
        p = TESTCASES_DIR / str(qid) / "cases.json"
        old = load_json(p) or [] if p.exists() else []
        plan.append({"qid": qid, "old": len(old), "new": len(corpus[qid]),
                     "backup": f"cases.json.bak_pre_rebuild" if p.exists() else None,
                     "changed": old != corpus[qid],
                     "old_sha256": hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest(),
                     "new_sha256": hashlib.sha256(json.dumps(corpus[qid], sort_keys=True).encode()).hexdigest()})
    planp = logdir / f"validate_rebuild-{stamp}-plan.json"
    planp.write_text(json.dumps(
        {"intent": plan, "would_drop": len(would_drop),
         "unverified_problems": skipped_unverified,
         "source_sha256": hashlib.sha256(differential_file.read_bytes()).hexdigest(),
         "expected_evidence": expected_evidence},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  意图清单已落盘（{len(plan)} 题）: {planp.name}")

    updates = []
    for qid in sorted(corpus):
        path = TESTCASES_DIR / str(qid) / "cases.json"
        from local.gen_testcases.corpus_io import prepare_checked_metadata
        meta = prepare_checked_metadata(path, corpus[qid], preimages[qid],
                                        "validate_rebuild",
                                        reference_evidence=expected_evidence[str(qid)])
        updates.append((path, corpus[qid], meta, preimages[qid]))
    from local.gen_testcases.corpus_io import publish_batch
    outp = logdir / f"validate_rebuild-{stamp}-outcome.json"
    try:
        publish_batch(TESTCASES_DIR, updates)
    except Exception as error:
        save_json(outp, {"ok": False, "error": str(error),
                        "recovery_required": (TESTCASES_DIR / ".publishing").exists()})
        raise SystemExit(4) from error
    save_json(outp, {"ok": True, "qids": sorted(corpus)})
    return corpus


# --------------------------------------------------------------------------
# 只读自检
# --------------------------------------------------------------------------

def load_corpus() -> dict[int, list[dict]]:
    """读**磁盘上当前的**语料——不重建。"""
    out: dict[int, list[dict]] = {}
    for q in load_ft_test_qids():
        p = TESTCASES_DIR / str(q) / "cases.json"
        if p.exists():
            cs = load_json(p) or []
            if cs:
                out[q] = cs
    return out


def _run_reference(qid: int, lang: str, cases: list[dict], backend: str):
    from local.harness.output_drivers import render_output_driver
    from local.harness.output_protocol import OutputVerifier
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    entry = {} if qid in DESIGN_QIDS else extract_plain_entry(lang, load_snippet(qid, lang))
    drv = render_output_driver(lang, sig, entry, cases, load_reference(qid, lang))
    return run_submission(lang, drv, limit=len(cases), backend=backend,
                          run_timeout_s=REFERENCE_TIMEOUT_S,
                          output_verifier=OutputVerifier(qid, cases, signature=sig))


def validate_expected(qid: int, cases: list[dict], backend: str) -> dict:
    """Recompute evidence using all references; no candidate is silently dropped.

    For multiple-answer problems acceptance is the problem-specific predicate,
    not equality with one arbitrarily chosen reference output.
    """
    from local.harness.identity import code_sha, template_sha, judge_source_closure, image_digest
    from local.harness import runner
    if backend != "docker":
        raise ValueError("Publication requires the Docker reference profile")
    runner.DOCKER_IMAGE = image_digest()
    def inputs():
        return {"references": {lang: code_sha(load_reference(qid, lang)) for lang in LANGS},
                "templates": template_sha(qid, "python3"),
                "judge": dict(judge_source_closure()), "image": runner.DOCKER_IMAGE,
                "backend": backend, "run_timeout_s": 30, "memory_mb": runner.DOCKER_MEM_MB,
                "candidate_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest()}
    before = inputs()
    checked = {}
    for lang in LANGS:
        result = _run_reference(qid, lang, cases, backend)
        checked[lang] = result.status
        if result.status != "Accepted":
            raise ValueError(f"{lang}: {result.status}, case={result.failed_case}, {result.log[:160]}")
    if inputs() != before:
        raise ValueError("Reference inputs changed during validation")
    return {"protocol": 1, "inputs": before, "statuses": checked, "n_cases": len(cases)}


def golden_one(qid: int, lang: str, cases: list[dict], backend: str) -> dict:
    """一个 (题, 语言) 的自检。

    `status`      参考解对**该语言投过票的**用例（原语义）
    `status_full` 参考解对**全部**用例。旧检查只有前者，于是结构性地看不见
                  "从未投票的语言"——那种语言根本不会被执行，一个只有
                  Python/JavaScript 能表达的用例会表现为无害的 NO_VOTE 而不是失败。
    """
    out = {"qid": qid, "lang": lang, "status": "NO_VOTE", "error": "",
           "n_cases": len(cases), "n_voted": 0,
           "status_full": "", "error_full": "", "failed_case_full": None,
           # **超时标定**：此前这里**不记录 runtime**，于是"这台机器跑**正确解**
           # 需要多久"从未留下任何数据 —— 标定缺少最直接的基线。
           # 记下来之后才能判断"5 s 对正确解是否宽松"，以及哪些题的参考解
           # 本身就接近预算（那种题的**任何**解都可能在本地假 TLE）。
           "runtime": "", "memory": "", "runtime_ms": None, "memory_mb": None,
           "wall_ms": None, "protocol": REFERENCE_PROTOCOL}
    voted_cases = [c for c in cases if lang in c.get("votes", ["python3"])]
    out["n_voted"] = len(voted_cases)

    if cases:
        try:
            res = _run_reference(qid, lang, cases, backend)
            out["status_full"] = res.status
            out["failed_case_full"] = res.failed_case
            # 字段名是 runtime_ms / memory_mb（ExecResult），不是 runtime/memory
            out["runtime_ms"] = res.runtime_ms if res.runtime_available else None
            out["memory_mb"] = res.memory_mb if res.memory_available else None
            out["wall_ms"] = res.wall_ms
            out["runtime"] = f"{res.runtime_ms:.0f} ms" if res.runtime_available else ""
            out["memory"] = f"{res.memory_mb:.1f} MB" if res.memory_available else ""
            out["timing_source"] = res.timing_source if res.runtime_available else "unavailable"
            out["execution_supervisor"] = res.supervisor_protocol
            if res.status != "Accepted":
                out["error_full"] = res.log[:400]
        except Exception as e:  # noqa: BLE001
            out["status_full"] = "RENDER_ERROR"
            out["error_full"] = f"{type(e).__name__}: {e}"

    if not voted_cases:
        out["error"] = out["error_full"] or "no case carries this language's vote"
        return out
    if voted_cases == cases:
        out["status"] = out["status_full"]
        out["error"] = out["error_full"]
        return out
    try:
        res = _run_reference(qid, lang, voted_cases, backend)
        out["status"] = res.status
        out["error"] = res.log[:400] if res.status != "Accepted" else ""
    except Exception as e:  # noqa: BLE001
        out["status"] = "RENDER_ERROR"
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="语料自检（默认只读；重建需显式 rebuild --yes）")
    ap.add_argument("mode", nargs="?", default="check",
                    choices=["check", "rebuild"])
    ap.add_argument("--differential", default="local/results/differential.json")
    ap.add_argument("--max_workers", type=int, default=4)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--yes", action="store_true", help="rebuild 时确认覆盖")
    ap.add_argument("--no_reuse", action="store_true",
                    help="忽略缓存，全部重跑")
    # B4-001 的两道安全闸门（默认开启，需显式旗标才绕过）
    ap.add_argument("--allow-stale-source", action="store_true",
                    help="即使 differential.json 比现有语料旧也重建（默认拒绝）")
    ap.add_argument("--allow-drop", action="store_true",
                    help="即使会删掉当前语料里**合法**的用例也重建（默认拒绝）")
    args = ap.parse_args()

    if args.mode == "rebuild":
        rebuild(Path(args.differential), args.yes, args)
        print("\n重建完成。**请接着跑只读自检**确认没退化：")
        print("    python -m local.gen_testcases.validate")
        return

    if args.backend != "docker":
        raise SystemExit("The reference baseline requires Docker")
    from local.harness import runner
    from local.harness.identity import image_digest
    runner.DOCKER_IMAGE = image_digest()
    corpus = load_corpus()
    if set(corpus) != set(load_ft_test_qids()):
        raise SystemExit("Reference matrix incomplete: some requested problems lack corpus")
    fp = fingerprint(list(corpus))
    total = sum(len(v) for v in corpus.values())
    print(f"只读自检：{len(corpus)} 题 / {total} 条用例   指纹 {fp}")

    tasks = [(q, lang) for q in sorted(corpus) for lang in LANGS]
    out = Path(args.out)

    # Reuse only complete rows from the exact protocol, including an interrupted
    # partial file. A dict prevents duplicate history rows from inflating coverage.
    partial = out.with_suffix(out.suffix + ".partial")
    reusable = {}
    if not args.no_reuse:
        for source in (out, partial):
            if not source.exists():
                continue
            for line in source.read_text(encoding="utf-8").splitlines():
                try:
                    row = load_evidence(line)
                except ValueError:
                    continue
                pair = (row.get("qid"), row.get("lang"))
                if (pair in tasks and row.get("fingerprint") == fp
                        and row.get("protocol") == REFERENCE_PROTOCOL
                        and row.get("status_full") == "Accepted"
                        and valid_measurement(row.get("runtime_ms"))):
                    reusable[pair] = row
    done = set(reusable)
    remaining = [task for task in tasks if task not in done]
    print(f"  已完成 {len(done)}，待跑 {len(remaining)}")
    if remaining:
        out.parent.mkdir(parents=True, exist_ok=True)
        # B4-005：**不要边跑边追加到最终产物**。
        # 原先这里是 `with out.open("a") as f: f.write(...)` —— 于是运行期间
        # `golden_check.json` 只包含**已完成的那部分**（审查代理 B 三次读到
        # 46 → 78 → 102 行），任何在运行中读它的人都会把中间态当成"结果"，
        # 也无从判断那次 800/800 是否真的完整。
        #
        # 改成：结果先写到 `<out>.partial`，**全部跑完后原子替换**。
        # 复用缓存仍从 `out`（上一份完整产物）读 —— `done` 已在上面算好。
        partial = out.with_suffix(out.suffix + ".partial")
        # 指纹变了就整体重写（不复用旧行）；否则把已复用的旧行先写进 partial
        kept_lines = [json.dumps(reusable[pair], ensure_ascii=False, allow_nan=False) for pair in sorted(reusable)]
        partial.write_text(("\n".join(kept_lines) + "\n") if kept_lines else "",
                           encoding="utf-8")
        with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
            for r in ex.map(
                    lambda t: golden_one(t[0], t[1], corpus[t[0]], args.backend),
                    remaining):
                r["fingerprint"] = fp
                print(f"{r['qid']:>5} {r['lang']:11s} {r['status']}", flush=True)
                with partial.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
        # 原子替换：此刻之前 `out` 一直是**上一份完整产物**
        if fingerprint(list(corpus)) != fp:
            raise SystemExit("Inputs changed during reference run; partial results not published")
        partial.replace(out)
        print(f"  **产物已原子替换**：{out.name}"
              f"（{len(kept_lines)} 条复用 + {len(remaining)} 条新跑）")

    if not remaining:
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text("\n".join(json.dumps(reusable[pair], ensure_ascii=False, allow_nan=False)
                          for pair in sorted(reusable)) + "\n", encoding="utf-8")
        partial.replace(out)

    results = []
    for line in out.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                results.append(load_evidence(line))
            except ValueError:
                pass
    results = [r for r in results if r.get("fingerprint") == fp]
    bad = [r for r in results if r["status"] != "Accepted"]
    bad_full = [r for r in results
                if r.get("status_full") not in ("", "Accepted")]
    print(f"\n自检（仅投票用例）: {len(results) - len(bad)}/{len(results)} accepted")
    for r in bad:
        print(f"  VOTED-{r['status']:<12} {r['qid']} {r['lang']:11s} "
              f"{r['error'][:110]}")
    print(f"自检（**全语料**）: {len(results) - len(bad_full)}/{len(results)} "
          f"accepted")
    for r in bad_full:
        print(f"  FULL-{r.get('status_full',''):<13} {r['qid']} {r['lang']:11s} "
              f"case={r.get('failed_case_full')} {r.get('error_full','')[:110]}")
    if bad_full:
        print("\n全语料失败说明**语料**可疑，不是模型：一个合法用例必须能被"
              "每一个能表达它的参考解通过。")
    pairs = [(r.get("qid"), r.get("lang")) for r in results]
    complete = set(pairs) == set(tasks) and len(pairs) == len(tasks)
    sys.exit(1 if bad_full or not complete else 0)


if __name__ == "__main__":
    main()
