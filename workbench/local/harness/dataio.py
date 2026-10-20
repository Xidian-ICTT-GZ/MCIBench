# -*- coding: utf-8 -*-
r"""Encoded input channel: pass case data as a compact token stream instead of
source literals.

Why this exists
---------------
Drivers used to embed every argument as a SOURCE LITERAL. That caps input size
per language, measured on q2270:

    n         python3  c    cpp  java  javascript  csharp  golang  rust
    5000      OK       OK   OK   OK    OK          OK      OK      OK
    10000     OK       OK   OK   CE    OK          OK      OK      OK
    20000     OK       OK   OK   CE    OK          OK      OK      CE

Java dies on the 64 KB per-method bytecode limit and Rust on its constant
limits, so any problem needing n > ~10^4 was structurally unrepresentable --
which is why the corpus maxes out at n=204 across all 100 problems while the
stated constraints allow 10^5.

Format
------
One flat, whitespace-separated token stream for all cases (args in order, then
the expected value). The reader is type-directed, so tokens carry no type tags:

    Int            -?\d+
    Float          -?\d+(\.\d+)?([eE][-+]?\d+)?
    Bool           0 | 1
    Str            <byte_len>:<lowercase_hex>      (hex => never contains space)
    List[T]        <count> followed by count x T

Strings are hex-encoded so that *every* token is whitespace-free and any
language can tokenise with its simplest split primitive.
"""
from __future__ import annotations

import json
from typing import Any

from local.harness.typespec import (Bool, Float, Int, ListT, Str, Type)

# Per-language literal size caps: Java's constant pool is 65535 *bytes* of
# modified UTF-8, GCC's default is 64 KB. Stay well clear and concatenate.
MAX_LITERAL = 48000

# Use the encoded channel once the literal form would get large. Small corpora
# keep the long-validated literal path so historical numbers stay comparable.
ENCODE_THRESHOLD = 120_000


def _enc_value(v: Any, t: Type, out: list[str]) -> None:
    if isinstance(t, ListT):
        assert isinstance(v, (list, tuple)), f"expected list, got {type(v)}"
        out.append(str(len(v)))
        for x in v:
            _enc_value(x, t.inner, out)
        return
    if isinstance(t, Str):
        b = str(v).encode("utf-8")
        out.append(f"{len(b)}:{b.hex()}")
        return
    if isinstance(t, Bool):
        out.append("1" if v else "0")
        return
    if isinstance(t, Float):
        out.append(repr(float(v)))
        return
    if isinstance(t, Int):
        out.append(str(int(v)))
        return
    raise TypeError(f"unsupported type for encoding: {t!r}")


def encode(sig, cases: list[dict]) -> str:
    """Encode args (in signature order) plus expected for each case.

    Design problems (ops/args lists) are not supported by the encoded channel;
    callers must keep them on the literal path.
    """
    params = sig.params
    out: list[str] = []
    for c in cases:
        args = c["args"]
        for p in params:
            _enc_value(args[p.name], p.typ, out)
        _enc_value(c["expected"], sig.ret, out)
    return " ".join(out)


def encoded_size(sig, cases: list[dict]) -> int:
    try:
        return len(encode(sig, cases))
    except Exception:  # noqa: BLE001
        return 0


def should_encode(sig, cases: list[dict]) -> bool:
    """Use the encoded channel only when literals would be large.

    Keeps the literal path (and therefore all historical results) untouched for
    ordinary corpora; large-scale corpora take the encoded path instead of
    failing to compile.
    """
    if not cases:
        return False
    return encoded_size(sig, cases) > ENCODE_THRESHOLD


