# -*- coding: utf-8 -*-
"""Shared paths, language constants and IO helpers for the local judge corpus pipeline."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = REPO_ROOT / "local"
TESTCASES_DIR = LOCAL_DIR / "testcases"
SEED_DIR = TESTCASES_DIR / "_seed"
SNIPPETS_DIR = REPO_ROOT / "MCIBench-test" / "metadata" / "templates" / "snippets"
REFERENCE_DIR = REPO_ROOT / "MCIBench-test" / "solutions" / "reference"
DESCRIPTIONS_DIR = REPO_ROOT / "MCIBench-test" / "metadata" / "problems" / "descriptions"
FT_TEST_FILE = REPO_ROOT / "SFT" / "data" / "datasets" / "FT_test.txt"

# LeetCode language keys as used in result filenames and snippets dirs.
LANGS = ["python3", "c", "cpp", "csharp", "java", "javascript", "golang", "rust"]
# Snippet/reference filename language labels (display names as in the repo).
LANG_LABELS = ["Python3", "C", "C++", "C#", "Java", "JavaScript", "Golang", "Rust"]
KEY_TO_LABEL = dict(zip(LANGS, LANG_LABELS))
LABEL_TO_KEY = dict(zip(LANG_LABELS, LANGS))

TARGET_TEST_CASES = 8  # minimum effective cases per problem (BootTrans ~8 is lossless)
DEFAULT_MAX_CASES = 30  # default cap used by the judge


def load_ft_test_qids() -> list[int]:
    """Load the 100 fixed evaluation problem ids (FT_test.txt has a 'problem_id' header line)."""
    qids = []
    for line in FT_TEST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.isdigit():
            qids.append(int(line))
    return qids


def load_snippet(qid: int, lang_key: str) -> str:
    """Return the interface template for (qid, lang) as a plain string."""
    label = KEY_TO_LABEL[lang_key]
    p = SNIPPETS_DIR / str(qid) / f"{label}.json"
    return json.loads(p.read_text(encoding="utf-8"))


# A few (problem, language) pairs ship a corrected follow-up solution as `_ans2`
# while `_ans1` is broken -- either an answer to a *different* problem or a
# fragment that cannot compile. The judge must use the corrected one.
#   q47   C++  : ans1 is a C-style free function, not a `class Solution` method
#   q2555 Java : ans1 implements `minEnd` (a different problem); ans2 has
#                `maximizeWin`, which is what q2555's corpus expects
REFERENCE_ATTEMPT_OVERRIDE: dict[tuple[int, str], int] = {
    (47, "cpp"): 2,
    (2555, "java"): 2,
}


def load_reference(qid: int, lang_key: str, attempt: int = 1) -> str:
    label = KEY_TO_LABEL[lang_key]
    if attempt == 1:
        attempt = REFERENCE_ATTEMPT_OVERRIDE.get((qid, lang_key), 1)
    p = REFERENCE_DIR / str(qid) / f"{qid}_{label}_ans{attempt}.txt"
    return p.read_text(encoding="utf-8")


def save_json(path: Path, obj, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
