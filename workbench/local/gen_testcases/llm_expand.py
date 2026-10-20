# -*- coding: utf-8 -*-
"""LLM-generated candidate inputs for problems lacking LeetCodeDataset coverage.

For plain problems: the LLM produces inputs (JSON dicts) following the
signature + constraints. For design problems: op sequences. The expected
outputs are NOT trusted from the LLM — differential verification derives them
from the reference solutions (python + >=1 other language agreement).

Output: local/testcases/_seed/llm_<qid>.json (plain: [{"args": {...}, "expected": null}];
design: [{"ops": [...], "args": [[...]], "expected": null}]).

Usage (from repo root):
    python -m local.gen_testcases.llm_expand --qids 1323,1969,2580,1146,1472,2080,2241,2575 \
        --n_per_problem 12 --api_url https://... --api_key sk-... --model qwen3-8b
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from local.common import SEED_DIR, load_snippet, save_json  # noqa: E402
from local.gen_testcases.design_cases import DESIGN_QIDS  # noqa: E402

PLAIN_PROMPT = """You generate test inputs for a LeetCode problem. Reply with ONLY a JSON
array of {n} objects; each object maps every parameter name to one valid value
(use the exact LeetCode value syntax: lists as [..], strings in double quotes).
Do not compute outputs. Cover edge cases from the constraints.

Function interface:
{signature}

Constraints:
{constraints}

Examples of valid inputs (vary these, do not copy):
{examples}
"""

DESIGN_PROMPT = """You generate test operation sequences for a LeetCode design problem. Reply
with ONLY a JSON array of {n} objects:
{{"ops": ["ClassName", ...], "args": [[ctor args], [op args], ...]}}.
Every sequence must start with the class name, and args must match each op's
signature. Do not compute outputs. Cover edge cases from the constraints.

Class methods:
{signature}

Constraints:
{constraints}

Example (vary this, do not copy):
{{"ops": {ops}, "args": {args}}}
"""


def call_llm(api_url: str, api_key: str, model: str, prompt: str) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(api_url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"no JSON array in LLM reply: {text[:200]}")
    return json.loads(m.group(0))


def plain_material(qid: int) -> tuple[str, str, str]:
    sig = load_snippet(qid, "python3")
    ex_file = SEED_DIR / f"examples_{qid}.json"
    examples = ""
    if ex_file.exists():
        examples = json.dumps(json.loads(ex_file.read_text(encoding="utf-8"))[:3],
                              ensure_ascii=False)
    # constraints from the FT_test prompt
    constraints = ""
    for line in open(Path("SFT/data/eval_materials/generation_FT_test.jsonl"),
                     encoding="utf-8"):
        row = json.loads(line)
        if int(row["problem_id"]) == qid:
            m = re.search(r"Constraints\s*:\s*(.*?)(?=Function/Class|\Z)",
                          row["prompt"], re.S)
            if m:
                constraints = m.group(1).strip()
            break
    return sig, constraints, examples


def expand_plain(qid: int, n: int, api_url: str, api_key: str, model: str) -> list[dict]:
    sig, constraints, examples = plain_material(qid)
    prompt = PLAIN_PROMPT.format(n=n, signature=sig, constraints=constraints,
                                 examples=examples)
    raw = call_llm(api_url, api_key, model, prompt)
    items = extract_json(raw)
    return [{"args": it, "expected": None} for it in items]


def expand_design(qid: int, n: int, api_url: str, api_key: str, model: str) -> list[dict]:
    sig = load_snippet(qid, "python3")
    constraints = ""
    for line in open(Path("SFT/data/eval_materials/generation_FT_test.jsonl"),
                     encoding="utf-8"):
        row = json.loads(line)
        if int(row["problem_id"]) == qid:
            m = re.search(r"Constraints\s*:\s*(.*?)(?=Function/Class|\Z)",
                          row["prompt"], re.S)
            if m:
                constraints = m.group(1).strip()
            break
    seed = SEED_DIR / f"design_{qid}.json"
    ops, args = [], []
    if seed.exists():
        s0 = json.loads(seed.read_text(encoding="utf-8"))[0]
        ops, args = s0["ops"], s0["args"]
    prompt = DESIGN_PROMPT.format(n=n, signature=sig, constraints=constraints,
                                  ops=json.dumps(ops), args=json.dumps(args))
    raw = call_llm(api_url, api_key, model, prompt)
    items = extract_json(raw)
    return [{"ops": it["ops"], "args": it["args"], "expected": None} for it in items]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", required=True)
    ap.add_argument("--n_per_problem", type=int, default=12)
    ap.add_argument("--api_url", default=os.environ.get("LLM_API_URL",
                    "https://api.deepseek.com/v1/chat/completions"))
    ap.add_argument("--api_key", default=os.environ.get("LLM_API_KEY", ""))
    ap.add_argument("--model", default="deepseek-chat")
    args = ap.parse_args()

    qids = [int(x) for x in args.qids.split(",") if x.strip()]
    for qid in qids:
        try:
            if qid in DESIGN_QIDS:
                cases = expand_design(qid, args.n_per_problem, args.api_url,
                                      args.api_key, args.model)
            else:
                cases = expand_plain(qid, args.n_per_problem, args.api_url,
                                     args.api_key, args.model)
        except Exception as e:  # noqa: BLE001
            print(f"qid {qid}: FAILED {type(e).__name__}: {e}")
            continue
        save_json(SEED_DIR / f"llm_{qid}.json", cases, indent=1)
        print(f"qid {qid}: {len(cases)} LLM cases -> {SEED_DIR / f'llm_{qid}.json'}")


if __name__ == "__main__":
    main()
