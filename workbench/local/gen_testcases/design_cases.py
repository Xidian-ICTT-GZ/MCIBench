# -*- coding: utf-8 -*-
"""Design-problem (stateful class) seed cases from official worked examples.

The 4 FT_test design problems (1146, 1472, 2080, 2241) have op-sequence
examples in the prompts:

    Input:  ["SnapshotArray","set","snap","set","get"]
            [[3],[0,5],[],[0,6],[0,0]]
    Output: [null,null,0,null,5]

Parsed into {"ops": [...], "args": [[...]], "expected": [...]}.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from local.common import REPO_ROOT, SEED_DIR, load_json, save_json
from local.gen_testcases.parse_io import parse_output

DESIGN_QIDS = [1146, 1472, 2080, 2241]
EVAL_MATERIALS = REPO_ROOT / "SFT" / "data" / "eval_materials"

_OPS_RE = re.compile(
    r"Input\s*:?\s*(\[[\"']\w+[\"'](?:,\s*[\"']\w+[\"'])*\])\s*\n\s*(\[\[.*\]\])\s*\n"
    r"Output\s*:?\s*(\[.*\])\s*(?=\nExplanation|\nConstraints|\Z)", re.S)


def _extract_from_prompt(prompt: str) -> list[dict]:
    cases = []
    for m in _OPS_RE.finditer(prompt):
        ops_raw, args_raw, exp_raw = m.group(1), m.group(2), m.group(3)
        try:
            ops = parse_output(ops_raw)
            args = parse_output(args_raw)
            expected = parse_output(exp_raw)
        except (ValueError, SyntaxError):
            continue
        assert isinstance(ops, list) and isinstance(args, list) and isinstance(expected, list)
        assert len(ops) == len(args) == len(expected)
        cases.append({"ops": ops, "args": args, "expected": expected})
    return cases


def design_seed_cases(qid: int) -> list[dict]:
    """Load seed cases for a design problem (from _seed or extracted on the fly)."""
    p = SEED_DIR / f"design_{qid}.json"
    if p.exists():
        return load_json(p)
    # fall back to re-extraction from the prompt
    gen_file = EVAL_MATERIALS / "generation_FT_test.jsonl"
    with open(gen_file, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if int(row["problem_id"]) == qid:
                return _extract_from_prompt(row["prompt"])
    return []


def extract_all() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    gen_file = EVAL_MATERIALS / "generation_FT_test.jsonl"
    with open(gen_file, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            qid = int(row["problem_id"])
            if qid not in DESIGN_QIDS or qid in out:
                continue
            cases = _extract_from_prompt(row["prompt"])
            if cases:
                out[qid] = cases
    return out


def main() -> None:
    for qid, cases in sorted(extract_all().items()):
        save_json(SEED_DIR / f"design_{qid}.json", cases, indent=1)
        print(f"qid {qid}: {len(cases)} op-sequence cases")
    missing = [q for q in DESIGN_QIDS if not (SEED_DIR / f"design_{q}.json").exists()]
    print(f"design problems without seed cases: {missing}")


if __name__ == "__main__":
    main()
