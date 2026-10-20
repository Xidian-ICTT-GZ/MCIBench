# -*- coding: utf-8 -*-
"""规模缺口诊断：语料用例的规模 vs 题面 Constraints。

Phase 0/1 的 `confirmed_gap` 有一个共同根因：语料的输入**规模**远小于题目约束
（实测 q2270 语料 n≤30，而约束 n≤10^5，模型在 C 里的 int 累加只在 LeetCode 的规模下
才溢出）。加更多同规模用例没有用，必须补**更大规模**的用例。

本工具按题对比"语料里参数的最大长度/最大绝对值"与"题面 Constraints 声明的上界"，
给出差距倍数，用来排定补用例的优先级。

    python -m local.audit.scale_gap
    python -m local.audit.scale_gap --qids 2270,1550 --json local/results/scale_gap.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from local.common import REPO_ROOT, TESTCASES_DIR, load_ft_test_qids

DESC_DIR = REPO_ROOT / "MCIBench-test" / "metadata" / "problems" / "descriptions"

# "1 <= nums.length <= 10^5" / "2 * 10^4" / "<= 2000"
# The .txt dumps lose superscripts, so "2 * 10^4" arrives as "2 * 104" and
# "10^5" as "105"; both forms must be reconstructed or the bound is understated.
_BOUND_PATTERNS = (
    re.compile(r"\*\s*10\s*\^\s*(\d+)"),          # explicit  2 * 10^4
    re.compile(r"(\d+)\s*\*\s*10(\d)\b"),          # flattened 2 * 104
    re.compile(r"<=\s*10\s*\^\s*(\d+)"),           # explicit  10^5
    re.compile(r"<=\s*2\s*\^\s*(\d+)"),
    re.compile(r"<=\s*(\d[\d,]*)\s*$", re.M),
    re.compile(r"<=\s*(\d[\d,]*)"),
)


def _desc_text(qid: int) -> str:
    d = DESC_DIR / str(qid)
    if not d.is_dir():
        return ""
    for p in sorted(d.iterdir()):
        if p.is_file() and "English" in p.name and p.suffix == ".txt":
            return p.read_text(encoding="utf-8", errors="replace")
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix == ".txt":
            return p.read_text(encoding="utf-8", errors="replace")
    return ""


def _expand_flattened(n: int) -> int:
    """Undo superscript flattening in the extracted problem text.

    The .txt dumps lose `<sup>` markup, so `10^5` arrives as `105`, `10^4` as
    `104`, and `10^15` as `1015`. Such a bound is a power of ten, not a literal.

    Rule: `10` followed by 1-2 digits that do not start with 0. The leading-zero
    guard keeps genuine round numbers (`1000`, `100000`) intact. A real bound of
    exactly 10X is vanishingly unlikely here, and this only affects diagnostics.
    """
    s = str(n)
    if s.startswith("10") and 3 <= len(s) <= 4:
        rest = s[2:]
        if rest and rest[0] != "0":
            return 10 ** int(rest)
    return n


def constraints_block(txt: str) -> str:
    i = txt.find("Constraints")
    return txt[i:] if i >= 0 else txt


_MULT_POW = re.compile(r"(\d+)\s*\*\s*10\s*\^?\s*(\d+)")
_POW10 = re.compile(r"(?<![\d])10\s*\^\s*(\d+)")


def _normalize_bounds(text: str) -> str:
    """Rewrite 'A * 10^B' / 'A * 10B' / '10^B' into plain integers.

    Superscripts are lost in the .txt dumps, so `2 * 10^4` arrives as `2 * 104`
    and `10^5` as `105`. Without this the bound is understated (q922's
    `2 * 104` parsed as 2 instead of 20000).
    """
    text = _MULT_POW.sub(lambda m: str(int(m.group(1)) * 10 ** int(m.group(2))),
                         text)
    return _POW10.sub(lambda m: str(10 ** int(m.group(1))), text)


def declared_bounds(qid: int) -> dict:
    """Largest declared length bound and largest declared value bound."""
    block = constraints_block(_desc_text(qid))
    if not block:
        return {"length": None, "value": None, "raw": ""}
    block = _normalize_bounds(block)
    length = value = None
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith(("1 <=", "0 <=", "-", "1<=", "0<=")) and "<=" not in line:
            continue
        nums = []
        for pat in _BOUND_PATTERNS:
            for m in pat.finditer(line):
                g = m.group(1).replace(",", "")
                try:
                    n = int(g)
                except ValueError:
                    continue
                nums.append(_expand_flattened(n))
        if not nums:
            continue
        hi = max(nums)
        if ".length" in line or "length of" in line or re.search(r"\bn\b", line):
            length = max(length or 0, hi)
        else:
            value = max(value or 0, hi)
    return {"length": length, "value": value, "raw": block[:200]}


def corpus_scale(qid: int) -> dict:
    p = TESTCASES_DIR / str(qid) / "cases.json"
    if not p.exists():
        return {}
    cases = json.loads(p.read_text(encoding="utf-8"))
    max_len = 0
    max_abs = 0
    max_scalar = 0      # largest scalar argument (catches e.g. n=2047 vs n<=1000)
    over: set[int] = set()
    case_vals: list[list[int]] = []
    case_scalars: list[list[int]] = []
    for ci, c in enumerate(cases):
        args = c.get("args") or {}
        vals = list(args.values()) if isinstance(args, dict) else [
            x for sub in args if isinstance(sub, list) for x in sub]
        local_vals: list[int] = []
        local_scalars: list[int] = []
        for v in vals:
            if isinstance(v, list):
                max_len = max(max_len, len(v))
                for x in v:
                    if isinstance(x, int) and not isinstance(x, bool):
                        local_vals.append(x)
                    elif isinstance(x, list):
                        local_vals += [y for y in x
                                       if isinstance(y, int) and not isinstance(y, bool)]
            elif isinstance(v, int) and not isinstance(v, bool):
                local_vals.append(v)
                local_scalars.append(v)
        for x in local_vals:
            max_abs = max(max_abs, abs(x))
        for x in local_scalars:
            max_scalar = max(max_scalar, abs(x))
        case_vals.append(local_vals)
        case_scalars.append(local_scalars)
    return {"cases": len(cases), "max_len": max_len, "max_abs": max_abs,
            "max_scalar": max_scalar, "_case_vals": case_vals,
            "_case_scalars": case_scalars}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--min_ratio", type=float, default=10.0)
    args = ap.parse_args()

    qids = ([int(x) for x in args.qids.split(",") if x.strip()]
            if args.qids else load_ft_test_qids())

    rows = []
    for qid in qids:
        cs = corpus_scale(qid)
        if not cs:
            continue
        db = declared_bounds(qid)
        dl, dv = db.get("length"), db.get("value")
        # guard: scalar-only problems (e.g. q2595 sumZero-style signatures)
        # have max_len == 0 and must not be skipped or divided by zero
        r_len = (dl / cs["max_len"]) if (dl and cs["max_len"]) else None
        # cases holding a value or scalar beyond the declared bound
        upper = max(dl or 0, dv or 0)
        n_over = n_over_scalar = 0
        if upper:
            for vals in cs.get("_case_vals", []):
                if any(abs(x) > upper for x in vals):
                    n_over += 1
            for sc in cs.get("_case_scalars", []):
                if any(abs(x) > upper for x in sc):
                    n_over_scalar += 1
        rows.append({"qid": qid, "cases": cs["cases"], "max_len": cs["max_len"],
                     "max_abs": cs["max_abs"], "max_scalar": cs["max_scalar"],
                     "declared_len": dl, "declared_val": dv, "ratio_len": r_len,
                     "cases_over_value_range": n_over,
                     "cases_over_bound_scalar": n_over_scalar})

    flagged = [r for r in rows if r["ratio_len"] and r["ratio_len"] >= args.min_ratio]
    flagged.sort(key=lambda r: -r["ratio_len"])

    print(f"含列表参数的题 = {len(rows)}")
    print(f"语料最大长度比题面约束小 >= {args.min_ratio:.0f} 倍的题 = {len(flagged)}\n")
    print(f"{'qid':>6} {'语料最大长度':>12} {'题面约束':>10} {'差距':>9} "
          f"{'语料最大绝对值':>14} {'题面值域':>10}")
    for r in flagged:
        print(f"{r['qid']:>6} {r['max_len']:>12} {r['declared_len']:>10} "
              f"{r['ratio_len']:>8.0f}x {r['max_abs']:>14} "
              f"{r['declared_val'] if r['declared_val'] else '-':>10}")

    print("\n补用例方向：这些题应新增**大规模**用例（按约束上界生成 n 与值域的组合，"
          "使其能触发整数溢出、超时等真实失效），而不是增加同规模用例数量。")

    over = sorted([r for r in rows
                   if r["cases_over_value_range"] or r["cases_over_bound_scalar"]],
                  key=lambda r: -(r["cases_over_value_range"]
                                  + r["cases_over_bound_scalar"]))
    print(f"\n=== 越界用例（值在 int32 内，但超出题面声明的界）===")
    if not over:
        print("  无")
    else:
        print(f"{'qid':>6} {'列表越界':>9} {'标量越界':>9} "
              f"{'语料最大|值|':>14} {'最大标量':>10} {'题面界':>10}")
        for r in over:
            print(f"{r['qid']:>6} {r['cases_over_value_range']:>9} "
                  f"{r['cases_over_bound_scalar']:>9} {r['max_abs']:>14} "
                  f"{r['max_scalar']:>10} "
                  f"{max(r['declared_len'] or 0, r['declared_val'] or 0):>10}")
        print("\n  标量越界尤其危险：它会让**在约束内正确的解法**被判错"
              "（实测 q2595 语料含 n=2047，而约束是 n<=1000，"
              "模型只循环 10 位的解法因此被误判 WA，而 LeetCode 判 AC）。")
        print("  列表越界多为无害（如 q1295 只数位数），但会掩盖/触发窄整型溢出。")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
