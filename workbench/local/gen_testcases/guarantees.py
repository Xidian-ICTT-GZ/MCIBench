# -*- coding: utf-8 -*-
r"""题面「输入保证」校验：找出违反题面声明的用例。

与 `clean_oob` 的分工
--------------------
- `clean_oob` 查**数值范围**（`1 <= nums[i] <= 10^5`）。
- 本模块查**结构性保证**：有序性、排列/去重、长度奇偶、参数间关系。

为什么必须单独查
----------------
**差分投票拦不住这类污染。** 8 种语言的参考解共享同一个「输入已满足保证」的假设，
于是它们会「一致地」算出同一个错误期望值，全票通过。实测 q624 的语料含
`[-1,-2,-3]`（题面要求每个子数组升序），所有参考解都按「`arrays[i][0]` 是最小值」
写，于是把一个在约束内完全正确的解法判成 WA。

用法
----
    python -m local.gen_testcases.guarantees              # 全量扫描
    python -m local.gen_testcases.guarantees --qids 624   # 只看某题
    python -m local.gen_testcases.guarantees --strict     # 有违例即非零退出
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.audit.scale_gap import constraints_block, _desc_text  # noqa: E402
from local.common import TESTCASES_DIR, load_ft_test_qids  # noqa: E402
from local.gen_testcases.corpus_io import (  # noqa: E402
    atomic_save, sync_meta, unique_backup, publish_checked_cases)


# ---- 题面措辞 → 检查规则 -------------------------------------------------
# 主体允许 `nums` 或 `arrays[i]`（带下标表示逐行检查）。
_UNIT = r"[A-Za-z_]\w*(?:\s*\[[^\]]*\])*"
SORTED = re.compile(
    rf"(?P<name>{_UNIT})\s+is\s+sorted\s+in\s+"
    r"(?P<dir>non-?decreasing|non-?increasing|ascending|descending|increasing)\s+order",
    re.I)
PERMUTATION = re.compile(
    rf"(?P<a>{_UNIT})\s+is\s+a\s+permutation\s+of\s+(?P<b>{_UNIT})", re.I)
LEN_EQ = re.compile(
    rf"(?P<a>{_UNIT})\.length\s*==\s*(?P<b>{_UNIT})\.length")
LEN_EVEN = re.compile(rf"(?P<name>{_UNIT})\.length\s+is\s+even", re.I)
HALF_EVEN = re.compile(
    r"Half of the integers in\s+(?P<name>\w+)\s+are even", re.I)


@dataclass
class Violation:
    qid: int
    case_index: int
    rule: str
    detail: str


def _base(subject: str) -> str:
    """'arrays[i]' -> 'arrays'."""
    return re.split(r"[\[.\s]", subject.strip())[0]


def _is_row_form(subject: str) -> bool:
    return "[" in subject


def _ints(v):
    if isinstance(v, bool):
        return
    if isinstance(v, int):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from _ints(x)


def _monotone(seq: list, direction: str) -> bool:
    inc = direction.lower().replace("-", "") in ("nondecreasing", "ascending",
                                                 "increasing")
    for i in range(len(seq) - 1):
        if inc and seq[i] > seq[i + 1]:
            return False
        if not inc and seq[i] < seq[i + 1]:
            return False
    return True


def rules_for(qid: int) -> list[tuple[str, object]]:
    """(规则名, 检查函数) —— 检查函数 (args) -> 违例说明或 None。"""
    txt = constraints_block(_desc_text(qid))
    out: list[tuple[str, object]] = []

    for m in SORTED.finditer(txt):
        name, direction = _base(m.group("name")), m.group("dir")
        row_form = _is_row_form(m.group("name"))

        def check_sorted(args, name=name, direction=direction, row_form=row_form):
            v = args.get(name)
            if not isinstance(v, list) or not v:
                return None
            if row_form or all(isinstance(x, list) for x in v):
                for r in v:
                    if isinstance(r, list) and r and not _monotone(r, direction):
                        return f"{name} 的一行 {r[:6]} 非 {direction}"
                return None
            if all(isinstance(x, int) and not isinstance(x, bool) for x in v):
                if not _monotone(v, direction):
                    return f"{name} 非 {direction}"
            return None

        out.append((f"sorted:{name}:{direction}", check_sorted))

    for m in PERMUTATION.finditer(txt):
        a, b = _base(m.group("a")), _base(m.group("b"))

        def check_perm(args, a=a, b=b):
            va, vb = args.get(a), args.get(b)
            if not isinstance(va, list) or not va or not isinstance(vb, list):
                return None
            if not vb:
                return None
            base = sorted(str(vb[0]))
            for s in va:
                if isinstance(s, str) and sorted(s) != base:
                    return f"{a} 中的 {s!r} 不是 {vb[0]!r} 的排列"
            return None

        out.append((f"permutation:{a}", check_perm))

    for m in HALF_EVEN.finditer(txt):
        name = _base(m.group("name"))

        def check_half_even(args, name=name):
            v = args.get(name)
            if not (isinstance(v, list) and v):
                return None
            ev = sum(1 for x in _ints(v) if x % 2 == 0)
            od = sum(1 for x in _ints(v) if x % 2 == 1)
            if ev != od:
                return f"{name} 偶数 {ev} 个、奇数 {od} 个，题面要求各占一半"
            return None

        out.append((f"half_even:{name}", check_half_even))

    for m in LEN_EVEN.finditer(txt):
        name = _base(m.group("name"))

        def check_len_even(args, name=name):
            v = args.get(name)
            if isinstance(v, list) and len(v) % 2 == 1:
                return f"{name} 长度为 {len(v)}，题面要求偶数"
            return None

        out.append((f"len_even:{name}", check_len_even))

    for m in LEN_EQ.finditer(txt):
        a, b = _base(m.group("a")), _base(m.group("b"))

        def check_len_eq(args, a=a, b=b):
            va, vb = args.get(a), args.get(b)
            if isinstance(va, list) and isinstance(vb, list) and len(va) != len(vb):
                return f"{a}({len(va)}) 与 {b}({len(vb)}) 长度不等"
            return None

        out.append((f"len_eq:{a}=={b}", check_len_eq))

    return out


def scan_problem(qid: int) -> tuple[list[Violation], list[str]]:
    import json
    p = TESTCASES_DIR / str(qid) / "cases.json"
    if not p.exists():
        return [], []
    rules = rules_for(qid)
    if not rules:
        return [], []
    cases = json.loads(p.read_text(encoding="utf-8"))
    out: list[Violation] = []
    for i, c in enumerate(cases):
        args = c.get("args")
        if not isinstance(args, dict):
            continue
        for rname, fn in rules:
            try:
                msg = fn(args)
            except Exception:  # noqa: BLE001
                continue
            if msg:
                out.append(Violation(qid, i, rname, msg))
    return out, [r[0] for r in rules]


def apply_fixes(qids: list[int], *, allow_unparsed: bool = False) -> int:
    """删除违反输入保证的用例（写入前备份）。返回删除条数。"""
    import json
    from local.common import save_json
    removed = 0
    for qid in qids:
        vs, _ = scan_problem(qid)
        if not vs:
            continue
        p = TESTCASES_DIR / str(qid) / "cases.json"
        old_bytes = p.read_bytes()
        cases = json.loads(old_bytes)
        drop = {v.case_index for v in vs}
        keep = [c for i, c in enumerate(cases) if i not in drop]
        # B4-002：**未知闸门**。删除是单向动作，而"未实现的规则"与
        # "没有约束"在数据上分不开 —— 这正是 q2140 事故的形态
        # （上限误写成 4 → 合法用例被当非法删掉，且没有第二道防线）。
        # 题面里有解析不出来的约束时，拒绝删除，除非显式 --allow-unparsed。
        from local.gen_testcases.constraints import unparsed as _unp
        if _unp(qid) and not allow_unparsed:
            print(f"  q{qid}: **有 {len(_unp(qid))} 行约束未能解析，拒绝删除**"
                  f"（按未知处理；确认要删除请加 --allow-unparsed）")
            for line in _unp(qid)[:2]:
                print(f"      {line[:86]}")
            continue
        publish_checked_cases(p, keep, old_bytes, "guarantees",
                              allow_unparsed=allow_unparsed)
        removed += len(cases) - len(keep)
        print(f"  q{qid}: {len(cases)} -> {len(keep)}"
              f"（删 {len(cases)-len(keep)}，备份 .bak_pre_guarantees）")
    return removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--apply", action="store_true", help="删除违例用例（自动备份）")
    ap.add_argument("--allow-unparsed", action="store_true",
                    help="即使题面有解析不出来的约束也删除（默认拒绝，防止 q2140 那种误删）")
    ap.add_argument("--strict", action="store_true",
                    help="发现违例即非零退出")
    args = ap.parse_args()

    qids = ([int(x) for x in args.qids.split(",") if x.strip()]
            if args.qids.strip() else load_ft_test_qids())
    n_rules = 0
    total = 0
    for qid in qids:
        vs, rnames = scan_problem(qid)
        n_rules += len(rnames)
        if not vs:
            continue
        total += len(vs)
        by_rule: dict[str, list[Violation]] = {}
        for v in vs:
            by_rule.setdefault(v.rule, []).append(v)
        import json
        n = len(json.loads((TESTCASES_DIR / str(qid) / "cases.json")
                           .read_text(encoding="utf-8")))
        print(f"\nq{qid}: {len(vs)}/{n} 条违反输入保证")
        for rule, group in by_rule.items():
            print(f"  [{rule}] {len(group)} 条")
            for v in group[:4]:
                print(f"      case[{v.case_index}] {v.detail}")
            if len(group) > 4:
                print(f"      ... 另 {len(group)-4} 条")

    print(f"\n扫描 {len(qids)} 题、{n_rules} 条规则；"
          f"共 {total} 条违例用例")
    if args.apply and total:
        print("\n执行删除：")
        n = apply_fixes(qids, allow_unparsed=args.allow_unparsed)
        print(f"共删除 {n} 条")
        return
    if args.strict and total:
        sys.exit(1)


if __name__ == "__main__":
    main()
