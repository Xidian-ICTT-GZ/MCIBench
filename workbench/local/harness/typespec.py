# -*- coding: utf-8 -*-
"""TypeSpec: the small type system shared by harness renderers.

Source of truth is the Python3 snippet signature (always has type hints in
FT_test). Other languages use their own entry-point names but the same types.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class Type:
    pass


class UnsupportedProblemError(ValueError):
    """The problem's shape is outside what this harness can judge.

    Subclasses ValueError so existing `except ValueError` callers keep working.
    Raised instead of letting an unsupported signature degrade into a generic
    render failure, which used to surface as a plain "Compile Error" -- i.e.
    blamed on the submission rather than on the harness.
    """


class Int(Type):
    pass


# Every target language renders Python `int` as a 32-bit C-style int (C, C++,
# Java, C#, Rust, Go's int on the judge image). A case value outside this range
# cannot be represented: the driver either fails to compile or silently
# truncates, which judges the *corpus* rather than the submission. Cases whose
# values fall outside the range are therefore invalid and must be dropped.
INT32_MIN = -(2 ** 31)
INT32_MAX = 2 ** 31 - 1
# 64-bit and JS-safe capacities. A value is representable iff **every** target
# language can hold it, so the effective capacity is the minimum over languages
# (see capacity_bits / unrepresentable_in_case).
INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1
INT53_MAX = 2 ** 53 - 1          # JavaScript Number.MAX_SAFE_INTEGER
_BITS_LIMITS = {32: INT32_MAX, 53: INT53_MAX, 64: INT64_MAX}

# Tokens that mean "this position is wider than 32 bits". Matched on the declared
# type after stripping pointers/containers, so `vector<long long>` and `long*`
# both resolve to 64.
_WIDE_TOKENS = ("long long", "longlong", "int64", "i64", "long int", "long")
_NARROW_TOKENS = ("int", "i32", "int32", "integer", "short", "char", "byte",
                  "bool", "unsigned")


def declared_bits(lang_key: str, entry: dict | None, j: int | None = None,
                  is_ret: bool = False, pname: str | None = None) -> int | None:
    """Bits available for a position under this language's own declaration.

    32 / 53 / 64, or None for unlimited (Python's arbitrary-precision int).
    Falls back to 32 whenever the declaration cannot be read, which keeps the
    previous conservative behaviour.
    """
    if lang_key == "python3":
        return None                      # Python int is unbounded
    if lang_key == "javascript":
        return 53                        # doubles are exact to 2**53-1
    if not entry:
        return 32
    decl = None
    if lang_key == "rust":
        if is_ret:
            decl = entry.get("rust_ret")
        else:
            rp = entry.get("rust_params") or []
            if j is not None and j < len(rp):
                decl = rp[j][1] if isinstance(rp[j], (tuple, list)) else rp[j]
    elif lang_key == "c":
        if is_ret:
            decl = entry.get("c_ret")
        else:
            # C's c_params also carries derived size / out params, so match by name.
            for cp in entry.get("c_params") or []:
                if pname is not None and cp.name == pname:
                    decl = cp.ctype
                    break
    else:
        decl = entry.get("ret_type") if is_ret else None
        if not is_ret:
            pt = entry.get("param_types") or []
            if j is not None and j < len(pt):
                decl = pt[j]
    if not decl:
        return 32
    return _bits_of_decl(str(decl))


def _bits_of_decl(decl: str) -> int:
    d = decl.lower().replace("const", "").replace("*", "").replace("&", "")
    d = re.sub(r"[\[\]<>]", " ", d).strip()
    # `long long` must win over `long`, and a bare `int` over `integer`.
    if "long long" in d or "int64" in d or d.strip() == "i64" or "i64" in d.split():
        return 64
    if "long" in d:
        return 64                        # LP64: C/C++/Java/C#/Go `long` is 64-bit
    for tok in _NARROW_TOKENS:
        if tok in d.split() or d.startswith(tok):
            return 32
    return 32


class Float(Type):
    pass


class Str(Type):
    pass


class Bool(Type):
    pass


@dataclass(frozen=True)
class ListT(Type):
    inner: Type


@dataclass(frozen=True)
class Param:
    name: str
    typ: Type


@dataclass(frozen=True)
class PlainSig:
    """Single-method problem signature (96/100 of FT_test)."""
    class_name: str
    method_name: str
    params: tuple[Param, ...]
    ret: Type


@dataclass(frozen=True)
class DesignSig:
    """Stateful class problem: constructor + methods (4/100 of FT_test)."""
    class_name: str
    methods: tuple[tuple[str, tuple[Param, ...], Type], ...]  # (name, params, ret)


_PY_TYPE_RE = re.compile(r"^(?:Optional\[)?(\w+|\w+\[[^]]*\])(?:\])?$")


def parse_py_type(text: str) -> Type | None:
    t = text.strip()
    if t == "None":
        return None  # void-returning methods
    m = re.fullmatch(r"Optional\[(.+)\]", t)
    if m:
        return parse_py_type(m.group(1))  # nullability has no harness impact here
    if t == "int":
        return Int()
    if t == "float":
        return Float()
    if t == "str":
        return Str()
    if t == "bool":
        return Bool()
    m = re.fullmatch(r"List\[(.+)\]", t)
    if m:
        return ListT(parse_py_type(m.group(1)))
    raise UnsupportedProblemError(
        f"unsupported Python type {text!r}: the harness handles "
        f"int/float/str/bool/List[...]/Optional[...] only. Tree, linked-list, "
        f"dict, set and tuple problems need a serializer that does not exist yet.")


def _split_top_level(s: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "[({":
            depth += 1
            cur.append(ch)
        elif ch in "])}":
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


def parse_python_snippet(code: str) -> PlainSig | DesignSig:
    """Parse the Python3 snippet into a signature."""
    ctor = re.search(r"def __init__\(self(?:,\s*(.*?))?\)", code, re.S)
    if ctor:
        # Design problem: __init__ + methods.
        methods: list[tuple[str, tuple[Param, ...], Type]] = []
        m = re.search(r"class (\w+)", code)
        class_name = m.group(1) if m else "Solution"
        for mm in re.finditer(
            r"def\s+(\w+)\s*\(self(?:\s*,\s*(.*?))?\)(?:\s*->\s*([^:]+))?:", code, re.S
        ):
            name, args, ret = mm.group(1), (mm.group(2) or "").strip(), mm.group(3)
            params: list[Param] = []
            for part in _split_top_level(args):
                if not part:
                    continue
                am = re.match(r"^(\w+)\s*:\s*(.+)$", part)
                if not am:
                    raise ValueError(f"cannot parse param {part!r} in {code[:80]}")
                params.append(Param(am.group(1), parse_py_type(am.group(2))))
            methods.append((name, tuple(params), parse_py_type(ret) if ret else None))
        return DesignSig(class_name, tuple(methods))

    m = re.search(
        r"class (\w+).*?def\s+(\w+)\s*\(self(?:\s*,\s*(.*?))?\)\s*->\s*([^:]+):", code, re.S
    )
    if not m:
        raise ValueError(f"cannot parse Python snippet: {code[:120]}")
    class_name, method_name, args, ret = m.groups()
    params: list[Param] = []
    for part in _split_top_level((args or "").strip()):
        if not part:
            continue
        am = re.match(r"^(\w+)\s*:\s*(.+)$", part)
        if not am:
            raise ValueError(f"cannot parse param {part!r} in {code[:80]}")
        params.append(Param(am.group(1), parse_py_type(am.group(2))))
    return PlainSig(class_name, method_name, tuple(params), parse_py_type(ret.strip()))


def _unrepresentable(typ: Type, value, max_bits: int = 32) -> bool:
    """True if `value` cannot be represented for a position of type `typ`.

    `max_bits` is the narrowest capacity among the target languages (see
    `declared_bits`). Only integer overflow is detected. Type mismatches are
    deliberately NOT flagged: the corpus stores values parsed generically from
    the dataset, and re-validating their declared types would drop legitimate
    cases.
    """
    if isinstance(typ, Int):
        limit = _BITS_LIMITS.get(max_bits)
        if limit is None:
            return False                 # unlimited (Python)
        return (isinstance(value, int) and not isinstance(value, bool)
                and not (-limit <= value <= limit))
    if isinstance(typ, ListT):
        if isinstance(value, list):
            return any(_unrepresentable(typ.inner, v, max_bits) for v in value)
        return False
    return False


def _capacity_for(entries: dict | None, j: int | None, is_ret: bool,
                  pname: str | None = None) -> int:
    """Narrowest capacity across all languages that declare this position.

    A case is usable only if EVERY language can hold it, hence the minimum.
    With no `entries` (callers that have not been updated) this stays 32, which
    reproduces the previous conservative behaviour exactly.
    """
    if not entries:
        return 32
    # Narrowest DECLARED capacity wins. Start unset rather than at 32, otherwise
    # the min() below can never exceed 32 and the widening is a no-op.
    bits: int | None = None
    for lang, e in entries.items():
        b = declared_bits(lang, e, j, is_ret, pname)
        if b is None:
            continue                     # unlimited -> cannot be the minimum
        bits = b if bits is None else min(bits, b)
    return bits if bits is not None else 32


def unrepresentable_in_case(sig: "PlainSig | DesignSig", case: dict,
                            entries: dict | None = None) -> list[str]:
    """Names of case values no target language can represent.

    `entries` maps language -> `extract_plain_entry` result; when supplied the
    check honours each language's **declared** type instead of assuming int32.
    q1922 declares `long`/`long long`/`int64`/`i64` for `n` in all 8 languages,
    so `n = 1e15` is representable and must not be dropped.
    """
    bad: list[str] = []
    if isinstance(sig, DesignSig):
        method_map = {name: (params, ret) for name, params, ret in sig.methods}
        ops = case.get("ops") or []
        args = case.get("args") or []
        expected = case.get("expected") or []
        for i, op in enumerate(ops):
            params, ret = method_map.get(op, ((), None))
            vals = args[i] if i < len(args) else []
            for k, (p, v) in enumerate(zip(params, vals)):
                if _unrepresentable(p.typ, v, _capacity_for(entries, k, False, p.name)):
                    bad.append(f"{op}({p.name})")
            if ret is not None and i < len(expected) and _unrepresentable(
                    ret, expected[i], _capacity_for(entries, None, True)):
                bad.append(f"{op}->return")
        return bad

    args = case.get("args") or {}
    for j, p in enumerate(sig.params):
        if p.name in args and _unrepresentable(
                p.typ, args[p.name], _capacity_for(entries, j, False, p.name)):
            bad.append(f"arg {p.name}")
    if "expected" in case and _unrepresentable(
            sig.ret, case["expected"], _capacity_for(entries, None, True)):
        bad.append("expected")
    return bad


def drop_unrepresentable(sig: "PlainSig | DesignSig",
                         cases: list[dict],
                         entries: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Split `cases` into (kept, dropped) by representability.

    Dropped entries are ``{"index": i, "fields": [...]}`` with `index` referring
    to the input list. Used both when building the corpus (so invalid cases never
    enter it) and when judging (so a stale corpus cannot blame the submission for
    a driver that cannot compile).

    Passing `entries` makes the check honour each language's declared type; see
    `unrepresentable_in_case`.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for i, case in enumerate(cases):
        bad = unrepresentable_in_case(sig, case, entries)
        if bad:
            dropped.append({"index": i, "fields": bad})
        else:
            kept.append(case)
    return kept, dropped
