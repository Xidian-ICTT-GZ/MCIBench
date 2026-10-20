# -*- coding: utf-8 -*-
r"""把对拍找到的分歧用例**收敛到最小**，再补进语料。

为什么需要
----------
`auto_fuzz` 找到的用例是随机生成的，可能很大。直接追加会让语料迅速膨胀
——`local/` 要推 GitHub，q2270 的语料备份就已经 8 MB。

判据（第一版搞错过，记录在此）
------------------------------
**不能**「单独跑这个输入，看模型是否失败」。两条原因：
  1. 收缩输入后 `expected` 必须**重算**——否则拿 `nums=[6]` 去比期望 4，
     会凭空造出"分歧"，收缩会一路退化成 `[6]` 这种假用例。
  2. 语料是按**一个进程跑全部用例**的方式判的，模型若有全局/静态状态，
     单独跑与放进批次跑结果不同。实测 q2270 就存在这种跨用例影响。

所以判据是：**「把这个候选追加进现有语料后，模型是否仍然判不过」**——
这与语料的实际运行语义一致，且因为 false_ac 槽位本来是通过现有语料的，
一旦失败就必然是新增候选造成的。
"""
from __future__ import annotations

import copy
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.common import load_snippet  # noqa: E402
from local.gen_testcases.differential import python_outputs  # noqa: E402
from local.harness.render import (extract_plain_entry,  # noqa: E402
                                  render_plain_driver)
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier
from local.harness.runner import run_submission  # noqa: E402
from local.harness.typespec import parse_python_snippet  # noqa: E402


def _size(v) -> int:
    if isinstance(v, list):
        return len(v) + sum(_size(x) for x in v)
    if isinstance(v, str):
        return len(v)
    return 1


def case_size(case: dict) -> int:
    return sum(_size(v) for v in case["args"].values())


def _shrink_list(v: list) -> list[list]:
    out = []
    n = len(v)
    if n <= 1:
        return out
    out += [v[:1], v[-1:], v[::2], v[: n // 2], v[n // 2:]]
    for i in (0, n // 2, n - 1):
        out.append(v[:i] + v[i + 1:])
    if all(isinstance(x, int) for x in v):
        out.append([0] * n)
        out.append([1] * n)
        out.append([(0 if x == 0 else (1 if x > 0 else -1)) for x in v])
        lo, hi = min(v), max(v)
        out.append([lo if x == lo else hi for x in v])
    elif all(isinstance(x, list) for x in v):
        out.append(v[:1])
        out.append([row[:1] for row in v])
        out.append(v[: n // 2])
        if v[0] and all(isinstance(x, int) for x in v[0]):
            out.append([[0] * len(row) for row in v])
    return [x for x in out if x]


def _shrink_str(s: str) -> list[str]:
    n = len(s)
    if n <= 1:
        return []
    out = [s[:1], s[: n // 2], s[n // 2:], s[::2], s[0] * n]
    if len(set(s)) > 1:
        a, b = sorted(set(s))[:2]
        out.append((a + b) * (n // 2 + 1))
    return [x for x in out if x]


def _shrink_int(v: int) -> list[int]:
    cands = [0, 1, -1, 2, v // 2]
    cands += [v - 1, v + 1] if v > 0 else [v + 1, v - 1]
    for p in (2, 3, 10, 31, 32, 53, 63):
        cands += [2 ** p - 1, -(2 ** p - 1)]
    return [c for c in cands if c != v]


def variants(case: dict, limit: int = 14) -> list[dict]:
    """生成一批更简单的变体（每个只改一个参数），按规模从小到大。"""
    out: list[dict] = []
    for key, val in case["args"].items():
        gen = (_shrink_list(val) if isinstance(val, list) else
               _shrink_str(val) if isinstance(val, str) else
               _shrink_int(val) if isinstance(val, int) else [])
        for nv in gen:
            c = copy.deepcopy(case)
            c["args"][key] = nv
            c.pop("expected", None)      # 必须重算，见模块说明
            out.append(c)
    seen, uniq = set(), []
    for c in out:
        sig = repr(sorted(c["args"].items()))
        if sig not in seen:
            seen.add(sig)
            uniq.append(c)
    uniq.sort(key=case_size)
    return uniq[:limit]


def _fails_with(qid: int, corpus: list[dict], cand: dict, code_path: Path,
                lang: str) -> bool:
    """把 cand 追加进 corpus 后，模型是否判不过。"""
    try:
        sig = parse_python_snippet(load_snippet(qid, "python3"))
        entry = extract_plain_entry(lang, load_snippet(qid, lang))
        drv = render_output_driver(lang, sig, entry, corpus + [cand],
                                  code_path.read_text(encoding="utf-8",
                                                      errors="replace"))
        r = run_submission(lang, drv, limit=len(corpus) + 1, backend="docker",
                           run_timeout_s=20, output_verifier=OutputVerifier(qid, corpus + [cand], signature=sig))
        return r.status != "Accepted"
    except Exception:  # noqa: BLE001
        return False


def shrink_case(qid: int, case: dict, code_path: Path, lang: str,
                corpus: list[dict], rounds: int = 6, workers: int = 4,
                valid=None, verbose: bool = False) -> dict | None:
    """反复简化，直到没有更简单的变体仍然让模型判不过。

    `corpus` 是**现有语料**（不含 case）；判据见模块说明。
    `valid(case) -> bool` 用来挡掉违反题面约束的变体——收缩很容易砍过头
    （例如 `2 <= nums.length` 的题被砍到只剩 1 个元素），那种用例会让
    "假设 n≥2"的正确解被判错。用依赖注入而不是直接 import，
    避免与 auto_fuzz 形成循环依赖。
    返回收缩后的用例（含重算的 expected），若原用例本身不成立则返回 None。
    """
    def ok(c: dict) -> bool:
        return valid is None or valid(c)

    # 0) 确认原用例在语料上下文里确实让模型失败，且不违反约束
    if not ok(case):
        if verbose:
            print("      原用例违反题面约束，放弃")
        return None
    outs = python_outputs(qid, [case], "docker")
    if not outs or outs[0] is None:
        return None
    best = dict(case, expected=outs[0])
    if not _fails_with(qid, corpus, best, code_path, lang):
        if verbose:
            print("      原用例在语料上下文里并不导致失败，放弃")
        return None
    best_sz = case_size(best)

    for r in range(rounds):
        cands = [c for c in variants(best) if ok(c)]
        if not cands:
            break
        # 一次参考解运行算出所有变体的期望值（否则期望会对不上）
        exps = python_outputs(qid, cands, "docker")
        pairs = [dict(c, expected=e) for c, e in zip(cands, exps) if e is not None]
        if not pairs:
            break
        with ThreadPoolExecutor(max_workers=workers) as ex:
            flags = list(ex.map(
                lambda c: _fails_with(qid, corpus, c, code_path, lang), pairs))
        alive = [c for c, okk in zip(pairs, flags) if okk]
        if not alive:
            if verbose:
                print(f"      轮 {r+1}: {len(pairs)} 个变体都不再失败，停止")
            break
        alive.sort(key=case_size)
        pick = alive[0]
        if case_size(pick) >= best_sz:
            if verbose:
                print(f"      轮 {r+1}: 没有更小的，停止")
            break
        best, best_sz = pick, case_size(pick)
        if verbose:
            print(f"      轮 {r+1}: {len(alive)}/{len(pairs)} 仍失败，规模 {best_sz}")
    return best
