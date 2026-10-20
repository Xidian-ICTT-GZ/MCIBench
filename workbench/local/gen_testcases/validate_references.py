# -*- coding: utf-8 -*-
"""Sweep all 100 x 8 reference solutions through the local judge (2 seed cases).

This validates the full stack (corpus + harness + sandbox) against references:
a reference should render, compile and pass its own language's driver. Broken
references (e.g. truncated files like qid 47 C++) show up as CE and are excluded
from differential voting later.

Usage (from repo root):
    python -m local.gen_testcases.validate_references --max_workers 4 --out local/results/ref_sweep.json
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local.common import (LANGS, SEED_DIR, load_json, load_reference,
                          load_snippet, load_ft_test_qids)
from local.gen_testcases.design_cases import DESIGN_QIDS, design_seed_cases
from local.harness.render import (extract_plain_entry, render_design_driver,
                                  render_plain_driver)
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier
from local.harness.runner import run_submission
from local.harness.typespec import DesignSig, PlainSig, parse_python_snippet


def seed_cases(qid: int, n: int) -> list[dict]:
    if qid in DESIGN_QIDS:
        return design_seed_cases(qid)[:n]
    for prefix in (f"lcd_{qid}", f"examples_{qid}"):
        p = SEED_DIR / f"{prefix}.json"
        if p.exists():
            return load_json(p)[:n]
    return []


def sweep_one(qid: int, lang: str, n_cases: int, backend: str) -> dict:
    try:
        if qid in DESIGN_QIDS:
            sig = parse_python_snippet(load_snippet(qid, "python3"))
            assert isinstance(sig, DesignSig)
            cases = seed_cases(qid, n_cases)
            if not cases:
                return {"qid": qid, "lang": lang, "status": "NO_CASES", "error": ""}
            drv = render_output_driver(lang, sig, {}, cases, load_reference(qid, lang))
        else:
            sig = parse_python_snippet(load_snippet(qid, "python3"))
            assert isinstance(sig, PlainSig)
            cases = seed_cases(qid, n_cases)
            if not cases:
                return {"qid": qid, "lang": lang, "status": "NO_CASES", "error": ""}
            entry = extract_plain_entry(lang, load_snippet(qid, lang))
            drv = render_output_driver(lang, sig, entry, cases, load_reference(qid, lang))
        res = run_submission(lang, drv, limit=len(cases), backend=backend,
                             output_verifier=OutputVerifier(qid, cases, signature=sig))
        return {"qid": qid, "lang": lang, "status": res.status,
                "error": res.log[:600]}
    except Exception as e:  # noqa: BLE001
        return {"qid": qid, "lang": lang, "status": "RENDER_ERROR",
                "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", default="")
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--cases", type=int, default=2)
    ap.add_argument("--max_workers", type=int, default=4)
    ap.add_argument("--backend", default="docker", choices=["host", "docker"])
    ap.add_argument("--out", default="local/results/ref_sweep.json")
    args = ap.parse_args()

    qids = ([int(x) for x in args.qids.split(",") if x.strip()]
            if args.qids else load_ft_test_qids())
    langs = [x for x in args.langs.split(",") if x.strip()]
    tasks = [(q, lang) for q in qids for lang in langs]

    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        for r in ex.map(lambda t: sweep_one(t[0], t[1], args.cases, args.backend),
                        tasks):
            results.append(r)
            print(f"{r['qid']:>5} {r['lang']:11s} {r['status']}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    c = Counter(r["status"] for r in results)
    print("\n=== summary ===")
    for status, n in sorted(c.items()):
        print(f"  {status}: {n}")
    bad = [r for r in results if r["status"] != "Accepted"]
    print(f"\n=== failures ({len(bad)}) ===")
    for r in bad:
        print(f"  {r['qid']} {r['lang']}: {r['error'][:150]}")


if __name__ == "__main__":
    main()
