# -*- coding: utf-8 -*-
r"""「任意合法答案」的答案校验器。

问题
----
有些题目面明确允许返回**任意一个合法答案**，而判题器一直在做**精确比较**——
于是模型返回一个完全合法的、只是与语料里那条不同的答案时会被判 WA。
实测 q1304：语料期望 `n=3 -> [1,-1,0]`，模型返回 `[-1,1,0]`（和为零、3 个互异整数，
题面原文 "return **any** array"），却被判错。

为什么不能用「归一化后比较」
----------------------------
这些题的合法答案集合没有统一的规范形（q922 要求奇偶位置各就各位，
排序就被破坏了）。所以只能用**谓词**：拿到返回值 + 该用例的输入，判断它是否合法。

为什么放在驱动里
----------------
差分校验 (`differential.verify_with_lang`) 也通过 `render_plain_driver` 跑参考解，
所以只要驱动改用校验器，判题与语料校验**两边同时生效**，不会出现口径不一致。

已覆盖
------
- q1304 `sumZero(n)`：返回任意 n 个互异整数，和为 0。
"""
from __future__ import annotations

import re

# qid -> 校验器名
ANSWER_VALIDATORS: dict[int, str] = {
    1304: "sum_zero",
    922: "parity_ii",
    1317: "no_zero_pair",
    2610: "find_matrix",
}

# 每个校验器需要的输入（与题面签名的参数名一致，仅作文档与自检用）。
# 调用约定：**按签名顺序传入该方法的全部参数**，返回值为第一个实参。
# 这样标量（q1304 的 n）和数组（q922 的 nums）用同一套规则表达。
VALIDATOR_PARAMS: dict[str, list[str]] = {
    "sum_zero": ["n"],
    "parity_ii": ["nums"],
    "no_zero_pair": ["n"],
    "find_matrix": ["nums"],
}


def has_validator(qid: int) -> bool:
    return qid in ANSWER_VALIDATORS


def call(lang_key: str, qid: int, got_expr: str, arg_names: list[str]) -> str:
    """生成调用校验器的表达式。"""
    name = ANSWER_VALIDATORS[qid]
    args = ", ".join([got_expr] + arg_names)
    if lang_key == "rust":
        return f"_valid(&{got_expr}, {', '.join(arg_names)})"
    if lang_key == "c":
        # C 的返回值带长度，另行处理（见 render._render_c_driver）。
        return f"_valid({args})"
    if lang_key == "csharp":
        # 必须待在类型里：顶层裸方法会撞 CS8803。
        return f"_Valid.check({args})"
    return f"_valid({args})"


