# -*- coding: utf-8 -*-
r"""题面约束的**权威**表示：自动解析 + 人工核验的覆盖表 + 显式的"未验证"标记。

为什么要单独一个模块
--------------------
此前约束解析散在 `auto_fuzz.parse_rules` 里，只有自动解析、没有兜底，
结果是**两个方向的错**同时存在（都实测过）：

  漏检（把非法当合法）：
    q2616  {"nums":[0],"p":10}      违反 `0 <= p <= nums.length/2`
    q1922  n=9007199254740991       违反 `n <= 10^15`
    q2140  55 行 brainpower=0       违反 `1 <= brainpower`
    q1014  49000 个元素 >1000       违反 `values[i] <= 1000`
  误拒（把合法当非法）：
    q1014  `2 <= values.length <= 5 * 104` 被截断成上限 5（应为 50000）

四条设计原则
------------
1. **一个来源**：生成、收缩、入库、清理都用 `check()`，不再各写一套。
2. **无法解析的约束显式标记为未验证**，默认**不通过**——宁可拒掉合法用例，
   也不放非法用例进语料。非法用例会让"假设了题面保证"的正确解被判错。
3. **人工核验优先于自动解析**：机器解析不了的语义（如 `pointsi` 指 `questions[i]`
   的第 0 个元素）写进 `VERIFIED` 表。
4. **检查器与生成器不共享同一个错误**：`tests/test_constraints.py` 用手写的
   合法/非法样例验证，样例不来自生成器。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.audit.scale_gap import (_desc_text, _expand_flattened,  # noqa: E402
                                   _normalize_bounds, constraints_block)

# ---------------------------------------------------------------- 自动解析

_NUM = r"-?\d+"
_RE_LEN = re.compile(rf"({_NUM})\s*<=\s*(\w+)\.length\s*<=\s*({_NUM})")
_RE_LEN1 = re.compile(rf"(\w+)\.length\s*<=\s*({_NUM})")
_RE_ELEM = re.compile(rf"({_NUM})\s*<=\s*(\w+)\[[^\]]*\]\s*<=\s*({_NUM})")
_RE_SCALAR = re.compile(rf"({_NUM})\s*<=\s*(\w+)\s*<=\s*({_NUM})")
# 上界引用另一参数长度：`1 <= k <= nums.length`
_RE_SCALAR_LEN = re.compile(rf"({_NUM})\s*<=\s*(\w+)\s*<=\s*(\w+)\.length")
# 上界是另一参数长度的一半：`0 <= p <= nums.length/2`
_RE_SCALAR_HALF = re.compile(rf"({_NUM})\s*<=\s*(\w+)\s*<=\s*(\w+)\.length\s*/\s*(\d+)")
# 链式相等：`n == a.length == b.length`
_RE_CHAIN = re.compile(r"(\w+)(?:\.length)?\s*==\s*(\w+)\.length\s*==\s*(\w+)\.length")
_RE_ALIAS = re.compile(r"(\w+)\.length\s*==\s*(\w+)")
_RE_ALIAS_REV = re.compile(r"(\w+)\s*==\s*(\w+)\.length")
_RE_ROWLEN = re.compile(rf"(\w+)\[i\]\.length\s*(==|<=|>=|<|>)\s*({_NUM})")
# 多名字共享一个区间：`1 <= pointsi, brainpoweri <= 105`
_RE_MULTI = re.compile(rf"({_NUM})\s*<=\s*((?:\w+\s*,\s*)+\w+)\s*<=\s*({_NUM})")

# 结构性判据用：**明确的非约束行**白名单。只有命中这些才不记入 `_unparsed`。
# 白名单要尽量短 —— 每多一条就少发现一类"未知"。
_RE_NON_CONSTRAINT = re.compile(
    r"^\s*$"
    r"|^\s*(?:Follow[- ]?up|Note|Notes|Example|Examples|Explanation|Hint)s?\s*:"
    r"|^\s*Constraints\s*:?\s*$"
    r"|^\s*Custom\s+Test\s+Cases?\b"
    r"|^\s*\d+\s*<=\s*\w+\s*<=\s*\d+\s*$",      # 已被规则消费的纯区间（兜底）
    re.I)

# "The test cases are generated ..." 这类**看起来像散文、其实可能带数值上界**的行。
# 我第一版把整类都当非约束行白名单，结果吞掉了 q2197 的
#   `The test cases are generated such that the values in the final array
#    are less than or equal to 108.`
# —— 它是一条**真实的数值上界**，却既没实现、也不受闸门保护（B 的 B3-002）。
# 现在只有当这行**不含**数字比较/上界措辞时才当非约束行。
_RE_PROSE_GENERATED = re.compile(
    r"^\s*The\s+(?:test\s+)?cases\s+are\s+generated", re.I)
_RE_NUMERIC_GUARANTEE = re.compile(
    r"<=|>=|\bat\s+most\b|\bat\s+least\b|\bless\s+than\b|\bgreater\s+than\b"
    r"|\bup\s+to\b|\bno\s+more\s+than\b|\bno\s+less\s+than\b|\d", re.I)


def _is_non_constraint_line(line: str) -> bool:
    """这一行是否**明确不是**约束（可以不计入"未知"）。"""
    if _RE_NON_CONSTRAINT.search(line):
        return True
    # B3-002：`...cases are generated ...` 只有在**不含数值保证**时才算非约束行
    if _RE_PROSE_GENERATED.search(line):
        return not _RE_NUMERIC_GUARANTEE.search(line)
    return False


def _mentions_non_str_param(qid: int, line: str) -> bool:
    """这一行提到的**主语**参数里，是否有非字符串类型的。

    用于拦掉"把数值属性误当字符集"的情况（B2-003 的 q1323）：
        `num consists of only 6 and 9 digits.`   # num 是 int → 交给"未知"
        `s consists of lowercase letters.`       # s 是 str → 正常走字符集

    **两处必须小心**（审查代理 B 的 B3-001 实测）：

    ① **按词边界匹配，不能用子串**。我第一版写的是 `p.name.lower() in low`，
       q2575 的 `word consists of digits from 0 to 9` 里 **'m' 落在 "from" 里**，
       于是被误判成"提到非字符串参数 m" → 字符集规则整条被弃用
       （`check(2575, {"word":"12a"})` 返回空 = 合法 ✗），还把该题拉进未知集。

    ② **只看主语**。句子里出现的名字未必是这条约束的主语：`nums.length is even`
       提到 nums，但约束的对象是长度。这里取 `consists of / contains / is / are`
       之前的片段作为主语区，减少误判。
    """
    # ② 取主语片段（没有这些关键词就退回整行）
    m = re.search(r"^(.{0,80}?)\b(?:consists?\s+of|contains?|is|are)\b",
                  line, re.I)
    subject = m.group(1) if m else line
    for p in _params(qid):
        # ① 词边界，而不是子串
        if not re.search(rf"\b{re.escape(p.name)}\b", subject, re.I):
            continue
        typ = (getattr(p, "typ", None) or "")
        tname = getattr(typ, "__name__", None) or str(typ)
        # ListT 之类容器：名字里没有 "str"，但元素可能是 str —— 只有在**明确**
        # 非字符串（Int/bool/float）时才判 True，避免把 List[str] 误杀。
        tl = tname.lower()
        if "str" in tl:
            continue
        if any(k in tl for k in ("int", "float", "bool")):
            return True
    return False


CHARSETS = [
    (re.compile(r"digits", re.I), "0123456789"),
    # 下面两条是**必须补的**：漏掉它们会造出**过窄**的字符集 → **误拒合法用例**。
    # 审查代理 B-006 明确警告过"一旦启用会对 q2288/q2390/q1935 产生误拒"，
    # 我第一版确实漏了，在 100 题现有语料上冒出 **57 条误拒**：
    #   q1935 23 条（空格） / q2390 12 条（*） / q2288 11 条（空格、$）
    #   q2129  9 条（大写、空格） / q2138 2 条（真违例，应保留）
    # 宁可**取并集**（偏宽 → 只漏检、不误拒）也不要取窄集合误拒合法输入。
    (re.compile(r"stars?\s*\*|asterisks?", re.I), "*"),
    (re.compile(r"separated by a single space", re.I), " "),
]
# 题面里用引号列出的字面字符：`' '`、`"$"`、`'-'` 等
_RE_QUOTED_CHAR = re.compile(r"['\"]([^'\"\w])['\"]")


def _charset_of(line: str) -> str | None:
    """从一行题面里取出**允许的字符集**；认不出返回 None。

    大小写要**单独**匹配，不能用 `uppercase English letters` 这种相邻模式：
    q2129 的原文是 `uppercase and lowercase English letters`，两个词不相邻 →
    匹配不上 → 集合里缺大写 → 该题 6 条含大写的**合法**用例被误拒（实测）。

    规则：
      - 有大小写限定词 → 按限定词取（q1717 `lowercase English letters`
        → **只有小写**，所以 `AAA` 仍是违例）
      - 没有限定词但说了 `English letters` → 大小写都算
    """
    # lowercase 与 lower case（**两个词**）都要认 —— B 的 B2-004 指出
    # q1472 原文是 lower case English letters，只认一个词会落到
    # English letters 分支、字符集多出 A-Z（过宽 → 漏检）。
    cs = ""
    has_case_word = False
    if re.search(r"\blower\s*case\b", line, re.I):
        cs += "abcdefghijklmnopqrstuvwxyz"
        has_case_word = True
    if re.search(r"\bupper\s*case\b", line, re.I):
        cs += "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        has_case_word = True
    if not has_case_word and re.search(r"\bEnglish letters\b", line, re.I):
        cs += "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for pat, extra in CHARSETS:
        if pat.search(line) and extra not in cs:
            cs += extra
    for ch in _RE_QUOTED_CHAR.findall(line):
        cs += ch
    return cs or None

# 唯一性保证。**这些行不含不等号**，所以此前连 `_unparsed` 都不进 —— 于是
# q1298/q2225/q2332 的违例用例被 scan_corpus 报成"0 条非法"（审查代理 B-002）。
#
# 三种措辞（都从题面原文抄来）：
#   `All values of keys[i] are unique.`        （q1298）
#   `All matches[i] are unique.`               （q2225）
#   `Each element in passengers is unique.`    （q2332）
# 注意这是**两条不同的规则**（我第一版把它们合成一条，导致 q1298 的行内重复检不出）：
#   `All values of X[i] are unique.` -> 每一行**内部**的元素互不相同（q1298）
#   `All X[i] are unique.`           -> 各**行**互不相同（q2225）
_RE_UNIQ_ROW_ELEMS = re.compile(
    r"All\s+values\s+of\s+(?P<name>\w+)\[i\]\s+are\s+unique", re.I)
_RE_UNIQ_ROWS = re.compile(
    r"All\s+(?P<name>\w+)\[i\]\s+are\s+unique", re.I)
_RE_UNIQ_ELEM = re.compile(
    r"Each\s+element\s+in\s+(?P<name>\w+)\s+is\s+unique", re.I)

# 还有一类"没有约束关键字"的保证行：既不含不等号、也不含 unique/sorted/consists。
# 它们同样不能被当成"没有约束"。这里列出一组**必须被识别**的措辞；命中其一却没被
# 上面任何规则消费，就记入 `_unparsed`（= 未知，不默认通过）。
_GUARANTEE_HINT = re.compile(
    r"\bis\s+(?:either|an?\s+integer|unique|positive|non-negative)"
    r"|\bare\s+unique|\bat\s+most\b|\bdistinct\b|\bpermutation\b"
    r"|\bsorted\b|\bconsists?\s+of\b|\bonly\s+contains\b|\bfrom\s+\d+\s+to\s+\d+",
    re.I)



def _exp(n: int) -> int:
    """展开压平的上标，保留符号（-105 -> -100000）。"""
    return -_expand_flattened(-n) if n < 0 else _expand_flattened(n)


def _lenval(v):
    """长度比较用：list/str → 长度；**int → 它的值**；其它 → None（不可比）。

    B-007 的正确修法在这里 —— 关键是**整数取"值"，不是取"十进制位数"**：

        题面 `n == status.length == candies.length`（q1298）
        题面 `m == arrays.length`           （q624，m 是整数参数）

    这里 `n`/`m` 的**数值**就应该等于长度。旧 `_lenof` 返回 `len(str(abs(n)))`，
    于是 `n=2` 被算成长度 1 → `status.length=2 != n.length=1` ✗

    我第一版改成了"整数返回 None（不可比）"，那更糟：它让 q624 的
    `arrays.length=1 != m.length=None` 变成**误报**，把合法用例判非法。
    """
    if isinstance(v, (list, str)):
        return len(v)
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return None


def _first_dup(seq: list):
    """返回第一个重复元素（无重复返回 None）。用于唯一性检查。"""
    seen = set()
    for x in seq:
        try:
            if x in seen:
                return x
            seen.add(x)
        except TypeError:              # 不可哈希（嵌套 list）→ 转 tuple
            k = tuple(x) if isinstance(x, list) else repr(x)
            if k in seen:
                return x
            seen.add(k)
    return None


def _seqlen(v):
    """**仅用于需要"序列长度"语义且不该接受整数的场合**。"""
    return len(v) if isinstance(v, (list, str)) else None


def _lenof(v) -> int:
    """**只在明确需要"整数按字符串长度"时使用**（目前仅 q2269 的特例）。"""
    if isinstance(v, (list, str)):
        return len(v)
    if isinstance(v, int):
        return len(str(abs(v)))
    return 0


# 人工核验过的约束。键为题号，值为规则；这里的规则**覆盖**自动解析的结果。
# 只在机器解析不了、或解析错了的时候才写。
VERIFIED: dict[int, dict] = {
    # 2026-10-13: checked against the repository's complete Constraints blocks.
    # Explicit bounds also cover shared-name syntax the regex parser misses.
    2070: {
        "items": {"min_len": 1, "max_len": 100000, "row_op": "==", "row_len": 2},
        "queries": {"min_len": 1, "max_len": 100000, "min_v": 1, "max_v": 1000000000},
        "_rows": {"items": [{"min": 1, "max": 1000000000}, {"min": 1, "max": 1000000000}]},
        "_verified_lines": ["1 <= pricei, beautyi, queries[j] <= 109"],
    },
    2187: {
        "time": {"min_len": 1, "max_len": 100000, "min_v": 1, "max_v": 10000000},
        "totalTrips": {"min_v": 1, "max_v": 10000000},
        "_verified_lines": ["1 <= time[i], totalTrips <= 107"],
    },
    2200: {
        "key": {"member_of": "nums"},
        "_verified_lines": ["key is an integer from the array nums."],
    },
    2332: {
        "buses": {"min_len": 1, "max_len": 100000, "min_v": 2, "max_v": 1000000000, "uniq_elem": True},
        "passengers": {"min_len": 1, "max_len": 100000, "min_v": 2, "max_v": 1000000000, "uniq_elem": True},
        "_verified_lines": ["2 <= buses[i], passengers[i] <= 109"],
    },
    2398: {
        "chargeTimes": {"min_len": 1, "max_len": 50000, "min_v": 1, "max_v": 100000},
        "runningCosts": {"min_len": 1, "max_len": 50000, "min_v": 1, "max_v": 100000, "len_from": "chargeTimes"},
        "_verified_lines": ["1 <= chargeTimes[i], runningCosts[i] <= 105"],
    },
    2580: {
        "ranges": {"min_len": 1, "max_len": 100000, "min_v": 0, "max_v": 1000000000,
                   "row_op": "==", "row_len": 2, "ordered_rows": True},
        "_verified_lines": ["0 <= starti <= endi <= 109"],
    },
    2597: {
        "nums": {"min_v": 1, "max_v": 1000},
        "k": {"min_v": 1, "max_v": 1000},
        "_verified_lines": ["1 <= nums[i], k <= 1000"],
    },
    2610: {
        "nums": {"min_v": 1, "max_v_from_len": "nums"},
        "_verified_lines": ["1 <= nums[i] <= nums.length"],
    },
    1298: {
        # Full Constraints block reviewed on 2026-10-14. Relative indices and
        # row lengths are checked by _reviewed_relations; no DAG or initial
        # box uniqueness requirement is invented.
        "status": {"min_len": 1, "max_len": 1000, "min_v": 0, "max_v": 1},
        "candies": {"len_from": "status", "min_v": 1, "max_v": 1000},
        "keys": {"len_from": "status", "uniq_row_elems": True},
        "containedBoxes": {"len_from": "status", "uniq_global": True, "uniq_row_elems": True},
        "_verified_lines": ["status[i] is either 0 or 1.",
            "0 <= keys[i].length <= n", "0 <= keys[i][j] < n",
            "0 <= containedBoxes[i].length <= n", "0 <= containedBoxes[i][j] < n",
            "Each box is contained in one box at most.",
            "0 <= initialBoxes.length <= n", "0 <= initialBoxes[i] < n"],
    },
    2145: {
        "lower": {"min_v": -100000, "max_v": 100000},
        "upper": {"min_v": -100000, "max_v": 100000},
        "_verified_lines": ["-105 <= lower <= upper <= 105"],
    },
    2438: {
        "queries": {"row_op": "==", "row_len": 2, "min_v": 0, "ordered_rows": True},
        "_verified_lines": ["0 <= starti <= endi < powers.length"],
    },
    2537: {
        "nums": {"min_len": 1, "max_len": 100000, "min_v": 1, "max_v": 1000000000},
        "k": {"min_v": 1, "max_v": 1000000000},
        "_verified_lines": ["1 <= nums[i], k <= 109"],
    },
    2140: {
        # 题面原文：`1 <= pointsi, brainpoweri <= 105`，**两个元素都是 1..10^5**。
        # pointsi/brainpoweri 是 `questions[i] = [pointsi, brainpoweri]` 的行元素，
        # 不是顶层参数，自动解析无法知道这个对应关系，所以需要人工映射。
        #
        # ⚠️ 这里曾把 brainpower 的上限写成 **4**（凭空编造，无任何依据），
        # 后果是 scan_corpus 把 q2140 的语料从 30 条删到 6 条，其中至少 11 条
        # 是合法的（如 [[5,10],[10,5],[15,1]]、[[1,99],[2,98],...]）。
        # 教训：表名叫 VERIFIED 就必须**逐条对照题面原文核验**，
        # 写下没核验过的数字比不写更危险——它会以"已核验"的名义通过所有检查。
        "_rows": {"questions": [{"min": 1, "max": 100000},
                                {"min": 1, "max": 100000}]},
    },
    2616: {
        # 题面：`0 <= p <= (nums.length)/2`。自动解析给出 p 的无界上界。
        #
        # B-007：这里原本写的是 `min_v_from: 0` —— **一个没人读取的死键**。
        # `check` 只消费 `min_v/max_v/max_len/max_from_len/max_half_of`，
        # 所以「0 <= p」这一半**从未生效**（实测 `check(2616, {"nums":[0],"p":-1})`
        # 返回空 = 合法 ✗）。改成 `min_v` 才真正执行。
        "p": {"min_v": 0, "max_half_of": "nums"},
        # B2-005：**`_verified_lines` 是"人工核验过的原始题面行"清单**。
        # 这一行已被上面的 `min_v` + `max_half_of` **完整覆盖**（`check(p=-1)` 会拒），
        # 但它仍留在 `_unparsed` 里 → 发布闸门**永久误拦** q2616。
        # 把核验过的行逐条列在这里（而不是靠启发式判断"是否已覆盖"），
        # `unparsed()` 会排除它们 —— 精确、可审计。
        "_verified_lines": ["0 <= p <= (nums.length)/2"],
    },
    1014: {
        # 题面：`1 <= values[i] <= 1000`（自动解析已能处理，此处仅作显式记录）
        "values": {"min_v": 1, "max_v": 1000},
    },
}


# ---------------------------------------------------------------- 检查

def parse(qid: int) -> dict:
    """解析题面约束。返回规则字典 + `_unparsed` 列表（无法理解的约束行）。"""
    text = _desc_text(qid)
    block = _normalize_bounds(constraints_block(text))
    rules: dict = {"_charset": None, "_sorted": False, "_perm": False,
                   "_unparsed": []}

    lines = [l.strip() for l in block.splitlines() if l.strip()]
    for line in lines[1:]:                     # 第一行是 "Constraints:"
        consumed = False
        low = line.lower()
        if ("<=" in line or "==" in line or ">=" in line):
            for rx, handler in (
                (_RE_ROWLEN, lambda m: _set(rules, m.group(1),
                                            row_op=m.group(2),
                                            row_len=_exp(int(m.group(3))))),
                (_RE_SCALAR_HALF, lambda m: _set(rules, m.group(2),
                                                 min_v=_exp(int(m.group(1))),
                                                 max_half_of=m.group(3))),
                (_RE_SCALAR_LEN, lambda m: _set(rules, m.group(2),
                                                min_v=_exp(int(m.group(1))),
                                                max_from_len=m.group(3))),
                (_RE_LEN, lambda m: _set(rules, m.group(2),
                                         min_len=_exp(int(m.group(1))),
                                         max_len=_exp(int(m.group(3))))),
                (_RE_LEN1, lambda m: _set(rules, m.group(1),
                                          max_len=_exp(int(m.group(2))))),
                (_RE_ELEM, lambda m: _set(rules, m.group(2),
                                          min_v=_exp(int(m.group(1))),
                                          max_v=_exp(int(m.group(3))))),
                (_RE_MULTI, lambda m: _multi(rules, m)),
                (_RE_SCALAR, lambda m: _set(rules, m.group(2),
                                            min_v=_exp(int(m.group(1))),
                                            max_v=_exp(int(m.group(3))))),
                (_RE_CHAIN, lambda m: _chain(rules, qid, m)),
                (_RE_ALIAS, lambda m: _set(rules, m.group(2),
                                           len_from=m.group(1))),
                (_RE_ALIAS_REV, lambda m: _rev(rules, m)),
            ):
                m = rx.search(line)
                if m:
                    handler(m)
                    consumed = True
                    break
        if not consumed:
            if re.search(r"sorted in ascending order", line, re.I):
                rules["_sorted"] = True
                consumed = True
            elif re.search(r"permutation of", line, re.I):
                rules["_perm"] = True
                consumed = True
            else:
                m = _RE_UNIQ_ROW_ELEMS.search(line)
                if m:
                    _set(rules, m.group("name"), uniq_row_elems=True)
                    consumed = True
                else:
                    m = _RE_UNIQ_ROWS.search(line)
                    if m:
                        _set(rules, m.group("name"), uniq_rows=True)
                        consumed = True
                    else:
                        m = _RE_UNIQ_ELEM.search(line)
                        if m:
                            _set(rules, m.group("name"), uniq_elem=True)
                            consumed = True
            if not consumed:
                # 字符集：**必须用赋值**。此前写的是
                # `rules.setdefault("_charset", cs)`，而 `_charset` 在函数开头已被
                # 初始化为 None —— setdefault 只在键**不存在**时生效，于是 100 题
                # 全是 None，字符集约束从未生效（审查代理 B-006）。
                # 另外 CHARSETS 是"首个匹配"语义，而题面可能同时提到多类字符
                # （q2288 的 letters + digits + 空格 + `$`），所以要取**并集**，
                # 否则启用后会误拒合法用例。
                cs_hit = _charset_of(line)
                # B2-003：字符集只对**字符串参数**有意义。
                # q1323 的 `num consists of only 6 and 9 digits.` 里 num 是 **Int**，
                # 说的是"十进制数字只含 6 和 9"（数值属性），却被这里当成字符集消费掉，
                # 于是规则完全失效、`unparsed(1323)` 也为空 → 连闸门都不拦。
                # 判据：这一行提到的参数里有非字符串类型的 → 不算字符集，留给"未知"。
                if cs_hit is not None and _mentions_non_str_param(qid, line):
                    cs_hit = None
                if cs_hit is not None:
                    prev = rules.get("_charset") or ""
                    merged = "".join(dict.fromkeys(prev + cs_hit))
                    rules["_charset"] = merged
                    consumed = True
        if not consumed and not _is_non_constraint_line(line):
            # **结构性判据**（审查代理 B 的 B2-003 建议）：
            # Constraints 段里**没有被任何规则消费**的行都算"未知"。
            #
            # 此前用的是关键词表（含运算符 或 命中手写 `_GUARANTEE_HINT`），
            # 于是漏掉了：
            #   q2288 `All prices will be positive numbers without leading zeros.`
            #         （`_GUARANTEE_HINT` 只认 `is ... positive`，这里是 `will be positive`）
            #   q2288 `sentence does not have leading or trailing spaces.`
            #   q1323 `num consists of only 6 and 9 digits.`
            #         （被字符集分支当 "digits" 消费成 0-9，而 num 是 Int → 规则完全失效）
            #   q2179 `nums1 and nums2 are permutations of [0, 1, ..., n - 1].`
            #         （复数 `permutations of` 不被 `permutation of` 命中）
            # 漏掉的后果不是"漏检"而是**闸门也不拦** —— 于是它们被当成"没有约束"。
            #
            # 关键词表的问题在于"你只能列出你想到的措辞"。改成结构性判据后，
            # 只有明确的非约束行（Follow-up / Note / 空行）被白名单放过。
            rules["_unparsed"].append(line)

    # 人工核验覆盖
    for k, v in VERIFIED.get(qid, {}).items():
        if k.startswith("_"):
            rules[k] = v
        else:
            rules.setdefault(k, {}).update(v)
    return rules


def _set(rules: dict, name: str, **kw) -> None:
    rules.setdefault(name, {}).update(kw)


def _multi(rules: dict, m) -> None:
    lo, names, hi = _exp(int(m.group(1))), m.group(2), _exp(int(m.group(3)))
    for nm in (x.strip() for x in names.split(",")):
        _set(rules, nm, min_v=lo, max_v=hi)


def _chain(rules: dict, qid: int, m) -> None:
    names = [x for x in m.groups()]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            _set(rules, names[j], len_eq=names[i])


def _rev(rules: dict, m) -> None:
    scalar, lst = m.group(1), m.group(2)
    r = rules.setdefault(lst, {})
    r.setdefault("len_from", scalar)
    sc = rules.get(scalar, {})
    if "min_v" in sc:
        r.setdefault("min_len", sc["min_v"])
    if "max_v" in sc:
        r.setdefault("max_len", sc["max_v"])


def _reviewed_relations(qid: int, args: dict) -> list[str]:
    """Only explicit cross-parameter relations from the reviewed problem text."""
    bad = []
    if qid == 1298 and isinstance(args.get("status"), list):
        n = len(args["status"])
        for name in ("keys", "containedBoxes"):
            for row in args.get(name, []):
                if not isinstance(row, list):
                    bad.append(f"{name}: every entry must be a row")
                    continue
                if len(row) > n:
                    bad.append(f"{name}[i].length exceeds n={n}")
                if any(not isinstance(x, int) or not 0 <= x < n for x in row):
                    bad.append(f"{name}: box index outside [0,{n})")
        initial = args.get("initialBoxes", [])
        if len(initial) > n:
            bad.append(f"initialBoxes.length exceeds n={n}")
        if any(not isinstance(x, int) or not 0 <= x < n for x in initial):
            bad.append(f"initialBoxes: box index outside [0,{n})")
    if qid == 2145 and "lower" in args and "upper" in args and args["lower"] > args["upper"]:
        bad.append("lower must not exceed upper")
    if qid == 2438 and isinstance(args.get("n"), int) and args["n"] > 0:
        # powers is the unique minimal sum decomposition: one power for each
        # set bit. This is an index bound, not the numerical value of n.
        limit = args["n"].bit_count()
        if any(isinstance(row, list) and any(not isinstance(x, int) or not 0 <= x < limit for x in row)
               for row in args.get("queries", [])):
            bad.append(f"queries: index outside powers.length={limit}")
    return bad


def check(qid: int, case: dict, sig_params=None, rules: dict | None = None,
          strict_unparsed: bool = False) -> list[str]:
    """返回违规原因列表；空列表 = 通过。

    **这是全流程唯一的检查入口**：生成、收缩、扫描、入库都必须走它。
    早先 `auto_fuzz.violates_constraints` 是另一份实现，检查器收紧了生成器
    却照旧造非法输入；现在那个函数直接委托到这里（见 auto_fuzz）。

    `strict_unparsed` 默认 **False**，这是有意的：

      「解析不出来的约束」是**未知**，不等于"这条用例违反了它"。把未知当成违规会让
      45 道题的**全部**用例都判不通过 —— `scan_corpus --apply` 会把它们的语料删光
      （本函数第一版就是这么写的，被自测立刻抓到）。

      所以三层分开：
        - `check()`           只报**实际检查出来**的违规
        - `unparsed(q)`       "有未知约束"走独立通道
        - **发布闸门**（`apply_found`、`scan_corpus --apply`）见 `unparsed(q)` 非空就
          **拒绝发布**该题，除非显式 `--allow-unparsed`
      调用方若确实要"未验证即不通过"的语义（入库前逐条复核），显式传 True。

    规范 7.2 的要求（"解析不出来属于未知，不是合法"）由**发布闸门**满足，
    而不是由 check 把未知当成违规来满足。
    """
    rules = rules if rules is not None else parse(qid)
    args = case.get("args", {})
    bad: list[str] = []
    if isinstance(args, dict):
        bad.extend(_reviewed_relations(qid, args))

    if sig_params is None:
        sig_params = _params(qid)

    if strict_unparsed:
        for line in rules.get("_unparsed", []):
            bad.append(f"题面约束未能解析，按未知处理（不默认通过）：{line}")

    # B2-004/B2-008：**设计题也走参数级检查**。
    # 设计题的用例是 `{"ops": [...], "args": [[..], ..]}`，参数挂在每个方法上，
    # 不在顶层 `params` 里 → 此前 `_params(qid)` 为空，参数级规则**一个都不跑**
    # （q1472 的 4 条 URL 违例因此永远检不出）。
    # 这里把两种形态统一成 `(Param, 值)` 序列，**下面同一个循环**处理。
    # 跨参数比较（len_eq / len_from / max_from_len）只在普通题做 ——
    # 设计题的 `args` 是列表，按名索引不成立，所以给它一个空查找表。
    if isinstance(args, dict):
        a_lookup = args
        pairs = [(p, args[p.name]) for p in sig_params if p.name in args]
    else:
        a_lookup = {}
        pairs = design_arg_pairs(qid, case)

    # 人工核验的行内约束
    for name, rows in (rules.get("_rows") or {}).items():
        for row in args.get(name, []) or []:
            if not isinstance(row, list):
                continue
            for idx, spec in enumerate(rows):
                if idx >= len(row) or not isinstance(row[idx], int):
                    continue
                if "min" in spec and row[idx] < spec["min"]:
                    bad.append(f"{name}[i][{idx}]={row[idx]} < {spec['min']}")
                if "max" in spec and row[idx] > spec["max"]:
                    bad.append(f"{name}[i][{idx}]={row[idx]} > {spec['max']}")

    cs = rules.get("_charset")
    for p, v in pairs:
        rl = rules.get(p.name, {})
        member = rl.get("member_of")
        if member and (member not in a_lookup or v not in a_lookup[member]):
            bad.append(f"{p.name} is not an element of {member}")
        if rl.get("ordered_rows") and isinstance(v, list):
            if any(isinstance(row, list) and len(row) == 2 and row[0] > row[1] for row in v):
                bad.append(f"{p.name}: start must not exceed end")

        # ---- 字符集（B-006：此前解析出来却从没人执行）----
        if cs:
            if isinstance(v, str):
                strs = [v]
            elif isinstance(v, list):
                strs = [x for x in _flatten(v) if isinstance(x, str)]
            else:
                strs = []          # 整数等标量没有字符集概念，跳过

            for s in strs:
                off = sorted({ch for ch in s if ch not in cs})
                if off:
                    bad.append(f"{p.name} 含字符集外的字符 {off!r}"
                               f"（题面限定 {cs!r}）")
                    break

        # ---- 唯一性（B-002：q1298/q2225/q2332 的违例此前完全检不出）----
        if rl.get("uniq_global") and isinstance(v, list) \
                and all(isinstance(r, list) for r in v):
            # `Each box is contained in one box at most.`（q1298）
            # 这是**跨行**的全局唯一：所有 containedBoxes[i] 的值合起来不能重复。
            # 措辞特殊（没有 "unique" 字样），自动解析不出来，所以写在 VERIFIED 里。
            # 审查代理 B 的 B2-004 独立判定 q1298 有 **13/29** 条违反它。
            seen_g: set = set()
            for row in v:
                for x in row:
                    if x in seen_g:
                        bad.append(f"{p.name} 的值 {x!r} 在多个 box 里出现"
                                   f"（题面：Each box is contained in one box at most）")
                        break
                    seen_g.add(x)
                else:
                    continue
                break
        if rl.get("uniq_row_elems") and isinstance(v, list) \
                and all(isinstance(r, list) for r in v):
            for row in v:
                dup = _first_dup(row)
                if dup is not None:
                    bad.append(f"{p.name} 的某行内有重复元素 {dup!r}"
                               f"（题面保证 All values of {p.name}[i] are unique）")
                    break
        if rl.get("uniq_rows") and isinstance(v, list) \
                and all(isinstance(r, list) for r in v):
            seen_rows = set()
            for row in v:
                key = tuple(row)
                if key in seen_rows:
                    bad.append(f"{p.name} 有重复的行 {row!r}（题面保证各行唯一）")
                    break
                seen_rows.add(key)
        if rl.get("uniq_elem") and isinstance(v, list):
            flat = [x for x in _flatten(v)]
            dup = _first_dup(flat)
            if dup is not None:
                bad.append(f"{p.name} 有重复元素 {dup!r}（题面保证元素唯一）")

        # ---- 结构性保证：排列 / 有序（B-010：有序要按**行**查）----
        if isinstance(v, list) and v:
            if rules.get("_perm") and all(isinstance(x, int) for x in v):
                if sorted(v) != list(range(len(v))):
                    bad.append(f"{p.name} 不是 [0..{len(v)-1}] 的排列")
            if rules.get("_sorted"):
                if all(isinstance(r, list) for r in v):
                    # 行形式（q624：`arrays[i] is sorted in ascending order`）——
                    # 此前被 `all(isinstance(x,int))` 守卫排除，导致行序违例检不出。
                    for row in v:
                        if all(isinstance(x, int) for x in row) and row != sorted(row):
                            bad.append(f"{p.name} 的某行未按升序排列（题面保证有序）")
                            break
                elif all(isinstance(x, int) for x in v) and v != sorted(v):
                    bad.append(f"{p.name} 未按升序排列（题面保证有序）")

        if not rl:
            continue
        eq = rl.get("len_eq")
        if eq and eq in a_lookup and _lenval(v) != _lenval(args[eq]):
            bad.append(f"{p.name}.length={_lenval(v)} != {eq}.length={_lenval(args[eq])}")
        # ---- 长度跟随另一参数（B-008：生成器用了这个键，检查器却不执行）----
        src = rl.get("len_from")
        if src and src in a_lookup and _lenval(v) != _lenval(args[src]):
            bad.append(f"{p.name}.length={_lenval(v)} != {src}.length="
                       f"{_lenval(args[src])}（题面要求二者相等）")

        if isinstance(v, list):
            n = len(v)
            if "min_len" in rl and n < rl["min_len"]:
                bad.append(f"{p.name}.length={n} < {rl['min_len']}")
            if "max_len" in rl and n > rl["max_len"]:
                bad.append(f"{p.name}.length={n} > {rl['max_len']}")
            lo, hi = rl.get("min_v"), rl.get("max_v")
            length_bound = rl.get("max_v_from_len")
            if length_bound and length_bound in a_lookup:
                hi = min(hi, len(a_lookup[length_bound])) if hi is not None else len(a_lookup[length_bound])
            if lo is not None or hi is not None:
                for x in _flatten(v):
                    if not isinstance(x, int):
                        continue
                    if lo is not None and x < lo:
                        bad.append(f"{p.name}[i]={x} < {lo}")
                        break
                    if hi is not None and x > hi:
                        bad.append(f"{p.name}[i]={x} > {hi}")
                        break
            op, want = rl.get("row_op"), rl.get("row_len")
            if op and want is not None:
                for row in v:
                    if isinstance(row, list) and not _cmp(len(row), op, want):
                        bad.append(
                            f"{p.name}[i].length={len(row)} {op} {want} 不成立")
                        break
        elif isinstance(v, str):
            if "min_len" in rl and len(v) < rl["min_len"]:
                bad.append(f"{p.name}.length={len(v)} < {rl['min_len']}")
            if "max_len" in rl and len(v) > rl["max_len"]:
                bad.append(f"{p.name}.length={len(v)} > {rl['max_len']}")
        elif isinstance(v, int):
            if "min_v" in rl and v < rl["min_v"]:
                bad.append(f"{p.name}={v} < {rl['min_v']}")
            if "max_v" in rl and v > rl["max_v"]:
                bad.append(f"{p.name}={v} > {rl['max_v']}")
            src = rl.get("max_from_len")
            if src and src in a_lookup and v > (_lenval(args[src]) or 0):
                bad.append(f"{p.name}={v} > {src}.length={_lenval(args[src])}")
            src = rl.get("max_half_of")
            if src and src in a_lookup and v > (_lenval(args[src]) or 0) // 2:
                bad.append(f"{p.name}={v} > {src}.length/2={(_lenval(args[src]) or 0)//2}")
    return bad


def _cmp(a: int, op: str, b: int) -> bool:
    return {"==": a == b, "<=": a <= b, ">=": a >= b,
            "<": a < b, ">": a > b}[op]


def _flatten(v):
    for x in v:
        if isinstance(x, list):
            yield from _flatten(x)
        else:
            yield x


_PARAMS: dict[int, list] = {}


def _params(qid: int):
    if qid not in _PARAMS:
        try:
            from local.common import load_snippet
            from local.harness.typespec import parse_python_snippet
            _PARAMS[qid] = list(getattr(
                parse_python_snippet(load_snippet(qid, "python3")), "params", ()))
        except Exception:  # noqa: BLE001
            _PARAMS[qid] = []
    return _PARAMS[qid]


# 设计题的参数表：`{方法名: [Param, ...]}`。
# 审查代理 B（B2-004/B2-008）：`_params(1146/1472/2080/2241)` 全为 **0**，
# 因为设计题的签名是 `DesignSig`（方法调用序列），参数挂在**每个方法**上，
# 不在顶层 `params` 里 —— 于是 `check` 的参数级规则（字符集/唯一性/长度/取值）
# 对 4 道设计题**一个都不跑**。q1472 的 4 条 URL 为 `"p1".."p4"`、
# 违反题面 `'.' or lower case English letters`，永远检不出。
_DESIGN_METHODS: dict[int, dict[str, list]] = {}


def _design_methods(qid: int) -> dict[str, list]:
    if qid not in _DESIGN_METHODS:
        out: dict[str, list] = {}
        try:
            from local.common import load_snippet
            from local.harness.typespec import parse_python_snippet
            sig = parse_python_snippet(load_snippet(qid, "python3"))
            for name, params, _ret in (getattr(sig, "methods", ()) or ()):
                out[name] = list(params)
        except Exception:  # noqa: BLE001
            pass
        _DESIGN_METHODS[qid] = out
    return _DESIGN_METHODS[qid]


def design_arg_pairs(qid: int, case: dict) -> list[tuple]:
    """把设计题用例展开成 `(Param, 值)` 序列，供 `check` 的参数级规则使用。

    用例形态：`{"ops": [...], "args": [[..], [..], ...], "expected": [...]}`
    —— 第 k 个 op 的参数是 `args[k]`。**构造器那一步（ops[0]）也要查**
    （q1472 的 `homepage`、q1146 的 `length` 都在构造器里）。
    """
    methods = _design_methods(qid)
    ops = case.get("ops") or []
    args = case.get("args") or []
    pairs: list[tuple] = []
    for i, (op, a) in enumerate(zip(ops, args)):
        # 第 0 个 op 是**类名**（`BrowserHistory`/`SnapshotArray`），
        # 对应构造器 `__init__`。此前没做这个映射，于是构造器的参数
        # （q1472 的 `homepage`、q1146 的 `length`）完全没被检查 ✗
        key = op if op in methods else ("__init__" if i == 0 else op)
        ps = methods.get(key)
        if not ps:
            continue
        vals = a if isinstance(a, list) else [a]
        for p, v in zip(ps, vals):
            pairs.append((p, v))
    return pairs


def unparsed(qid: int) -> list[str]:
    """返回**尚未核验**的约束行——调用方应据此拒绝发布用例。

    B2-005：`VERIFIED[qid]["_verified_lines"]` 里逐条列出的行是**人工核验过**的
    （规则已在 `VERIFIED` 的参数条目里实现、且 `check` 会执行），它们不算"未知"。
    此前不看这个清单，导致 q2616 的唯一未解析行（已被 `min_v`+`max_half_of`
    完整覆盖）把该题**永久**挡在发布闸门外。
    """
    rules = parse(qid)
    verified = set(VERIFIED.get(qid, {}).get("_verified_lines") or ())
    return [line for line in rules.get("_unparsed", []) if line not in verified]