def literal(lang_key: str, text: str) -> str:
    """A language expression producing `text`, split into concatenated chunks.

    Java/C#/Go fold `"a" + "b"` into ONE compile-time constant, which defeats
    chunking and trips "constant string too long"; those languages must use a
    runtime join instead. Java and GCC also cap a single literal, so long
    payloads become several constants combined at runtime, leaving the enclosing
    method with only a handful of instructions.
    """
    parts = [text[i:i + MAX_LITERAL] for i in range(0, len(text), MAX_LITERAL)]
    if not parts:
        parts = [""]
    q = lambda p: f'"{p}"'  # noqa: E731
    if lang_key == "java":
        # String.join is a runtime call -> javac cannot constant-fold it.
        return f"String.join(\"\", {', '.join(q(p) for p in parts)})"
    if lang_key == "csharp":
        return f"string.Concat({', '.join(q(p) for p in parts)})"
    if lang_key == "golang":
        return f"strings.Join([]string{{{', '.join(q(p) for p in parts)}}}, \"\")"
    if lang_key == "rust":
        # concat! is compile-time but Rust has no comparable literal cap.
        return f"concat!({', '.join(q(p) for p in parts)})"
    if lang_key in ("c", "cpp"):
        # Adjacent string literals; GCC merges them into one object without a
        # per-literal length limit.
        return "\n".join(f'    {q(p)}' for p in parts)
    # python3 / javascript: `+` is evaluated at runtime.
    return " + ".join(q(p) for p in parts)


# --------------------------------------------------------------------------
# Reader preludes. Each defines `rd` exposing: i() f() b() s() il() sl() ml()
# --------------------------------------------------------------------------

_PY = '''
class _Rd:
    def __init__(self, data):
        self.t = data.split()
        self.p = 0
    def _nx(self):
        v = self.t[self.p]; self.p += 1; return v
    def i(self):  return int(self._nx())
    def f(self):  return float(self._nx())
    def b(self):  return self._nx() == "1"
    def s(self):
        tok = self._nx(); n, h = tok.split(":"); return bytes.fromhex(h).decode("utf-8")
    def il(self):
        n = self.i(); return [self.i() for _ in range(n)]
    def sl(self):
        n = self.i(); return [self.s() for _ in range(n)]
    def ml(self):
        n = self.i(); return [self.il() for _ in range(n)]
rd = _Rd(__DATA__)
'''

_JS = '''
const __TOK = __DATA__.split(/\\s+/).filter(s => s.length);
let __POS = 0;
function __nx() { return __TOK[__POS++]; }
function __hex(s) {
  let out = "";
  for (let i = 0; i < s.length; i += 2)
    out += String.fromCharCode(parseInt(s.substr(i, 2), 16));
  return decodeURIComponent(escape(out));
}
const rd = {
  i: () => parseInt(__nx(), 10),
  f: () => parseFloat(__nx()),
  b: () => __nx() === "1",
  s: () => { const t = __nx(); const k = t.indexOf(":"); return __hex(t.slice(k + 1)); },
  il: () => { const n = rd.i(); const a = []; for (let i = 0; i < n; i++) a.push(rd.i()); return a; },
  sl: () => { const n = rd.i(); const a = []; for (let i = 0; i < n; i++) a.push(rd.s()); return a; },
  ml: () => { const n = rd.i(); const a = []; for (let i = 0; i < n; i++) a.push(rd.il()); return a; },
};
'''

_CPP = '''
struct _Rd {
    std::vector<std::string> t; size_t p = 0;
    _Rd() { std::istringstream _is(__DATA__); std::string _s;
             while (_is >> _s) t.push_back(_s); }
    const std::string& nx() { return t[p++]; }
    long long i() { return std::stoll(nx()); }
    double f() { return std::stod(nx()); }
    bool b() { return nx() == "1"; }
    std::string s() {
        const std::string& tok = nx(); size_t k = tok.find(':');
        std::string h = tok.substr(k + 1), out;
        for (size_t j = 0; j + 1 < h.size(); j += 2)
            out += (char)std::stoi(h.substr(j, 2), nullptr, 16);
        return out;
    }
    std::vector<long long> il() { long long n = i(); std::vector<long long> a;
        for (long long j = 0; j < n; j++) a.push_back(i()); return a; }
    std::vector<std::string> sl() { long long n = i(); std::vector<std::string> a;
        for (long long j = 0; j < n; j++) a.push_back(s()); return a; }
    std::vector<std::vector<long long> > ml() { long long n = i();
        std::vector<std::vector<long long> > a;
        for (long long j = 0; j < n; j++) a.push_back(il()); return a; }
} rd;
'''

