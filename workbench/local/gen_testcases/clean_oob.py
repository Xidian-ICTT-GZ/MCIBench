# -*- coding: utf-8 -*-
"""清理超出题面约束的用例（scale_gap 的"标量越界"类）。

为什么必须清：约束**之内**正确的解法会被这些用例判错。实测 q2595：
语料含 `n=2047` 而约束是 `1 <= n <= 1000`，模型只循环 10 位的解法（覆盖到 1023）
因此被判 WA，而 LeetCode（用例守约束）判 AC。

安全性：**先 dry-run 逐条列出**（哪题、哪条、哪个参数、值、界），
确认后才 `--apply`；写入前自动备份。删除会减少覆盖，所以必须精确——
误删一条合法用例会把假的 AC 造出来。

用法：
    python -m local.gen_testcases.clean_oob                 # 全量 dry-run
    python -m local.gen_testcases.clean_oob --qids 1432     # 只看某题
    python -m local.gen_testcases.clean_oob --qids 1432 --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.audit.scale_gap import (_desc_text, _expand_flattened,  # noqa: E402
                                   _normalize_bounds, constraints_block,
                                   declared_bounds)
from local.common import TESTCASES_DIR, load_json, load_snippet, save_json  # noqa: E402
from local.harness.typespec import (Bool, Float, Int, ListT, Str,  # noqa: E402
                                    parse_python_snippet)

import re  # noqa: E402
from local.gen_testcases.corpus_io import (  # noqa: E402
    atomic_save, sync_meta, unique_backup, publish_checked_cases)


# "1 <= nums[i] <= 105" / "-109 <= nums[i] <= 109" -> per-param VALUE bound.
# Using one global max for every param would flag values that are legal for
# their own param but above a smaller sibling's bound -- so resolve per param.
_PARAM_BOUND = re.compile(
    r"(?P<lo>-?\s*\d[\d,]*)\s*<=\s*(?P<name>\w+)\s*(?:\[[^\]]*\])*\s*"
    r"<=\s*(?P<hi>-?\s*\d[\d,]*)")





def param_bounds(qid: int) -> dict[str, int]:
    """Largest declared |value| bound per parameter name (best effort)."""
    block = _normalize_bounds(constraints_block(_desc_text(qid)))
    out: dict[str, int] = {}
    for m in _PARAM_BOUND.finditer(block):
        name = m.group("name")
        try:
            hi = abs(int(m.group("hi").replace(",", "").replace(" ", "")))
        except ValueError:
            continue
        # The .txt dumps lose superscripts, so "10^4" arrives as "104";
        # without this the bound reads as 104 and every value looks illegal.
        out[name] = max(out.get(name, 0), _expand_flattened(hi))
    return out


def _ints(v):
    """All integers inside a value (scalars and list elements, recursively)."""
    if isinstance(v, bool):
        return
    if isinstance(v, int):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from _ints(x)


def scan(qid: int) -> tuple[list[dict], int, int | None]:
    """Return (violating cases, total cases, global value bound)."""
    p = TESTCASES_DIR / str(qid) / "cases.json"
    if not p.exists():
        return [], 0, None
    glob = declared_bounds(qid).get("value")
    per = param_bounds(qid)
    if not glob and not per:
        return [], len(json.loads(p.read_text(encoding="utf-8"))), None
    cases = json.loads(p.read_text(encoding="utf-8"))
    bad = []
    for i, c in enumerate(cases):
        args = c.get("args")
        if not isinstance(args, dict):
            continue
        hits = []
        for name, v in args.items():
            # prefer this parameter's own bound; fall back to the global max
            bound = per.get(name) or glob
            if not bound:
                continue
            big = [x for x in _ints(v) if abs(x) > bound]
            if big:
                hits.append((name, max(big, key=abs), bound))
        if hits:
            bad.append({"index": i, "hits": hits})
    return bad, len(cases), glob


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="", help="逗号分隔；留空则扫描全部")
    ap.add_argument("--apply", action="store_true", help="真的删除（会自动备份）")
    ap.add_argument("--allow-unparsed", action="store_true",
                    help="即使题面有解析不出来的约束也删除（默认拒绝，防止 q2140 那种误删）")
    args = ap.parse_args()

    if args.qids.strip():
        qids = [int(x) for x in args.qids.split(",") if x.strip()]
    else:
        qids = sorted(int(d.name) for d in TESTCASES_DIR.iterdir()
                      if d.is_dir() and d.name.isdigit())

    total_bad = total_removed = 0
    plan = []
    for qid in qids:
        bad, n, bound = scan(qid)
        if not bad:
            continue
        total_bad += len(bad)
        print(f"\nq{qid}: {len(bad)}/{n} 条超界")
        for b in bad[:6]:
            desc = ", ".join(f"{nm}={val} (界 {bd})" for nm, val, bd in b["hits"])
            print(f"    case[{b['index']}]  {desc}")
        if len(bad) > 6:
            print(f"    ... 另 {len(bad)-6} 条")
        plan.append((qid, [b["index"] for b in bad], n))

    print(f"\n合计：{len(plan)} 题、{total_bad} 条超界用例")
    if not args.apply:
        print("（dry-run；确认后加 --apply 执行）")
        return

    for qid, idxs, n in plan:
        p = TESTCASES_DIR / str(qid) / "cases.json"
        old_bytes = p.read_bytes()
        cases = json.loads(old_bytes)
        keep = [c for i, c in enumerate(cases) if i not in set(idxs)]
        # B4-002：**未知闸门**。删除是单向动作，而"未实现的规则"与
        # "没有约束"在数据上分不开 —— 这正是 q2140 事故的形态
        # （上限误写成 4 → 合法用例被当非法删掉，且没有第二道防线）。
        # 题面里有解析不出来的约束时，拒绝删除，除非显式 --allow-unparsed。
        from local.gen_testcases.constraints import unparsed as _unp
        if _unp(qid) and not getattr(args, "allow_unparsed", False):
            print(f"  q{qid}: **有 {len(_unp(qid))} 行约束未能解析，拒绝删除**"
                  f"（按未知处理；确认要删除请加 --allow-unparsed）")
            for line in _unp(qid)[:2]:
                print(f"      {line[:86]}")
            continue
        publish_checked_cases(p, keep, old_bytes, "clean_oob",
                              allow_unparsed=args.allow_unparsed)
        total_removed += len(cases) - len(keep)
        print(f"  q{qid}: {len(cases)} -> {len(keep)}（备份 .bak_pre_oob[.N]）")
    print(f"\n共删除 {total_removed} 条")


if __name__ == "__main__":
    main()
