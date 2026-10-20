# -*- coding: utf-8 -*-
"""Build exploratory WIDE proposals with versioned, independent verification.

Python proposes outputs; both C++ and Java must confirm every retained candidate.
Disagreement and unavailable references remain inconclusive, never discarded votes.
Cached cases bind source, seeds, templates, references, configuration and image.
These exploratory checks do not replace the official eight-language publication gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from local.common import SEED_DIR, load_json, load_reference, load_snippet, save_json
from local.gen_testcases.design_cases import DESIGN_QIDS, design_seed_cases
from local.gen_testcases.differential import python_outputs
from local.harness.render import (extract_plain_entry, render_design_driver,
                                  render_plain_driver)
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier
from local.harness.runner import run_submission
from local.harness.typespec import (DesignSig, PlainSig, drop_unrepresentable,
                                    parse_python_snippet)

WIDE_CACHE = Path(__file__).resolve().parents[1] / "results" / "wide_cases"
DEFAULT_CAP = 200          # effectively "all"; guards against pathological seeds
VERIFY_LANGS = ("cpp", "java")


class WideInconclusive(RuntimeError):
    pass


def cache_identity(qid, backend):
    from local.common import LOCAL_DIR, LANGS
    from local.harness.identity import image_digest
    if backend != "docker":
        raise WideInconclusive("WIDE evidence requires the pinned Docker environment")
    payload = {"schema": 2, "qid": qid, "backend": backend, "cap": DEFAULT_CAP,
               "verify_langs": VERIFY_LANGS, "image": image_digest(),
               "sources": {}, "seeds": {}, "references": {}, "snippets": {}}
    for folder in ("audit", "gen_testcases", "harness"):
        for path in sorted((LOCAL_DIR / folder).glob("*.py")):
            payload["sources"][str(path.relative_to(LOCAL_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload["sources"]["common.py"] = hashlib.sha256((LOCAL_DIR / "common.py").read_bytes()).hexdigest()
    for prefix in ("lcd", "llm", "examples"):
        path = SEED_DIR / f"{prefix}_{qid}.json"
        payload["seeds"][prefix] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    for lang in LANGS:
        payload["references"][lang] = hashlib.sha256(load_reference(qid, lang).encode()).hexdigest()
        payload["snippets"][lang] = hashlib.sha256(load_snippet(qid, lang).encode()).hexdigest()
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()



def all_candidates(qid: int, cap: int = DEFAULT_CAP) -> tuple[list[dict], int]:
    """Every candidate case for a problem (no 30-case truncation), plus n_lcd."""
    if qid in DESIGN_QIDS:
        cases = list(design_seed_cases(qid))
        llm = SEED_DIR / f"llm_{qid}.json"
        if llm.exists():
            cases += load_json(llm)
        return cases[:cap], 0
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
    return cases[:cap], min(n_lcd, cap)


def _run_lang(qid: int, lang: str, cases: list[dict], expected: list,
              backend: str) -> list[str]:
    """Which cases this language's reference passes (expected = Python output)."""
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    user = load_reference(qid, lang)
    sub = [dict(c, expected=expected[i]) for i, c in enumerate(cases)]
    try:
        if qid in DESIGN_QIDS:
            drv = render_output_driver(lang, sig, {}, sub, user)
        else:
            assert isinstance(sig, PlainSig)
            entry = extract_plain_entry(lang, load_snippet(qid, lang))
            drv = render_output_driver(lang, sig, entry, sub, user)
    except Exception:  # noqa: BLE001
        return ["Render Error"] * len(cases)
    res = run_submission(lang, drv, limit=len(sub), backend=backend,
                         run_timeout_s=30, output_verifier=OutputVerifier(qid, sub, signature=sig))
    if res.status == "Accepted":
        return ["Accepted"] * len(cases)
    if res.status == "Compile Error":
        return ["Compile Error"] * len(cases)
    # attribute per case: a plain verdict only tells us where it stopped
    out: list[str] = []
    for i in range(len(cases)):
        one = [dict(cases[i], expected=expected[i])]
        try:
            if qid in DESIGN_QIDS:
                drv1 = render_output_driver(lang, sig, {}, one, user)
            else:
                sig2 = parse_python_snippet(load_snippet(qid, "python3"))
                entry2 = extract_plain_entry(lang, load_snippet(qid, lang))
                drv1 = render_output_driver(lang, sig2, entry2, one, user)
            r1 = run_submission(lang, drv1, limit=1, backend=backend,
                                run_timeout_s=30, output_verifier=OutputVerifier(qid, one, signature=sig))
            out.append(r1.status)
        except Exception:  # noqa: BLE001
            out.append("Execution Error")
    return out


