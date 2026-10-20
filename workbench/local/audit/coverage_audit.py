# -*- coding: utf-8 -*-
"""Phase 0 -- 覆盖度审计。

问题：语料固定 30 个用例（实际可用 8,494 个，68% 被丢弃）。LeetCode 判某个提交
不通过，本地判它通过 —— 这就是"用例不全"的候选证据。

流程（每条槽位）：
  1. 读历史 LeetCode 判定（oracle）
  2. 用**生产语料**（≤30 用例）本地重判        -> narrow
  3. 若 narrow == Accepted 而 LeetCode != Accepted：
     用**全量用例集**（未截断，见 wide_cases.py）再判 -> wide
  4. 分类：
       gap_closed_by_wide : narrow 过、wide 挂  -> 补用例就能修好（有救）
       confirmed_gap      : narrow 过、wide 也过 -> 两套用例都没覆盖到（真缺口）
       agrees_negative    : narrow 就挂了        -> 本地与 LeetCode 一致
       too_strict         : LeetCode 过、narrow 挂 -> 反向问题（语料/判题器缺陷）

只产出报告，不改语料。
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
from local.audit.historical_audit import has_corpus
from local.audit.wide_cases import get_wide_cases
from local.judge import judge_one
from local.common import REPO_ROOT

ACCEPTED = "Accepted"
# LeetCode verdicts worth auditing: the submission produced code that ran but
# was rejected. Compile Error is usually the model's output format, not coverage.
HUNT = {"Wrong Answer", "Runtime Error", "Time Limit Exceeded",
        "Memory Limit Exceeded"}

_wide_lock = threading.Lock()
_wide_cache: dict[int, list[dict]] = {}


def _wide(qid: int, backend: str) -> list[dict]:
    with _wide_lock:
        return get_wide_cases(qid, backend=backend)


def sample_round_robin(pairs: list[pairing.Pair], limit: int) -> list[pairing.Pair]:
    """Interleave by (run, problem) so a limited run still covers the whole scope.

    Stratifying on problem alone would exhaust the alphabetically-first run
    before reaching the others, because `pairs` is ordered run-first.
    """
    by_rq: dict[tuple[str, int], list[pairing.Pair]] = defaultdict(list)
    for p in pairs:
        by_rq[(p.run, p.slot.qid)].append(p)
    keys = sorted(by_rq)
    out: list[pairing.Pair] = []
    i = 0
    while len(out) < limit:
        added = False
        for k in keys:
            if i < len(by_rq[k]):
                out.append(by_rq[k][i])
                added = True
                if len(out) >= limit:
                    break
        if not added:
            break
        i += 1
    return out


def classify(leetcode: str, narrow: str, wide: str | None) -> str:
    if narrow.startswith('error:') or narrow in ('INCOMPLETE', 'Pending'):
        return 'inconclusive'
    if wide is not None and (wide.startswith('error:') or wide in ('INCOMPLETE', 'Pending')):
        return 'inconclusive'
    if leetcode == ACCEPTED and narrow != ACCEPTED:
        return "too_strict"
    if narrow == ACCEPTED and leetcode != ACCEPTED:
        if wide is None:
            return "suspected_gap"
        return "gap_closed_by_wide" if wide != ACCEPTED else "confirmed_gap"
    if narrow == leetcode:
        return "agrees"
    return "agrees_negative" if narrow != ACCEPTED and leetcode != ACCEPTED else "other"


def audit_slot(p: pairing.Pair, task: str, backend: str, max_workers_note: int,
               run_timeout_s: int, hunt_only: bool) -> dict:
    leet = p.leetcode_status
    rec = {
        "run": p.run,
        "qid": p.slot.qid,
        "lang": p.slot.target_lang,
        "src": p.slot.src,
        "tgt": p.slot.tgt,
        "cand": p.slot.cand,
        "code": str(p.code_path.relative_to(REPO_ROOT)),
        "leetcode": leet,
    }
    if hunt_only and leet not in HUNT:
        rec.update(narrow="", wide="", klass="skipped")
        return rec

    try:
        nr = judge_one(p.code_path, task, 30, backend, run_timeout_s)
        narrow = nr["ac_status"]
    except Exception as e:  # noqa: BLE001
        rec.update(narrow="", wide="", klass="judge_error", error=str(e)[:200])
        return rec
    rec["narrow"] = narrow
    rec["narrow_ncases"] = nr.get("total_testcases", 0)

    wide = None
    if narrow == ACCEPTED and leet != ACCEPTED:
        try:
            cases = _wide(p.slot.qid, backend)
            rec["wide_ncases"] = len(cases)
            wr = judge_one(p.code_path, task, 0, backend, run_timeout_s,
                           cases_override=cases)
            wide = wr["ac_status"]
            rec["wide_failed_at"] = (wr.get("total_correct")
                                     if wide == "Wrong Answer" else None)
            rec["wide_error"] = wr.get("_meta", {}).get("error", "")[:200]
        except Exception as e:  # noqa: BLE001
            wide = f"error:{type(e).__name__}"
    rec["wide"] = wide or ""
    rec["klass"] = classify(leet, narrow, wide)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="", help="逗号分隔；空=全部可对拍 run")
    ap.add_argument("--task", default="gen", choices=["gen", "trans"])
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--max_workers", type=int, default=6)
    ap.add_argument("--run_timeout_s", type=int, default=20)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--all_verdicts", action="store_true",
                    help="也审计 LeetCode==Accepted 的槽位（默认只查被拒的）")
    ap.add_argument("--out", default="local/results/coverage_audit")
    ap.add_argument("--qids", default="",
                    help="只审计这些题号（逗号分隔），用于针对已知缺口精确归因")
    args = ap.parse_args()

    runs = ([r for r in args.runs.split(",") if r.strip()]
            if args.runs else pairing.list_runs(args.task))
    print(f"task={args.task} runs={len(runs)}")

    pairs: list[pairing.Pair] = []
    for run in runs:
        pairs.extend(pairing.iter_pairs(run, args.task))
    total = len(pairs)
    pairs = [p for p in pairs if has_corpus(p.slot.qid)]
    if args.qids:
        want = {int(x) for x in args.qids.split(",") if x.strip()}
        pairs = [p for p in pairs if p.slot.qid in want]
        print(f"按题筛选 --qids: 保留 {len(pairs)} 槽位（{len(want)} 道题）")
    print(f"可对拍槽位 = {total}（其中 {total-len(pairs)} 被过滤）")
    hunt = [p for p in pairs if p.leetcode_status in HUNT]
    print(f"其中 LeetCode 被拒（审计目标）= {len(hunt)}")

    chosen = sample_round_robin(hunt, args.limit)
    print(f"本次审计 = {len(chosen)} 条")

    out_dir = REPO_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    jsonl = out_dir / f"coverage_audit_{args.task}_{stamp}.jsonl"

    recs: list[dict] = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        with jsonl.open("w", encoding="utf-8") as f:
            for rec in ex.map(lambda p: audit_slot(
                    p, args.task, args.backend, args.max_workers,
                    args.run_timeout_s, not args.all_verdicts), chosen):
                recs.append(rec)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                done += 1
                if done % 25 == 0 or done == len(chosen):
                    print(f"  {done}/{len(chosen)}  {time.time()-t0:.0f}s", flush=True)

    # ---------------- report ----------------
    klasses = Counter(r["klass"] for r in recs)
    print(f"\n=== 分类 ===")
    for k, n in klasses.most_common():
        print(f"  {k:22s} {n:5d}")

    gaps = [r for r in recs if r["klass"] in ("confirmed_gap", "gap_closed_by_wide")]
    per_q = Counter(r["qid"] for r in gaps)
    print(f"\n=== 疑似覆盖不足的题（共 {len(per_q)} 题 / {len(gaps)} 槽位）===")
    for q, n in per_q.most_common(30):
        closed = sum(1 for r in gaps if r["qid"] == q
                     and r["klass"] == "gap_closed_by_wide")
        print(f"  q{q:<5} {n:3d} 槽位  其中 {closed} 个补全量用例即可修好")

    csv_p = out_dir / f"coverage_audit_{args.task}_{stamp}.csv"
    fieldnames: list[str] = []
    for r in recs:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with csv_p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        w.writeheader()
        for r in recs:
            w.writerow(r)

    print("\n=== 疑似覆盖不足的槽位明细 ===")
    for r in sorted(gaps, key=lambda x: (x["qid"], x["lang"]))[:25]:
        extra = (f"  全量用例在 case {r['wide_failed_at']} 挂了"
                 if r.get("wide_failed_at") is not None else
                 "  全量用例也过 -> 需新增场景")
        print(f"  q{r['qid']:<5} {r['lang']:11s} cand{r['cand']} "
              f"narrow={r['narrow_ncases']} wide={r.get('wide_ncases','-')} "
              f"[{r['klass']}]{extra}")

    print(f"\n明细 -> {jsonl}")
    print(f"CSV  -> {csv_p}")


if __name__ == "__main__":
    main()