_GO = '''
type _Rd struct{ t []string; p int }
func _newRd(d string) *_Rd { return &_Rd{t: strings.Fields(d)} }
func (r *_Rd) nx() string { v := r.t[r.p]; r.p++; return v }
func (r *_Rd) I() int { v, _ := strconv.Atoi(r.nx()); return v }
func (r *_Rd) I64() int64 { v, _ := strconv.ParseInt(r.nx(), 10, 64); return v }
func (r *_Rd) F() float64 { v, _ := strconv.ParseFloat(r.nx(), 64); return v }
func (r *_Rd) B() bool { return r.nx() == "1" }
func (r *_Rd) S() string {
	tok := r.nx(); k := strings.Index(tok, ":"); h := tok[k+1:]
	b := make([]byte, len(h)/2)
	for i := 0; i < len(b); i++ { v, _ := strconv.ParseUint(h[i*2:i*2+2], 16, 8); b[i] = byte(v) }
	return string(b)
}
func (r *_Rd) IL() []int { n := r.I(); a := make([]int, n); for i := 0; i < n; i++ { a[i] = r.I() }; return a }
func (r *_Rd) I64L() []int64 { n := r.I(); a := make([]int64, n); for i := 0; i < n; i++ { a[i] = r.I64() }; return a }
func (r *_Rd) SL() []string { n := r.I(); a := make([]string, n); for i := 0; i < n; i++ { a[i] = r.S() }; return a }
func (r *_Rd) ML() [][]int { n := r.I(); a := make([][]int, n); for i := 0; i < n; i++ { a[i] = r.IL() }; return a }
var rd = _newRd(__DATA__)
'''

_RUST = '''
struct _Rd { t: Vec<String>, p: usize }
impl _Rd {
    fn new(d: &str) -> _Rd { _Rd { t: d.split_whitespace().map(|s| s.to_string()).collect(), p: 0 } }
    fn nx(&mut self) -> String { let v = self.t[self.p].clone(); self.p += 1; v }
    fn i(&mut self) -> i64 { self.nx().parse::<i64>().unwrap() }
    fn f(&mut self) -> f64 { self.nx().parse::<f64>().unwrap() }
    fn b(&mut self) -> bool { self.nx() == "1" }
    fn s(&mut self) -> String {
        let tok = self.nx(); let k = tok.find(':').unwrap(); let h = &tok[k+1..];
        let b: Vec<u8> = (0..h.len()/2)
            .map(|i| u8::from_str_radix(&h[i*2..i*2+2], 16).unwrap()).collect();
        String::from_utf8(b).unwrap()
    }
    fn il(&mut self) -> Vec<i64> { let n = self.i(); (0..n).map(|_| self.i()).collect() }
    fn il32(&mut self) -> Vec<i32> { self.il().into_iter().map(|x| x as i32).collect() }
    fn sl(&mut self) -> Vec<String> { let n = self.i(); (0..n).map(|_| self.s()).collect() }
    fn ml(&mut self) -> Vec<Vec<i32>> {
        let n = self.i(); (0..n).map(|_| self.il32()).collect()
    }
    fn mll(&mut self) -> Vec<Vec<i64>> {
        let n = self.i(); (0..n).map(|_| self.il()).collect()
    }
}
'''

_CS = '''
class _Rd {
    string[] t; int p;
    public _Rd(string d) { t = d.Split(new char[]{' ', '\\n', '\\r', '\\t'},
                                       System.StringSplitOptions.RemoveEmptyEntries); p = 0; }
    string nx() { return t[p++]; }
    public int i() { return int.Parse(nx()); }
    public long l() { return long.Parse(nx()); }
    public double f() { return double.Parse(nx(), System.Globalization.CultureInfo.InvariantCulture); }
    public bool b() { return nx() == "1"; }
    public string s() {
        string tok = nx(); int k = tok.IndexOf(':'); string h = tok.Substring(k + 1);
        var by = new byte[h.Length / 2];
        for (int j = 0; j < by.Length; j++) by[j] = System.Convert.ToByte(h.Substring(j * 2, 2), 16);
        return System.Text.Encoding.UTF8.GetString(by);
    }
    public int[] il() { int n = i(); var a = new int[n]; for (int j = 0; j < n; j++) a[j] = i(); return a; }
    public string[] sl() { int n = i(); var a = new string[n]; for (int j = 0; j < n; j++) a[j] = s(); return a; }
    public int[][] ml() { int n = i(); var a = new int[n][]; for (int j = 0; j < n; j++) a[j] = il(); return a; }
}
'''

