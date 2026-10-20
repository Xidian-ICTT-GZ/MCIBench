# -*- coding: utf-8 -*-
r"""通用对拍 fuzzer：按「签名 + 题面约束」随机造输入，找出模型与参考解的分歧。

为什么需要它
------------
`find_divergence.py` 需要**每题手写一个 fuzz 生成器**。实测 54 道待补题里
有 52 道（291/313 个槽位）的参数类型都是常见类型，题面也给了约束范围——
这类完全可以**自动生成**，不必手写。本模块就是把这个过程自动化。

三种模式（对应三类失效）
------------------------
  small     小规模、小值域     -> 找**逻辑**分歧（并列、边界判断）
  boundary  极值/边界值        -> 找**溢出**与边界处理（0、1、max、max±1）
  large     最大规模           -> 找**超时/规模**问题

用法
----
    python -m local.gen_testcases.auto_fuzz --qids 2270,2575 --n 500
    python -m local.gen_testcases.auto_fuzz --from-audit --top 10 --n 300
    python -m local.gen_testcases.auto_fuzz --qids 2270 --mode boundary --n 200
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.audit.scale_gap import (_desc_text, _expand_flattened,  # noqa: E402
                                   _normalize_bounds, constraints_block)
from local.common import KEY_TO_LABEL, load_snippet  # noqa: E402
from local.gen_testcases.differential import python_outputs  # noqa: E402
from local.harness.render import extract_plain_entry, render_plain_driver  # noqa: E402
from local.harness.typespec import (DesignSig, Int, ListT, Str,  # noqa: E402
                                    parse_python_snippet)
from local.gen_testcases.shrink import shrink_case  # noqa: E402
from local.judge import judge_one  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LOCAL_DB = REPO / "local" / "dashboard" / "packages" / "server" / "data" / "local.db"
ALL_MODELS = REPO / "local" / "results" / "all_models"

# ---------------------------------------------------------------- 约束解析

_NUM = r"-?\d+"
# `1 <= nums.length <= 100000`
_RE_LEN = re.compile(rf"({_NUM})\s*<=\s*(\w+)\.length\s*<=\s*({_NUM})")
_RE_LEN1 = re.compile(rf"(\w+)\.length\s*<=\s*({_NUM})")
# 元素界，含嵌套下标：`-104 <= arrays[i][j] <= 104`
_RE_ELEM = re.compile(rf"({_NUM})\s*<=\s*(\w+)\[[^\]]*\](?:\[[^\]]*\])?\s*<=\s*({_NUM})")
_RE_SCALAR = re.compile(rf"({_NUM})\s*<=\s*(\w+)\s*<=\s*({_NUM})")
_RE_ALIAS = re.compile(rf"(\w+)\.length\s*==\s*(\w+)")
# 反序：m == arrays.length
_RE_ALIAS_REV = re.compile(rf"(\w+)\s*==\s*(\w+)\.length")
# 嵌套行长度：`ranges[i].length == 2`。漏了它，shrink 会砍出 [[0,6,0]]
# 这种 3 元素行，而题面要求每行恰好 2 个。
_RE_ROWLEN = re.compile(rf"(\w+)\[i\]\.length\s*(==|<=|>=|<|>)\s*({_NUM})")
# 标量上界引用另一参数的长度：`1 <= k <= nums.length`
_RE_SCALAR_LEN = re.compile(rf"({_NUM})\s*<=\s*(\w+)\s*<=\s*(\w+)\.length")
# 链式长度相等：`n == nums1.length == nums2.length`
_RE_CHAIN = re.compile(r"(\w+)(?:\.length)?\s*==\s*(\w+)\.length\s*==\s*(\w+)\.length")


def _lenof(v) -> int:
    """题面里的 `.length` 对整数是指它的**字符串长度**。

    q2269 的 `1 <= k <= num.length (taking num as a string)` 里 num 是 Int，
    直接 len(num) 会抛 TypeError。实测这一条让该题 200/200 次生成全部失败。
    """
    if isinstance(v, (list, str)):
        return len(v)
    if isinstance(v, int):
        return len(str(abs(v)))
    return 0


def _exp(n: int) -> int:
    """展开被压平的上标，并**保留负号**。

    直接对负数调 `_expand_flattened` 是无效的（它以 "10" 开头判断），
    所以取绝对值展开后再补回符号——`-105` 才会变成 `-100000`。
    """
    return -_expand_flattened(-n) if n < 0 else _expand_flattened(n)

CHARSETS = [
    (re.compile(r"lowercase English letters", re.I), "abcdefghijklmnopqrstuvwxyz"),
    (re.compile(r"uppercase English letters", re.I), "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (re.compile(r"English letters", re.I), "abcdefghijklmnopqrstuvwxyz"),
    (re.compile(r"digits", re.I), "0123456789"),
    (re.compile(r"lowercase|英文字母", re.I), "abcdefghijklmnopqrstuvwxyz"),
]

BIG = 10 ** 9          # 未给界时的默认值域上限
BIG_LEN = 1000         # 未给界时的默认长度上限


def parse_rules(qid: int) -> dict:
    """把题面 Constraints 解析成 per-参数 的规则。

    数字一律过 `_expand_flattened`：题面 dump 丢了 `<sup>` 标记，
    `10^5` 会到达成 `105`、`10^9` 成 `109`、`10^15` 成 `1015`。
    不过这一关，`large` 模式就会把"最大规模"当成 105 条。
    """
    text = _desc_text(qid)
    # 必须先归一化：题面 dump 丢了上标，`5 * 10^4` 到达成 `5 * 104`，
    # 不处理会被正则截断成 `5`——q1014 的长度上限、q2398 的 n 上限都因此错了。
    block = _normalize_bounds(constraints_block(text))
    rules: dict[str, dict] = {"_charset": None, "_sorted": False, "_perm": False}

    for m in _RE_LEN.finditer(block):
        a, name, b = _exp(int(m.group(1))), m.group(2), \
            _exp(int(m.group(3)))
        rules.setdefault(name, {})["min_len"] = a
        rules[name]["max_len"] = b
    for m in _RE_LEN1.finditer(block):
        name, b = m.group(1), _exp(int(m.group(2)))
        r = rules.setdefault(name, {})
        r.setdefault("min_len", 1)
        r.setdefault("max_len", b)
    for m in _RE_ELEM.finditer(block):
        a, name, b = _exp(int(m.group(1))), m.group(2), \
            _exp(int(m.group(3)))
        rules.setdefault(name, {})["min_v"] = a
        rules[name]["max_v"] = b
    for m in _RE_SCALAR.finditer(block):
        a, name, b = _exp(int(m.group(1))), m.group(2), \
            _exp(int(m.group(3)))
        if name.endswith(".length") or name == "i":
            continue
        r = rules.setdefault(name, {})
        r.setdefault("min_v", a)
        r.setdefault("max_v", b)
    # 人工核验过的约束（见 constraints.VERIFIED）：机器解析不了的语义写在那里，
    # 生成与校验必须共用，否则检查器收紧了而生成器照旧造非法输入。
    from local.gen_testcases.constraints import VERIFIED
    for k, v in VERIFIED.get(qid, {}).items():
        if k.startswith('_'):
            rules[k] = v
        else:
            rules.setdefault(k, {}).update(v)
    for m in _RE_ALIAS.finditer(block):
        rules.setdefault(m.group(2), {})["len_from"] = m.group(1)
    # 反序写法：`m == arrays.length`。约束里两种顺序都出现，只认一种会漏掉
    # q624 这种——实测漏掉后 m=1 的非法输入混进了语料，坏了 3 个槽位。
    for m in _RE_ALIAS_REV.finditer(block):
        scalar, lst = m.group(1), m.group(2)
        r = rules.setdefault(lst, {})
        r.setdefault("len_from", scalar)
        sc = rules.get(scalar, {})
        if "min_v" in sc:
            r.setdefault("min_len", sc["min_v"])
        if "max_v" in sc:
            r.setdefault("max_len", sc["max_v"])
    for m in _RE_ROWLEN.finditer(block):
        rules.setdefault(m.group(1), {})["row_op"] = m.group(2)
        rules[m.group(1)]["row_len"] = _exp(int(m.group(3)))
    # 标量上界是另一参数的长度：记下来，校验时按实际长度比。
    for m in _RE_SCALAR_LEN.finditer(block):
        r = rules.setdefault(m.group(2), {})
        r["min_v"] = _exp(int(m.group(1)))
        r["max_from_len"] = m.group(3)
    # 链式相等：n == a.length == b.length -> a、b 的长度都等于 n（也就是彼此相等）
    for m in _RE_CHAIN.finditer(block):
        a, b, c = m.group(1), m.group(2), m.group(3)
        names = [x for x in (a, b, c) if x in _param_names(qid)]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                rules.setdefault(names[j], {})["len_eq"] = names[i]

    for pat, cs in CHARSETS:
        if pat.search(text):
            rules["_charset"] = cs
            break
    if re.search(r"sorted in ascending order", text, re.I):
        rules["_sorted"] = True
    if re.search(r"permutation of", text, re.I):
        rules["_perm"] = True

    # ---- B-005：与检查器**合并**规则，消除"生成器与检查器不一致"----
    #
    # 本函数是**另一套解析器**（自带正则 + 自己的 CHARSETS），与
    # `constraints.parse` 长期不一致（审查代理 B 实测 19 道题的参数规则不同）：
    #   - q120/q624/q1277：元素界 `a <= X[i][j] <= b` 生成器认得、检查器不认
    #   - q2145/q1963/q1278/q2070/q2255：长度规则生成器有、检查器没有
    # 方向很关键：**生成器宽、检查器严**时，差集里的非法输入会被造出来再被 check
    # 挡掉（浪费对拍预算）；反过来**检查器宽**时就直接漏检。
    #
    # 与其重写成一套（风险大），这里把检查器的规则**并进来**，让生成器
    # 「至少和检查器一样严」：同名参数下，取两者的**并集**；
    # 数值区间取**交集**（更严的一侧生效），这样不会因为合并而放松生成范围。
    try:
        from local.gen_testcases.constraints import parse as _c_parse
        cr = _c_parse(qid)
        for k, v in cr.items():
            if k.startswith("_"):
                # 结构开关取并集
                if isinstance(v, bool) and v:
                    rules[k] = True
                elif k == "_charset" and v:
                    prev = rules.get("_charset") or ""
                    rules["_charset"] = "".join(dict.fromkeys(prev + v))
                elif k == "_unparsed":
                    rules.setdefault(k, [])
                    for line in v:
                        if line not in rules[k]:
                            rules[k].append(line)
                continue
            if not isinstance(v, dict):
                continue
            dst = rules.setdefault(k, {})
            for kk, vv in v.items():
                if kk in ("min_len", "min_v") and kk in dst:
                    dst[kk] = max(dst[kk], vv)      # 下界取更严
                elif kk in ("max_len", "max_v") and kk in dst:
                    dst[kk] = min(dst[kk], vv)      # 上界取更严
                else:
                    dst.setdefault(kk, vv)
    except Exception:  # noqa: BLE001
        # 合并失败不能让生成停摆；但要留下痕迹
        rules.setdefault("_unparsed", []).append("(constraints.parse 合并失败)")
    return rules


# ---------------------------------------------------------------- 生成

def _rng_int(r: random.Random, rl: dict, mode: str) -> int:
    lo = rl.get("min_v", 0)
    hi = rl.get("max_v", BIG)
    if mode == "small":
        hi = min(hi, 12)
        lo = max(lo, -12) if lo < 0 else lo
    elif mode == "boundary":
        # 在极值附近取：lo / hi / lo±1 / hi±1 / 0 / 1
        pool = [lo, hi, lo + 1, hi - 1 if hi > lo + 1 else hi, 0, 1, -1,
                lo * 2 if lo < 0 else lo, hi // 2]
        return r.choice([p for p in pool if lo <= p <= hi] or [lo])
    if hi < lo:
        hi = lo
    return r.randint(lo, hi)


def _rng_len(r: random.Random, rl: dict, mode: str) -> int:
    lo = rl.get("min_len", 1)
    hi = rl.get("max_len", BIG_LEN)
    if mode == "small":
        hi = min(hi, 12)
    elif mode == "boundary":
        return r.choice([lo, max(lo, 1), min(hi, lo + 1), hi])
    if hi < lo:
        hi = lo
    # 大模式偏爱接近上界
    if mode == "large":
        return r.randint(max(lo, hi * 9 // 10), hi)
    return r.randint(lo, min(hi, max(lo, 40)))


def gen_args(qid: int, sig, rules: dict, r: random.Random, mode: str) -> dict:
    out: dict = {}
    for p in sig.params:
        rl = rules.get(p.name, {})
        # 长度跟随另一个参数
        if "min_len" not in rl and "max_len" not in rl and rl.get("len_from"):
            src = out.get(rl["len_from"])
            if isinstance(src, list) or isinstance(src, str):
                rl = dict(rl, min_len=len(src), max_len=len(src))
        n = _rng_len(r, rl, mode)
        if isinstance(p.typ, Int):
            if p.name in rules:
                val = _rng_int(r, rl, mode)
                # 上界写成另一参数的长度时必须夹住，否则会生成 k > nums.length
                # 这类违反题面约束的输入（q1673 实测就是这么错的）。
                from_len = rl.get("max_from_len")
                if from_len and from_len in out:
                    val = max(1, min(val, _lenof(out[from_len])))
                # 上界是另一参数长度的一半：`0 <= p <= nums.length/2`（q2616）。
                # 这条规则加进检查器后生成器也必须遵守，否则生成与校验不一致。
                half_of = rl.get("max_half_of")
                if half_of and half_of in out:
                    val = max(0, min(val, _lenof(out[half_of]) // 2))
                out[p.name] = val
            else:
                out[p.name] = n if mode != "small" else min(n, 12)
        elif isinstance(p.typ, Str):
            cs = rules.get("_charset") or "abcdefghijklmnopqrstuvwxyz"
            if mode == "boundary" and len(cs) > 2:
                # 全同字符、单字符、两字符交替，都是边界
                pick = r.choice([cs[0] * n, cs[0] + cs[1] * (n - 1),
                                 (cs[0] + cs[1]) * (n // 2 + 1)])
                out[p.name] = pick[:n] if n else cs[0]
            else:
                out[p.name] = "".join(r.choice(cs) for _ in range(max(n, 1)))
        elif isinstance(p.typ, ListT):
            inner = p.typ.inner
            if isinstance(inner, ListT):
                # List[List[int]]
                rows = []
                inner_rl = rl
                # 题面若规定行长度（`items[i].length == 2`），每行都必须正好那么长；
                # 否则会生成大量非法输入——实测 q2070/q2580/q2140 有 195-198/200 非法。
                fixed_row = (rl.get("row_len")
                             if rl.get("row_op") == "==" else None)
                for _ in range(max(n, 1)):
                    if fixed_row is not None:
                        k = fixed_row
                    else:
                        k = (r.randint(1, max(1, min(inner_rl.get("max_v", 8), 8)))
                             if mode != "large" else 8)
                    if rules.get("_sorted"):
                        row = sorted(_rng_int(r, inner_rl, mode) for _ in range(k))
                    else:
                        row = [_rng_int(r, inner_rl, mode) for _ in range(k)]
                    # 人工核验的行**元素**约束（如 q2140 的
                    # `1 <= pointsi, brainpoweri <= 105`——它们指 questions[i]
                    # 的第 0、1 个元素，不是顶层参数，机器解析不出这层对应关系）。
                    # 生成器必须与检查器用同一套规则，否则又会造出非法输入。
                    specs = (rules.get("_rows") or {}).get(p.name)
                    if specs:
                        for idx, spec in enumerate(specs):
                            if idx >= len(row):
                                break
                            lo = spec.get("min", row[idx])
                            hi = spec.get("max", row[idx])
                            if mode == "small":
                                hi = min(hi, max(lo, 4))
                            row[idx] = max(lo, min(row[idx], hi))
                    rows.append(row)
                out[p.name] = rows
            elif isinstance(inner, Str):
                out[p.name] = ["".join(r.choice("ab") for _ in range(r.randint(1, 5)))
                               for _ in range(max(n, 1))]
            else:
                if rules.get("_perm"):
                    vals = list(range(max(n, 2)))
                    r.shuffle(vals)
                    out[p.name] = vals
                elif rules.get("_sorted"):
                    out[p.name] = sorted(_rng_int(r, rl, mode)
                                         for _ in range(max(n, 1)))
                else:
                    out[p.name] = [_rng_int(r, rl, mode) for _ in range(max(n, 1))]
        else:
            out[p.name] = n
    return out


def violates_constraints(qid: int, case: dict, rules: dict | None = None) -> str | None:
    """检查用例是否违反题面约束；违反则返回原因字符串。

    **委托给 constraints.check** —— 全流程唯一的检查入口。
    这个函数原先是另一份独立实现，后果是检查器收紧了而生成器照旧造非法输入：
    实测 q2070/q2580/q2140 曾各有 195-198/200 条非法。两份实现还各自出过错
    （这里的 VERIFIED 表把 q2140 的 brainpower 上限写成 4，导致误删 24 条语料）。

    返回第一个违规原因（保持原签名），完整列表见 constraints.check。
    """
    from local.gen_testcases.constraints import check
    bad = check(qid, case, rules=rules)
    return bad[0] if bad else None


def _param_names(qid: int) -> set:
    return {p.name for p in _sig_params(qid)}


_SIG_CACHE: dict[int, list] = {}


def _sig_params(qid: int):
    if qid not in _SIG_CACHE:
        try:
            sig = parse_python_snippet(load_snippet(qid, "python3"))
            _SIG_CACHE[qid] = list(getattr(sig, "params", ()))
        except Exception:  # noqa: BLE001
            _SIG_CACHE[qid] = []
    return _SIG_CACHE[qid]


# ---------------------------------------------------------------- 主流程

def audit_false_ac(min_slots: int = 1) -> list[tuple[int, int]]:
    """从仪表盘库取「本地过 / LC 不过」且非 CE 驱动的题，按槽位数排序。"""
    if not LOCAL_DB.exists():
        return []
    c = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
    try:
        return [(q, n) for q, n in c.execute(
            "SELECT qid, COUNT(*) n FROM slots WHERE klass='false_ac' "
            "AND leetcode IN ('Wrong Answer','Runtime Error','Time Limit Exceeded') "
            "GROUP BY qid HAVING n >= ? ORDER BY n DESC", (min_slots,))]
    finally:
        c.close()


def models_for(qid: int) -> list[tuple[str, str]]:
    """该题上有 false_ac 的 (model, lang)。"""
    c = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
    try:
        return list(c.execute(
            "SELECT model, lang FROM slots WHERE qid=? AND klass='false_ac' "
            "AND leetcode IN ('Wrong Answer','Runtime Error','Time Limit Exceeded')",
            (qid,)))
    finally:
        c.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--from-audit", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--n", type=int, default=300, help="每题随机输入条数")
    ap.add_argument("--mode", default="small",
                    choices=["small", "boundary", "large"])
    ap.add_argument("--seed", type=int, default=20261006)
    ap.add_argument("--max_hits", type=int, default=3)
    ap.add_argument("--shrink", action="store_true",
                    help="把找到的用例收敛到最小后再报告（推荐）")
    ap.add_argument("--shrink_workers", type=int, default=4)
    ap.add_argument("--verbose", action="store_true",
                    help="打印跳过原因等细节")
    args = ap.parse_args()

    if args.from_audit:
        todo = audit_false_ac()[:args.top]
    elif args.qids:
        todo = [(int(x), 0) for x in args.qids.split(",") if x.strip()]
    else:
        sys.exit("需要 --qids 或 --from-audit")
    print(f"待查 {len(todo)} 题，模式={args.mode}，每题 {args.n} 条随机输入\n")

    rng = random.Random(args.seed)
    total_hits = 0
    found_cases: dict[int, list] = {}
    summary = []
    for qid, nslot in todo:
        try:
            sig = parse_python_snippet(load_snippet(qid, "python3"))
        except Exception as e:  # noqa: BLE001
            print(f"q{qid}: 签名无法解析 {type(e).__name__}，跳过")
            continue
        if isinstance(sig, DesignSig):
            print(f"q{qid}: 设计题，本工具暂不支持")
            continue
        rules = parse_rules(qid)
        cases = [{"args": gen_args(qid, sig, rules, rng, args.mode)}
                 for _ in range(args.n)]
        outs = python_outputs(qid, cases, "docker")
        good = [(c, o) for c, o in zip(cases, outs) if o is not None]
        if not good:
            print(f"q{qid}: 参考解全部失败，跳过")
            continue
        cases = [dict(c, expected=o) for c, o in good]

        hits = []
        seen = set()
        # 现有语料——归因的基准。必须**显式传给 judge_one**：
        # 早先这里漏传了 cases_override，judge_one 读的是磁盘上的旧语料，
        # 而脚本又拿旧语料上的失败位置去索引随机用例，报出的"分歧"基本是随机的。
        # 这一条是本次最严重的流程错误。
        corpus = []
        cp = REPO / "local" / "testcases" / str(qid) / "cases.json"
        if cp.exists():
            corpus = json.loads(cp.read_text(encoding="utf-8"))
        all_cases = corpus + cases
        for model, lang in models_for(qid):
            if (model, lang) in seen:
                continue
            seen.add((model, lang))
            cf = ALL_MODELS / model / "codes" / f"{qid}_{KEY_TO_LABEL[lang]}_1.txt"
            if not cf.exists():
                continue
            try:
                # 第一步：模型在**现有语料**上必须通过，否则失败无法归因到新用例
                base = judge_one(cf, "gen", 1000, "docker", 20,
                                 cases_override=corpus)
                if base["ac_status"] != "Accepted":
                    continue
                # 第二步：现有语料 + 随机用例
                r = judge_one(cf, "gen", 1000, "docker", 20,
                              cases_override=all_cases)
            except Exception:  # noqa: BLE001
                continue
            if r["ac_status"] == "Accepted":
                continue
            k = r.get("total_correct")
            # 只有落在**随机用例区间**内的失败才能归因给新用例
            if not isinstance(k, int) or k < len(corpus):
                if args.verbose:
                    print(f"    {model}/{lang}: 失败落在旧语料区间（k={k}），"
                          f"存在跨用例影响，跳过")
                continue
            if k - len(corpus) < len(cases):
                c = cases[k - len(corpus)]
                hits.append({"model": model, "lang": lang, "idx": k,
                             "args": c["args"], "expected": c["expected"],
                             "status": r["ac_status"]})
            if len(hits) >= args.max_hits:
                break

        tag = f"{nslot} 个槽位" if nslot else ""
        if hits:
            total_hits += len(hits)
            print(f"q{qid} {tag}: **找到 {len(hits)} 个分歧**")
            # 收缩：判据是「追加进现有语料后模型是否仍失败」，见 shrink.py 的说明。
            # 收缩同时会**验证**该候选在语料上下文里确实成立，不成立的会被丢掉。
            if args.shrink:
                corpus = []
                cp = REPO / "local" / "testcases" / str(qid) / "cases.json"
                if cp.exists():
                    corpus = json.loads(cp.read_text(encoding="utf-8"))
                keep = []
                for h in hits:
                    cf = (ALL_MODELS / h["model"] / "codes" /
                          f"{qid}_{KEY_TO_LABEL[h['lang']]}_1.txt")
                    if not cf.exists():
                        continue
                    s = shrink_case(qid, {"args": h["args"]}, cf, h["lang"],
                                    corpus, workers=args.shrink_workers,
                                    valid=lambda c: violates_constraints(qid, c) is None)
                    if s is None:
                        print(f"    {h['model']}/{h['lang']}: 在语料上下文里不成立，丢弃")
                        continue
                    s["_model"], s["_lang"] = h["model"], h["lang"]
                    keep.append(s)
                hits = keep
                if not hits:
                    print(f"q{qid} {tag}: 收缩后没有有效用例")
                    continue
            for h in hits[:3]:
                print(f"    {h.get('_model', h.get('model'))}/"
                      f"{h.get('_lang', h.get('lang'))} -> {h.get('status', '')}")
                print(f"      args     = {json.dumps(h['args'], ensure_ascii=False)[:130]}")
                print(f"      期望     = {json.dumps(h.get('expected'), ensure_ascii=False)[:70]}")
            found_cases[qid] = hits
            summary.append((qid, nslot, len(hits)))
        else:
            print(f"q{qid} {tag}: 未发现分歧")

    print(f"\n=== 小结：{total_hits} 个分歧，涉及 {len(summary)} 题 ===")
    for qid, nslot, nh in summary:
        print(f"  q{qid:<6} 原 {nslot:>3} 个槽位 -> 找到 {nh} 个分歧用例")

    # 把（收缩后的）用例落盘，供后续入库
    out = REPO / "local" / "results" / "auto_fuzz_cases.json"
    if args.shrink and found_cases:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {str(q): [{"args": h["args"], "expected": h.get("expected"),
                       "model": h.get("_model"), "lang": h.get("_lang")}
                      for h in hs] for q, hs in found_cases.items()},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n收缩后的用例已写入 {out}")
        print("入库：python -m local.gen_testcases.apply_found --file <上面这个文件>")


if __name__ == "__main__":
    main()
