# -*- coding: utf-8 -*-
r"""用语料约束检查器扫描全部 100 题语料，报告非法条目与未验证的题。

    python -m local.gen_testcases.scan_corpus            # 只报告
    python -m local.gen_testcases.scan_corpus --apply    # 移出非法条目（带备份）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.common import TESTCASES_DIR, load_ft_test_qids  # noqa: E402
from local.gen_testcases.constraints import check, unparsed  # noqa: E402
from local.gen_testcases.corpus_io import (  # noqa: E402
    atomic_save, sync_meta, unique_backup, publish_checked_cases)



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="把非法条目移出语料（备份为 .bak_constraints）")
    ap.add_argument("--allow-unparsed", action="store_true",
                    help="即使题面有解析不出来的约束也删除（默认拒绝，防止 q2140 那种误删）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 题")
    args = ap.parse_args()

    qids = load_ft_test_qids()
    if args.limit:
        qids = qids[:args.limit]

    total = illegal_total = 0
    skipped_unparsed = 0
    per_q: dict[int, list] = {}
    reasons = Counter()
    unver: dict[int, list[str]] = {}

    for q in qids:
        p = TESTCASES_DIR / str(q) / "cases.json"
        if not p.exists():
            continue
        old_bytes = p.read_bytes()
        cases = json.loads(old_bytes)
        total += len(cases)
        bad = []
        for c in cases:
            v = check(q, c)
            if v:
                bad.append((c, v))
                reasons[v[0].split("=")[0].split("[")[0]] += 1
        if bad:
            per_q[q] = bad
            illegal_total += len(bad)
        u = unparsed(q)
        if u:
            unver[q] = u

    print(f"扫描 {len(qids)} 题，语料共 {total} 条")
    print(f"**非法条目 {illegal_total} 条**，涉及 {len(per_q)} 题\n")

    if per_q:
        print("按题（前 20）:")
        for q, bad in sorted(per_q.items(), key=lambda kv: -len(kv[1]))[:20]:
            print(f"  q{q:<6} {len(bad):>4} 条   例: "
                  f"{json.dumps(bad[0][0]['args'], ensure_ascii=False)[:60]}"
                  f"  <- {bad[0][1][0][:46]}")
        print("\n违规类型:")
        for k, n in reasons.most_common(10):
            print(f"  {k:<24} {n}")

    if unver:
        print(f"\n含**未解析约束**的题 {len(unver)} 道（这些题的用例不应默认通过）:")
        for q, u in list(unver.items())[:12]:
            print(f"  q{q}: {u[0][:60]}")
        if len(unver) > 12:
            print(f"  … 另 {len(unver)-12} 道")

    if not args.apply:
        print("\n（加 --apply 才移出非法条目）")
        return

    moved = 0
    change_log: list[dict] = []
    for q, bad in per_q.items():
        p = TESTCASES_DIR / str(q) / "cases.json"
        # B2-005：**未知闸门**。`--apply` 会**单向删除**语料，而"未实现的规则"
        # 与"没有约束"在数据上分不开 —— 这正是 q2140 事故的形态
        # （上限误写成 4 → 合法用例被当非法删掉，而且没有第二道防线）。
        # 题面里有解析不出来的约束时，删除动作一律拒绝，除非显式 --allow-unparsed。
        if unparsed(q) and not args.allow_unparsed:
            print(f"  q{q}: **有 {len(unparsed(q))} 行约束未能解析，拒绝删除**"
                  f"（按未知处理；确认要删除请加 --allow-unparsed）")
            for line in unparsed(q)[:2]:
                print(f"      {line[:86]}")
            skipped_unparsed += 1
            continue
        # B-012：备份只**增**不覆盖。此前 `if not bak.exists()` 让第二次删除
        # 无法单独回滚（上一次状态的回滚副本还在，但它对应的是更早的语料）。
        bak = unique_backup(p, ".bak_constraints")   # B3-003：统一到 corpus_io
        old_bytes = p.read_bytes()
        cases = json.loads(old_bytes)
        keep = []
        for c in cases:
            v = check(q, c)
            if v:
                # B-012：删除原因必须**落盘**，不能只 print。
                # 规范 7.2「删除用例前必须能逐条解释」。
                change_log.append({
                    "qid": q, "action": "remove",
                    "reason": v, "case": c,
                    "backup": bak.name,
                    "source": "scan_corpus（约束检查器）",
                })
            else:
                keep.append(c)
        # B-012：写盘用临时文件 + 原子替换，避免中断留下半截语料
        publish_checked_cases(p, keep, old_bytes, "scan_corpus",
                              allow_unparsed=args.allow_unparsed)
        moved += len(cases) - len(keep)

    # 变更清单落盘（规范 7.2 的可回滚 + 可解释要求）
    if change_log:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        logdir = TESTCASES_DIR.parent / "results" / "corpus_changes"
        logdir.mkdir(parents=True, exist_ok=True)
        logp = logdir / f"scan_corpus-{stamp}.json"
        logp.write_text(json.dumps(change_log, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"\n变更清单已落盘: {logp}")
    acted = len(per_q) - skipped_unparsed
    print(f"\n已移出 {moved} 条非法用例，实际处理 {max(0, acted)} 题"
          f"（备份 *.bak_constraints）")
    # B3-004：此前把"被闸门拒绝"的题也算进"涉及 N 题"，读者会以为清理覆盖了它
    if skipped_unparsed:
        print(f"另有 **{skipped_unparsed} 题因含未解析约束被拒绝删除**"
              f"（按未知处理，未改动它们的语料）")
    print("注意：语料变了，需重判受影响的题。")


if __name__ == "__main__":
    main()
