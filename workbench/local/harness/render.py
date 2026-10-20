# -*- coding: utf-8 -*-
"""Render per-language test drivers for the local judge.

A driver is: [prelude] + [eqv helpers] + [user code] + [main: bake cases, call
entry point, compare with expected, print OK / FAIL <idx> and exit 3].

Exit code contract (consumed by local/judge.py):
  0   -> all cases passed
  3   -> wrong answer (driver-printed "FAIL <idx>")
  4   -> runtime error (crash / other non-zero exit)
  124 -> timeout (imposed by the outer timeout command)
  137 -> OOM (imposed by the cgroup memory limit)

The driver reads the case limit from argv[1] (judge passes --max_cases).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from local.common import KEY_TO_LABEL, load_snippet
from local.harness import dataio, validators
from local.harness.typespec import (
    Bool,
    DesignSig,
    Float,
    Int,
    ListT,
    Param,
    PlainSig,
    Str,
    Type,
    UnsupportedProblemError,
)

# --------------------------------------------------------------------------
# Entry-point extraction from each language's own snippet (plain problems)
# --------------------------------------------------------------------------

_CPP_METHOD_RE = re.compile(r"public:\s*(?:[^{}]*?)([\w:<>*&]+)\s+(\w+)\s*\(([^)]*)\)")
_JAVA_METHOD_RE = re.compile(r"public\s+([\w\[\]<>]+)\s+(\w+)\s*\(([^)]*)\)")
_CSHARP_METHOD_RE = re.compile(r"public\s+([\w\[\]<>]+)\s+(\w+)\s*\(([^)]*)\)")
_GO_FUNC_RE = re.compile(r"func\s+(\w+)\s*\(([^)]*)\)")
_JS_VAR_RE = re.compile(r"var\s+(\w+)\s*=\s*function\s*\(([^)]*)\)")
_RUST_FN_RE = re.compile(r"impl\s+\w+\s*{\s*pub\s+fn\s+(\w+)\s*\(([^)]*)\)")
_C_FUNC_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_ *]+?)\s+(\w+)\s*\(([^)]*)\)\s*\{", re.S
)


class CParam:
    def __init__(self, ctype: str, name: str):
        self.ctype = ctype.strip()
        self.name = name.strip()
        self.is_ptr = "*" in self.ctype

    @property
    def is_out(self) -> bool:
        return self.name.startswith("return") and self.is_ptr


def build_entries(qid: int) -> dict[str, dict]:
    """Extract every language's entry, for declared-type representability checks.

    Used by `typespec.unrepresentable_in_case` so the check honours each
    language's own declaration (`long`/`int64`/`i64`) instead of assuming int32.
    Missing language snippets are simply skipped; the check then falls back to
    the conservative 32-bit assumption for that language.
    """
    out: dict[str, dict] = {}
    for lang in KEY_TO_LABEL:
        try:
            out[lang] = extract_plain_entry(lang, load_snippet(qid, lang))
        except Exception:  # noqa: BLE001
            continue
    return out


def extract_plain_entry(lang_key: str, code: str) -> dict[str, Any]:
    """Extract entry point info for a plain problem from that language's snippet."""
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)  # strip block comments
    if lang_key == "python3":
        from local.harness.typespec import parse_python_snippet
        sig = parse_python_snippet(code)
        assert isinstance(sig, PlainSig)
        return {"class_name": sig.class_name, "method_name": sig.method_name}
    if lang_key in ("cpp", "java", "csharp"):
        m = (_CPP_METHOD_RE.search(code) if lang_key == "cpp" else
             _JAVA_METHOD_RE.search(code) if lang_key == "java" else
             _CSHARP_METHOD_RE.search(code))
        assert m, f"no method found in {lang_key} snippet: {code[:120]}"
        entry = {"class_name": "Solution", "method_name": m.group(2)}
        ptypes = []
        for a in m.group(3).split(","):
            a = a.strip()
            if not a:
                continue
            # type = everything before the LAST whitespace token; name = last token
            parts_ = a.rsplit(None, 1)
            assert len(parts_) == 2, f"cannot parse {lang_key} param {a!r} in {code[:120]}"
            ptypes.append(parts_[0].replace("&", "").strip())
        entry["param_types"] = ptypes
        entry["ret_type"] = m.group(1)
        return entry
    if lang_key == "golang":
        m = re.search(r"func\s+(\w+)\s*\(([^)]*)\)\s*([\w\[\]<>]+)?", code)
        assert m, f"no func found in golang snippet: {code[:120]}"
        entry = {"class_name": None, "method_name": m.group(1)}
        ptypes = []
        for a in m.group(2).split(","):
            a = a.strip()
            if not a:
                continue
            am = re.match(r"^(\w+)\s+([\w\[\]]+)$", a)
            assert am, f"cannot parse golang param {a!r} in {code[:120]}"
            ptypes.append(am.group(2))
        entry["param_types"] = ptypes
        entry["ret_type"] = (m.group(3) or "").strip()
        return entry
    if lang_key == "javascript":
        m = _JS_VAR_RE.search(code)
        assert m, f"no var function found in javascript snippet: {code[:120]}"
        return {"class_name": None, "method_name": m.group(1)}
    if lang_key == "rust":
        m = re.search(
            r"impl\s+\w+\s*{\s*pub\s+fn\s+(\w+)\s*\(([^)]*)\)(?:\s*->\s*([^;{]+))?", code)
        assert m, f"no fn found in rust snippet: {code[:120]}"
        entry = {"class_name": "Solution", "method_name": m.group(1)}
        rust_params = []
        for a in m.group(2).split(","):
            a = a.strip()
            if not a:
                continue
            am = re.match(r"^(\w+)\s*:\s*(.+)$", a)
            assert am, f"cannot parse rust param {a!r} in {code[:120]}"
            rust_params.append((am.group(1), am.group(2).strip()))
        entry["rust_params"] = rust_params
        entry["rust_ret"] = (m.group(3) or "").strip()
        return entry
    if lang_key == "c":
        m = _C_FUNC_RE.search(code)
        assert m, f"no function found in C snippet: {code[:120]}"
        ctype, name, args = m.groups()
        params = []
        for a in args.split(","):
            a = a.strip()
            if not a:
                continue
            am = re.match(r"^([A-Za-z_][A-Za-z0-9_ *]+?)\s+(\w+)$", a)
            assert am, f"cannot parse C param {a!r} in {code[:120]}"
            params.append(CParam(am.group(1), am.group(2)))
        return {"class_name": None, "method_name": name, "c_ret": ctype.strip(),
                "c_params": params}
    raise ValueError(f"unknown lang {lang_key}")


# --------------------------------------------------------------------------
# Value literal rendering (per language, driven by TypeSpec)
# --------------------------------------------------------------------------

def _py_repr(v: Any, t: Type = None) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    return repr(v)


def _cpp_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return "{" + ", ".join(_cpp_val(x, t.inner) for x in v) + "}"
    if isinstance(t, Str):
        return f'string("{_esc(v)}")'
    if isinstance(t, Bool):
        return "true" if v else "false"
    return repr(v)


def _java_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return "new " + _java_array_type(t) + "{" + ", ".join(
            _java_val(x, t.inner) for x in v) + "}"
    if isinstance(t, Str):
        return f'"{_esc(v)}"'
    if isinstance(t, Bool):
        return "true" if v else "false"
    if isinstance(t, Float):
        return repr(float(v))
    return repr(v)


def _java_array_type(t: Type) -> str:
    if isinstance(t, ListT):
        return _java_array_type(t.inner) + "[]"
    base = {"Int": "int", "Str": "String", "Float": "double", "Bool": "boolean"}[
        type(t).__name__]
    return base


def _cs_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return "new " + _cs_array_type(t) + "{" + ", ".join(
            _cs_val(x, t.inner) for x in v) + "}"
    if isinstance(t, Str):
        return f'"{_esc(v)}"'
    if isinstance(t, Bool):
        return "true" if v else "false"
    if isinstance(t, Float):
        return repr(float(v))
    return repr(v)


def _cs_array_type(t: Type) -> str:
    if isinstance(t, ListT):
        return _cs_array_type(t.inner) + "[]"
    base = {"Int": "int", "Str": "string", "Float": "double", "Bool": "bool"}[
        type(t).__name__]
    return base


def _go_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return _go_array_type(t) + "{" + ", ".join(
            _go_val(x, t.inner) for x in v) + "}"
    if isinstance(t, Str):
        return f'"{_esc(v)}"'
    if isinstance(t, Bool):
        return "true" if v else "false"
    if isinstance(t, Float):
        return repr(float(v))
    return repr(v)


def _go_array_type(t: Type) -> str:
    if isinstance(t, ListT):
        return "[]" + _go_array_type(t.inner)
    base = {"Int": "int", "Str": "string", "Float": "float64", "Bool": "bool"}[
        type(t).__name__]
    return base


def _js_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return "[" + ", ".join(_js_val(x, t.inner) for x in v) + "]"
    if isinstance(t, Str):
        return json.dumps(v)
    if isinstance(t, Bool):
        return "true" if v else "false"
    return repr(v)


def _rust_val(v: Any, t: Type) -> str:
    if isinstance(t, ListT):
        assert isinstance(v, list), f"value {v!r} not list for {t}"
        return "vec![" + ", ".join(_rust_val(x, t.inner) for x in v) + "]"
    if isinstance(t, Str):
        return f'String::from("{_esc(v, rust=True)}")'
    if isinstance(t, Float):
        return f"{float(v)}f64"
    if isinstance(t, Bool):
        return "true" if v else "false"
    return f"{v}i32"


def _arg_expr(lang_key: str, entry: dict, sig: PlainSig, j: int, v: Any) -> str:
    """Render one argument, preferring the language's actual declared param type."""
    ptypes = entry.get("param_types")
    if ptypes and j < len(ptypes):
        ptype = ptypes[j]
        if lang_key == "java":
            if ptype.startswith("List<"):
                return _java_list_val(v, ptype)
            if ptype == "char":
                return f"'{_esc_char(v)}'"
            if ptype == "long":
                return f"{int(v)}L"
        if lang_key == "csharp":
            if ptype.startswith("IList<"):
                return _cs_list_val(v, ptype)
            if ptype == "char":
                return f"'{_esc_char(v)}'"
            if ptype == "long":
                return f"{int(v)}L"
        if lang_key == "cpp" and ptype == "char":
            return f"'{_esc_char(v)}'"
        if lang_key == "golang" and ptype == "byte":
            return f"'{_esc_char(v)}'"
    return value_expr(lang_key, v, sig.params[j].typ)


def _ret_expr(lang_key: str, entry: dict, v: Any, t: Type) -> str:
    """Render an expected value with the language's actual return type (long suffix)."""
    rt = entry.get("ret_type") or ""
    if rt == "long" and lang_key in ("java", "csharp") and isinstance(v, (int, float)):
        return f"{int(v)}L"
    if rt in ("long long", "long") and lang_key == "cpp" and isinstance(v, (int, float)):
        return f"{int(v)}LL"
    return value_expr(lang_key, v, t)


def _cpp_decl_type(ptype: str) -> str:
    """C++ declared type from the snippet's actual param type string."""
    ptype = ptype.strip()
    if ptype.startswith("vector<"):
        return ptype.replace("vector<", "vector<")
    if ptype.startswith("string"):
        return "string"
    return ptype  # int / long / long long / double / bool / char


def _cpp_type(t: Type) -> str:
    if isinstance(t, ListT):
        return f"vector<{_cpp_type(t.inner)}>"
    return {"Int": "int", "Str": "string", "Float": "double", "Bool": "bool"}[
        type(t).__name__]


_STR_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r",
                "\t": "\\t", "\b": "\\b", "\f": "\\f", "\0": "\\0"}
_CHAR_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\r": "\\r",
                 "\t": "\\t", "\b": "\\b", "\f": "\\f", "\0": "\\0"}


