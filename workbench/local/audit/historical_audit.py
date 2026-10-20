# -*- coding: utf-8 -*-
"""Phase 1 -- 与历史 LeetCode 判定的大规模对拍。

不提交任何新代码：SFT_Full 里已有约 4.7 万条 (提交代码, LeetCode 判定) 配对，
本地重判即可与 oracle 对比。

方向分类（关键：两个方向含义相反）：

  false_ac   本地 AC   / LeetCode 非 AC    -> 本地用例**太弱**（覆盖不足）★ 主要目标
  false_wa   本地 非 AC / LeetCode AC      -> 本地用例**太严**或判题器缺陷
  same_neg   双方都非 AC 但类型不同        -> 多为环境/编译差异，一般不动语料
  agrees     判定一致

结果可续跑：每条槽位的本地判定缓存在 JSONL 里，重跑自动跳过。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from local.audit import pairing
from local.audit.wide_cases import get_wide_cases
from local.common import REPO_ROOT, TESTCASES_DIR
from local.harness.runner import docker_available
from local.judge import judge_one

ACCEPTED = "Accepted"
OUT_DIR = REPO_ROOT / "local" / "results" / "historical_audit"
CACHE = OUT_DIR / "judged_cache.jsonl"
_cache_lock = threading.Lock()


def has_corpus(qid: int) -> bool:
    """Is this problem in the local evaluation set (FT_test, 100 problems)?

    `judge_one` returns ac_status="Wrong Answer" when a qid has no corpus, so an
    out-of-scope submission would otherwise be counted as a conflicting verdict
    -- 2,223 gen slots come from a run that used a wider problem set.
    """
    return (TESTCASES_DIR / str(qid) / "cases.json").exists()


def load_cache() -> dict[str, dict]:
    """audit key -> full record, from previous runs (last write wins)."""
    out: dict[str, dict] = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("key"):
                    out[r["key"]] = r
    return out


def cache_append(rec: dict) -> None:
    with _cache_lock:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def classify(leetcode: str, local: str) -> str:
    if leetcode == local:
        return "agrees"
    if local == ACCEPTED:
        return "false_ac"
    if leetcode == ACCEPTED:
        return "false_wa"
    return "same_neg"


def audit_one(p: pairing.Pair, task: str, backend: str, timeout: int,
              cache: dict[str, dict], wide_on_gap: bool) -> dict:
    run_key = p.audit_key          # includes the run: never join across runs
    rec = cache.get(run_key, {})
    rec.update({"key": run_key, "run": p.run, "qid": p.slot.qid,
                "lang": p.slot.target_lang, "src": p.slot.src,
                "tgt": p.slot.tgt, "cand": p.slot.cand,
                "leetcode": p.leetcode_status})

    if not rec.get("local"):
        try:
            rec["local"] = judge_one(p.code_path, task, 30, backend,
                                     timeout)["ac_status"]
        except Exception as e:  # noqa: BLE001
            rec["local"] = f"error:{type(e).__name__}"
        rec.pop("wide", None)          # a fresh local verdict invalidates wide
        cache_append(rec)

    rec["klass"] = classify(p.leetcode_status, rec["local"])

    # Phase 0 integration: only false_ac slots (local AC / LeetCode not AC) can
    # reveal a coverage gap, and only they need the expensive wide re-judge.
    need_wide = (wide_on_gap and rec["klass"] == "false_ac"
                 and not rec.get("wide"))
    if need_wide:
        try:
            cases = get_wide_cases(p.slot.qid, backend=backend)
            rec["wide_ncases"] = len(cases)
            w = judge_one(p.code_path, task, 0, backend, timeout,
                          cases_override=cases)
            rec["wide"] = w["ac_status"]
            rec["wide_failed_at"] = (w.get("total_correct")
                                     if w["ac_status"] == "Wrong Answer" else None)
        except Exception as e:  # noqa: BLE001
            rec["wide"] = f"error:{type(e).__name__}"
        rec["gap_kind"] = ("gap_closed_by_wide"
                           if rec["wide"] != ACCEPTED else "confirmed_gap")
        if rec['wide'].startswith('error:') or rec['wide'] in ('INCOMPLETE', 'Pending'):
            rec['gap_kind'] = 'inconclusive'
        cache_append(rec)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="")
    ap.add_argument("--task", default="gen", choices=["gen", "trans"])
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--max_workers", type=int, default=8)
    # 与 judge.py 保持一致：5s 更贴近 LeetCode 的 TLE 口径（见 judge.py 注释）。
    ap.add_argument("--run_timeout_s", type=int, default=5)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--include_out_of_corpus", action="store_true",
                    help="也审计不在 FT_test 100 题内的提交（会产生假 false_wa）")
    ap.add_argument("--wide_on_gap", action="store_true",
                    help="对 false_ac 槽位再用全量用例集重判（Phase 0 集成，"
                         "区分'补用例能修'与'真缺口'）")
    args = ap.parse_args()

    # Preflight: fail fast if the sandbox is unavailable, instead of recording
    # every slot as a bogus verdict. (Docker CLI exit code 1 used to fall
    # through map_status() and be reported as "Runtime Error".)
    if args.backend == "docker":
        ok, info = docker_available()
        if not ok:
            sys.exit(f"preflight failed: docker/沙箱不可用 -> {info}")
        print(f"preflight ok: docker server {info}")

    runs = ([r for r in args.runs.split(",") if r.strip()]
            if args.runs else pairing.list_runs(args.task))
    print(f"task={args.task} runs={len(runs)}")

    pairs: list[pairing.Pair] = []
    for run in runs:
        pairs.extend(pairing.iter_pairs(run, args.task))
    total = len(pairs)
    skipped = [p for p in pairs if not has_corpus(p.slot.qid)]
    if not args.include_out_of_corpus:
        pairs = [p for p in pairs if has_corpus(p.slot.qid)]
    print(f"可对拍槽位 = {total}")
    if skipped:
        print(f"  其中 {len(skipped)} 条的题目不在本地评测集（FT_test 100 题）内"
              + ("，已跳过" if not args.include_out_of_corpus else "，仍纳入（会污染分类）"))
    print(f"纳入审计 = {len(pairs)}")

    cache = load_cache()
    print(f"本地判定缓存 = {len(cache)} 条（已判过的会跳过）")

    # Stratify by (run, qid), not qid alone: `pairs` is ordered run-first, so
    # interleaving on qid alone would exhaust the alphabetically-first run
    # before touching the others, making a partial run badly biased.
    by_rq: dict[tuple[str, int], list[pairing.Pair]] = defaultdict(list)
    for p in pairs:
        by_rq[(p.run, p.slot.qid)].append(p)
    keys = sorted(by_rq)
    chosen: list[pairing.Pair] = []
    i = 0
    while len(chosen) < args.limit:
        added = False
        for k in keys:
            if i < len(by_rq[k]):
                chosen.append(by_rq[k][i])
                added = True
                if len(chosen) >= args.limit:
                    break
        if not added:
            break
        i += 1
    print(f"本次处理 = {len(chosen)} 条（按 run×题 分层）")

    recs: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        for n, rec in enumerate(ex.map(
                lambda p: audit_one(p, args.task, args.backend,
                                    args.run_timeout_s, cache,
                                    args.wide_on_gap), chosen), 1):
            recs.append(rec)
            if n % 50 == 0 or n == len(chosen):
                print(f"  {n}/{len(chosen)}  {time.time()-t0:.0f}s", flush=True)

    # ---------------- report ----------------
    klasses = Counter(r["klass"] for r in recs)
    print("\n=== 方向分类 ===")
    print(f"  一致 agrees        {klasses.get('agrees', 0):5d}")
    print(f"  false_ac (覆盖不足) {klasses.get('false_ac', 0):5d}   <- 主要目标")
    print(f"  false_wa (太严/缺陷){klasses.get('false_wa', 0):5d}")
    print(f"  same_neg           {klasses.get('same_neg', 0):5d}")
    if klasses.get("error:judge_error"):
        print(f"  判定出错            {klasses.get('error:judge_error'):5d}")

    n = len(recs)
    if n:
        agree = klasses.get("agrees", 0) + klasses.get("same_neg", 0)
        print(f"\n  总体一致率 = {agree}/{n} ({agree/n*100:.1f}%)")

    for label, kind in (("覆盖不足 false_ac", "false_ac"),
                        ("太严/缺陷 false_wa", "false_wa")):
        rows = [r for r in recs if r["klass"] == kind]
        if not rows:
            continue
        print(f"\n=== {label}：按题排序（Top 15）===")
        per = Counter(r["qid"] for r in rows)
        for q, c in per.most_common(15):
            langs = Counter(r["lang"] for r in rows if r["qid"] == q)
            print(f"  q{q:<5} {c:3d} 槽位  " +
                  " ".join(f"{l}:{v}" for l, v in langs.most_common()))
        print("  按语言: " + " ".join(
            f"{l}:{v}" for l, v in Counter(r["lang"] for r in rows).most_common()))

    if args.wide_on_gap:
        gk = Counter(r.get("gap_kind", "not_evaluated")
                     for r in recs if r["klass"] == "false_ac")
        print(f"\n=== 缺口性质（全量用例能否修好）===")
        for k, v in gk.most_common():
            print(f"  {k:22s} {v:5d}")
        print("  gap_closed_by_wide = 用已有的全量用例即可修好；"
              "confirmed_gap = 必须新增场景（多为输入规模不足）")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    fields: list[str] = []
    for r in recs:
        for k in r:
            if k not in fields:
                fields.append(k)
    csv_p = OUT_DIR / f"historical_audit_{args.task}_{stamp}.csv"
    with csv_p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        for r in recs:
            w.writerow(r)
    print(f"\nCSV -> {csv_p}")
    print(f"缓存 -> {CACHE}（可续跑）")


if __name__ == "__main__":
    main()