# --------------------------------------------------------------------------
# 各语言的校验器实现。参数顺序：返回值, 然后是用例输入。
# --------------------------------------------------------------------------
_HELPERS: dict[str, dict[str, str]] = {
    "sum_zero": {
        "python3": """
def _valid(got, n):
    if not isinstance(got, list) or len(got) != n:
        return False
    if len(set(got)) != n:
        return False
    return sum(got) == 0
""",
        "javascript": """
function _valid(got, n) {
    if (!Array.isArray(got) || got.length !== n) return false;
    if (new Set(got).size !== n) return false;
    let s = 0; for (const x of got) s += x;
    return s === 0;
}
""",
        "cpp": """
static bool _valid(const std::vector<int>& got, long long n) {
    if ((long long)got.size() != n) return false;
    std::set<int> _s(got.begin(), got.end());
    if ((long long)_s.size() != n) return false;
    long long _sum = 0;
    for (size_t _i = 0; _i < got.size(); ++_i) _sum += got[_i];
    return _sum == 0;
}
""",
        "c": """
static int _valid(int *got, int gotLen, long long n) {
    if ((long long)gotLen != n) return 0;
    long long _sum = 0;
    for (int _i = 0; _i < gotLen; ++_i) {
        _sum += got[_i];
        for (int _j = _i + 1; _j < gotLen; ++_j)
            if (got[_i] == got[_j]) return 0;
    }
    return _sum == 0;
}
""",
        "java": """
static boolean _valid(int[] got, long n) {
    if (got == null || (long) got.length != n) return false;
    java.util.Set<Integer> _s = new java.util.HashSet<Integer>();
    long _sum = 0;
    for (int x : got) { _s.add(x); _sum += x; }
    if ((long) _s.size() != n) return false;
    return _sum == 0;
}
""",
        "csharp": """
static class _Valid {
    public static bool check(int[] got, long n) {
        if (got == null || (long) got.Length != n) return false;
        var _s = new System.Collections.Generic.HashSet<int>();
        long _sum = 0;
        foreach (int x in got) { _s.Add(x); _sum += x; }
        if ((long) _s.Count != n) return false;
        return _sum == 0;
    }
}
""",
        "golang": """
func _valid(got []int, n int) bool {
    if len(got) != n { return false }
    seen := make(map[int]bool)
    sum := 0
    for _, x := range got {
        if seen[x] { return false }
        seen[x] = true
        sum += x
    }
    return sum == 0
}
""",
        "rust": """
fn _valid<T: Into<i64>>(got: &Vec<i32>, n: T) -> bool {
    let n: i64 = n.into();
    if got.len() as i64 != n { return false; }
    let mut s = std::collections::HashSet::new();
    let mut sum: i64 = 0;
    for &x in got.iter() {
        if !s.insert(x) { return false; }
        sum += x as i64;
    }
    sum == 0
}
""",
    },

    # q922 sortArrayByParityII —— 题面 "Return **any** answer array that
    # satisfies this condition"。合法 = nums 的一个重排，且偶数下标放偶数、
    # 奇数下标放奇数。所以既要查重排（多重集相等），也要查位置奇偶。
    "parity_ii": {
        "python3": """
def _valid(got, nums):
    if not isinstance(got, list) or len(got) != len(nums):
        return False
    if sorted(got) != sorted(nums):
        return False
    for i, x in enumerate(got):
        if (x % 2 == 0) != (i % 2 == 0):
            return False
    return True
""",
        "javascript": """
function _valid(got, nums) {
    if (!Array.isArray(got) || got.length !== nums.length) return false;
    const a = [...got].sort((x, y) => x - y);
    const b = [...nums].sort((x, y) => x - y);
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    for (let i = 0; i < got.length; i++) {
        if ((got[i] % 2 === 0) !== (i % 2 === 0)) return false;
    }
    return true;
}
""",
        "cpp": """
static bool _valid(const std::vector<int>& got, const std::vector<int>& nums) {
    if (got.size() != nums.size()) return false;
    std::vector<int> _a(got), _b(nums);
    std::sort(_a.begin(), _a.end());
    std::sort(_b.begin(), _b.end());
    if (_a != _b) return false;
    for (size_t _i = 0; _i < got.size(); ++_i) {
        int _p = (got[_i] % 2 == 0) ? 0 : 1;
        int _q = (_i % 2 == 0) ? 0 : 1;
        if (_p != _q) return false;
    }
    return true;
}
""",
        "c": """
static int _valid(int *got, int gotLen, int *nums, int numsSize) {
    if (gotLen != numsSize) return 0;
    /* 多重集相等：按值排序后逐位比。输入不可改，先各拷一份。 */
    int *_a = (int *)malloc(sizeof(int) * (gotLen > 0 ? gotLen : 1));
    int *_b = (int *)malloc(sizeof(int) * (numsSize > 0 ? numsSize : 1));
    for (int _i = 0; _i < gotLen; ++_i) _a[_i] = got[_i];
    for (int _i = 0; _i < numsSize; ++_i) _b[_i] = nums[_i];
    for (int _i = 1; _i < gotLen; ++_i) {
        int _k = _a[_i], _j = _i - 1;
        while (_j >= 0 && _a[_j] > _k) { _a[_j + 1] = _a[_j]; _j--; }
        _a[_j + 1] = _k;
    }
    for (int _i = 1; _i < numsSize; ++_i) {
        int _k = _b[_i], _j = _i - 1;
        while (_j >= 0 && _b[_j] > _k) { _b[_j + 1] = _b[_j]; _j--; }
        _b[_j + 1] = _k;
    }
    int _ok = 1;
    for (int _i = 0; _i < gotLen; ++_i) if (_a[_i] != _b[_i]) { _ok = 0; break; }
    free(_a); free(_b);
    if (!_ok) return 0;
    for (int _i = 0; _i < gotLen; ++_i) {
        int _p = (got[_i] % 2 == 0) ? 0 : 1;
        int _q = (_i % 2 == 0) ? 0 : 1;
        if (_p != _q) return 0;
    }
    return 1;
}
""",
        "java": """
static boolean _valid(int[] got, int[] nums) {
    if (got == null || nums == null || got.length != nums.length) return false;
    int[] a = got.clone(), b = nums.clone();
    java.util.Arrays.sort(a);
    java.util.Arrays.sort(b);
    if (!java.util.Arrays.equals(a, b)) return false;
    for (int i = 0; i < got.length; i++) {
        if ((got[i] % 2 == 0) != (i % 2 == 0)) return false;
    }
    return true;
}
""",
        "csharp": """
static class _Valid {
    public static bool check(int[] got, int[] nums) {
        if (got == null || nums == null || got.Length != nums.Length) return false;
        var a = (int[])got.Clone();
        var b = (int[])nums.Clone();
        System.Array.Sort(a);
        System.Array.Sort(b);
        for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false;
        for (int i = 0; i < got.Length; i++) {
            if ((got[i] % 2 == 0) != (i % 2 == 0)) return false;
        }
        return true;
    }
}
""",
        "golang": """
func _valid(got []int, nums []int) bool {
    if len(got) != len(nums) { return false }
    a := append([]int(nil), got...)
    b := append([]int(nil), nums...)
    sort.Ints(a)
    sort.Ints(b)
    for i := range a { if a[i] != b[i] { return false } }
    for i, x := range got {
        if (x%2 == 0) != (i%2 == 0) { return false }
    }
    return true
}
""",
        "rust": """
fn _valid(got: &Vec<i32>, nums: Vec<i32>) -> bool {
    if got.len() != nums.len() { return false; }
    let mut a = got.clone();
    let mut b = nums.clone();
    a.sort();
    b.sort();
    if a != b { return false; }
    for (i, &x) in got.iter().enumerate() {
        if (x % 2 == 0) != (i % 2 == 0) { return false; }
    }
    true
}
""",
    },

    # q1317 getNoZeroIntegers —— 题面 "If there are many valid solutions,
    # you can return **any** of them"。合法 = 两数之和为 n，且都是**正整数**
    # 且十进制表示里不含 0。
    "no_zero_pair": {
        "python3": """
def _valid(got, n):
    if not isinstance(got, list) or len(got) != 2:
        return False
    a, b = got
    if not isinstance(a, int) or not isinstance(b, int):
        return False
    if a < 1 or b < 1 or a + b != n:
        return False
    return "0" not in str(a) and "0" not in str(b)
""",
        "javascript": """
function _valid(got, n) {
    if (!Array.isArray(got) || got.length !== 2) return false;
    const [a, b] = got;
    if (!Number.isInteger(a) || !Number.isInteger(b)) return false;
    if (a < 1 || b < 1 || a + b !== n) return false;
    return !String(a).includes('0') && !String(b).includes('0');
}
""",
        "cpp": """
static bool _valid(const std::vector<int>& got, int n) {
    if (got.size() != 2) return false;
    long long a = got[0], b = got[1];
    if (a < 1 || b < 1 || a + b != (long long)n) return false;
    return std::to_string(a).find('0') == std::string::npos
        && std::to_string(b).find('0') == std::string::npos;
}
""",
        "c": """
static int _valid(int *got, int gotLen, int n) {
    if (gotLen != 2) return 0;
    long long _a = got[0], _b = got[1];
    if (_a < 1 || _b < 1 || _a + _b != (long long)n) return 0;
    char _buf[32];
    snprintf(_buf, sizeof(_buf), "%lld", _a);
    if (strchr(_buf, '0') != NULL) return 0;
    snprintf(_buf, sizeof(_buf), "%lld", _b);
    return strchr(_buf, '0') == NULL;
}
""",
        "java": """
static boolean _valid(int[] got, int n) {
    if (got == null || got.length != 2) return false;
    long a = got[0], b = got[1];
    if (a < 1 || b < 1 || a + b != (long) n) return false;
    return !String.valueOf(a).contains("0") && !String.valueOf(b).contains("0");
}
""",
        "csharp": """
static class _Valid {
    public static bool check(int[] got, int n) {
        if (got == null || got.Length != 2) return false;
        long a = got[0], b = got[1];
        if (a < 1 || b < 1 || a + b != (long) n) return false;
        return !a.ToString().Contains("0") && !b.ToString().Contains("0");
    }
}
""",
        "golang": """
func _valid(got []int, n int) bool {
    if len(got) != 2 { return false }
    a, b := got[0], got[1]
    if a < 1 || b < 1 || a+b != n { return false }
    return !strings.Contains(strconv.Itoa(a), "0") &&
        !strings.Contains(strconv.Itoa(b), "0")
}
""",
        "rust": """
fn _valid<T: Into<i64>>(got: &Vec<i32>, n: T) -> bool {
    let n: i64 = n.into();
    if got.len() != 2 { return false; }
    let (a, b) = (got[0] as i64, got[1] as i64);
    if a < 1 || b < 1 || a + b != n { return false; }
    !a.to_string().contains('0') && !b.to_string().contains('0')
}
""",
    },

    # q2610 findMatrix —— 题面 "If there are multiple answers, return
    # **any** of them"。合法 = 把 nums 分成若干行，每行内元素互异
    # （行序、行内元素序、以及不同的分组方式都允许）。
    # q2610 findMatrix —— 题面 "If there are multiple answers, return
    # **any** of them"，但有**三个**条件，缺一不可：
    #   1. 只含 nums 里的元素（多重集相等）
    #   2. 每行内元素互异
    #   3. **行数最少** —— 最少行数 = 元素的最大出现次数
    # 第一版漏了第 3 条，接受了行数偏多的答案：实测 q2610 有 6 个槽位从
    # agrees（我们判 WA、LC 也判 WA）变成 false_ac（我们判 AC）。
    # 而我的测试恰好只测了"元素不对 / 行内重复"，没测"行数太多"，所以没抓到
    # —— 这正是"接近正确但不合法"这一类必须配全的原因。
    "find_matrix": {
        "python3": """
def _valid(got, nums):
    if not isinstance(got, list):
        return False
    flat = []
    for row in got:
        if not isinstance(row, list):
            return False
        if len(set(row)) != len(row):
            return False
        flat.extend(row)
    if sorted(flat) != sorted(nums):
        return False
    from collections import Counter
    return len(got) == (max(Counter(nums).values()) if nums else 0)
""",
        "javascript": """
function _valid(got, nums) {
    if (!Array.isArray(got)) return false;
    const flat = [];
    for (const row of got) {
        if (!Array.isArray(row)) return false;
        if (new Set(row).size !== row.length) return false;
        flat.push(...row);
    }
    const a = flat.slice().sort((x, y) => x - y);
    const b = nums.slice().sort((x, y) => x - y);
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    const cnt = new Map();
    for (const x of nums) cnt.set(x, (cnt.get(x) || 0) + 1);
    return got.length === (cnt.size ? Math.max(...cnt.values()) : 0);
}
""",
        "cpp": """
static bool _valid(const std::vector<std::vector<int>>& got,
                   const std::vector<int>& nums) {
    std::vector<int> _flat;
    for (size_t _r = 0; _r < got.size(); ++_r) {
        std::set<int> _s(got[_r].begin(), got[_r].end());
        if (_s.size() != got[_r].size()) return false;
        _flat.insert(_flat.end(), got[_r].begin(), got[_r].end());
    }
    std::sort(_flat.begin(), _flat.end());
    std::vector<int> _b(nums);
    std::sort(_b.begin(), _b.end());
    if (_flat != _b) return false;
    std::map<int, int> _c;
    int _mx = 0;
    for (size_t _i = 0; _i < nums.size(); ++_i) {
        int _v = ++_c[nums[_i]];
        if (_v > _mx) _mx = _v;
    }
    return (int)got.size() == _mx;
}
""",
        "c": """
static int _valid(int **got, int gotLen, int *gotCols, int *nums, int numsSize) {
    int _total = 0;
    for (int _r = 0; _r < gotLen; ++_r) {
        for (int _i = 0; _i < gotCols[_r]; ++_i)
            for (int _j = _i + 1; _j < gotCols[_r]; ++_j)
                if (got[_r][_i] == got[_r][_j]) return 0;
        _total += gotCols[_r];
    }
    if (_total != numsSize) return 0;
    int *_a = (int *)malloc(sizeof(int) * (_total > 0 ? _total : 1));
    int *_b = (int *)malloc(sizeof(int) * (numsSize > 0 ? numsSize : 1));
    int _k = 0;
    for (int _r = 0; _r < gotLen; ++_r)
        for (int _i = 0; _i < gotCols[_r]; ++_i) _a[_k++] = got[_r][_i];
    for (int _i = 0; _i < numsSize; ++_i) _b[_i] = nums[_i];
    for (int _i = 1; _i < _total; ++_i) {
        int _v = _a[_i], _j = _i - 1;
        while (_j >= 0 && _a[_j] > _v) { _a[_j + 1] = _a[_j]; _j--; }
        _a[_j + 1] = _v;
    }
    for (int _i = 1; _i < numsSize; ++_i) {
        int _v = _b[_i], _j = _i - 1;
        while (_j >= 0 && _b[_j] > _v) { _b[_j + 1] = _b[_j]; _j--; }
        _b[_j + 1] = _v;
    }
    int _ok = 1;
    for (int _i = 0; _i < _total; ++_i) if (_a[_i] != _b[_i]) { _ok = 0; break; }
    free(_a); free(_b);
    if (!_ok) return 0;
    /* 条件 3：行数 = 元素的最大出现次数 */
    int _mx = 0;
    for (int _i = 0; _i < numsSize; ++_i) {
        int _c = 0;
        for (int _j = 0; _j < numsSize; ++_j) if (nums[_j] == nums[_i]) _c++;
        if (_c > _mx) _mx = _c;
    }
    return gotLen == _mx;
}
""",
        "java": """
static boolean _valid(java.util.List<java.util.List<Integer>> got, int[] nums) {
    if (got == null) return false;
    java.util.List<Integer> flat = new java.util.ArrayList<Integer>();
    for (java.util.List<Integer> row : got) {
        if (row == null) return false;
        java.util.Set<Integer> s = new java.util.HashSet<Integer>();
        for (int x : row) {
            if (!s.add(x)) return false;
            flat.add(x);
        }
    }
    if (flat.size() != nums.length) return false;
    java.util.List<Integer> b = new java.util.ArrayList<Integer>();
    for (int x : nums) b.add(x);
    java.util.Collections.sort(flat);
    java.util.Collections.sort(b);
    if (!flat.equals(b)) return false;
    java.util.Map<Integer, Integer> cnt = new java.util.HashMap<Integer, Integer>();
    int mx = 0;
    for (int x : nums) {
        int v = cnt.getOrDefault(x, 0) + 1;
        cnt.put(x, v);
        if (v > mx) mx = v;
    }
    return got.size() == mx;
}
""",
        "csharp": """
static class _Valid {
    public static bool check(System.Collections.Generic.IList<System.Collections.Generic.IList<int>> got, int[] nums) {
        if (got == null) return false;
        var flat = new System.Collections.Generic.List<int>();
        foreach (var row in got) {
            if (row == null) return false;
            var s = new System.Collections.Generic.HashSet<int>();
            foreach (int x in row) { if (!s.Add(x)) return false; flat.Add(x); }
        }
        if (flat.Count != nums.Length) return false;
        var b = new System.Collections.Generic.List<int>(nums);
        flat.Sort();
        b.Sort();
        for (int i = 0; i < flat.Count; i++) if (flat[i] != b[i]) return false;
        var cnt = new System.Collections.Generic.Dictionary<int, int>();
        int mx = 0;
        foreach (int x in nums) {
            cnt.TryGetValue(x, out int v);
            v++;
            cnt[x] = v;
            if (v > mx) mx = v;
        }
        return got.Count == mx;
    }
}
""",
        "golang": """
func _valid(got [][]int, nums []int) bool {
    flat := []int{}
    for _, row := range got {
        seen := map[int]bool{}
        for _, x := range row {
            if seen[x] { return false }
            seen[x] = true
            flat = append(flat, x)
        }
    }
    if len(flat) != len(nums) { return false }
    a := append([]int(nil), flat...)
    b := append([]int(nil), nums...)
    sort.Ints(a)
    sort.Ints(b)
    for i := range a { if a[i] != b[i] { return false } }
    cnt := map[int]int{}
    mx := 0
    for _, x := range nums {
        cnt[x]++
        if cnt[x] > mx { mx = cnt[x] }
    }
    return len(got) == mx
}
""",
        "rust": """
fn _valid(got: &Vec<Vec<i32>>, nums: Vec<i32>) -> bool {
    let mut flat: Vec<i32> = Vec::new();
    for row in got.iter() {
        let mut s = std::collections::HashSet::new();
        for &x in row.iter() {
            if !s.insert(x) { return false; }
            flat.push(x);
        }
    }
    if flat.len() != nums.len() { return false; }
    let mut a = flat.clone();
    let mut b = nums.clone();
    a.sort();
    b.sort();
    if a != b { return false; }
    let mut cnt: std::collections::HashMap<i32, usize> =
        std::collections::HashMap::new();
    let mut mx = 0usize;
    for &x in nums.iter() {
        let e = cnt.entry(x).or_insert(0);
        *e += 1;
        if *e > mx { mx = *e; }
    }
    got.len() == mx
}
""",
    },
}