def build_wide_cases(qid: int, backend: str = "docker",
                     verify_langs: tuple[str, ...] = ("cpp", "java"),
                     cap: int = DEFAULT_CAP, verbose: bool = False) -> dict:
    """Return {"qid", "cases", "n_candidates", "dropped": {...}, "voters": [...]}."""
    cand, n_lcd = all_candidates(qid, cap)
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    cand, dropped_oom = drop_unrepresentable(sig, cand)
    if not cand:
        return {"qid": qid, "cases": [], "n_candidates": 0,
                "dropped": {"unrepresentable": len(dropped_oom)}, "voters": []}

    py = python_outputs(qid, cand, backend)
    keep = [i for i, o in enumerate(py) if o is not None]
    dropped_py = len(cand) - len(keep)
    cases = [dict(cand[i], expected=py[i]) for i in keep]
    expected = [c["expected"] for c in cases]

    voters = ["python3"]
    diagnostics = {}
    passed = [True] * len(cases)
    for lang in verify_langs:
        if not cases:
            break
        try:
            statuses = _run_lang(qid, lang, cases, expected, backend)
        except Exception as exc:
            statuses = ["Infrastructure Error: " + type(exc).__name__] * len(cases)
        diagnostics[lang] = statuses
        if len(statuses) != len(cases):
            raise WideInconclusive("reference coverage mismatch")
        # A disagreeing or unavailable reference is never silently removed.
        passed = [old and status == "Accepted" for old, status in zip(passed, statuses)]
        if all(status == "Accepted" for status in statuses):
            voters.append(lang)
    confirmed = len(set(verify_langs) - {"python3"}) >= 2 and bool(cases) and all(passed) and dropped_py == 0

    return {
        "qid": qid,
        "cases": cases,
        "n_candidates": len(cand) + len(dropped_oom),
        "dropped": {"unrepresentable": len(dropped_oom), "python_failed": dropped_py},
        "voters": voters,
        "status": "confirmed_exploratory" if confirmed else "inconclusive",
        "diagnostics": diagnostics,
    }


def get_wide_cases(qid: int, backend: str = "docker", rebuild: bool = False,
                   verbose: bool = False) -> list[dict]:
    """Cached wide case set for a problem."""
    WIDE_CACHE.mkdir(parents=True, exist_ok=True)
    p = WIDE_CACHE / f"{qid}.json"
    identity = cache_identity(qid, backend)
    rec = load_json(p) if p.exists() and not rebuild else None
    if not isinstance(rec, dict) or rec.get("identity") != identity:
        rec = build_wide_cases(qid, backend=backend, verify_langs=VERIFY_LANGS, verbose=verbose)
        if cache_identity(qid, backend) != identity:
            raise WideInconclusive("WIDE inputs changed during verification")
        rec["identity"] = identity
        save_json(p, rec, indent=1)
    if rec.get("status") != "confirmed_exploratory":
        raise WideInconclusive(f"q{qid}: independent references did not confirm the WIDE proposal")

    if verbose:
        print(f"  q{qid}: wide={len(rec['cases'])} candidates={rec['n_candidates']} "
              f"voters={rec['voters']} dropped={rec['dropped']}")
    return rec["cases"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    from local.common import load_ft_test_qids
    qids = ([int(x) for x in args.qids.split(",") if x.strip()]
            if args.qids else load_ft_test_qids())
    tot_c = tot_w = 0
    for q in qids:
        cs = get_wide_cases(q, args.backend, args.rebuild, args.verbose)
        from local.common import TESTCASES_DIR
        narrow_p = TESTCASES_DIR / str(q) / "cases.json"
        n = len(load_json(narrow_p)) if narrow_p.exists() else 0
        tot_c += n
        tot_w += len(cs)
        print(f"q{q:<5} narrow={n:3d}  wide={len(cs):4d}")
    print(f"\n合计 narrow={tot_c}  wide={tot_w}")


if __name__ == "__main__":
    main()