# Java gets a string reader that returns char and String views, because the
# same encoded value is sometimes needed as both.
_JAVA = '''
static String[] __TOK; static int __POS;
static void __initRd(String d) { __TOK = d.split(" "); __POS = 0; }
static String __nx() { return __TOK[__POS++]; }
static int rdi() { return Integer.parseInt(__nx()); }
static long rdl() { return Long.parseLong(__nx()); }
static double rdf() { return Double.parseDouble(__nx()); }
static boolean rdb() { return __nx().equals("1"); }
static String rds() {
    String tok = __nx(); int k = tok.indexOf(':'); String h = tok.substring(k + 1);
    byte[] by = new byte[h.length() / 2];
    for (int j = 0; j < by.length; j++)
        by[j] = (byte) Integer.parseInt(h.substring(j * 2, j * 2 + 2), 16);
    try { return new String(by, "UTF-8"); } catch (Exception e) { return new String(by); }
}
static int[] rdil() { int n = rdi(); int[] a = new int[n]; for (int j = 0; j < n; j++) a[j] = rdi(); return a; }
static long[] rdll() { int n = rdi(); long[] a = new long[n]; for (int j = 0; j < n; j++) a[j] = rdl(); return a; }
static String[] rdsl() { int n = rdi(); String[] a = new String[n]; for (int j = 0; j < n; j++) a[j] = rds(); return a; }
static int[][] rdml() { int n = rdi(); int[][] a = new int[n][]; for (int j = 0; j < n; j++) a[j] = rdil(); return a; }
static java.util.List<Integer> rdListI() {
    int n = rdi(); java.util.List<Integer> a = new java.util.ArrayList<Integer>(n);
    for (int j = 0; j < n; j++) a.add(rdi()); return a;
}
static java.util.List<Long> rdListL() {
    int n = rdi(); java.util.List<Long> a = new java.util.ArrayList<Long>(n);
    for (int j = 0; j < n; j++) a.add(rdl()); return a;
}
static java.util.List<String> rdListS() {
    int n = rdi(); java.util.List<String> a = new java.util.ArrayList<String>(n);
    for (int j = 0; j < n; j++) a.add(rds()); return a;
}
static java.util.List<java.util.List<Integer>> rdListListI() {
    int n = rdi(); java.util.List<java.util.List<Integer>> a =
        new java.util.ArrayList<java.util.List<Integer>>(n);
    for (int j = 0; j < n; j++) a.add(rdListI()); return a;
}
'''

_C = '''
static const char *__TOK[1 << 22]; static int __NTOK = 0, __POS = 0;
static void __initRd(const char *d) {
    char *buf = (char *) malloc(strlen(d) + 1);
    strcpy(buf, d);
    char *p = strtok(buf, " \\n\\r\\t");
    while (p && __NTOK < (1 << 22)) { __TOK[__NTOK++] = p; p = strtok(NULL, " \\n\\r\\t"); }
}
static const char *__nx(void) { return __TOK[__POS++]; }
static long long rdi(void) { return strtoll(__nx(), NULL, 10); }
static double rdf(void) { return strtod(__nx(), NULL); }
static int rdb(void) { return __nx()[0] == '1'; }
static char *rds(void) {
    const char *tok = __nx(); const char *c = strchr(tok, ':');
    const char *h = c + 1; size_t n = strlen(h) / 2;
    char *out = (char *) malloc(n + 1);
    for (size_t j = 0; j < n; j++) {
        char b[3] = { h[j * 2], h[j * 2 + 1], 0 };
        out[j] = (char) strtol(b, NULL, 16);
    }
    out[n] = 0; return out;
}
static long long *rdil(int *n) { *n = (int) rdi(); long long *a = (long long *) malloc(sizeof(long long) * (*n ? *n : 1));
    for (int j = 0; j < *n; j++) a[j] = rdi(); return a; }
static char **rdsl(int *n) { *n = (int) rdi(); char **a = (char **) malloc(sizeof(char *) * (*n ? *n : 1));
    for (int j = 0; j < *n; j++) a[j] = rds(); return a; }
static long long **rdml(int *rn, int **cn) {
    *rn = (int) rdi();
    long long **a = (long long **) malloc(sizeof(long long *) * (*rn ? *rn : 1));
    *cn = (int *) malloc(sizeof(int) * (*rn ? *rn : 1));
    for (int j = 0; j < *rn; j++) a[j] = rdil(&(*cn)[j]);
    return a;
}
'''