def helper(lang_key: str, qid: int) -> str:
    """该校验器在该语言下的函数源码（无校验器时返回空串）。"""
    name = ANSWER_VALIDATORS.get(qid)
    if not name:
        return ""
    d = _HELPERS.get(name, {})
    src = d.get(lang_key, "")
    return (src + "\n") if src else ""


# Go 里未使用的 import 是**编译错误**，所以校验器需要的包必须按需加，
# 不能无条件塞进 import 块（见 render.go_import_block 的 extra 参数）。
GO_IMPORTS: dict[str, list[str]] = {
    "parity_ii": ["sort"],
    "find_matrix": ["sort"],
    "no_zero_pair": ["strings", "strconv"],
}


def go_imports(qid: int) -> list[str]:
    """该校验器在 Go 下额外需要的包（无校验器时为空）。"""
    return GO_IMPORTS.get(ANSWER_VALIDATORS.get(qid, ""), [])


# --------------------------------------------------------------------------
# 输入快照
# --------------------------------------------------------------------------
# **调用提交之前必须保存输入的副本，checker 只能用副本。**
#
# 否则提交可以原地改写输入再返回它，checker 看到的就是被改过的版本，
# 失去了"必须保留原始元素"的依据。实测 q922：
#
#     class Solution:
#         def sortArrayByParityII(self, nums):
#             for i in range(len(nums)):
#                 nums[i] = 0 if i % 2 == 0 else 1
#             return nums          # 返回 [0,1,0,1]，不是 [2,3,6,7] 的重排
#
# 这段代码曾判 **Accepted** —— 它把 nums 改成了满足奇偶位置要求的样子，
# 而 checker 拿的就是那个被改过的 nums。
#
# 实现方式：**把输入声明复制一份、把变量名从 _a{j} 改成 _s{j}**，
# 让字面量重新求值一次。这样：
#   - 类型自动正确（复用原来的声明，不必按语言写模板）
#   - 数组/列表/Vec/切片/标量都各自得到独立副本
#   - 标量本来就不可变，多算一次也无害
#
# 起初我按语言写了拷贝模板（`.clone()` / `append(...)` / `Clone() as int[]`），
# 结果对**标量**输入全部语法错误（cpp/csharp/golang 共 10 个参考解编译失败），
# 而 Java 因为另有渲染函数根本没接上。改成复用声明后这些问题一并消失。
def snapshot_decls(decls: str, n: int) -> tuple[str, list[str]]:
    """由输入声明生成快照声明。

    `decls` 是输入声明块（每行形如 `T _a{j} = ...;`）。
    返回 (快照声明块, 供 checker 使用的变量名列表)。

    三处细节都是被审查代理 A-007 指出的**静默失效条件**，这里逐个处理：

    ① **变量名用词边界匹配**。原先用 `"_a1" in line` / `line.replace("_a1", ...)`，
       而 `_a1` 是 `_a10`/`_a11` 的**子串** —— 参数 ≥11 个时 j=1 的快照块里会多出
       重复的 `_s10/_s11` 声明，C/C++/Java/C# 直接编译错误（代理用 12 参数合成例
       实测复现）。
    ② **只替换声明名（每行第一次出现）**。原先 `line.replace` 会改到**值里的
       字面量**：`_a0 = "literal containing _a0 text"` 会变成
       `_s0 = "literal containing _s0 text"`，快照值被篡改，等于没有保真证据。
    ③ **匹配不到就报错，不静默退回**。原先没有匹配行时返回 `_a{j}`（未快照的
       原对象）且不报错、不记日志 —— 于是"checker 用快照"这句话在那种情况下是假的，
       而且没人会发现。现在直接 raise。

    仍**未解决**（已在审查记录登记）：C 的 `char* p = buf;` 这一形态复制出来的是
    **别名**而非副本，字符串/字符串数组的原地改写仍会污染证据。当前 4 个校验器
    都没有字符串输入，所以不可达；新增字符串参数的校验器前必须先处理。
    """
    snaps: list[str] = []
    names: list[str] = []
    for j in range(n):
        name = f"_a{j}"
        pat = re.compile(rf"\b{re.escape(name)}\b")     # ① 词边界
        lines = []
        for line in decls.splitlines():
            if "=" in line and pat.search(line):
                # ② 只替换声明名（第一次出现），不动值里的字面量
                lines.append(pat.sub(f"_s{j}", line, count=1))
        if not lines:
            # ③ 宁可大声失败，也不要静默给出"没快照"的证据
            raise ValueError(
                f"快照失败：输入声明里找不到 `{name} = ...` 这一行。"
                f"checker 必须拿到调用前的副本，静默退回未快照的原对象会让"
                f"「用快照」这句话变成假的。声明块：\n{decls}")
        snaps.append("\n".join(lines))
        names.append(f"_s{j}")
    return "\n".join(snaps), names

