# -*- coding: utf-8 -*-
"""Differential verification of test cases against the 8-language references.

Protocol (per problem):
  1. Python probe driver runs all candidate cases and prints per-case outputs
     (Python is the pivot language, as in BootTrans).
  2. Cases where the Python reference crashes or its output disagrees with the
     dataset's expected value are dropped.
  3. For each other language L, a standard driver is built with expected =
     Python's outputs. On FAIL at case k, case k is marked "disagreeing for L",
     dropped from L's list and the driver re-run, until it passes.
  4. A case is accepted iff >=2 languages agree (Python + >=1 other).
  5. Accepted cases with >=8 count form the problem's final corpus.

Usage (from repo root):
    python -m local.gen_testcases.differential --max_cases 30 \
        --out local/results/differential.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local.common import (LANGS, SEED_DIR, load_json, load_reference,
                          load_snippet, load_ft_test_qids, save_json)
from local.gen_testcases.design_cases import DESIGN_QIDS, design_seed_cases
from local.harness.render import (build_entries, extract_plain_entry,
                                  render_design_driver, render_plain_driver,
                                  render_py_probe, render_py_probe_design)
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier, OutputCollector
from local.harness.runner import run_submission
from local.harness.typespec import (DesignSig, PlainSig, drop_unrepresentable,
                                    parse_python_snippet)

MIN_VOTES = 2
# A case must additionally be validated by at least one language with 32-bit
# int semantics. Python / JavaScript / Go can represent values the C-family
# languages cannot, so agreement among only those languages proves nothing
# about representability.
WIDTH_SAFE_LANGS = ("c", "cpp", "java", "csharp", "rust")


def py_eqv(a, b) -> bool:
    """Python-side equivalence (mirrors the per-language eqv helpers)."""
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return a == b
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        if a and isinstance(a[0], list) and b and isinstance(b[0], list):
            used = [False] * len(a)
            for e in b:
                found = False
                for j, g in enumerate(a):
                    if not used[j] and py_eqv(g, e):
                        used[j] = True
                        found = True
                        break
                if not found:
                    return False
            return True
        return all(py_eqv(x, y) for x, y in zip(a, b))
    return a == b


def candidate_cases(qid: int, max_cases: int) -> tuple[list[dict], int, list[dict]]:
    """Candidate cases; returns (cases, n_lcd, dropped).

    The first n_lcd kept cases come from LeetCodeDataset (trusted expected
    outputs); `dropped` lists the cases removed for int32-unrepresentable values.

    Dropping happens BEFORE any driver is rendered: a single out-of-range
    literal makes the whole driver fail to compile in C/C++/Java/C#/Rust, and
    verify_with_lang would then conclude "this language cannot vote" and exclude
    it from validating *every* case of the problem -- which is how invalid cases
    used to slip through with only Python+JavaScript voting for them.
    """
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    if qid in DESIGN_QIDS:
        cases = list(design_seed_cases(qid))
        llm = SEED_DIR / f"llm_{qid}.json"
        if llm.exists():
            cases += load_json(llm)
        kept, dropped = drop_unrepresentable(sig, cases[:max_cases],
                                            build_entries(qid))
        return kept, 0, dropped
    cases: list[dict] = []
    n_lcd = 0
    lcd = SEED_DIR / f"lcd_{qid}.json"
    if lcd.exists():
        cases += load_json(lcd)
        n_lcd = len(cases)
    else:
        ex = SEED_DIR / f"examples_{qid}.json"
        if ex.exists():
            cases += load_json(ex)
    llm = SEED_DIR / f"llm_{qid}.json"
    if llm.exists():
        cases += load_json(llm)
    kept, dropped = drop_unrepresentable(sig, cases[:max_cases],
                                            build_entries(qid))
    # LeetCodeDataset cases form a prefix of the *truncated* candidate list, so
    # clip to max_cases first, then subtract the dropped ones inside that prefix.
    n_lcd_clipped = min(n_lcd, max_cases)
    n_lcd_kept = n_lcd_clipped - sum(1 for d in dropped if d["index"] < n_lcd_clipped)
    return kept, n_lcd_kept, dropped


def coerce_expected(raw, ret) -> object:
    """Coerce a dataset-parsed expected value for string-returning problems:
    the dataset stores string outputs unquoted (parsed as int/bool) or uses
    null for the empty string."""
    from local.harness.typespec import Str as StrT
    if isinstance(ret, StrT):
        if raw is None:
            return ""
        if isinstance(raw, bool):
            return "true" if raw else "false"
        if isinstance(raw, (int, float)):
            return str(raw)
    return raw


# Rendering embeds each case's args as a SOURCE LITERAL, and the container
# compiles that source under a memory cap at roughly 120x the source size
# (measured: 782 KB -> 94 MB, 3126 KB -> 346 MB, 4660 KB -> MLE). That is the
# structural reason the corpus has always been tiny: large inputs could not be
# expressed at all. Chunking keeps each rendered driver under the budget, so a
# corpus CAN hold large-scale cases.
#
# 预算按**内存上限**标定，上限变了就要重新标定。原值 2 MB 是按 512 MB 标的
# （-> ~240 MB，约 47%）。上限提高到 1536 MB 后，2026-10 实测了全部 8 种语言的
# 峰值（最重的语料 q2179 4.80 MB / q2145 3.96 MB）：
#
#     语言       驱动 MB   峰值 MB   比值
#     c/cpp      5.61      4.6/6.8   ~1
#     golang     5.61      11.8      2
#     csharp     5.61      36.6      7
#     rust       4.80      52.8      11
#     javascript 5.61      79.8      14
#     java       4.80      116.0     24
#     python3    3.96      542.7     137   <- 决定上限的是它
#
# 所以 python3 约 137 MB/驱动MB。取 6 MB -> python3 峰值约 820 MB（上限的 53%），
# 与原来 47% 的安全比例相当。提到 6 MB 的直接好处：**当前没有任何语料需要分块**
# （最大 4.80 MB），从而避免分块带来的进程状态重置（见 judge.py）。
# 以后语料再长，应按上表重新实测，不要只按比例推算。
DRIVER_SIZE_BUDGET = 6_000_000   # bytes of embedded args per rendered driver
                                 # -> python3 峰值约 820 MB / 1536 MB 上限


def _case_bytes(c: dict) -> int:
    """Embedded size of one case: args AND expected.

    Expected values must be counted too. q47 (`permuteUnique`) has tiny args but
    expecteds of up to 8! permutations; measuring args alone let the rendered
    driver grow until gcc/g++ were OOM-killed ("Killed signal terminated program
    cc1") and the reference was blamed with a bogus Compile Error.
    """
    return (_case_size(c.get("args", c)) + _case_size(c.get("expected")) + 400)


def _case_size(v) -> int:
    try:
        return len(json.dumps(v, separators=(",", ":")))
    except (TypeError, ValueError):
        return 0


def chunk_indices(cases: list[dict],
                  budget: int = DRIVER_SIZE_BUDGET) -> list[list[int]]:
    """Group case indices so each rendered driver stays under `budget` bytes.

    A single oversized case still gets its own chunk rather than being dropped.
    """
    chunks: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for i, c in enumerate(cases):
        sz = _case_bytes(c)
        if cur and size + sz > budget:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += sz
    if cur:
        chunks.append(cur)
    return chunks


def python_outputs(qid: int, cases: list[dict], backend: str) -> list:
    """Run the Python reference on all cases; return per-case output or None."""
    user = load_reference(qid, "python3")
    outputs = [None] * len(cases)
    for idxs in chunk_indices(cases):
        sub = [cases[i] for i in idxs]
        sig = parse_python_snippet(load_snippet(qid, "python3"))
        entry = {} if qid in DESIGN_QIDS else extract_plain_entry('python3', load_snippet(qid, 'python3'))
        drv = render_output_driver('python3', sig, entry, sub, user)
        collector = OutputCollector(qid, sub, signature=sig)
        res = run_submission("python3", drv, limit=len(sub), backend=backend,
                             run_timeout_s=30, output_verifier=collector)
        if res.status == 'Collected':
            for i, value in zip(idxs, collector.outputs):
                outputs[i] = value
    return outputs


def _probe_crashes(qid: int, lang: str, cases: list[dict], expected: list,
                   backend: str) -> list[int]:
    """Return the indices (into `cases`) on which this reference crashes.

    A compiling reference that crashes has either been handed invalid input or
    is itself broken; either way the case must not enter the corpus. Used when a
    multi-case run dies without a FAIL marker, so the crash cannot be attributed
    from the log alone.
    """
    crashed: list[int] = []
    for i in range(len(cases)):
        sub = [dict(cases[i], expected=expected[i])]
        user = load_reference(qid, lang)
        try:
            if qid in DESIGN_QIDS:
                sig = parse_python_snippet(load_snippet(qid, "python3"))
                drv = render_output_driver(lang, sig, {}, sub, user)
            else:
                sig = parse_python_snippet(load_snippet(qid, "python3"))
                entry = extract_plain_entry(lang, load_snippet(qid, lang))
                drv = render_output_driver(lang, sig, entry, sub, user)
            res = run_submission(lang, drv, limit=1, backend=backend,
                                 run_timeout_s=30, output_verifier=OutputVerifier(qid, sub, signature=sig))
        except Exception:  # noqa: BLE001
            continue
        if res.status in ("Runtime Error", "Time Limit Exceeded",
                          "Memory Limit Exceeded"):
            crashed.append(i)
    return crashed


def verify_with_lang(qid: int, lang: str, cases: list[dict], expected: list,
                     backend: str, verbose: bool) -> tuple[list[int], str, list[int]]:
    """Chunked wrapper around `_verify_chunk`.

    Cases are split so no rendered driver exceeds the memory budget; results are
    mapped back to absolute indices. A language counts as voting only if at
    least one chunk voted, and `reason` is reported only when no chunk could --
    preserving the original "casts no vote at all" contract.
    """
    agreed_all: list[int] = []
    crashed_all: list[int] = []
    reasons: list[str] = []
    for idxs in chunk_indices(cases):
        sub_cases = [cases[i] for i in idxs]
        sub_exp = [expected[i] for i in idxs]
        agreed_rel, reason, crashed_rel = _verify_chunk(
            qid, lang, sub_cases, sub_exp, backend, verbose)
        agreed_all += [idxs[i] for i in agreed_rel]
        crashed_all += [idxs[i] for i in crashed_rel]
        if reason:
            reasons.append(reason)
    if not agreed_all and reasons:
        return [], "; ".join(reasons), crashed_all
    return agreed_all, "", crashed_all


def _verify_chunk(qid: int, lang: str, cases: list[dict], expected: list,
                  backend: str, verbose: bool) -> tuple[list[int], str, list[int]]:
    """Return (indices the language agrees with, reason if it cannot vote,
    absolute indices of cases that crash its reference).

    An empty index list means the language casts no vote at all; `reason` then
    explains why, so NO_VOTE outcomes are diagnosable instead of silent.
    """
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    remaining = list(range(len(cases)))
    bad: list[int] = []
    crashed_abs: list[int] = []
    guard = 0
    while remaining and guard < len(cases) + 2:
        guard += 1
        sub = [dict(cases[i], expected=expected[i]) for i in remaining]
        user = load_reference(qid, lang)
        try:
            if qid in DESIGN_QIDS:
                assert isinstance(sig, DesignSig)
                sig = parse_python_snippet(load_snippet(qid, "python3"))
                drv = render_output_driver(lang, sig, {}, sub, user)
            else:
                assert isinstance(sig, PlainSig)
                entry = extract_plain_entry(lang, load_snippet(qid, lang))
                drv = render_output_driver(lang, sig, entry, sub, user)
            res = run_submission(lang, drv, limit=len(sub), backend=backend,
                                 run_timeout_s=30, output_verifier=OutputVerifier(qid, sub, signature=sig))
        except Exception as e:  # noqa: BLE001
            reason = f"render/exec error: {type(e).__name__}: {e}"
            if verbose:
                print(f"    qid {qid} {lang}: {reason}")
            return [], reason, crashed_abs
        if res.status == "Accepted":
            break
        if res.status == "Compile Error":
            # The reference itself does not compile (e.g. q47 C++ is a code
            # fragment). Unrepresentable *values* no longer land here: they are
            # removed up front by drop_unrepresentable.
            reason = f"reference compile error: {res.log[:200]}"
            if verbose:
                print(f"    qid {qid} {lang}: {reason}")
            return [], reason, crashed_abs
        if res.failed_case is None or res.failed_case >= len(sub):
            # Died with no FAIL marker. Attribute the crash case by case rather
            # than discarding every case's vote, then drop the offenders.
            rel_crash = _probe_crashes(
                qid, lang, [cases[i] for i in remaining],
                [expected[i] for i in remaining], backend)
            if not rel_crash:
                reason = f"unattributable {res.status}: {res.log[:200]}"
                if verbose:
                    print(f"    qid {qid} {lang}: {reason}")
                return [], reason, crashed_abs
            for rel in rel_crash:
                crashed_abs.append(remaining[rel])
                bad.append(remaining[rel])
            for rel in sorted(rel_crash, reverse=True):
                remaining.pop(rel)
            if verbose:
                print(f"    qid {qid} {lang}: cases {crashed_abs} crash the reference")
            continue
        k = remaining[res.failed_case]
        bad.append(k)
        remaining.remove(k)
        if verbose:
            print(f"    qid {qid} {lang}: case {k} disagrees, retry without it")
    return [i for i in range(len(cases)) if i not in bad], "", crashed_abs


def differential_problem(qid: int, max_cases: int, backend: str,
                         verbose: bool) -> dict:
    cases, n_lcd, dropped_oom = candidate_cases(qid, max_cases)
    if not cases:
        return {"qid": qid, "ok": False, "reason": "no candidate cases",
                "dropped_unrepresentable": len(dropped_oom), "cases": []}
    py_out = python_outputs(qid, cases, backend)
    # dataset expected coercion: string-returning problems have unquoted/null
    # outputs in LeetCodeDataset (see coerce_expected).
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    ret_t = sig.ret if isinstance(sig, PlainSig) else None
    # drop cases where python crashed or disagrees with the dataset expected
    keep: list[int] = []
    dropped_py: list[int] = []
    for i, (case, out) in enumerate(zip(cases, py_out)):
        if out is None:
            dropped_py.append(i)
            continue
        if i < n_lcd and ret_t is not None \
                and not py_eqv(out, coerce_expected(case["expected"], ret_t)):
            dropped_py.append(i)
            continue
        keep.append(i)
    cases = [dict(cases[i], expected=py_out[i]) for i in keep]
    voters: list[list[str]] = [["python3"] for _ in cases]
    vote_langs = ["python3"]
    no_vote_reasons: dict[str, str] = {}
    crashed: set[int] = set()
    for lang in LANGS:
        if lang == "python3":
            continue
        agreed, reason, crashed_here = verify_with_lang(
            qid, lang, cases, [c["expected"] for c in cases], backend, verbose)
        crashed.update(crashed_here)
        if not agreed:
            if reason:
                no_vote_reasons[lang] = reason
            continue
        vote_langs.append(lang)
        for i in agreed:
            voters[i].append(lang)
    accepted = []
    rejected_width = 0
    rejected_crash = 0
    for i in range(len(cases)):
        if i in crashed:
            # A compiling reference crashed on this case. Either the input
            # breaks the problem's stated guarantees (e.g. q2390 s="*", where
            # every star is guaranteed a character on its left) or the reference
            # is broken; neither belongs in the corpus.
            rejected_crash += 1
            continue
        v = voters[i]
        if len(v) < MIN_VOTES:
            continue
        if not (set(v) & set(WIDTH_SAFE_LANGS)):
            # Only wide-int languages agreed: the case is not proven
            # representable in the C-family, so do not ship it.
            rejected_width += 1
            continue
        accepted.append(dict(cases[i], votes=v))
    rejected = len(cases) - len(accepted)
    return {
        "qid": qid,
        "ok": True,
        "from_lcd": n_lcd > 0,
        "candidates": len(cases) + len(dropped_py),
        "dropped_python": len(dropped_py),
        "dropped_unrepresentable": len(dropped_oom),
        "dropped_unrepresentable_detail": dropped_oom[:10],
        "rejected_low_votes": rejected,
        "rejected_no_width_safe_vote": rejected_width,
        "rejected_reference_crash": rejected_crash,
        "crashed_case_indices": sorted(crashed),
        "no_vote_reasons": no_vote_reasons,
        "accepted": len(accepted),
        "vote_langs": vote_langs,
        "cases": accepted,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--max_cases", type=int, default=30)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--max_workers", type=int, default=3)
    ap.add_argument("--out", default="local/results/differential.json")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    qids = ([int(x) for x in args.qids.split(",") if x.strip()]
            if args.qids else load_ft_test_qids())
    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        for r in ex.map(lambda q: differential_problem(q, args.max_cases,
                                                       args.backend, args.verbose),
                        qids):
            results.append(r)
            n_oom = r.get("dropped_unrepresentable", 0)
            print(f"qid {r['qid']}: accepted {r.get('accepted', 0)}/"
                  f"{r.get('candidates', 0)} votes={r.get('vote_langs', [])}"
                  + (f" dropped_unrepresentable={n_oom}" if n_oom else "")
                  + f"{'' if r.get('ok') else ' — ' + r.get('reason', '')}",
                  flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_json(out, results, indent=1)
    low = [r for r in results if r.get("ok") and r["accepted"] < 8]
    print(f"\nresults -> {out}")
    print(f"problems with <8 accepted cases: {[(r['qid'], r['accepted']) for r in low]}")


if __name__ == "__main__":
    main()