PRELUDE_BY_LANG = {
    "python3": _PY, "javascript": _JS, "cpp": _CPP, "golang": _GO,
    "rust": _RUST, "csharp": _CS, "java": _JAVA, "c": _C,
}

# Reader call expression per (language, type shape).
_CALLS: dict[str, dict[str, str]] = {
    "python3": {"Int": "rd.i()", "Float": "rd.f()", "Bool": "rd.b()",
                "Str": "rd.s()", "List[Int]": "rd.il()", "List[Str]": "rd.sl()",
                "List[List[Int]]": "rd.ml()"},
    "javascript": {"Int": "rd.i()", "Float": "rd.f()", "Bool": "rd.b()",
                   "Str": "rd.s()", "List[Int]": "rd.il()",
                   "List[Str]": "rd.sl()", "List[List[Int]]": "rd.ml()"},
    "cpp": {"Int": "rd.i()", "Float": "rd.f()", "Bool": "rd.b()",
            "Str": "rd.s()", "List[Int]": "rd.il()", "List[Str]": "rd.sl()",
            "List[List[Int]]": "rd.ml()"},
    "golang": {"Int": "rd.I()", "Float": "rd.F()", "Bool": "rd.B()",
               "Str": "rd.S()", "List[Int]": "rd.IL()", "List[Str]": "rd.SL()",
               "List[List[Int]]": "rd.ML()"},
    "rust": {"Int": "rd.i()", "Float": "rd.f()", "Bool": "rd.b()",
             "Str": "rd.s()", "List[Int]": "rd.il32()", "List[Str]": "rd.sl()",
             "List[List[Int]]": "rd.ml()"},
    "csharp": {"Int": "rd.i()", "Float": "rd.f()", "Bool": "rd.b()",
               "Str": "rd.s()", "List[Int]": "rd.il()", "List[Str]": "rd.sl()",
               "List[List[Int]]": "rd.ml()"},
    "java": {"Int": "rdi()", "Float": "rdf()", "Bool": "rdb()",
             "Str": "rds()", "List[Int]": "rdil()", "List[Str]": "rdsl()",
             "List[List[Int]]": "rdml()"},
    "c": {"Int": "(int) rdi()", "Float": "rdf()", "Bool": "rdb()",
          "Str": "rds()", "List[Int]": "__il_tmp", "List[Str]": "__sl_tmp",
          "List[List[Int]]": "__ml_tmp"},
}

# C needs a length out-parameter, so list reads are emitted as statements.
C_LIST_READ = {
    "List[Int]": ("int {n} = 0; long long *{v} = rdil(&{n});", "long long *"),
}


def shape(t: Type) -> str:
    """Canonical shape key used by _CALLS."""
    if isinstance(t, ListT):
        return f"List[{shape(t.inner)}]"
    return type(t).__name__


def reader_expr(lang_key: str, lang_type: str, t: Type) -> str | None:
    """Reader expression for this type, or None if unsupported."""
    key = shape(t)
    # Java/C#/Go/Rust declared container types differ from the Python shape, so
    # prefer the language's own type name when we have one.
    if lang_key in ("java", "csharp") and lang_type:
        if lang_type.startswith(("List<", "IList<")):
            inner = "Int" if "Integer" in lang_type else (
                "Str" if "String" in lang_type else "Int")
            key = f"List[{inner}]"
    return _CALLS.get(lang_key, {}).get(key)


def json_fingerprint(cases: list[dict]) -> str:
    return json.dumps(cases, sort_keys=True)[:64]


