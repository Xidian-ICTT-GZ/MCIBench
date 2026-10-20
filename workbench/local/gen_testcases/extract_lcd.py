# -*- coding: utf-8 -*-
"""Extract LeetCodeDataset input_output cases for the FT_test problems.

Source: LeetCodeDataset-train.jsonl (newfacade/LeetCodeDataset, Apache-2.0),
downloaded to <LCD_JSONL> (default: /tmp/lcj/lcd_train.jsonl). Emits one
local/testcases/_seed/lcd_<qid>.json per matched problem with parsed cases.

Usage:
    python local/gen_testcases/extract_lcd.py --lcd /tmp/lcj/lcd_train.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from local.common import load_ft_test_qids, save_json, SEED_DIR
from local.gen_testcases.parse_io import parse_input, parse_output


def extract(lcd_path: Path) -> tuple[dict[int, list[dict]], dict[int, int]]:
    qids = set(load_ft_test_qids())
    hits: dict[int, list[dict]] = {}
    dropped: dict[int, int] = {}
    with open(lcd_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            qid = int(row.get("question_id") or -1)
            if qid not in qids:
                continue
            cases = []
            for io in row.get("input_output", []):
                try:
                    args = parse_input(io["input"])
                    expected = parse_output(io["output"])
                except (ValueError, SyntaxError, KeyError):
                    # Unparseable cases are dropped (e.g. LeetCodeDataset's own
                    # "Execution timed out" placeholder outputs).
                    dropped[qid] = dropped.get(qid, 0) + 1
                    continue
                cases.append({"args": args, "expected": expected})
            hits[qid] = cases
    return hits, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lcd", default="/tmp/lcj/lcd_train.jsonl")
    args = ap.parse_args()

    hits, dropped = extract(Path(args.lcd))
    for qid, cases in sorted(hits.items()):
        note = f" ({dropped.get(qid, 0)} dropped)" if dropped.get(qid) else ""
        save_json(SEED_DIR / f"lcd_{qid}.json", cases, indent=1)
        print(f"qid {qid}: {len(cases)} cases{note} -> {SEED_DIR / f'lcd_{qid}.json'}")
    print(f"\n{len(hits)} problems extracted, "
          f"{sum(dropped.values())} invalid cases dropped across {len(dropped)} problems")


if __name__ == "__main__":
    main()
