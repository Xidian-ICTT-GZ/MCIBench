# -*- coding: utf-8 -*-
"""Parse LeetCode-style "name = value" test IO strings into Python values.

Input strings look like:  "nums1 = [100,200,300], nums2 = [150,250,350]"
                          "root = [5,3,6,5,2,5,7,1,8,null,null,6,8], k = 2"
Output strings look like: "225.0" / "[2, 2, 2]" / "false" / "null" / "\"abc\""

LeetCode serialisation uses null/true/false (JSON literals) inside values, so we
normalise those to Python tokens before ast.literal_eval.
"""
from __future__ import annotations

import ast
import re

_NULL_RE = re.compile(r"\bnull\b")
_TRUE_RE = re.compile(r"\btrue\b")
_FALSE_RE = re.compile(r"\bfalse\b")


def _normalize_leet_tokens(s: str) -> str:
    s = _NULL_RE.sub("None", s)
    s = _TRUE_RE.sub("True", s)
    s = _FALSE_RE.sub("False", s)
    return s


def _split_top_level(s: str) -> list[str]:
    """Split on top-level commas, ignoring commas inside brackets/quotes."""
    parts, depth, cur, in_str, esc = [], 0, [], False, False
    for ch in s:
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                cur.append(ch)
            elif ch in "[{(":
                depth += 1
                cur.append(ch)
            elif ch in "]})":
                depth -= 1
                cur.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def _parse_value(raw: str):
    """Parse one LeetCode-serialised value (possibly multiline) into a Python value."""
    text = _normalize_leet_tokens(raw.strip())
    if text == "":
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        # Last resort: strip quotes LeetCode uses around string outputs.
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            return text[1:-1]
        raise


def parse_input(s: str) -> dict[str, object]:
    """Parse an input string into {param_name: value}."""
    out = {}
    for part in _split_top_level(s):
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", part, re.S)
        if not m:
            raise ValueError(f"cannot parse input assignment: {part!r} in {s!r}")
        name, raw = m.group(1), m.group(2)
        out[name] = _parse_value(raw)
    return out


def parse_output(s: str):
    """Parse an output string into a Python value."""
    text = s.strip()
    if text == "":
        return None
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        # JSON string literal: decode escapes then strip quotes.
        try:
            import json
            return json.loads(text)
        except json.JSONDecodeError:
            return text[1:-1]
    return _parse_value(text)