def _esc(s: str, single: bool = False, rust: bool = False) -> str:
    """Escape a Python string for embedding in a target-language literal.

    `single` selects single-quote (char literal) escaping, which must escape `'`
    and must NOT escape `"`. `rust` selects Rust's `\\u{XXXX}` form instead of
    the `\\uXXXX` universal-character-name form used by C/C++/Java/C#/Go.

    The previous version escaped neither `'` nor `\\r`: a `'` char value became
    `'''` (a syntax error in all 6 char-capable languages) and a CR was injected
    raw into the literal.
    """
    if s is None:
        raise ValueError("None value rendered as string literal")
    table = _CHAR_ESCAPES if single else _STR_ESCAPES
    out: list[str] = []
    for ch in s:
        if ch in table:
            out.append(table[ch])
        elif ord(ch) < 0x20:
            out.append("\\u{%04x}" % ord(ch) if rust else "\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _esc_char(s: str, rust: bool = False) -> str:
    """Escape a single character for a single-quoted char literal."""
    if not isinstance(s, str) or len(s) != 1:
        raise ValueError(f"char value must be a 1-char string, got {s!r}")
    return _esc(s, single=True, rust=rust)


def _java_list_val(v: Any, elem_ptype: str) -> str:
    """Render a List<T> literal for Java (Arrays.asList, usable as List<T>)."""
    inner = elem_ptype[elem_ptype.index("List<") + 5:-1] if "List<" in elem_ptype else None
    if inner and "List<" in inner:
        return "Arrays.asList(" + ", ".join(_java_list_val(x, inner) for x in v) + ")"
    # elements are scalars
    return "Arrays.asList(" + ", ".join(
        repr(x) if not isinstance(x, str) else f'"{_esc(x)}"' for x in v) + ")"


def _cs_list_val(v: Any, elem_ptype: str) -> str:
    """Render an IList<T> literal for C# (new List<T>{...})."""
    inner = elem_ptype[elem_ptype.index("IList<") + 6:-1] if "IList<" in elem_ptype else None
    if inner and "IList<" in inner:
        rows = ", ".join(_cs_list_val(x, inner) for x in v)
        return f"new List<{_cs_ilist_name(elem_ptype)}>{{{rows}}}"
    # elements are scalars
    return "new List<" + _cs_ilist_name(elem_ptype) + ">{" + ", ".join(
        repr(x) if not isinstance(x, str) else f'"{_esc(x)}"' for x in v) + "}"


def _cs_ilist_name(ptype: str) -> str:
    """Strip the whole outer IList<>: 'IList<IList<int>>' -> 'IList<int>',
    'IList<int>' -> 'int'. Callers wrap it in 'new List<...>'."""
    if ptype.startswith("IList<"):
        return ptype[6:-1]
    return ptype


def value_expr(lang_key: str, v: Any, t: Type) -> str:
    fn = {
        "python3": _py_repr,
        "cpp": _cpp_val,
        "java": _java_val,
        "csharp": _cs_val,
        "golang": _go_val,
        "javascript": _js_val,
        "rust": _rust_val,
    }[lang_key]
    return fn(v, t)


# --------------------------------------------------------------------------
# Comparison helpers
# --------------------------------------------------------------------------

def _cmp_fn(lang_key: str) -> str:
    return {
        "python3": "_eqv",
        "cpp": "eqv",
        "java": "_Eqv.eqv",
        "csharp": "_Eqv.Eqv",
        "golang": "eqv",
        "javascript": "eqv",
    }[lang_key]


# --- Rust: generated per-problem recursive compare ------------------------

def _rust_leaf(t: Type) -> str:
    return {"Int": "i32", "Str": "String", "Bool": "bool", "Float": "f64"}[
        type(t).__name__]


def _rust_type_name(t: Type) -> str:
    if isinstance(t, ListT):
        return f"Vec<{_rust_type_name(t.inner)}>"
    return _rust_leaf(t)


# --- Rust: actual-snippet-type-driven rendering (i64/char differ from TypeSpec) ---

def _rust_val_typed(v: Any, rt: str) -> str:
    rt = rt.strip()
    if rt.startswith("Vec<"):
        inner = rt[4:-1]
        return "vec![" + ", ".join(_rust_val_typed(x, inner) for x in v) + "]"
    if rt == "String":
        return f'String::from("{_esc(v, rust=True)}")'
    if rt == "char":
        return f"'{_esc_char(v, rust=True)}'"
    if rt == "bool":
        return "true" if v else "false"
    if rt == "f64":
        return f"{float(v)}f64"
    if rt == "i64":
        return f"{v}i64"
    return f"{v}i32"


def _rust_leaf_typed(rt: str) -> str:
    return rt  # i32 / i64 / f64 / String / bool / char


def _rust_fn_id(rt: str) -> str:
    return rt.replace("<", "_").replace(">", "").replace(",", "_")


def rust_eqv_fns_typed(rt: str) -> str:
    out: list[str] = []
    _rust_eqv_typed_rec(rt, out)
    return "\n".join(out)


def _rust_eqv_typed_rec(rt: str, out: list[str]) -> None:
    if not rt.startswith("Vec<"):
        return
    inner = rt[4:-1].strip()
    if inner.startswith("Vec<"):
        inner_fn = f"eqv_{_rust_fn_id(inner)}"
        out.append(
            f"fn eqv_{_rust_fn_id(rt)}(a: &{rt}, b: &{rt}) -> bool {{\n"
            f"    if a.len() != b.len() {{ return false; }}\n"
            f"    if !ROWS_UNORDERED {{\n"
            f"        return a.iter().zip(b.iter()).all(|(g, e)| {inner_fn}(g, e));\n"
            f"    }}\n"
            f"    let mut used = vec![false; a.len()];\n"
            f"    for e in b {{\n"
            f"        let mut found = false;\n"
            f"        for (j, g) in a.iter().enumerate() {{\n"
            f"            if !used[j] && {inner_fn}(g, e) {{ used[j] = true; found = true; break; }}\n"
            f"        }}\n"
            f"        if !found {{ return false; }}\n"
            f"    }}\n"
            f"    true\n"
            f"}}")
    elif inner == "f64":
        out.append(
            f"fn eqv_{_rust_fn_id(rt)}(a: &{rt}, b: &{rt}) -> bool {{\n"
            f"    a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| (x - y).abs() < 1e-6)\n"
            f"}}")
    else:
        out.append(
            f"fn eqv_{_rust_fn_id(rt)}(a: &{rt}, b: &{rt}) -> bool {{\n"
            f"    if a.len() != b.len() {{ return false; }}\n"
            f"    if !INNER_UNORDERED {{\n"
            f"        return a.iter().zip(b.iter()).all(|(x, y)| x == y);\n"
            f"    }}\n"
            f"    let mut used = vec![false; a.len()];\n"
            f"    for y in b {{\n"
            f"        let mut found = false;\n"
            f"        for (j, x) in a.iter().enumerate() {{\n"
            f"            if !used[j] && x == y {{ used[j] = true; found = true; break; }}\n"
            f"        }}\n"
            f"        if !found {{ return false; }}\n"
            f"    }}\n"
            f"    true\n"
            f"}}")
    _rust_eqv_typed_rec(inner, out)


def _rust_cmp_typed(a: str, b: str, rt: str) -> str:
    rt = rt.strip()
    if rt.startswith("Vec<"):
        return f"eqv_{_rust_fn_id(rt)}(&{a}, &{b})"
    if rt == "f64":
        return f"({a} - {b}).abs() < 1e-6"
    return f"{a} == {b}"


def rust_eqv_fns(ret: Type) -> str:
    """Generate recursive eqv_* helper functions for the return type."""
    out: list[str] = []
    _rust_eqv_rec(ret, out)
    return "\n".join(out)


def _rust_eqv_rec(t: Type, out: list[str]) -> None:
    if not isinstance(t, ListT):
        return
    inner = t.inner
    fn_id = _rust_type_name(t).replace('<', '_').replace('>', '').replace(',', '_')
    tn = _rust_type_name(t)
    if isinstance(inner, ListT):
        inner_fn = f"eqv_{_rust_type_name(inner).replace('<', '_').replace('>', '').replace(',', '_')}"
        out.append(
            f"fn eqv_{fn_id}(a: &{tn}, b: &{tn}) -> bool {{\n"
            f"    if a.len() != b.len() {{ return false; }}\n"
            f"    if !ROWS_UNORDERED {{\n"
            f"        return a.iter().zip(b.iter()).all(|(g, e)| {inner_fn}(g, e));\n"
            f"    }}\n"
            f"    let mut used = vec![false; a.len()];\n"
            f"    for e in b {{\n"
            f"        let mut found = false;\n"
            f"        for (j, g) in a.iter().enumerate() {{\n"
            f"            if !used[j] && {inner_fn}(g, e) {{ used[j] = true; found = true; break; }}\n"
            f"        }}\n"
            f"        if !found {{ return false; }}\n"
            f"    }}\n"
            f"    true\n"
            f"}}")
    elif isinstance(inner, Float):
        out.append(
            f"fn eqv_{fn_id}(a: &{tn}, b: &{tn}) -> bool {{\n"
            f"    a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| (x - y).abs() < 1e-6)\n"
            f"}}")
    else:
        out.append(
            f"fn eqv_{fn_id}(a: &{tn}, b: &{tn}) -> bool {{\n"
            f"    if a.len() != b.len() {{ return false; }}\n"
            f"    if !INNER_UNORDERED {{\n"
            f"        return a.iter().zip(b.iter()).all(|(x, y)| x == y);\n"
            f"    }}\n"
            f"    let mut used = vec![false; a.len()];\n"
            f"    for y in b {{\n"
            f"        let mut found = false;\n"
            f"        for (j, x) in a.iter().enumerate() {{\n"
            f"            if !used[j] && x == y {{ used[j] = true; found = true; break; }}\n"
            f"        }}\n"
            f"        if !found {{ return false; }}\n"
            f"    }}\n"
            f"    true\n"
            f"}}")
    _rust_eqv_rec(inner, out)


def _rust_cmp(a: str, b: str, t: Type) -> str:
    if isinstance(t, ListT):
        fn = f"eqv_{_rust_type_name(t).replace('<', '_').replace('>', '').replace(',', '_')}"
        return f"{fn}(&{a}, &{b})"
    if isinstance(t, Float):
        return f"({a} - {b}).abs() < 1e-6"
    return f"{a} == {b}"


# --------------------------------------------------------------------------
# C-specific rendering (signature-driven)
# --------------------------------------------------------------------------

def _c_scalar_literal(v: Any, ctype: str) -> str:
    base = ctype.replace("unsigned", "").replace("const", "").strip()
    if base == "char":
        return f"'{_esc_char(v)}'" if isinstance(v, str) else repr(v)
    if base in ("long long", "long", "int"):
        return str(int(v))
    if base in ("double", "float"):
        return repr(float(v))
    if base == "bool":
        return "true" if v else "false"
    raise ValueError(f"unsupported C scalar type {ctype!r}")


def render_c_arguments(entry: dict, args: dict[str, Any], qid: int = 0):
    """Input and out-parameter declarations shared by both C protocols."""
    c_params = entry["c_params"]
    decls: list[str] = []
    call_args: list[str] = []
    for cp in c_params:
        if cp.is_out:
            if cp.ctype.endswith("**"):
                decls.append(f"    int* {cp.name} = NULL;")
                call_args.append(f"&{cp.name}")
            else:
                decls.append(f"    int {cp.name} = 0;")
                call_args.append(f"&{cp.name}")
            continue
        if cp.is_ptr:
            val = args.get(cp.name)
            if cp.ctype == "int*":
                if val is None:
                    # column-sizes array derived from the rows param (e.g. arraysColSize)
                    prefix = re.sub(r"ColSize$", "", cp.name)
                    rows = args.get(prefix)
                    assert rows is not None, \
                        f"qid {qid}: cannot derive C param {cp.name} (no {prefix!r} in args)"
                    val = [len(r) for r in rows]
                assert isinstance(val, list), f"qid {qid}: C param {cp.name} needs list, got {val!r}"
                decls.append(f"    int {cp.name}[] = {{{', '.join(str(int(x)) for x in val)}}};")
                call_args.append(cp.name)
            elif cp.ctype == "int**":
                assert isinstance(val, list) and all(isinstance(r, list) for r in val), \
                    f"qid {qid}: C param {cp.name} needs list-of-lists"
                rows = ", ".join(
                    "(int[]){" + ", ".join(str(int(x)) for x in r) + "}" for r in val)
                decls.append(f"    int* {cp.name}[] = {{{rows}}};")
                call_args.append(cp.name)
            elif cp.ctype in ("char*", "const char*"):
                assert isinstance(val, str), f"qid {qid}: C param {cp.name} needs str"
                # Writable copy, matching LeetCode's harness. Binding the input
                # to a read-only literal made in-place solutions crash (SIGSEGV)
                # and would not convert to a `char*` parameter either.
                decls.append(f'    char {cp.name}_buf[] = "{_esc(val)}";')
                decls.append(f"    char* {cp.name} = {cp.name}_buf;")
                call_args.append(cp.name)
            elif cp.ctype in ("char**", "const char**"):
                assert isinstance(val, list) and all(isinstance(s, str) for s in val), \
                    f"qid {qid}: C param {cp.name} needs list-of-str"
                for i, s in enumerate(val):
                    decls.append(f'    char {cp.name}_{i}[] = "{_esc(s)}";')
                items = ", ".join(f"{cp.name}_{i}" for i in range(len(val))) or "NULL"
                decls.append(f"    char* {cp.name}[] = {{{items}}};")
                call_args.append(cp.name)
            else:
                raise ValueError(f"qid {qid}: unsupported C ptr type {cp.ctype!r}")
        else:
            if cp.name in args:
                decls.append(f"    {cp.ctype} {cp.name} = {_c_scalar_literal(args[cp.name], cp.ctype)};")
                call_args.append(cp.name)
            else:
                # size param: derive from the array param with matching prefix
                prefix = re.sub(r"(Size|Len|Count|Cols|ColSize|ColumnSize)$", "", cp.name)
                src = args.get(prefix)
                assert src is not None, \
                    f"qid {qid}: cannot derive size param {cp.name} (no {prefix!r} in args)"
                decls.append(f"    int {cp.name} = {len(src)};")
                call_args.append(cp.name)
    return decls, call_args


def render_c_case(qid: int, entry: dict, args: dict[str, Any],
                  expected: Any) -> str:
    """Render one C case block (decls + call + compare + limit check)."""
    c_params = entry["c_params"]
    c_ret = entry["c_ret"]
    decls, call_args = render_c_arguments(entry, args, qid)
    # The void check must come first: _c_expected_and_compare raises on "void",
    # so calling it unconditionally made every void-returning C solution a
    # Compile Error before the branch below could be reached.
    call = f"{entry['method_name']}({', '.join(call_args)})"
    if c_ret == "void":
        exp_decl, cmp = "", ""
        call_line = f"    {call};"
    elif validators.has_validator(qid) and c_ret in ("int*", "int**"):
        # 谓词校验：不比对该返回哪个数组，只判断它是否合法（见 validators.py）。
        # 参数直接用 **call_args**（传给用户方法的实参）——它对标量是 `n`，
        # 对数组是 `nums, numsSize`，正好覆盖 q1304/q922/q1317/q2610 三种形态。
        # 早先只挑"非指针标量"，于是需要输入数组的题（q922）拿不到数组。
        size_p = next((cp.name for cp in c_params
                       if cp.is_out and cp.ctype == "int*"), "returnSize")
        # call_args 里也含 **out 参数**（`&returnSize` 之类），校验器不该收到它们
        # ——否则 `_valid(_got, returnSize, n, &returnSize)` 参数过多。
        out_names = {cp.name for cp in c_params if cp.is_out}
        val_args = [a for a in call_args if a.strip("&") not in out_names]
        # **快照**：C 的参数是原始数组，提交能原地改写它。校验器必须拿到
        # 调用前的副本，否则被改过的输入会当自己的证据（见 validators.SNAPSHOT）。
        # 做法是用**同一份初始值**再声明一个数组 —— decls 里已有字面量，
        # 这里把 `T name[] = {...}` 复制一份改成 `_sN`。
        snap_decls = []
        for a in val_args:
            for d in decls:
                if re.search(rf"\b{re.escape(a)}\[\]\s*=", d):
                    snap_decls.append(re.sub(rf"\b{re.escape(a)}\[\]",
                                             f"_s_{a}[]", d, count=1))
                elif re.search(rf"\b{re.escape(a)}\s*=", d) and \
                        re.search(r"\b(int|long long|double|bool|char)\b", d):
                    # 标量：不可变，直接复制一份
                    snap_decls.append(re.sub(rf"\b{re.escape(a)}\s*=",
                                             f"_s_{a} =", d, count=1))
        if snap_decls:
            decls = decls + snap_decls
            val_args = [f"_s_{a}" if any(f"_s_{a} " in x or f"_s_{a}[" in x
                                         or f"_s_{a}=" in x for x in snap_decls)
                        else a for a in val_args]
        exp_decl = ""
        if c_ret == "int**":
            # 二维返回：长度在 returnSize，每行长度在 returnColumnSizes
            col_p = next((cp.name for cp in c_params
                          if cp.is_out and cp.ctype == "int**"), "returnColumnSizes")
            cmp = (f'    if (!_valid(_got, {size_p}, {col_p}, '
                   f'{", ".join(val_args)})) '
                   f'{{ printf("FAIL %d\\n", idx); return 3; }}')
        else:
            cmp = (f'    if (!_valid(_got, {size_p}, {", ".join(val_args)})) '
                   f'{{ printf("FAIL %d\\n", idx); return 3; }}')
        call_line = f"    {c_ret} _got = {call};"
    else:
        exp_decl, cmp = _c_expected_and_compare(c_ret, expected, qid)
        call_line = f"    {c_ret} _got = {call};"
    return (
        "    {\n"
        + "\n".join(decls) + "\n"
        + exp_decl + "\n"
        + call_line + "\n"
        + (cmp + "\n" if cmp else "")
        + "        idx++;\n"
        + '        if (++total >= limit) { printf("OK\\n"); return 42; }\n'
        "    }\n"
    )


def _c_expected_and_compare(c_ret: str, expected: Any,
                            qid: int = 0) -> tuple[str, str]:
    base = c_ret.replace("unsigned", "").replace("const", "").strip()
    if base in ("int", "long", "long long", "double", "float", "bool", "char"):
        lit = _c_scalar_literal(expected, base)
        decl = f"    {c_ret} _exp = {lit};"
        if base in ("double", "float"):
            cmp = '    if (fabs(_got - _exp) > 1e-6) { printf("FAIL %d\\n", idx); return 3; }'
        else:
            cmp = '    if (_got != _exp) { printf("FAIL %d\\n", idx); return 3; }'
        return decl, cmp
    if base == "char*":
        decl = f'    const char* _exp = "{_esc(expected)}";'
        cmp = '    if (strcmp(_got, _exp) != 0) { printf("FAIL %d\\n", idx); return 3; }'
        return decl, cmp
    if base == "int*":
        n = len(expected)
        items = ", ".join(str(int(x)) for x in expected) if n else "0"
        decl = f"    int _exp[{max(n, 1)}] = {{{items}}};"
        cmp = (
            f'    if (returnSize != {n}) {{ printf("FAIL %d\\n", idx); return 3; }}\n'
            f'    for (int _i = 0; _i < {n}; _i++) if (_got[_i] != _exp[_i]) {{ printf("FAIL %d\\n", idx); return 3; }}'
        )
        return decl, cmp
    if base == "char**":
        items = ", ".join(f'"{_esc(s)}"' for s in expected) if expected else "0"
        n = len(expected)
        decl = f"    const char* _exp[{max(n, 1)}] = {{{items}}};"
        cmp = (
            f'    if (returnSize != {n}) {{ printf("FAIL %d\\n", idx); return 3; }}\n'
            f'    for (int _i = 0; _i < {n}; _i++) if (strcmp(_got[_i], _exp[_i]) != 0) {{ printf("FAIL %d\\n", idx); return 3; }}'
        )
        return decl, cmp
    if base == "int**":
        n = len(expected)
        if n:
            rows = ", ".join(
                "(int[]){" + ", ".join(str(int(x)) for x in r) + "}" for r in expected)
            cols = ", ".join(str(len(r)) for r in expected)
        else:
            rows, cols = "0", "0"
        decl = (
            f"    int* _exp[{max(n, 1)}] = {{{rows}}};\n"
            f"    int _expCols[{max(n, 1)}] = {{{cols}}};"
        )
        rows_unordered, inner_unordered = _MODE_FLAGS[list_result_mode(qid)]
        fail = 'printf("FAIL %d\\n", idx); return 3;'
        if not rows_unordered:
            # q2225-style: rows and their contents must both be in order.
            return decl, (
                f'    if (returnSize != {n}) {{ {fail} }}\n'
                f"    for (int _i = 0; _i < {n}; _i++) {{\n"
                f'        if (returnColumnSizes[_i] != _expCols[_i]) {{ {fail} }}\n'
                f"        for (int _k = 0; _k < _expCols[_i]; _k++)\n"
                f'            if (_got[_i][_k] != _exp[_i][_k]) {{ {fail} }}\n'
                f"    }}"
            )
        if inner_unordered:
            # q2610-style: rows match as a multiset, and so do their contents.
            return decl, (
                f'    if (returnSize != {n}) {{ {fail} }}\n'
                f"    int _used[{max(n, 1)}] = {{0}};\n"
                f"    for (int _ei = 0; _ei < {n}; _ei++) {{\n"
                f"        int _found = 0;\n"
                f"        for (int _gj = 0; _gj < {n}; _gj++) {{\n"
                f"            if (_used[_gj] || returnColumnSizes[_gj] != _expCols[_ei]) continue;\n"
                f"            int _rc = returnColumnSizes[_gj] ? returnColumnSizes[_gj] : 1;\n"
                f"            int _rowused[_rc];\n"
                f"            for (int _z = 0; _z < _rc; _z++) _rowused[_z] = 0;\n"
                f"            int _ok = 1;\n"
                f"            for (int _k = 0; _k < _expCols[_ei]; _k++) {{\n"
                f"                int _f2 = 0;\n"
                f"                for (int _l = 0; _l < returnColumnSizes[_gj]; _l++) {{\n"
                f"                    if (!_rowused[_l] && _got[_gj][_l] == _exp[_ei][_k]) {{ _rowused[_l] = 1; _f2 = 1; break; }}\n"
                f"                }}\n"
                f"                if (!_f2) {{ _ok = 0; break; }}\n"
                f"            }}\n"
                f"            if (_ok) {{ _used[_gj] = 1; _found = 1; break; }}\n"
                f"        }}\n"
                f'        if (!_found) {{ {fail} }}\n'
                f"    }}"
            )
        # default: rows as a multiset, each row compared in order
        return decl, (
            f'    if (returnSize != {n}) {{ {fail} }}\n'
            f"    int _used[{max(n, 1)}] = {{0}};\n"
            f"    for (int _ei = 0; _ei < {n}; _ei++) {{\n"
            f"        int _found = 0;\n"
            f"        for (int _gj = 0; _gj < {n}; _gj++) {{\n"
            f"            if (_used[_gj] || returnColumnSizes[_gj] != _expCols[_ei]) continue;\n"
            f"            int _ok = 1;\n"
            f"            for (int _k = 0; _k < _expCols[_ei]; _k++) if (_got[_gj][_k] != _exp[_ei][_k]) {{ _ok = 0; break; }}\n"
            f"            if (_ok) {{ _used[_gj] = 1; _found = 1; break; }}\n"
            f"        }}\n"
            f'        if (!_found) {{ {fail} }}\n'
            f"    }}"
        )
    raise ValueError(f"unsupported C return type {c_ret!r}")


# --------------------------------------------------------------------------
# Driver assembly (plain problems)
# --------------------------------------------------------------------------

# LeetCode's Python runner pre-imports a standard module set; solutions (and the
# models we evaluate) rely on it. Replicate it faithfully. Note: bisect's star
# import comes BEFORE the module import so `bisect.bisect_left` keeps working
# (the star import exports a same-named function that would otherwise shadow it).
_LEETCODE_PY_IMPORTS = (
    "import random\n"
    "import functools\n"
    "import collections\n"
    "import string\n"
    "import math\n"
    "import datetime\n"
    "import itertools\n"
    "import heapq\n"
    "import re\n"
    "import operator\n"
    "from typing import *\n"
    "from functools import *\n"
    "from collections import *\n"
    "from itertools import *\n"
    "from heapq import *\n"
    "from bisect import *\n"
    "from string import *\n"
    "from operator import *\n"
    "from math import *\n"
    "from builtins import pow\n"
    "import bisect\n"
    # NOTE: `from math import *` / `from operator import *` shadow the builtin
    # 3-arg pow() with 2-arg variants; `from builtins import pow` restores it.
    # `import bisect` comes last so `bisect.bisect_left` works despite the
    # same-named function exported by the star import.
    #
    # 这里曾加过 `import copy`，注释说"校验器用 deepcopy 保存输入快照"——
    # **注释与实现不符**：快照的实际机制是"复用输入声明、让字面量重新求值"
    # （见 validators.snapshot_decls），deepcopy 从未被调用。审查代理 A-010 指出
    # 这种残留会让维护者误判 checker 的实参来源，故移除。
)

PRELUDE = {
    "python3": _LEETCODE_PY_IMPORTS + "import sys as _sys\n",
    # LeetCode's C++ runner pre-includes a broad STL set; our references rely on it.
    "cpp": (
        "#include <vector>\n#include <string>\n#include <cstdio>\n#include <cmath>\n"
        "#include <cstdlib>\n#include <cstring>\n#include <algorithm>\n#include <numeric>\n"
        "#include <map>\n#include <unordered_map>\n#include <set>\n#include <unordered_set>\n"
        "#include <queue>\n#include <stack>\n#include <deque>\n#include <functional>\n"
        "#include <limits>\n#include <climits>\n#include <memory>\n#include <iterator>\n#include <regex>\n"
        "#include <iomanip>\n#include <sstream>\n#include <iostream>\n"
        "using namespace std;\n"
    ),
    "java": "import java.util.*;\nimport java.math.*;\n",
    "csharp": "using System;\nusing System.Collections.Generic;\nusing System.Linq;\nusing System.Text;\n",
    "golang": 'package main\n\nIMPORT_BLOCK\n',
    "javascript": "",
    "rust": "#[allow(dead_code)]\nstruct Solution;\n",
    # LeetCode's C runner pre-includes these (including uthash for hash tables).
    #
    # ctype.h 是必须的：`toupper`/`tolower`/`isdigit` 极其常用，而参考解里就有
    # 没写 `#include <ctype.h>` 直接用的（q2129、q2288）。以前靠 GCC 的隐式声明
    # 警告才编过；一旦打开 `-Werror=implicit-function-declaration`（对齐 GCC 14 /
    # LeetCode 的口径），它们就会 CE。LeetCode 必然提供这个头文件，否则任何用
    # isdigit 的 C 解法都无法提交。
    "c": ("#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n"
          "#include <math.h>\n#include <stdbool.h>\n#include <limits.h>\n#include <stdint.h>\n"
          "#include <ctype.h>\n#include <uthash.h>\n"),
}

_GO_DRIVER_PKGS = ['"fmt"', '"os"', '"reflect"', '"math"', '"strconv"']
_GO_USER_PKG_MARKERS = [
    ('"sort"', "sort."), ('"strings"', "strings."), ('"strconv"', "strconv."),
    ('"math"', "math."), ('"container/heap"', "heap."), ('"regexp"', "regexp."),
    ('"slices"', "slices."), ('"bytes"', "bytes."), ('"unicode"', "unicode."),
    ('"container/list"', "list."),
]


def _norm_go_import_spec(line: str) -> str | None:
    """Normalise one Go import spec line to `[alias] "path"`, or None."""
    line = line.split("//")[0].strip()
    if not line:
        return None
    m = re.fullmatch(r'(?:([\w.]+)[ \t]+)?"([^"]+)"', line)
    if not m:
        return None
    alias, path = m.group(1), m.group(2)
    return f'{alias} "{path}"' if alias else f'"{path}"'


def harvest_go_imports(code: str) -> list[str]:
    """Collect the import specs from a Go source's own import declarations.

    Must be called on the code BEFORE clean_go_user_code() strips them. Needed
    because the marker heuristic in go_import_block() can only recover the ten
    packages listed in _GO_USER_PKG_MARKERS; anything else (math/big,
    math/rand, unicode/utf8, container/list-plus, ...) used to vanish and break
    compilation.
    """
    specs: list[str] = []
    for m in re.finditer(r"^[ \t]*import[ \t]*\(([^)]*)\)", code, re.M | re.S):
        for line in m.group(1).splitlines():
            for statement in line.split(';'):
                spec = _norm_go_import_spec(statement)
                if spec:
                    specs.append(spec)
    for m in re.finditer(r"^[ \t]*import[ \t]+(.+)$", code, re.M):
        spec = _norm_go_import_spec(m.group(1))
        if spec:
            specs.append(spec)
    out: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        path = spec.split('"')[1]
        if path not in seen:
            seen.add(path)
            out.append(spec)
    return out


def go_import_block(user_code: str, harvested: list[str] | None = None,
                    extra: list[str] | None = None) -> str:
    """Build the Go import block: driver packages + the user's own imports.

    Harvested specs (read from the declarations before they were stripped) are
    authoritative. The substring-marker heuristic is only a fallback: it also
    fires on `sort.` inside a comment or string literal, and an unused import is
    itself a Go compile error.

    `extra` 是**校验器**需要的包（见 validators.GO_IMPORTS）。必须按需加：
    Go 里未使用的 import 是编译错误，所以不能无条件塞进去。
    """
    pkgs: list[str] = list(_GO_DRIVER_PKGS)
    have = {p.split('"')[1] for p in pkgs}
    for name in (extra or []):
        if name not in have:
            have.add(name)
            pkgs.append(f'"{name}"')
    if harvested:
        for spec in harvested:
            path = spec.split('"')[1]
            if path not in have:
                have.add(path)
                pkgs.append(spec)
    else:
        for pkg, marker in _GO_USER_PKG_MARKERS:
            if marker in user_code and pkg.split('"')[1] not in have:
                have.add(pkg.split('"')[1])
                pkgs.append(pkg)
    return "import (\n" + "".join(f"\t{pkg}\n" for pkg in pkgs) + ")\n"


def hoist_java_imports(code: str) -> tuple[list[str], str]:
    """Java：把用户自带的 `import ...;` 提到文件最前面。

    合法 Java 源码里 `import` 必须出现在**任何类型声明之前**。而驱动把 prelude
    与 `class _Eqv {` 放在用户代码前面，于是用户自带的 import 落到 class 之后，
    javac 直接报：

        Judge.java:50: error: class, interface, enum, or record expected
            import java.util.*;

    **实测影响**（审查代理 C 报、主代理用真实 javac 对照实验确认）：
      - java 槽位里「提交自带 import」组 **26/26 = 100% 本地 Compile Error**
      - 「不带 import」组只有 8.2%
      - 同一份 q1366 参考解：无 import → Accepted；首行加一行 import → Compile Error
      - 当前基线 **12/59 个 false_wa（20%）** 因此是判题器假失败
        （java gpt-4o 10 + java qwen3-coder 1 + csharp gpt-4o 1）

    覆盖的形态（复核代理 C 的 N1 指出第一版漏了后三种，**尾随注释一种就足以复现**）：
      - 普通 / `static` import
      - **尾随行注释**：`import java.util.*;   // needed`
      - **CRLF 行尾**（复核实测 1093/1093 个 Java 提交在字节层含 CRLF；
        原先靠 `read_text()` 的通用换行翻译掩盖，但那不是我们能依赖的前提）
      - 一行多个 import（`import a.B; import c.D;`）
      - **不误删文本块内的行**：Java 文本块（`\"\"\" ... \"\"\"`）里若有一行恰好长得像
        `import x;`，把它移出去会**静默改变字符串内容**。所以先按 `\"\"\"` 切分，
        只在不含文本块的区段里匹配。
    """
    # 1) 先按 Java 文本块（"""）切分，只在**非文本块**的区段里摘 import。
    #    文本块里若有一行恰好长得像 `import x;`，把它移出去会静默改变字符串内容。
    parts = re.split(r'("""(?:.|\n)*?""")', code)
    imports: list[str] = []
    out_segs: list[str] = []
    for i, seg in enumerate(parts):
        if i % 2 == 1:                       # 文本块本体，原样保留
            out_segs.append(seg)
            continue
        kept: list[str] = []
        for line in seg.splitlines(keepends=True):
            # 该行含哪些 `import ...;`
            found = re.findall(
                r"import[ \t]+(?:static[ \t]+)?[A-Za-z_][\w.*]*[ \t]*;", line)
            # 判定"纯 import 行"：去掉行尾注释、再逐个移除匹配到的 import，
            # 剩下的必须只有空白或多余分号。这样
            #   `import a; import b;` -> 剩 " "         -> 纯
            #   `import a;;`          -> 剩 ";"          -> 纯（多余分号，javac 接受）
            #   `int x=1; import a;`  -> 剩 "int x=1; "  -> 不纯，不动
            rest = re.sub(r"//[^\r\n]*", "", line)
            for f in found:
                rest = rest.replace(f, "", 1)
            if found and not rest.strip().strip(";"):
                imports.extend(f.strip() for f in found)
                continue
            kept.append(line)
        out_segs.append("".join(kept))
    return imports, "".join(out_segs)


def clean_cs_user_code(code: str) -> tuple[list[str], str]:
    """C#: hoist `using X.Y;` *directives* to the top (CS1529 fires when they
    appear after members).

    Only directives are hoisted. `using (var x = ...) { ... }` and
    `using var x = ...;` statements must stay in the method body: the old
    pattern `using\\s+[^;]+;` let `[^;]` cross newlines, so a using *statement*
    was ripped out of its method, pasted at the top of the file, and left the
    braces unbalanced -- silently corrupting the submission rather than failing
    it cleanly.
    """
    pat = re.compile(
        r"^[ \t]*using[ \t]+(?:static[ \t]+)?[A-Za-z_][\w.]*[ \t]*;[ \t]*$", re.M)
    usings = [m.group(0).strip() for m in pat.finditer(code)]
    body = pat.sub("", code)
    return usings, body


def clean_go_user_code(code: str) -> str:
    """Strip a leading package clause and any import block the model emitted.

    The header region is skipped while only blank lines, comments, the package
    clause and import declarations have been seen. The previous guard was
    `not out`, so a blank line -- or a leading comment -- after `package main`
    (the most common model output format) ended the header early, leaving the
    user's own import block in place. The file then carried two import blocks
    and failed with `imports must appear before other declarations`.
    """
    lines = code.splitlines()
    out: list[str] = []
    in_header = True
    in_block_comment = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if in_header:
            if in_block_comment:
                out.append(raw)
                if "*/" in stripped:
                    in_block_comment = False
                i += 1
                continue
            if stripped.startswith("/*"):
                out.append(raw)
                if "*/" not in stripped:
                    in_block_comment = True
                i += 1
                continue
            if stripped.startswith("package "):
                i += 1
                continue
            if stripped.startswith("import ("):
                if re.search(r'\)\s*;?\s*(?://.*)?$', stripped):
                    i += 1
                    continue
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(")"):
                    i += 1
                i += 1
                continue
            if stripped.startswith("import "):
                i += 1
                continue
            if stripped and not stripped.startswith("//"):
                in_header = False
        out.append(raw)
        i += 1
    return "\n".join(out).lstrip("\n") + "\n"

# --------------------------------------------------------------------------
# Result comparison semantics
#
# LeetCode judges every problem with its own checker, so for results shaped as a
# list of lists there is no single correct rule. The harness previously applied
# "rows unordered" to every such result, which was simultaneously too lenient
# (q2225 findWinners: reversing the two rows was still Accepted) and too strict
# (q2610 findMatrix: a legal alternative grouping was rejected). The policy is
# now stated per problem.
#
#   rows_unordered (default) -- rows compared as a multiset, row contents in order
#   ordered                  -- exact order at both levels
#   all_unordered            -- rows as a multiset, row contents also unordered
# --------------------------------------------------------------------------
LIST_RESULT_MODE: dict[int, str] = {
    2225: "ordered",        # findWinners -> exactly [[winners...], [one-loss...]]
    2610: "all_unordered",  # findMatrix  -> any valid grouping, any row order
}
DEFAULT_LIST_RESULT_MODE = "rows_unordered"

_MODE_FLAGS = {
    "rows_unordered": (True, False),
    "ordered": (False, False),
    "all_unordered": (True, True),
}


def list_result_mode(qid: int) -> str:
    return LIST_RESULT_MODE.get(qid, DEFAULT_LIST_RESULT_MODE)


def _eqv_helper(lang_key: str, qid: int) -> str:
    """Return the language's eqv helper with its comparison flags baked in."""
    tpl = EQV_HELPERS.get(lang_key, "")
    if not tpl:
        return tpl
    rows, inner = _MODE_FLAGS[list_result_mode(qid)]
    py = lang_key == "python3"
    return (tpl.replace("@ROWS_UNORDERED@", ("True" if py else "true") if rows
                        else ("False" if py else "false"))
               .replace("@INNER_UNORDERED@", ("True" if py else "true") if inner
                        else ("False" if py else "false")))


def rust_mode_consts(qid: int) -> str:
    """Rust comparison-policy constants, emitted once before the eqv_* helpers."""
    rows, inner = _MODE_FLAGS[list_result_mode(qid)]
    return (f"const ROWS_UNORDERED: bool = {'true' if rows else 'false'};\n"
            f"const INNER_UNORDERED: bool = {'true' if inner else 'false'};\n")


EQV_HELPERS = {
    "python3": """\
_ROWS_UNORDERED = @ROWS_UNORDERED@
_INNER_UNORDERED = @INNER_UNORDERED@


def _match(seq, want, unordered, in_row):
    if not unordered:
        return all(_eqv(x, y, in_row) for x, y in zip(seq, want))
    used = [False] * len(seq)
    for e in want:
        found = False
        for j, g in enumerate(seq):
            if not used[j] and _eqv(g, e, in_row):
                used[j] = True
                found = True
                break
        if not found:
            return False
    return True


def _eqv(a, b, in_row=False):
    if isinstance(b, float) or isinstance(a, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return a == b
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        if a and isinstance(a[0], list) and b and isinstance(b[0], list):
            # list of lists: the per-problem policy decides row ordering
            return _match(a, b, _ROWS_UNORDERED, True)
        return _match(a, b, in_row and _INNER_UNORDERED, in_row)
    return a == b

""",
    "cpp": """static const bool ROWS_UNORDERED = @ROWS_UNORDERED@;
static const bool INNER_UNORDERED = @INNER_UNORDERED@;

bool eqv(double a, double b) { return fabs(a - b) < 1e-6; }
template <typename T, typename std::enable_if<std::is_integral<T>::value, int>::type = 0>
bool eqv(T a, T b) { return a == b; }
bool eqv(const string& a, const string& b) { return a == b; }
bool eqv(bool a, bool b) { return a == b; }
template <typename T> struct _is_vec : std::false_type {};
template <typename U> struct _is_vec<vector<U>> : std::true_type {};
// _match calls eqv on elements; for nested vectors that is the overload defined
// below. ADL cannot find it (std::vector's associated namespace is std), so it
// must be declared before use.
template <typename T> bool eqv(const vector<T>& a, const vector<T>& b);

template <typename T>
bool _match(const vector<T>& a, const vector<T>& b, bool unordered) {
    if (!unordered) {
        for (size_t i = 0; i < a.size(); ++i) if (!eqv(a[i], b[i])) return false;
        return true;
    }
    vector<int> used(a.size(), 0);
    for (const auto& e : b) {
        bool found = false;
        for (size_t j = 0; j < a.size(); ++j) {
            if (!used[j] && eqv(a[j], e)) { used[j] = 1; found = true; break; }
        }
        if (!found) return false;
    }
    return true;
}

template <typename T> bool eqv(const vector<T>& a, const vector<T>& b) {
    if (a.size() != b.size()) return false;
    if constexpr (_is_vec<T>::value) {
        // list of lists: the per-problem policy decides row ordering
        return _match(a, b, ROWS_UNORDERED);
    } else {
        return _match(a, b, INNER_UNORDERED);
    }
}

""",
    "java": """class _Eqv {
    static final boolean ROWS_UNORDERED = @ROWS_UNORDERED@;
    static final boolean INNER_UNORDERED = @INNER_UNORDERED@;
    static Object canon(Object x) {
        if (x instanceof int[]) { int[] a = (int[]) x; List<Object> r = new ArrayList<>(); for (int v : a) r.add(v); return r; }
        if (x instanceof long[]) { long[] a = (long[]) x; List<Object> r = new ArrayList<>(); for (long v : a) r.add(v); return r; }
        if (x instanceof double[]) { double[] a = (double[]) x; List<Object> r = new ArrayList<>(); for (double v : a) r.add(v); return r; }
        if (x instanceof String[]) { return Arrays.asList((String[]) x); }
        if (x instanceof int[][]) { int[][] a = (int[][]) x; List<Object> r = new ArrayList<>(); for (int[] row : a) r.add(canon(row)); return r; }
        if (x instanceof List) { List<Object> r = new ArrayList<>(); for (Object v : (List<?>) x) r.add(canon(v)); return r; }
        return x;
    }
    static boolean match(List<?> x, List<?> y, boolean unordered) {
        if (!unordered) {
            for (int i = 0; i < x.size(); i++) if (!eqv(x.get(i), y.get(i))) return false;
            return true;
        }
        boolean[] used = new boolean[x.size()];
        for (Object e : y) {
            boolean found = false;
            for (int j = 0; j < x.size(); j++) {
                if (!used[j] && eqv(x.get(j), e)) { used[j] = true; found = true; break; }
            }
            if (!found) return false;
        }
        return true;
    }
    static boolean eqv(Object a, Object b) {
        a = canon(a); b = canon(b);
        if (a instanceof Number && b instanceof Number) {
            if (a instanceof Double || a instanceof Float || b instanceof Double || b instanceof Float) {
                double x = ((Number) a).doubleValue(), y = ((Number) b).doubleValue();
                return Math.abs(x - y) < 1e-6;
            }
            return ((Number) a).longValue() == ((Number) b).longValue();
        }
        if (a instanceof List && b instanceof List) {
            List<?> x = (List<?>) a, y = (List<?>) b;
            if (x.size() != y.size()) return false;
            boolean nested = !x.isEmpty() && !y.isEmpty() && x.get(0) instanceof List && y.get(0) instanceof List;
            if (nested) return match(x, y, ROWS_UNORDERED);
            return match(x, y, INNER_UNORDERED);
        }
        return a.equals(b);
    }
}

""",
    "csharp": """class _Eqv {
    const bool ROWS_UNORDERED = @ROWS_UNORDERED@;
    const bool INNER_UNORDERED = @INNER_UNORDERED@;
    static object Canon(object x) {
        if (x is int[]) { var a = (int[])x; var r = new List<object>(); foreach (var v in a) r.Add(v); return r; }
        if (x is long[]) { var a = (long[])x; var r = new List<object>(); foreach (var v in a) r.Add(v); return r; }
        if (x is string[]) { var a = (string[])x; var r = new List<object>(); foreach (var v in a) r.Add(v); return r; }
        if (x is int[][]) { var a = (int[][])x; var r = new List<object>(); foreach (var row in a) r.Add(Canon(row)); return r; }
        if (x is System.Collections.IEnumerable && !(x is string)) {
            var r = new List<object>();
            foreach (var v in (System.Collections.IEnumerable)x) r.Add(Canon(v));
            return r;
        }
        return x;
    }
    static bool Match(System.Collections.IList x, System.Collections.IList y, bool unordered) {
        if (!unordered) {
            for (int i = 0; i < x.Count; i++) if (!Eqv(x[i], y[i])) return false;
            return true;
        }
        var used = new bool[x.Count];
        foreach (var e in y) {
            bool found = false;
            for (int j = 0; j < x.Count; j++) {
                if (!used[j] && Eqv(x[j], e)) { used[j] = true; found = true; break; }
            }
            if (!found) return false;
        }
        return true;
    }
    public static bool Eqv(object a, object b) {
        a = Canon(a); b = Canon(b);
        if (a is double || b is double) {
            double x = Convert.ToDouble(a), y = Convert.ToDouble(b);
            return Math.Abs(x - y) < 1e-6;
        }
        if (a is System.Collections.IList && b is System.Collections.IList) {
            var x = (System.Collections.IList)a; var y = (System.Collections.IList)b;
            if (x.Count != y.Count) return false;
            bool nested = x.Count > 0 && y.Count > 0 && x[0] is System.Collections.IList && y[0] is System.Collections.IList;
            if (nested) return Match(x, y, ROWS_UNORDERED);
            return Match(x, y, INNER_UNORDERED);
        }
        return Equals(a, b);
    }
}

""",
    "golang": """var rowsUnordered = @ROWS_UNORDERED@
var innerUnordered = @INNER_UNORDERED@

func _isSeq(v reflect.Value) bool {
    k := v.Kind()
    return k == reflect.Slice || k == reflect.Array
}

func _seqItems(v reflect.Value) []interface{} {
    out := make([]interface{}, v.Len())
    for i := 0; i < v.Len(); i++ {
        out[i] = v.Index(i).Interface()
    }
    return out
}

func _toF(v reflect.Value) float64 {
    switch v.Kind() {
    case reflect.Float64, reflect.Float32:
        return v.Float()
    case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
        return float64(v.Int())
    case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
        return float64(v.Uint())
    }
    return 0
}

func _match(seq, want []interface{}, unordered, inRow bool) bool {
    if !unordered {
        for i := range seq {
            if !_eqv(seq[i], want[i], inRow) {
                return false
            }
        }
        return true
    }
    used := make([]bool, len(seq))
    for _, e := range want {
        found := false
        for j := range seq {
            if !used[j] && _eqv(seq[j], e, inRow) {
                used[j] = true
                found = true
                break
            }
        }
        if !found {
            return false
        }
    }
    return true
}

// Slices are compared structurally, so a nil slice and an empty slice of the
// same type count as equal. reflect.DeepEqual distinguishes them, which used to
// fail legitimate Go answers such as `make([][]int, 2)` against `[][]int{{}, ...}`.
func _eqv(a, b interface{}, inRow bool) bool {
    if a == nil || b == nil {
        return a == nil && b == nil
    }
    av, bv := reflect.ValueOf(a), reflect.ValueOf(b)
    as, bs := _isSeq(av), _isSeq(bv)
    if as || bs {
        if !as || !bs || av.Len() != bv.Len() {
            return false
        }
        ai, bi := _seqItems(av), _seqItems(bv)
        nested := av.Len() > 0 && _isSeq(reflect.ValueOf(ai[0])) &&
            bv.Len() > 0 && _isSeq(reflect.ValueOf(bi[0]))
        if nested {
            // list of lists: the per-problem policy decides row ordering
            return _match(ai, bi, rowsUnordered, true)
        }
        return _match(ai, bi, inRow && innerUnordered, inRow)
    }
    if av.Kind() == reflect.Float64 || av.Kind() == reflect.Float32 ||
        bv.Kind() == reflect.Float64 || bv.Kind() == reflect.Float32 {
        return math.Abs(_toF(av)-_toF(bv)) < 1e-6
    }
    return fmt.Sprint(a) == fmt.Sprint(b)
}

func eqv(a, b interface{}) bool {
    return _eqv(a, b, false)
}

""",
    "javascript": """// LeetCode's JS runner provides a Deque class.
class Deque {
    constructor() { this.a = []; }
    pushBack(x) { this.a.push(x); }
    popBack() { return this.a.pop(); }
    pushFront(x) { this.a.unshift(x); }
    popFront() { return this.a.shift(); }
    front() { return this.a[0]; }
    back() { return this.a[this.a.length - 1]; }
    size() { return this.a.length; }
    isEmpty() { return this.a.length === 0; }
    at(i) { return this.a[i]; }
    clear() { this.a = []; }
}
const ROWS_UNORDERED = @ROWS_UNORDERED@;
const INNER_UNORDERED = @INNER_UNORDERED@;
function _match(seq, want, unordered, inRow) {
    if (!unordered) {
        for (let i = 0; i < seq.length; i++) if (!_eqv(seq[i], want[i], inRow)) return false;
        return true;
    }
    const used = new Array(seq.length).fill(false);
    for (const e of want) {
        let found = false;
        for (let j = 0; j < seq.length; j++) {
            if (!used[j] && _eqv(seq[j], e, inRow)) { used[j] = true; found = true; break; }
        }
        if (!found) return false;
    }
    return true;
}
function _eqv(a, b, inRow) {
    // LeetCode JS solutions return BigInt once a value exceeds 2^53, while the
    // expected side is a Number literal: 6n === 6 is false, so compare across
    // the two numeric types instead of falling through to ===.
    if (typeof a === "bigint" || typeof b === "bigint") {
        try {
            if (typeof a === "bigint" && typeof b === "bigint") return a === b;
            const bi = typeof a === "bigint" ? a : b;
            const nu = typeof a === "bigint" ? b : a;
            if (typeof nu !== "number" || !Number.isInteger(nu)) return false;
            return bi === BigInt(nu);
        } catch (err) { return false; }
    }
    if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-6;
    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) return false;
        if (a.length > 0 && Array.isArray(a[0]) && b.length > 0 && Array.isArray(b[0])) {
            // list of lists: the per-problem policy decides row ordering
            return _match(a, b, ROWS_UNORDERED, true);
        }
        return _match(a, b, inRow && INNER_UNORDERED, inRow);
    }
    return a === b;
}
function eqv(a, b) { return _eqv(a, b, false); }

""",
    "rust": "",
    "c": "",
}

_HEADER = {
    "python3": "_limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else 10**9\n_total = 0\nidx = 0\n",
    "cpp": 'int main(int argc, char** argv) {\n    int limit = argc > 1 ? atoi(argv[1]) : 1000000000;\n    int total = 0, idx = 0;\n',
    "java": 'public class Judge {\n    public static void main(String[] args) {\n        int limit = args.length > 0 ? Integer.parseInt(args[0]) : 1000000000;\n        int total = 0, idx = 0;\n',
    "csharp": 'public class Judge {\n    public static void Main(string[] args) {\n        int limit = args.Length > 0 ? int.Parse(args[0]) : 1000000000;\n        int total = 0, idx = 0;\n',
    "golang": 'func main() {\n    limit := 1000000000\n    if len(os.Args) > 1 {\n        l, _ := strconv.Atoi(os.Args[1])\n        limit = l\n    }\n    total, idx := 0, 0\n',
    "javascript": 'const limit = process.argv[2] ? parseInt(process.argv[2]) : 1000000000;\nlet total = 0, idx = 0;\n',
}

# Fresh object per case: LeetCode creates a new Solution per test case.
_OBJ_NEW = {
    "python3": "_sol = Solution()\n",
    "cpp": "Solution sol;\n",
    "java": "var sol = new Solution();\n",
    "csharp": "var sol = new Solution();\n",
}

_FAIL = {
    "python3": 'print("FAIL", idx); _sys.exit(3)\n',
    "cpp": 'printf("FAIL %d\\n", idx); return 3;\n',
    "java": 'System.out.println("FAIL " + idx); System.exit(3);\n',
    "csharp": 'Console.WriteLine("FAIL " + idx); Environment.Exit(3);\n',
    "golang": 'fmt.Println("FAIL", idx); os.Exit(3)\n',
    "javascript": 'console.log("FAIL " + idx); process.exit(3);\n',
}

_LIMIT_CHK = {
    "python3": "idx += 1\n_total += 1\nif _total >= _limit:\n    print(\"OK\")\n    _sys.exit(42)\n",
    "cpp": 'idx++;\nif (++total >= limit) { printf("OK\\n"); return 42; }\n',
    "java": 'idx++;\nif (++total >= limit) { System.out.println("OK"); System.exit(42); }\n',
    "csharp": 'idx++;\nif (++total >= limit) { Console.WriteLine("OK"); Environment.Exit(42); }\n',
    "golang": "idx++\ntotal++\nif total >= limit {\n    fmt.Println(\"OK\")\n    os.Exit(42)\n}\n",
    "javascript": 'idx++;\nif (++total >= limit) { console.log("OK"); process.exit(42); }\n',
}

_CALL = {
    "python3": "_got = _sol.{m}({args})\n",
    "cpp": "auto _got = sol.{m}({args});\n",
    "java": "var _got = sol.{m}({args});\n",
    "csharp": "var _got = sol.{m}({args});\n",
    "golang": "_got := {m}({args})\n",
    "javascript": "const _got = {m}({args});\n",
}

_TAIL = {
    "python3": 'print("OK")\n_sys.exit(42)\n',
    "cpp": 'printf("OK\\n"); return 42;\n}\n',
    "java": 'System.out.println("OK"); System.exit(42);\n    }\n}\n',
    "csharp": 'Console.WriteLine("OK"); Environment.Exit(42);\n    }\n}\n',
    "golang": 'fmt.Println("OK"); os.Exit(42)\n}\n',
    "javascript": 'console.log("OK"); process.exit(42);\n',
}


def render_plain_driver(lang_key: str, sig: PlainSig, entry: dict,
                        cases: list[dict], user_code: str,
                        qid: int = 0) -> str:
    """cases: [{"args": {name: value}, "expected": value}] (args keyed by Python names)."""
    if sig.ret is None:
        raise UnsupportedProblemError(
            f"qid {qid}: {sig.method_name}() returns nothing. Judging a "
            f"void-returning problem means comparing the *mutated arguments*, "
            f"which the corpus format does not record, so no driver can be "
            f"generated. (C used to die even earlier, in _c_expected_and_compare.)")
    method = entry["method_name"]
    if lang_key == "c":
        return _render_c_driver(entry, cases, user_code, qid)
    if lang_key == "rust":
        return _render_rust_driver(sig, entry, cases, user_code, qid)
    if lang_key == "java":
        return _render_java_driver(sig, entry, cases, user_code, qid)

    for p in sig.params:
        for case in cases:
            if p.name not in case["args"]:
                raise ValueError(
                    f"qid {qid}: arg {p.name!r} missing from case args {list(case['args'])}")

    if lang_key == "golang":
        go_specs = harvest_go_imports(user_code)  # read before they are stripped
        user_code = clean_go_user_code(user_code)
        prelude = PRELUDE["golang"].replace(
            "IMPORT_BLOCK",
            go_import_block(user_code, go_specs, validators.go_imports(qid)))
    elif lang_key == "csharp":
        usings, user_code = clean_cs_user_code(user_code)
        prelude = PRELUDE["csharp"] + "".join(u + "\n" for u in usings)
    else:
        prelude = PRELUDE[lang_key]
    parts = [prelude, _eqv_helper(lang_key, qid),
             validators.helper(lang_key, qid),
             user_code.rstrip() + "\n", _HEADER[lang_key]]
    cmp_fn = _cmp_fn(lang_key)
    indent = "" if lang_key == "python3" else "    "
    # 题面允许"任意合法答案"时，用谓词校验替换精确比较（见 validators.py）。
    use_val = validators.has_validator(qid)
    # 校验器拿到的是 **_s{j}（调用前的输入快照）**，不是 _a{j}：
    # 提交可以原地改写输入，用 _a{j} 就等于让被改过的输入当自己的证据。
    val_args = [f"_s{j}" for j in range(len(sig.params))]

    def _snap_from(decls_text: str, n: int) -> tuple[str, list[str]]:
        """由输入声明生成快照声明（复用声明，类型自动正确 —— 见 validators）。"""
        if not use_val:
            return "", [f"_a{j}" for j in range(n)]
        try:
            return validators.snapshot_decls(decls_text, n)
        except ValueError as e:
            # A-007④ 的诊断残留（复核代理 A 指出）：裸 ValueError 会走 judge_one
            # 的通用 except，结果 state 仍是 SUCCESS、error 只进 _meta 而**不入库**，
            # 于是生产上和"提交编译不过"无法区分。改抛 UnsupportedProblemError，
            # 这样 state=UNSUPPORTED 会被写进结果 JSON，能区分出来。
            raise UnsupportedProblemError(str(e)) from e

    for i, case in enumerate(cases):
        vals = [case["args"][p.name] for p in sig.params]
        exp = _ret_expr(lang_key, entry, case["expected"], sig.ret)
        if lang_key == "python3":
            if use_val:
                adecls = "\n".join(f"_a{j} = {_py_repr(v)}"
                                   for j, v in enumerate(vals))
                sdecls, val_args = _snap_from(adecls, len(vals))
                decls = adecls + ("\n" + sdecls if sdecls else "")
                vcall = validators.call(lang_key, qid, "_got", val_args)
                args_s = ", ".join(f"_a{j}" for j in range(len(vals)))
                parts.append(
                    decls + "\n" + _OBJ_NEW["python3"]
                    + _CALL["python3"].format(m=method, args=args_s)
                    + f"if not {vcall}:\n"
                    + "    " + _FAIL["python3"]
                    + _LIMIT_CHK["python3"])
                continue
            args_s = ", ".join(_py_repr(v) for v in vals)
            parts.append(
                _OBJ_NEW["python3"]
                + _CALL["python3"].format(m=method, args=args_s)
                + f"if not {cmp_fn}(_got, {exp}):\n"
                + "    " + _FAIL["python3"]
                + _LIMIT_CHK["python3"])
        else:
            if lang_key == "cpp":
                # C++ vectors are (const) refs: predeclare args to avoid rvalue binding.
                ptypes = entry.get("param_types") or []
                decls = "\n".join(
                    f"{indent}    {_cpp_decl_type(ptypes[j]) if j < len(ptypes) else _cpp_type(sig.params[j].typ)} _a{j} = "
                    f"{_arg_expr(lang_key, entry, sig, j, v)};"
                    for j, v in enumerate(vals))
            elif use_val:
                # 校验器要按名字拿到输入，所以这些语言也要预声明。
                # Go 用 :=，JS/C# 用 var —— 混用会直接变成语法错误。
                decls = "\n".join(
                    (f"{indent}    _a{j} := {_arg_expr(lang_key, entry, sig, j, v)}"
                     if lang_key == "golang" else
                     f"{indent}    var _a{j} = {_arg_expr(lang_key, entry, sig, j, v)};")
                    for j, v in enumerate(vals))
            else:
                decls = None

            if decls is not None:
                args_s = ", ".join(f"_a{j}" for j in range(len(vals)))
                cond = f"!{cmp_fn}(_got, {exp})"
                if use_val:
                    # 快照必须在**调用之前**取（见 validators.snapshot_decls）
                    snap, vargs = _snap_from(decls, len(vals))
                    decls = decls + ("\n" + snap if snap else "")
                    cond = f"!({validators.call(lang_key, qid, '_got', vargs)})"
                parts.append(
                    f"{indent}{{\n{decls}\n"
                    f"{indent}    {_OBJ_NEW.get(lang_key, '')}"
                    f"{indent}    {_CALL[lang_key].format(m=method, args=args_s)}"
                    f"{indent}    if ({cond}) {{\n"
                    f"{indent}        {_FAIL[lang_key]}{indent}    }}\n"
                    f"{indent}    {_LIMIT_CHK[lang_key]}{indent}}}\n")
            else:
                args_s = ", ".join(
                    _arg_expr(lang_key, entry, sig, j, v) for j, v in enumerate(vals))
                obj = _OBJ_NEW.get(lang_key, "")
                parts.append(
                    f"{indent}{{\n"
                    f"{indent}    {obj}"
                    f"{indent}    {_CALL[lang_key].format(m=method, args=args_s)}"
                    f"{indent}    if (!{cmp_fn}(_got, {exp})) {{\n"
                    f"{indent}        {_FAIL[lang_key]}{indent}    }}\n"
                    f"{indent}    {_LIMIT_CHK[lang_key]}{indent}}}\n")
    parts.append(_TAIL[lang_key])
    return "".join(parts)


def render_py_probe(sig: PlainSig, cases: list[dict], user_code: str,
                   qid: int = 0) -> str:
    """Python-only probe driver: prints `CASE <i> <repr(output)>` per case.

    Used by differential verification to obtain the Python reference's outputs,
    which then serve as expected outputs for the other 7 languages.
    """
    method = sig.method_name
    parts = [PRELUDE["python3"], user_code.rstrip() + "\n"]
    parts.append("_sys.stdout.reconfigure(encoding='utf-8')\n")
    for i, case in enumerate(cases):
        args_s = ", ".join(_py_repr(case["args"][p.name]) for p in sig.params)
        parts.append(
            f"try:\n"
            f"    _sol = Solution()\n"
            f"    _got = _sol.{method}({args_s})\n"
            f'    print("CASE", {i}, repr(_got))\n'
            f"except Exception as _e:\n"
            f'    print("CASE", {i}, "ERROR", type(_e).__name__)\n')
    return "".join(parts)


def render_py_probe_design(qid: int, user_code: str, cases: list[dict]) -> str:
    """Python-only probe for design problems: prints repr of the collected outputs."""
    from local.harness.typespec import parse_python_snippet
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    assert isinstance(sig, DesignSig)
    methods = {name: (params, ret) for name, params, ret in sig.methods}
    parts = [PRELUDE["python3"], user_code.rstrip() + "\n"]
    parts.append("_sys.stdout.reconfigure(encoding='utf-8')\n")
    for i, case in enumerate(cases):
        ops, args, _exp = case["ops"], case["args"], case["expected"]
        parts.append(f"try:\n    _out = []\n")
        for op, a in zip(ops, args):
            if op == sig.class_name:
                vals = ", ".join(_py_repr(v) for v in a)
                parts.append(f"    _obj = {sig.class_name}({vals})\n    _out.append(None)\n")
            else:
                params, ret = methods[op]
                vals = ", ".join(_py_repr(v) for v in a)
                if ret is None:
                    parts.append(f"    _obj.{op}({vals})\n    _out.append(None)\n")
                else:
                    parts.append(f"    _out.append(_obj.{op}({vals}))\n")
        parts.append(f'    print("CASE", {i}, repr(_out))\n'
                     f'except Exception as _e:\n'
                     f'    print("CASE", {i}, "ERROR", type(_e).__name__)\n')
    return "".join(parts)


_JAVA_CHUNK = 8  # cases per static method (javac's 64KB method limit)


def _render_java_driver(sig: PlainSig, entry: dict, cases: list[dict],
                        user_code: str, qid: int) -> str:
    """Java needs chunked static methods: large expected arrays can exceed
    javac's 64KB method bytecode limit (e.g. qid 47 with 30 permutation cases)."""
    user_code = re.sub(r"\bpublic\s+class\b", "class", user_code)
    # C-004：用户自带的 import 必须提到 prelude 之前（否则落到 class 之后 → javac 报错）
    java_imports, user_code = hoist_java_imports(user_code)
    # Large corpora cannot be expressed as Java literals (64 KB per-method
    # bytecode limit), so they go through the encoded channel instead.
    use_enc = (dataio.should_encode(sig, cases)
               and dataio.supported("java", entry, sig))
    enc_text = dataio.encode(sig, cases) if use_enc else ""
    parts = [PRELUDE["java"] + "".join(s + "\n" for s in java_imports),
             _eqv_helper("java", qid), user_code.rstrip() + "\n",
             "public class Judge {\n"]
    # 谓词校验器必须是 Java 的静态方法，所以要放在 class Judge 里。
    use_val = validators.has_validator(qid)
    if use_enc and use_val:
        # A-002：编码通路的分支只负责"读出用例数据"，**不会**生成谓词校验的调用
        # （`val_call_j` 只在 `elif use_val` 里赋值），于是后面引用它时抛
        # UnboundLocalError，被 judge 记成 Compile Error。
        #
        # 清理死代码时这处从"javac 报错"变成了"Python 异常"，**结果相同但诊断更差**
        # （复核代理 C 指出）。这里显式失败，把原因说清楚：当前 4 个有校验器的题
        # （922/1304/1317/2610）的语料都远小于编码阈值，所以走不到；
        # 一旦它们的语料变大，就会在这里**大声**失败，而不是静默给出错误语义。
        raise UnsupportedProblemError(
            f"qid {qid}: Java 驱动同时需要「编码通路」与「谓词校验器」，"
            f"但编码分支不生成校验调用（会漏掉多解判定）。"
            f"请先把该题语料拆小、或让编码通路支持校验器。"
            f"编码尺寸={len(enc_text)}")
    if use_val:
        parts.append(validators.helper("java", qid))
    if use_enc:
        parts.append(dataio.data_decl("java", enc_text))
        parts.append(dataio.reader_source("java", enc_text))
    parts.append("    static int limit = 1000000000, total = 0, idx = 0;\n")
    val_args = [f"_a{j}" for j in range(len(sig.params))]
    blocks = []
    for case in cases:
        stmts: list[str] = []
        if use_enc:
            got = dataio.java_case_stmts(entry, sig)
            if got is None:
                raise UnsupportedProblemError(
                    f"qid {qid}: java encoded channel cannot read this shape")
            stmts, names, exp = got
            args_s = ", ".join(names)
        elif use_val:
            # 谓词要按名字拿到输入 -> 预声明（Java 10+ 的 var）。
            vals = [case["args"][p.name] for p in sig.params]
            adecls = "\n".join(
                f"            var _a{j} = {_arg_expr('java', entry, sig, j, v)};"
                for j, v in enumerate(vals))
            # 输入快照：提交能原地改写数组，checker 必须用调用前的副本
            snap, vargs = validators.snapshot_decls(adecls, len(vals))
            stmts = ((adecls + "\n" + snap).splitlines() if snap
                     else adecls.splitlines())
            args_s = ", ".join(f"_a{j}" for j in range(len(vals)))
            val_call_j = validators.call("java", qid, "_got", vargs)
            exp = None
        else:
            vals = [case["args"][p.name] for p in sig.params]
            args_s = ", ".join(
                _arg_expr("java", entry, sig, j, v) for j, v in enumerate(vals))
            exp = _ret_expr("java", entry, case["expected"], sig.ret)
        cond = (f"!({val_call_j})" if use_val
                else f"!_Eqv.eqv(_got, {exp})")
        blocks.append(
            "        {\n"
            + ("".join(s + "\n" for s in stmts))
            + "            var sol = new Solution();\n"
            f"            var _got = sol.{entry['method_name']}({args_s});\n"
            f"            if ({cond}) {{\n"
            f"                System.out.println(\"FAIL \" + idx); System.exit(3);\n"
            "            }\n"
            "            idx++;\n"
            "            if (++total >= limit) { System.out.println(\"OK\"); System.exit(42); }\n"
            "        }\n")
    n_chunks = max(1, (len(blocks) + _JAVA_CHUNK - 1) // _JAVA_CHUNK)
    for c in range(n_chunks):
        parts.append(f"    static void run{c}() {{\n")
        parts.append("        if (total >= limit) return;\n")
        parts.extend(blocks[c * _JAVA_CHUNK:(c + 1) * _JAVA_CHUNK])
        parts.append("    }\n")
    parts.append("    public static void main(String[] args) {\n")
    if use_enc:
        parts.append("        __initRd(__ENC);\n")
    parts.append("        limit = args.length > 0 ? Integer.parseInt(args[0]) : 1000000000;\n")
    for c in range(n_chunks):
        parts.append(f"        run{c}();\n")
    parts.append('        System.out.println("OK"); System.exit(42);\n    }\n}\n')
    return "".join(parts)


def _render_rust_driver(sig: PlainSig, entry: dict, cases: list[dict],
                        user_code: str, qid: int) -> str:
    method = entry["method_name"]
    rust_ret = entry.get("rust_ret") or ""
    rust_params = entry.get("rust_params") or []
    typed = bool(rust_ret) or bool(rust_params)
    parts = [PRELUDE["rust"], rust_mode_consts(qid)]
    parts.append((rust_eqv_fns_typed(rust_ret) if typed and rust_ret.startswith("Vec<")
                  else rust_eqv_fns(sig.ret)) + "\n")
    # 题面允许"任意合法答案"时用谓词校验替换精确比较。
    use_val = validators.has_validator(qid)
    if use_val:
        parts.append(validators.helper("rust", qid) + "\n")
    val_args = [f"_a{j}" for j in range(len(sig.params))]
    # 校验器拿的是 clone 出来的副本 `_v{j}`（方法调用会移走 `_a{j}`）。
    val_call_args = [f"_v{j}" for j in range(len(sig.params))]
    val_call = (validators.call("rust", qid, "_got", val_call_args)
                if use_val else "")
    # Large corpora cannot be expressed as Rust literals (constant limits), so
    # they go through the encoded channel instead.
    use_enc = (dataio.should_encode(sig, cases)
               and dataio.supported("rust", entry, sig))
    enc_text = dataio.encode(sig, cases) if use_enc else ""
    if use_enc and use_val:
        # A-003：**比 A-002 更危险**。编码分支下面的比较用的是 `cmp`，
        # 而 `if use_enc:` 会覆盖 `elif use_val:` —— 结果是 `_valid` 被定义、
        # 却**从不调用**，改用与语料 expected 的精确比较。
        # 那会把「题面允许任意合法答案」的题（q922/q1304/q1317/q2610）里
        # **合法的多解判成 Wrong Answer**：不崩溃、不报错，只是静默判错。
        #
        # 复核代理 A 实测渲染 q922 的大语料得到
        # `if !(eqv_Vec_i32(&_got, &_exp))`，`_valid` 出现了但没人调用。
        # 当前 4 题的语料都远小于编码阈值，所以走不到；这里显式失败，
        # 避免将来语料变大后静默给出错误的判定口径。
        raise UnsupportedProblemError(
            f"qid {qid}: Rust 驱动同时需要「编码通路」与「谓词校验器」。"
            f"编码分支会绕过校验器、改用精确比较，从而把合法多解判成 WA —— "
            f"这是静默的错误判定。请先把该题语料拆小、或让编码通路支持校验器。"
            f"编码尺寸={len(enc_text)}")
    if use_enc:
        parts.append(dataio.data_decl("rust", enc_text))
        parts.append(dataio.reader_source("rust", enc_text) + "\n")
    parts.append(user_code.rstrip() + "\n")
    parts.append("fn main() {\n")
    parts.append('    let args: Vec<String> = std::env::args().collect();\n')
    parts.append('    let limit: usize = if args.len() > 1 { args[1].parse().unwrap_or(1000000000) } else { 1000000000 };\n')
    parts.append("    let mut total: usize = 0;\n    let mut idx: usize = 0;\n")
    if use_enc:
        parts.append("    let mut rd = _Rd::new(__ENC);\n")
    for case in cases:
        read_stmts = ""
        if use_enc:
            got = dataio.rust_case_stmts(entry, sig)
            if got is None:
                raise UnsupportedProblemError(
                    f"qid {qid}: rust encoded channel cannot read this shape")
            stmts, names, exp = got
            args_s = ", ".join(names)
            cmp = (_rust_cmp_typed("_got", exp, rust_ret) if typed
                   else _rust_cmp("_got", exp, sig.ret))
            read_stmts = "".join(s + "\n" for s in stmts)
        elif use_val:
            # 谓词要按名字拿到输入，所以预声明参数。
            #
            # Rust 的所有权：`Solution::method(_a0)` 会把 `_a0` **移走**，
            # 之后校验器再用它就是 E0382 use of moved value（q922/q2610 实测）。
            # 所以方法调用前先 clone 一份给校验器用：`_v{j}`。
            # 用 `.clone()` 而不是 `&` —— 标量（i32）与 Vec 都能用，不必知道类型。
            decls = []
            for j, p in enumerate(sig.params):
                v = case["args"][p.name]
                expr = (_rust_val_typed(v, rust_params[j][1]) if typed
                        else value_expr("rust", v, p.typ))
                decls.append(f"        let _a{j} = {expr};")
                decls.append(f"        let _v{j} = _a{j}.clone();")
            read_stmts = "".join(d + "\n" for d in decls)
            args_s = ", ".join(val_args)
            cmp = val_call
        elif typed:
            args_s = ", ".join(
                _rust_val_typed(case["args"][p.name], rt)
                for p, (_, rt) in zip(sig.params, rust_params))
            exp = _rust_val_typed(case["expected"], rust_ret)
            cmp = _rust_cmp_typed("_got", exp, rust_ret)
        else:
            args_s = ", ".join(
                value_expr("rust", case["args"][p.name], p.typ) for p in sig.params)
            exp = value_expr("rust", case["expected"], sig.ret)
            cmp = _rust_cmp("_got", exp, sig.ret)
        parts.append(f"    {{\n{read_stmts}        let _got = Solution::{method}({args_s});\n")
        parts.append(f"        if !({cmp}) {{\n")
        parts.append('            println!("FAIL {}", idx);\n            std::process::exit(3);\n        }\n')
        parts.append("        idx += 1; total += 1;\n        if total >= limit { println!(\"OK\"); std::process::exit(42); }\n    }\n")
    parts.append('    println!("OK"); std::process::exit(42);\n}\n')
    return "".join(parts)


def _render_c_driver(entry: dict, cases: list[dict], user_code: str, qid: int) -> str:
    parts = [PRELUDE["c"], validators.helper("c", qid),
             user_code.rstrip() + "\n"]
    parts.append("int main(int argc, char** argv) {\n")
    parts.append('    int limit = argc > 1 ? atoi(argv[1]) : 1000000000;\n')
    parts.append("    int total = 0, idx = 0;\n")
    for case in cases:
        parts.append(render_c_case(qid, entry, case["args"], case["expected"]))
    parts.append('    printf("OK\\n");\n    return 42;\n}\n')
    return "".join(parts)


# --------------------------------------------------------------------------
# Design problems (stateful classes, op-sequence cases)
# --------------------------------------------------------------------------

# Per-problem per-language op tables. Python op names are canonical; target
# names come from each language's snippet (verified 2026-09-29).
# style: ctor=new-instance / method=obj.name(...) / goctor / rustctor / cctor /
#        cfunc=name(obj, ...) with C signature info.
DESIGN_OPS: dict[int, dict[str, dict]] = {
    1146: {  # SnapshotArray: ctor(int); set(int,int)->None; snap()->int; get(int,int)->int
        "python3": {"ops": {"SnapshotArray": ("SnapshotArray", "ctor"), "set": ("set", "method"),
                             "snap": ("snap", "method"), "get": ("get", "method")}},
        "cpp": {"ops": {"SnapshotArray": ("SnapshotArray", "ctor"), "set": ("set", "method"),
                        "snap": ("snap", "method"), "get": ("get", "method")}},
        "java": {"ops": {"SnapshotArray": ("SnapshotArray", "ctor"), "set": ("set", "method"),
                         "snap": ("snap", "method"), "get": ("get", "method")}},
        "csharp": {"ops": {"SnapshotArray": ("SnapshotArray", "ctor"), "set": ("Set", "method"),
                           "snap": ("Snap", "method"), "get": ("Get", "method")}},
        "golang": {"ops": {"SnapshotArray": ("Constructor", "goctor"), "set": ("Set", "method"),
                           "snap": ("Snap", "method"), "get": ("Get", "method")}},
        "javascript": {"ops": {"SnapshotArray": ("SnapshotArray", "ctor"), "set": ("set", "method"),
                               "snap": ("snap", "method"), "get": ("get", "method")}},
        "rust": {"ops": {"SnapshotArray": ("new", "rustctor"), "set": ("set", "method"),
                         "snap": ("snap", "method"), "get": ("get", "method")}},
        "c": {"ops": {"SnapshotArray": ("snapshotArrayCreate", "cctor", "SnapshotArray*", ("int",)),
                      "set": ("snapshotArraySet", "cfunc", "void", ("int", "int")),
                      "snap": ("snapshotArraySnap", "cfunc", "int", ()),
                      "get": ("snapshotArrayGet", "cfunc", "int", ("int", "int"))}},
    },
    1472: {  # BrowserHistory: ctor(str); visit(str)->None; back(int)->str; forward(int)->str
        "python3": {"ops": {"BrowserHistory": ("BrowserHistory", "ctor"), "visit": ("visit", "method"),
                             "back": ("back", "method"), "forward": ("forward", "method")}},
        "cpp": {"ops": {"BrowserHistory": ("BrowserHistory", "ctor"), "visit": ("visit", "method"),
                        "back": ("back", "method"), "forward": ("forward", "method")}},
        "java": {"ops": {"BrowserHistory": ("BrowserHistory", "ctor"), "visit": ("visit", "method"),
                         "back": ("back", "method"), "forward": ("forward", "method")}},
        "csharp": {"ops": {"BrowserHistory": ("BrowserHistory", "ctor"), "visit": ("Visit", "method"),
                           "back": ("Back", "method"), "forward": ("Forward", "method")}},
        "golang": {"ops": {"BrowserHistory": ("Constructor", "goctor"), "visit": ("Visit", "method"),
                           "back": ("Back", "method"), "forward": ("Forward", "method")}},
        "javascript": {"ops": {"BrowserHistory": ("BrowserHistory", "ctor"), "visit": ("visit", "method"),
                               "back": ("back", "method"), "forward": ("forward", "method")}},
        "rust": {"ops": {"BrowserHistory": ("new", "rustctor"), "visit": ("visit", "method"),
                         "back": ("back", "method"), "forward": ("forward", "method")}},
        "c": {"ops": {"BrowserHistory": ("browserHistoryCreate", "cctor", "BrowserHistory*", ("char*",)),
                      "visit": ("browserHistoryVisit", "cfunc", "void", ("char*",)),
                      "back": ("browserHistoryBack", "cfunc", "char*", ("int",)),
                      "forward": ("browserHistoryForward", "cfunc", "char*", ("int",))}},
    },
    2080: {  # RangeFreqQuery: ctor(List[int]); query(int,int,int)->int
        "python3": {"ops": {"RangeFreqQuery": ("RangeFreqQuery", "ctor"), "query": ("query", "method")}},
        "cpp": {"ops": {"RangeFreqQuery": ("RangeFreqQuery", "ctor"), "query": ("query", "method")}},
        "java": {"ops": {"RangeFreqQuery": ("RangeFreqQuery", "ctor"), "query": ("query", "method")}},
        "csharp": {"ops": {"RangeFreqQuery": ("RangeFreqQuery", "ctor"), "query": ("Query", "method")}},
        "golang": {"ops": {"RangeFreqQuery": ("Constructor", "goctor"), "query": ("Query", "method")}},
        "javascript": {"ops": {"RangeFreqQuery": ("RangeFreqQuery", "ctor"), "query": ("query", "method")}},
        "rust": {"ops": {"RangeFreqQuery": ("new", "rustctor"), "query": ("query", "method")}},
        "c": {"ops": {"RangeFreqQuery": ("rangeFreqQueryCreate", "cctor", "RangeFreqQuery*", ("int*", "int")),
                      "query": ("rangeFreqQueryQuery", "cfunc", "int", ("int", "int", "int"))}},
    },
    2241: {  # ATM: ctor(); deposit(List[int])->None; withdraw(int)->List[int]
        "python3": {"ops": {"ATM": ("ATM", "ctor"), "deposit": ("deposit", "method"),
                             "withdraw": ("withdraw", "method")}},
        "cpp": {"ops": {"ATM": ("ATM", "ctor"), "deposit": ("deposit", "method"),
                        "withdraw": ("withdraw", "method")}},
        "java": {"ops": {"ATM": ("ATM", "ctor"), "deposit": ("deposit", "method"),
                         "withdraw": ("withdraw", "method")}},
        "csharp": {"ops": {"ATM": ("ATM", "ctor"), "deposit": ("Deposit", "method"),
                           "withdraw": ("Withdraw", "method")}},
        "golang": {"ops": {"ATM": ("Constructor", "goctor"), "deposit": ("Deposit", "method"),
                           "withdraw": ("Withdraw", "method")}},
        "javascript": {"ops": {"ATM": ("ATM", "ctor"), "deposit": ("deposit", "method"),
                               "withdraw": ("withdraw", "method")}},
        "rust": {"ops": {"ATM": ("new", "rustctor"), "deposit": ("deposit", "method"),
                         "withdraw": ("withdraw", "method")}},
        "c": {"ops": {"ATM": ("aTMCreate", "cctor", "ATM*", ()),
                      "deposit": ("aTMDeposit", "cfunc", "void", ("int*", "int")),
                      "withdraw": ("aTMWithdraw", "cfunc", "int*", ("int", "int*out"))}},
    },
}


def _design_py_sig(qid: int) -> DesignSig:
    from local.harness.typespec import parse_python_snippet
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    assert isinstance(sig, DesignSig)
    return sig


def _design_py_methods(qid: int) -> dict[str, tuple[tuple[Param, ...], Type]]:
    """Python-side per-op (params, ret). Ctor op keyed by class name."""
    sig = _design_py_sig(qid)
    out: dict[str, tuple[tuple[Param, ...], Type]] = {}
    for name, params, ret in sig.methods:
        if name == "__init__":
            out[sig.class_name] = (params, Int())  # ctor "return" unused
        else:
            out[name] = (params, ret)
    return out


def render_design_driver(lang_key: str, qid: int, user_code: str,
                         cases: list[dict]) -> str:
    """cases: [{"ops": [...], "args": [[...]], "expected": [...]}] — one op sequence each."""
    if qid not in DESIGN_OPS:
        raise UnsupportedProblemError(
            f"qid {qid}: design (stateful-class) problems need a per-language "
            f"operation table; only {sorted(DESIGN_OPS)} currently have one. Add "
            f"this problem's operation names to DESIGN_OPS to judge it -- without "
            f"this check the missing key surfaced as a confusing Compile Error.")
    table = DESIGN_OPS[qid].get(lang_key)
    if table is None:
        raise UnsupportedProblemError(
            f"qid {qid}: DESIGN_OPS has no entry for language {lang_key!r}")
    py_methods = _design_py_methods(qid)
    if lang_key == "golang":
        go_specs = harvest_go_imports(user_code)  # read before they are stripped
        user_code = clean_go_user_code(user_code)
        prelude = PRELUDE["golang"].replace("IMPORT_BLOCK",
                                            go_import_block(user_code, go_specs))
    else:
        prelude = PRELUDE[lang_key]
    java_imports: list[str] = []
    cs_usings: list[str] = []
    if lang_key == "java":
        user_code = re.sub(r"\bpublic\s+class\b", "class", user_code)
        # C-004（设计题路径同样受影响）
        java_imports, user_code = hoist_java_imports(user_code)
    elif lang_key == "csharp":
        # C-004 的 C# 同源问题：`clean_cs_user_code` 此前只在**普通驱动**里调用
        # （L1550），设计题路径完全没做 using 提升 → 自带 using 的设计题提交被判 CE。
        cs_usings, user_code = clean_cs_user_code(user_code)
    parts = [prelude + "".join(s + "\n" for s in java_imports + cs_usings)]
    if lang_key in EQV_HELPERS:
        parts.append(_eqv_helper(lang_key, qid))
    if lang_key == "rust":
        parts.append(rust_mode_consts(qid))
        for _, ret in py_methods.values():
            if isinstance(ret, ListT):
                parts.append(rust_eqv_fns(ret) + "\n")
    parts.append(user_code.rstrip() + "\n")
    parts.append({
        "python3": "_limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else 10**9\n_total = 0\nidx = 0\n",
        "cpp": 'int main(int argc, char** argv) {\n    int limit = argc > 1 ? atoi(argv[1]) : 1000000000;\n    int total = 0, idx = 0;\n',
        "java": 'public class Judge {\n    public static void main(String[] args) {\n        int limit = args.length > 0 ? Integer.parseInt(args[0]) : 1000000000;\n        int total = 0, idx = 0;\n',
        "csharp": 'public class Judge {\n    public static void Main(string[] args) {\n        int limit = args.Length > 0 ? int.Parse(args[0]) : 1000000000;\n        int total = 0, idx = 0;\n',
        "golang": 'func main() {\n    limit := 1000000000\n    if len(os.Args) > 1 {\n        l, _ := strconv.Atoi(os.Args[1])\n        limit = l\n    }\n    total, idx := 0, 0\n',
        "javascript": 'const limit = process.argv[2] ? parseInt(process.argv[2]) : 1000000000;\nlet total = 0, idx = 0;\n',
        "rust": 'fn main() {\n    let args: Vec<String> = std::env::args().collect();\n    let limit: usize = if args.len() > 1 { args[1].parse().unwrap_or(1000000000) } else { 1000000000 };\n    let mut total: usize = 0;\n    let mut idx: usize = 0;\n',
        "c": 'int main(int argc, char** argv) {\n    int limit = argc > 1 ? atoi(argv[1]) : 1000000000;\n    int total = 0, idx = 0;\n',
    }[lang_key])

    for case in cases:
        ops = case["ops"]
        args = case["args"]
        expected = case["expected"]
        assert len(ops) == len(args) == len(expected), \
            f"qid {qid}: ops/args/expected length mismatch"
        parts.append({
            "python3": "",
            "cpp": "    {\n",
            "java": "    {\n",
            "csharp": "    {\n",
            "golang": "    {\n",
            "javascript": "    {\n",
            "rust": "    {\n",
            "c": "    {\n",
        }[lang_key])
        for i, op in enumerate(ops):
            parts.append(_design_op_stmt(lang_key, qid, table, py_methods, op,
                                         args[i], expected[i]))
        parts.append({
            "python3": "idx += 1\n_total += 1\nif _total >= _limit:\n    print(\"OK\")\n    _sys.exit(42)\n",
            "cpp": '    idx++;\n    if (++total >= limit) { printf("OK\\n"); return 42; }\n    }\n',
            "java": '    idx++;\n    if (++total >= limit) { System.out.println("OK"); System.exit(42); }\n    }\n',
            "csharp": '    idx++;\n    if (++total >= limit) { Console.WriteLine("OK"); Environment.Exit(42); }\n    }\n',
            "golang": "    idx++\n    total++\n    if total >= limit {\n        fmt.Println(\"OK\")\n        os.Exit(42)\n    }\n    }\n",
            "javascript": '    idx++;\n    if (++total >= limit) { console.log("OK"); process.exit(42); }\n    }\n',
            "rust": '    idx += 1;\n    total += 1;\n    if total >= limit { println!("OK"); std::process::exit(42); }\n    }\n',
            "c": '    idx++;\n    if (++total >= limit) { printf("OK\\n"); return 42; }\n    }\n',
        }[lang_key])

    parts.append({
        "python3": 'print("OK")\n_sys.exit(42)\n',
        "cpp": '    printf("OK\\n"); return 42;\n}\n',
        "java": '        System.out.println("OK"); System.exit(42);\n    }\n}\n',
        "csharp": '        Console.WriteLine("OK"); Environment.Exit(42);\n    }\n}\n',
        "golang": '    fmt.Println("OK"); os.Exit(42)\n}\n',
        "javascript": 'console.log("OK"); process.exit(42);\n',
        "rust": '    println!("OK"); std::process::exit(42);\n}\n',
        "c": '    printf("OK\\n"); return 42;\n}\n',
    }[lang_key])
    return "".join(parts)


def _design_op_stmt(lang_key: str, qid: int, table: dict, py_methods: dict,
                    op: str, args: list, expected: Any) -> str:
    """Render one op of a design case, comparing non-void results inline."""
    name, style = table["ops"][op][0], table["ops"][op][1]
    params, ret = py_methods[op]
    ind = "    "
    if style == "ctor":
        vals = _design_vals(lang_key, qid, args, params, "ctor")
        if lang_key == "cpp":
            # ctor may take vector<T>& (non-const ref): predeclare list args
            decls = "\n".join(
                f"{ind}    {_cpp_type(p.typ)} _a{j} = "
                f"{value_expr('cpp', v, p.typ)};"
                for j, (v, p) in enumerate(zip(args, params))
                if isinstance(p.typ, ListT))
            if decls:
                call_args = ", ".join(
                    f"_a{j}" if isinstance(p.typ, ListT) else
                    value_expr("cpp", v, p.typ)
                    for j, (v, p) in enumerate(zip(args, params)))
                # decls stay at case-block scope so _obj remains visible
                return f"{decls}\n{ind}auto _obj = {name}({call_args});\n"
            return f"{ind}auto _obj = {name}({vals});\n"
        if lang_key in ("java", "csharp", "javascript"):
            return f"{ind}var _obj = new {name}({vals});\n"
        if lang_key == "python3":
            return f"_obj = {name}({vals})\n"
        raise ValueError(style)
    if style == "goctor":
        vals = _design_vals(lang_key, qid, args, params, "goctor")
        return f"{ind}_obj := {name}({vals})\n"
    if style == "rustctor":
        vals = _design_vals(lang_key, qid, args, params, "rustctor")
        # op IS the class name (ctor op), name is the fn name (e.g. "new")
        return f"{ind}let mut _obj = {op}::{name}({vals});\n"
    if style == "cctor":
        ctypes = table["ops"][op][3]
        ctype = table["ops"][op][2]
        return _c_ctor_stmt(qid, name, ctype, ctypes, args)
    if style == "method":
        vals = _design_vals(lang_key, qid, args, params, "method")
        if ret is None:
            if lang_key == "python3":
                return f"_obj.{name}({vals})\n"
            if lang_key in ("cpp", "java", "csharp", "javascript", "rust"):
                return f"{ind}_obj.{name}({vals});\n"
            if lang_key == "golang":
                return f"{ind}_obj.{name}({vals})\n"
        exp = value_expr(lang_key, expected, ret)
        if lang_key == "python3":
            return (f"_got = _obj.{name}({vals})\n"
                    f"if not _eqv(_got, {exp}):\n"
                    f"    print(\"FAIL\", idx); _sys.exit(3)\n")
        if lang_key == "rust":
            cmp = _rust_cmp("_got", exp, ret)
            return (f"{ind}{{\n"
                    f"{ind}    let _got = _obj.{name}({vals});\n"
                    f"{ind}    if !({cmp}) {{\n{ind}        println!(\"FAIL {{}}\", idx); std::process::exit(3);\n{ind}    }}\n"
                    f"{ind}}}\n")
        cmp_fn = _cmp_fn(lang_key)
        fail = _FAIL[lang_key]
        # each non-void op gets its own nested block (fresh _got per op)
        if lang_key == "cpp":
            return (f"{ind}{{\n"
                    f"{ind}    auto _got = _obj.{name}({vals});\n"
                    f"{ind}    if (!{cmp_fn}(_got, {exp})) {{\n{ind}        {fail}{ind}    }}\n"
                    f"{ind}}}\n")
        if lang_key in ("java", "csharp"):
            kw = "var"
            return (f"{ind}{{\n"
                    f"{ind}    {kw} _got = _obj.{name}({vals});\n"
                    f"{ind}    if (!{cmp_fn}(_got, {exp})) {{\n{ind}        {fail}{ind}    }}\n"
                    f"{ind}}}\n")
        if lang_key == "golang":
            return (f"{ind}{{\n"
                    f"{ind}    _got := _obj.{name}({vals})\n"
                    f"{ind}    if !{cmp_fn}(_got, {exp}) {{\n{ind}        {fail}{ind}    }}\n"
                    f"{ind}}}\n")
        if lang_key == "javascript":
            return (f"{ind}{{\n"
                    f"{ind}    const _got = _obj.{name}({vals});\n"
                    f"{ind}    if (!{cmp_fn}(_got, {exp})) {{\n{ind}        {fail}{ind}    }}\n"
                    f"{ind}}}\n")
    if style == "cfunc":
        ctypes = table["ops"][op][3]
        cret = table["ops"][op][2]
        # nested block: C decls (_a0/_retSize) must not collide across ops
        return _wrap_block(_c_design_func_stmt(qid, name, cret, ctypes, args, expected))
    raise ValueError(f"unknown style {style}")


def _wrap_block(body: str, ind: str = "    ") -> str:
    """Wrap C statements in a nested block so per-op decls don't collide."""
    lines = [ind + "{\n"]
    for line in body.splitlines():
        lines.append(ind + line + "\n" if line.strip() else "\n")
    lines.append(ind + "}\n")
    return "".join(lines)


def _design_vals(lang_key: str, qid: int, args: list, params, mode: str) -> str:
    return ", ".join(
        _py_repr(v) if lang_key == "python3" else value_expr(lang_key, v, p.typ)
        for v, p in zip(args, params))


def _c_ctor_stmt(qid: int, name: str, ctype: str, ctypes: tuple, args: list) -> str:
    """C constructor: render array/string decls (with size args) + typed obj decl."""
    ind = "    "
    decls: list[str] = []
    call_args: list[str] = []
    ai = 0
    for ct in ctypes:
        if ct in ("int*", "char*"):
            a = args[ai]
            if ct == "int*":
                decls.append(f"{ind}int _a{ai}[] = {{{', '.join(str(int(x)) for x in a)}}};")
            else:
                decls.append(f'{ind}const char* _a{ai} = "{_esc(a)}";')
            call_args.append(f"_a{ai}")
            ai += 1
            # The next param in the C signature is the size arg (no Python value).
            if ai < len(ctypes) and ctypes[ai] == "int":
                call_args.append(str(len(a)))
                ai += 1
        elif ct == "int":
            # Either a real int arg (has Python value) or a size we already consumed.
            if ai < len(args):
                decls.append(f"{ind}int _a{ai} = {int(args[ai])};")
                call_args.append(f"_a{ai}")
                ai += 1
            # else: already handled as size above
        else:
            raise ValueError(f"qid {qid}: unsupported C ctor param type {ct}")
    stmt = f"{ind}{ctype} _obj = {name}({', '.join(call_args)});"
    return ("\n".join(decls) + ("\n" if decls else "") + stmt + "\n")


def _c_design_func_stmt(qid: int, name: str, cret: str, ctypes: tuple,
                        args: list, expected: Any) -> str:
    ind = "    "
    decls: list[str] = []
    call_args: list[str] = ["_obj"]
    ai = 0
    while ai < len(ctypes):
        ct = ctypes[ai]
        if ct == "int*out":
            decls.append(f"{ind}int _retSize = 0;")
            call_args.append("&_retSize")
            ai += 1
            continue
        if ct == "int*":
            a = args[ai]
            decls.append(f"{ind}int _a{ai}[] = {{{', '.join(str(int(x)) for x in a)}}};")
            call_args.append(f"_a{ai}")
            ai += 1
            # (array, size) pair: the next "int" is the size arg (no Python value)
            if ai < len(ctypes) and ctypes[ai] == "int" and ai >= len(args):
                call_args.append(str(len(a)))
                ai += 1
            continue
        a = args[ai]
        if ct == "int":
            decls.append(f"{ind}int _a{ai} = {int(a)};")
            call_args.append(f"_a{ai}")
        elif ct in ("str", "char*"):
            decls.append(f'{ind}const char* _a{ai} = "{_esc(a)}";')
            call_args.append(f"_a{ai}")
        else:
            raise ValueError(f"qid {qid}: unsupported C design param type {ct}")
        ai += 1
    base = cret.replace("unsigned", "").replace("const", "").strip()
    if base == "void":
        stmt = f"{ind}{name}({', '.join(call_args)});\n"
        return "\n".join(decls) + ("\n" if decls else "") + stmt
    if base == "int":
        stmt = (f"{ind}int _got = {name}({', '.join(call_args)});\n"
                f'{ind}if (_got != {int(expected)}) {{ printf("FAIL %d\\n", idx); return 3; }}\n')
        return "\n".join(decls) + ("\n" if decls else "") + stmt
    if base == "char*":
        stmt = (f"{ind}char* _got = {name}({', '.join(call_args)});\n"
                f'{ind}if (strcmp(_got, "{_esc(expected)}") != 0) {{ printf("FAIL %d\\n", idx); return 3; }}\n')
        return "\n".join(decls) + ("\n" if decls else "") + stmt
    if base == "int*":  # ATM withdraw: int* + returnSize out param (declared above)
        n = len(expected)
        decls.append(f"{ind}int _exp[] = {{{', '.join(str(int(x)) for x in expected)}}};")
        stmt = (f"{ind}int* _got = {name}({', '.join(call_args)});\n"
                f'{ind}if (_retSize != {n}) {{ printf("FAIL %d\\n", idx); return 3; }}\n'
                f'{ind}for (int _i = 0; _i < {n}; _i++) if (_got[_i] != _exp[_i]) {{ printf("FAIL %d\\n", idx); return 3; }}\n')
        return "\n".join(decls) + "\n" + stmt
    raise ValueError(f"qid {qid}: unsupported C design return type {cret!r}")
