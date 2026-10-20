# -*- coding: utf-8 -*-
"""Pair historical LeetCode verdicts with the submissions that produced them.

Two naming conventions have to be reconciled -- this is why a naive pairing
yields 0 matches:

    code files    Submit_Gen/<run>/codes/1014_C#_1.txt       display labels
                  Submit_Trans/<run>/codes/1014_C#_C++.txt   display labels
    result files  .../1014/1014_csharp_1.json                language keys
                  .../1014/1014_cpp_csharp_1.json            language keys

Display labels are `Python3/C/C++/C#/Java/JavaScript/Golang/Rust`; language keys
are `python3/c/cpp/csharp/java/javascript/golang/rust`. The code side is parsed
with `local.judge.parse_code_filename` so it stays the single source of truth.

A slot key is `(qid, src_or_lang, tgt_or_None, candidate)`.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from local.common import KEY_TO_LABEL, LABEL_TO_KEY, REPO_ROOT
from local.judge import parse_code_filename

SFT_FULL = REPO_ROOT / "SFT_Full"

# canonical LeetCode vocabulary; anything else must not be silently bucketed
CANONICAL = {"Accepted", "Wrong Answer", "Compile Error", "Runtime Error",
             "Time Limit Exceeded", "Memory Limit Exceeded",
             "Output Limit Exceeded"}
# seen in the wild in old runs, and NOT canonical -> clean_results.py would raise
NON_CANONICAL = {"REVOKED", "PENDING", "Internal Error", "UNKNOWN"}

_KEY = r"python3|c|cpp|csharp|java|javascript|golang|rust"
_GEN_RESULT_RE = re.compile(rf"^(\d+)_({_KEY})_(\d+)\.json$")
_TRANS_RESULT_RE = re.compile(rf"^(\d+)_({_KEY})_({_KEY})_(\d+)\.json$")


@dataclass(frozen=True)
class Slot:
    qid: int
    lang: Optional[str]      # gen target language
    src: Optional[str]       # trans source language
    tgt: Optional[str]       # trans target language
    cand: int

    @property
    def key(self) -> tuple:
        return (self.qid, self.src or self.lang, self.tgt, self.cand)

    @property
    def target_lang(self) -> str:
        """The language whose code is judged (gen: lang, trans: tgt)."""
        return self.tgt or self.lang  # type: ignore[return-value]

    def label(self) -> str:
        if self.tgt:
            return (f"q{self.qid} {KEY_TO_LABEL[self.src]}->{KEY_TO_LABEL[self.tgt]}"
                    f" #{self.cand}")
        return f"q{self.qid} {KEY_TO_LABEL[self.lang]} #{self.cand}"


def result_root(run: str, task: str) -> Path:
    prefix = "Submit_Results_" if task == "gen" else "Submit_Results_Trans_"
    return SFT_FULL / "Submit_Result" / f"{prefix}{run}"


def code_root(run: str, task: str) -> Path:
    base = SFT_FULL / ("Submit_Gen" if task == "gen" else "Submit_Trans")
    return base / run / "codes"


def list_runs(task: str) -> list[str]:
    """Run names that have BOTH historical results and the submitted code."""
    root = SFT_FULL / "Submit_Result"
    prefix = "Submit_Results_" if task == "gen" else "Submit_Results_Trans_"
    out = []
    for d in sorted(root.glob(f"{prefix}*")):
        run = d.name[len(prefix):]
        if code_root(run, task).is_dir() and any(code_root(run, task).glob("*.txt")):
            out.append(run)
    return out


def load_verdict(path: Path) -> tuple[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    status = data.get("ac_status") or data.get("state") or "UNKNOWN"
    return status, data


def _slot_from_code(name: str) -> Optional[Slot]:
    meta = parse_code_filename(name)
    if not meta:
        return None
    if meta["task"] == "trans":
        return Slot(meta["qid"], None, meta["src"], meta["tgt"], meta["cand"])
    return Slot(meta["qid"], meta["lang"], None, None, meta["cand"])


def code_slots(run: str, task: str) -> dict[tuple, Path]:
    root = code_root(run, task)
    out: dict[tuple, Path] = {}
    if not root.is_dir():
        return out
    for p in root.glob("*.txt"):
        s = _slot_from_code(p.name)
        if s:
            out[s.key] = p
    return out


def result_slots(run: str, task: str) -> dict[tuple, tuple[Path, str]]:
    root = result_root(run, task)
    out: dict[tuple, tuple[Path, str]] = {}
    if not root.is_dir():
        return out
    rx = _GEN_RESULT_RE if task == "gen" else _TRANS_RESULT_RE
    for p in root.rglob("*.json"):
        if p.name == "judge_meta.json":
            continue
        m = rx.match(p.name)
        if not m:
            continue
        if task == "gen":
            qid, lang, cand = int(m.group(1)), m.group(2), int(m.group(3))
            key = (qid, lang, None, cand)
        else:
            qid, src, tgt, cand = (int(m.group(1)), m.group(2), m.group(3),
                                   int(m.group(4)))
            key = (qid, src, tgt, cand)
        status, _ = load_verdict(p)
        out[key] = (p, status)
    return out


@dataclass
class Pair:
    slot: Slot
    code_path: Path
    leetcode_status: str
    leetcode_raw: dict
    run: str = ""

    @property
    def audit_key(self) -> str:
        """Stable identity for caching/joining. MUST include the run name.

        The same (qid, language, candidate) slot exists in many runs with
        *different* code, so a key without the run silently returns another
        run's verdict.
        """
        task = "trans" if self.slot.tgt else "gen"
        return f"{task}:{self.run}:{self.slot.key}"


def iter_pairs(run: str, task: str, qids: Optional[set[int]] = None
               ) -> Iterator[Pair]:
    """Yield slots that have BOTH a historical verdict and the submitted code."""
    codes = code_slots(run, task)
    results = result_slots(run, task)
    for key in sorted(set(codes) & set(results)):
        if qids and key[0] not in qids:
            continue
        path, status = results[key]
        s = _slot_from_code(codes[key].name)
        if s is None:
            continue
        _, raw = load_verdict(path)
        yield Pair(s, codes[key], status, raw, run)


def pairing_report(tasks: tuple[str, ...] = ("gen", "trans")) -> None:
    """Print how many slots are pairable per run (the audit's usable scale)."""
    total = 0
    for task in tasks:
        runs = list_runs(task)
        print(f"\n=== {task} ({len(runs)} 个可对拍 run) ===")
        for run in runs:
            codes = code_slots(run, task)
            results = result_slots(run, task)
            common = set(codes) & set(results)
            total += len(common)
            verdicts = Counter(results[k][1] for k in common)
            nc = {s: n for s, n in verdicts.items() if s not in CANONICAL}
            print(f"  {run[:58]:58s} 结果{len(results):6d} 代码{len(codes):6d} "
                  f"配对{len(common):6d}"
                  + (f"  非规范判定={nc}" if nc else ""))
    print(f"\n可配对槽位合计 = {total}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="自检：历史 LeetCode 结果与提交代码的配对规模")
    ap.add_argument("--task", default="", choices=["", "gen", "trans"])
    args = ap.parse_args()
    pairing_report((args.task,) if args.task else ("gen", "trans"))


if __name__ == "__main__":
    main()
