# -*- coding: utf-8 -*-
r"""定向搜索：随机小输入 + 模型 vs 参考解对拍，找出能让两者分歧的用例。

为什么需要它
------------
有一类 `false_ac` 既不是规模不足、也不是超时：模型代码在我们**所有**用例上
都与参考解一致，但 LeetCode 判它 WA——说明 LeetCode 用了一个我们没有的场景。
继续放大规模没用（规模只影响"能不能触发崩溃/超时"），需要的是**覆盖到那个场景**。

做法
----
用每题注册的 fuzz 生成器造大量**小规模随机输入**（小值域更容易产生并列/边界），
Python 参考解给出期望输出，然后把模型代码放到同一批输入上跑，报告首个分歧用例。
找到的输入就是应该补进语料的场景。

用法
----
    python -m local.gen_testcases.find_divergence --qid 1673 --n 2000
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.audit import pairing  # noqa: E402
from local.audit.report import CACHE, classify  # noqa: E402
from local.common import load_reference, load_snippet  # noqa: E402
from local.gen_testcases.differential import python_outputs  # noqa: E402
from local.harness.render import extract_plain_entry, render_plain_driver  # noqa: E402
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier
from local.harness.runner import run_submission  # noqa: E402
from local.harness.typespec import parse_python_snippet  # noqa: E402

# ---- 每题一个 fuzz 生成器：只产出 args，期望值由参考解推导 ----
# 刻意用小值域/小规模：目标是**触发逻辑分歧**，不是压性能。
# 但值域要够到该题的"敏感区"——例如 q2575 的 int32 溢出需要 m 接近 1e9，
# 用小 m 永远测不出来（这一点踩过：第一版 fuzzer 的 m≤1000，结果全是"一致"）。
FUZZERS: dict[int, callable] = {
    1673: lambda r: (lambda n: {"nums": [r.randint(0, 9) for _ in range(n)],
                                "k": r.randint(1, n)})(r.randint(1, 12)),
    2588: lambda r: {"nums": [r.randint(0, 7)
                              for _ in range(r.randint(1, 40))]},
    1717: lambda r: {"s": "".join(r.choice("abc")
                                 for _ in range(r.randint(1, 30))),
                     "x": r.randint(1, 10), "y": r.randint(1, 10)},
    2575: lambda r: {"word": ("".join(r.choice("0123456789")
                                     for _ in range(r.randint(0, 12)))
                              + "0" * r.randint(0, 4)),
                     "m": r.choice([2, 3, 7, 10 ** 6, 10 ** 8, 10 ** 9,
                                    999999937, 999999999])},
    2179: lambda r: (lambda n: (lambda p: {
        "nums1": list(range(n)), "nums2": p})(r.sample(range(n), n)))(
            r.randint(3, 10)),
    2009: lambda r: {"nums": [r.randint(1, 30)
                              for _ in range(r.randint(1, 12))]},
    1014: lambda r: {"values": [r.randint(1, 20)
                                for _ in range(r.randint(2, 20))]},
    1957: lambda r: {"s": "".join(r.choice("ab")
                                  for _ in range(r.randint(1, 20)))},
}


def model_slots(qid: int) -> list:
    latest: dict[str, dict] = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            latest[r["key"]] = r
    index: dict[str, tuple[str, pairing.Pair]] = {}
    for task in ("gen", "trans"):
        for rname in pairing.list_runs(task):
            for p in pairing.iter_pairs(rname, task):
                index[p.audit_key] = (task, p)
    out = []
    for r in latest.values():
        if (r.get("local") and r["qid"] == qid and r["key"] in index
                and classify(r["leetcode"], r["local"], qid) == "false_ac"):
            out.append((r, index[r["key"]]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", type=int, required=True)
    ap.add_argument("--n", type=int, default=2000, help="随机输入条数")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max_matches", type=int, default=5)
    args = ap.parse_args()

    qid = args.qid
    fz = FUZZERS.get(qid)
    if fz is None:
        sys.exit(f"q{qid}: 还没有 fuzz 生成器")
    rng = random.Random(args.seed)
    cases = [{"args": fz(rng)} for _ in range(args.n)]
    print(f"q{qid}: 生成 {len(cases)} 条随机小输入")

    outs = python_outputs(qid, cases, "docker")
    good = [(c, o) for c, o in zip(cases, outs) if o is not None]
    print(f"  参考解成功 {len(good)}/{len(cases)}")
    cases = [dict(c, expected=o) for c, o in good]

    sig = parse_python_snippet(load_snippet(qid, "python3"))
    slots = model_slots(qid)
    print(f"  待查的 false_ac 槽位 {len(slots)} 个")
    found = 0
    for r, (task, p) in slots:
        if found >= args.max_matches:
            break
        lang = r["lang"]
        code = p.code_path.read_text(encoding="utf-8", errors="replace")
        try:
            entry = extract_plain_entry(lang, load_snippet(qid, lang))
            drv = render_output_driver(lang, sig, entry, cases, code)
            res = run_submission(lang, drv, limit=len(cases), backend="docker",
                                 run_timeout_s=20, output_verifier=OutputVerifier(qid, cases, signature=sig))
        except Exception as e:  # noqa: BLE001
            print(f"  {lang}: 渲染/运行失败 {type(e).__name__}")
            continue
        if res.status == "Accepted":
            print(f"  {lang}: 全部一致（未发现分歧）")
            continue
        k = res.failed_case
        found += 1
        if k is not None and k < len(cases):
            c = cases[k]
            print(f"  {lang}: **发现分歧** 用例 #{k}")
            print(f"      args     = {json.dumps(c['args'], ensure_ascii=False)[:110]}")
            print(f"      参考期望 = {json.dumps(c['expected'], ensure_ascii=False)[:110]}")
        else:
            print(f"  {lang}: {res.status}（无 FAIL 标记，可能是崩溃/超时）")
    if not found:
        print("\n  结论：这批随机输入下模型与参考解一致——"
              "需要换值域/结构再试，或该差异来自 LeetCode 侧")


if __name__ == "__main__":
    main()
