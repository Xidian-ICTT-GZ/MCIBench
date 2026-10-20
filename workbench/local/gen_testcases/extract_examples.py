# -*- coding: utf-8 -*-
"""Extract official worked examples from the FT_test prompts.

generation_FT_test.jsonl / translation_FT_test.jsonl prompts embed the LeetCode
problem statement, including "Example N: Input: ... Output: ..." blocks. These
are official example test cases — used as seeds for the problems missing from
LeetCodeDataset and as priority cases everywhere.

Usage (from repo root):
    python -m local.gen_testcases.extract_examples
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from local.common import REPO_ROOT, SEED_DIR, load_ft_test_qids, save_json
from local.gen_testcases.parse_io import parse_input, parse_output

EVAL_MATERIALS = REPO_ROOT / "SFT" / "data" / "eval_materials"

_EXAMPLE_RE = re.compile(r"Example\s*(\d+)\s*:\s*\n(.*?)(?=Example\s*\d+\s*:\s*\n|Constraints|Note|\Z)",
                          re.S)
_INPUT_RE = re.compile(r"Input\s*:\s*(.*?)(?=Output\s*:|\Z)", re.S)
_OUTPUT_RE = re.compile(
    r"Output\s*:\s*(.*?)(?=\nExplanation|\nConstraints|\nNote|Example\s*\d|提示|\Z)", re.S)


def extract_from_prompt(prompt: str) -> list[dict]:
    cases = []
    for m in _EXAMPLE_RE.finditer(prompt):
        block = m.group(2)
        im = _INPUT_RE.search(block)
        if not im:
            continue
        om = _OUTPUT_RE.search(block[im.end():]) if im else None
        if not om:
            continue
        try:
            args = parse_input(im.group(1).strip())
            expected = parse_output(om.group(1).strip())
        except (ValueError, SyntaxError):
            continue
        cases.append({"args": args, "expected": expected})
    return cases


def extract_all() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    gen_file = EVAL_MATERIALS / "generation_FT_test.jsonl"
    seen = set()
    with open(gen_file, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            qid = int(row["problem_id"])
            if qid in seen:
                continue
            seen.add(qid)
            cases = extract_from_prompt(row["prompt"])
            if cases:
                out[qid] = cases
    return out


def main() -> None:
    cases_by_qid = extract_all()
    n = 0
    for qid, cases in sorted(cases_by_qid.items()):
        save_json(SEED_DIR / f"examples_{qid}.json", cases, indent=1)
        n += len(cases)
        print(f"qid {qid}: {len(cases)} examples")
    print(f"\n{len(cases_by_qid)} problems, {n} example cases total")
    missing = [q for q in load_ft_test_qids() if q not in cases_by_qid]
    print(f"problems without parseable examples: {missing}")


if __name__ == "__main__":
    main()