# --------------------------------------------------------------------------
# Per-case read statements. Only Java and Rust need these: at n=100000 as a
# literal every other language is Accepted (c 3 MB, cpp 4 MB, golang 3 MB,
# csharp 28 MB, javascript 54 MB, python3 94 MB), while Java dies on the 64 KB
# per-method bytecode limit and Rust on its constant limits.
# --------------------------------------------------------------------------

JAVA_READERS = {
    "int[]": "rdil()", "long[]": "rdll()", "String[]": "rdsl()",
    "int[][]": "rdml()", "boolean[]": "rdil()", "double[]": "rdml()",
    "List<Integer>": "rdListI()", "List<Long>": "rdListL()",
    "List<String>": "rdListS()",
    "List<List<Integer>>": "rdListListI()",
    "int": "rdi()", "long": "rdl()", "double": "rdf()",
    "boolean": "rdb()", "String": "rds()", "char": "(char) rdi()",
    "Integer": "rdi()", "Long": "rdl()",
}

RUST_READERS = {
    "Vec<i32>": "rd.il32()", "Vec<i64>": "rd.il()",
    "Vec<String>": "rd.sl()",
    "Vec<Vec<i32>>": "rd.ml()", "Vec<Vec<i64>>": "rd.mll()",
    "i32": "(rd.i() as i32)", "i64": "rd.i()", "usize": "(rd.i() as usize)",
    "String": "rd.s()", "f64": "rd.f()", "bool": "rd.b()",
}


def _java_decl(pt: str) -> str:
    return ("java.util.List" + pt[4:]) if pt.startswith("List<") else pt


def java_case_stmts(entry: dict, sig, indent: str = "        "):
    """(statements, arg var names, expected var) for one Java case, or None.

    None means the declared shape is not covered -> caller keeps literals.
    """
    ptypes = entry.get("param_types") or []
    vals = [c for c in (entry.get("param_types") or [])]
    stmts: list[str] = []
    names: list[str] = []
    params = list(sig.params)
    for j, p in enumerate(params):
        pt = ptypes[j] if j < len(ptypes) else "int"
        rd = JAVA_READERS.get(pt)
        if rd is None:
            return None
        names.append(f"_a{j}")
        stmts.append(f"{indent}{_java_decl(pt)} _a{j} = {rd};")
    rt = entry.get("ret_type") or "int"
    rd = JAVA_READERS.get(rt)
    if rd is None:
        return None
    stmts.append(f"{indent}{_java_decl(rt)} _exp = {rd};")
    del vals
    return stmts, names, "_exp"


def rust_case_stmts(entry: dict, sig, indent: str = "        "):
    """(statements, arg var names, expected var) for one Rust case, or None."""
    rps = entry.get("rust_params") or []
    # rust_params is a list of (name, type) pairs; tolerate bare type lists too.
    rtypes = [(p[1] if isinstance(p, (tuple, list)) else p) for p in rps]
    params = list(sig.params)
    if len(rtypes) != len(params):
        return None
    stmts: list[str] = []
    names: list[str] = []
    for j, rt in enumerate(rtypes):
        rd = RUST_READERS.get(rt)
        if rd is None:
            return None
        names.append(f"_a{j}")
        stmts.append(f"{indent}let _a{j} = {rd};")
    rret = entry.get("rust_ret") or ""
    rd = RUST_READERS.get(rret)
    if rd is None:
        return None
    stmts.append(f"{indent}let _exp = {rd};")
    return stmts, names, "_exp"


def data_decl(lang_key: str, text: str) -> str:
    """A declaration binding the encoded payload in the given language."""
    if lang_key == "java":
        return f"    static final String __ENC = {literal('java', text)};\n"
    if lang_key == "rust":
        return f"const __ENC: &str = {literal('rust', text)};\n"
    raise KeyError(lang_key)


def reader_source(lang_key: str, text: str) -> str:
    """Reader prelude with the payload bound (used by Java/Rust drivers)."""
    return PRELUDE_BY_LANG[lang_key].replace(
        "__DATA__", "__ENC" if lang_key in ("java", "rust") else text)


def supported(lang_key: str, entry: dict, sig) -> bool:
    """Can this problem's shape go through the encoded channel for this language?"""
    if lang_key == "java":
        return java_case_stmts(entry, sig) is not None
    if lang_key == "rust":
        return rust_case_stmts(entry, sig) is not None
    return False
