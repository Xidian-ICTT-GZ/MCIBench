# -*- coding: utf-8 -*-
"""按题生成"大规模用例"并把通过校验的追加进语料。

背景：审计显示 83–96% 的覆盖缺口是**输入规模不足**——
语料 n 往往比题面约束小 3~4 个数量级，模型的窄整型累加在真实规模下会溢出，
但在我们的规模下碰不到。加"更多同规模用例"无效，必须加"更大规模的用例"。

与 `differential.py` 的关系：这里**复用**它的校验逻辑
（`python_outputs` + `verify_with_lang`，后者已含多语言投票与崩溃守卫），
但不走 `max_cases=30` 截断——大规模用例是**追加**到现有语料，而不是参与筛选。
这正是它能生效的原因：现有 30 个用例保持不变，历史数字仍可比。

用法：
    python -m local.gen_testcases.scale_expand --qids 2270 --dry_run
    python -m local.gen_testcases.scale_expand --qids 2270 --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.common import TESTCASES_DIR, load_json, load_snippet, save_json  # noqa: E402
from local.gen_testcases.differential import (MIN_VOTES, WIDTH_SAFE_LANGS,  # noqa: E402
                                              python_outputs, verify_with_lang)
from local.harness.render import build_entries
from local.harness.typespec import drop_unrepresentable, parse_python_snippet  # noqa: E402

# --------------------------------------------------------------------------
# 每题的规模生成器：只产出 args，期望值由 Python 参考解推导（与主管线一致）
# --------------------------------------------------------------------------

def gen_2270() -> list[dict]:
    """q2270 waysToSplitArray: 1<=n<=1e5, -1e5<=nums[i]<=1e5.

    失效模式：把前缀和/总和累加进 32 位 int，n*|nums[i]| 超过 2^31 时溢出。
    2^31-1 = 2147483647，用 |nums[i]|=1e5 时阈值恰在 n=21474/21475 之间，
    所以围绕这个边界给用例。
    """
    B = 100000
    out = [
        {"args": {"nums": [B] * 100000}},                       # 极限：和 1e10
        {"args": {"nums": [-B] * 100000}},
        {"args": {"nums": [B if i % 2 == 0 else -B for i in range(100000)]}},
        {"args": {"nums": [B] * 21474}},                        # 2147400000 < 2^31-1
        {"args": {"nums": [B] * 21475}},                        # 2147500000 > 2^31-1
        {"args": {"nums": [B] * 30000}},
        {"args": {"nums": [-B] * 30000}},
        {"args": {"nums": [B] * 50000 + [-B] * 50000}},
        {"args": {"nums": [1] * 99999 + [B]}},
        {"args": {"nums": [B] + [0] * 99998 + [B]}},
    ]
    return out


def gen_2187() -> list[dict]:
    """q2187 minimumTime: 1<=time.length<=1e5, 1<=time[i],totalTrips<=1e7.

    失效模式：每次二分检查算 Σ(mid // time[i])，规模大时该和可达 1e12，
    32 位累加器溢出。time 取值拉满、长度拉满都能触发。
    """
    T = 10 ** 7
    B = 10 ** 7
    return [
        {"args": {"time": [1] * 100000, "totalTrips": T}},
        {"args": {"time": [B] * 100000, "totalTrips": T}},
        {"args": {"time": [B] * 99999 + [1], "totalTrips": T}},
        {"args": {"time": [B // 2] * 100000, "totalTrips": T}},
        {"args": {"time": [1] * 50000 + [B] * 50000, "totalTrips": T}},
        {"args": {"time": [9999999] * 100000, "totalTrips": 1}},
    ]


def gen_2575() -> list[dict]:
    """q2575 divisibilityArray: word 为数字串，1<=n<=1e5, 1<=m<=1e9.

    失效模式：前缀余数按 (rem*10 + digit) % m 递推，rem 可达 1e9-1，
    rem*10 超过 2^31 时 32 位溢出。

    **用例必须"敏感"**：全 9 串 + m=1e9 的正确答案是恒 0，溢出后的值也几乎不可能
    恰好为 0，于是正确解与溢出解结果相同，用例白加。要让答案真的出现 1，
    前缀必须能被 m 整除——所以用**尾随若干个 0** 且 **m 取 10 的幂**。
    """
    n = 10 ** 5
    M = 10 ** 9
    return [
        # 末尾 9 个 0 -> 第 n-9 位起余数为 0（真值出现 1）
        {"args": {"word": "9" * (n - 9) + "0" * 9, "m": M}},
        # 18 个 0 -> 连续 18 个位置判 1
        {"args": {"word": "9" * (n - 18) + "0" * 18, "m": M}},
        # 前 9 个 9，其后全 0
        {"args": {"word": "9" * 9 + "0" * (n - 9), "m": M}},
        # 不同数字模式 + 尾随 0
        {"args": {"word": "123456789" * ((n - 9) // 9) + "0" * 9, "m": M}},
        # 低一档的 10 的幂
        {"args": {"word": "9" * (n - 8) + "0" * 8, "m": 10 ** 8}},
        {"args": {"word": "7" * (n - 6) + "0" * 6, "m": 10 ** 6}},
    ]


def gen_1922() -> list[dict]:
    """q1922 countGoodNumbers: 题面 `1 <= n <= 1e15`。

    失效模式：答案要模 1e9+7 的快速幂——对 n 线性循环会超时，快速幂里不取模的
    乘法会溢出，把指数 `(n+1)/2` 截成 int 也会算错（实测 q1922 剩下的那个
    java 槽位正是 `(int)((n+1)/2)` 的截断）。

    注意：以前这里只能取到 2^31-1，因为类型系统一律按 int32 判可表示性，
    更大的 n 会被 `drop_unrepresentable` 丢掉。现在 `declared_bits` 会读各语言的
    **声明类型**（该题 8 种语言全是 64 位，JavaScript 是 53 位），
    实际上限放宽到 **2^53-1**——JavaScript 能精确表示的边界，也是各语言的最小值。
    """
    LIM = 10 ** 15                 # 题面约束上界
    JS = 2 ** 53 - 1               # 实际可用的最紧上限
    return [
        {"args": {"n": LIM}},              # 题面最大
        {"args": {"n": LIM - 1}},          # 奇数：暴露 (n+1)/2 的取整
        {"args": {"n": LIM - 2}},
        {"args": {"n": JS}},               # 逼近 JavaScript 安全上限
        {"args": {"n": JS - 1}},
        {"args": {"n": 10 ** 12}},
        {"args": {"n": 2 ** 31}},          # 刚越过 int32
        {"args": {"n": 2 ** 31 - 1}},
    ]


def gen_2616() -> list[dict]:
    """q2616 minimizeMax: 1<=n<=1e5, 0<=nums[i]<=1e9, 0<=p<=n/2.

    失效模式（**不是溢出，是二分上界取错**）：模型常写
        right = nums[p] - nums[0]
    而正确上界是 nums[n-1] - nums[0]。要让答案**超过** nums[p]-nums[0]，
    得让"被迫配对"里出现一个跨越 p 的大间隔。

    构造（n=2p，p 为偶数）：前 p+1 个元素紧凑（0..p），第 p+1 个元素起跳到
    BIG，于是贪心必须把 (nums[p], BIG) 配成一对，答案 = BIG - p，
    而模型的上界只有 p。取 BIG=1e9、p=50000 -> 真答案 999950000，模型最多搜到 50000。
    """
    n = 100000
    p = n // 2
    BIG = 10 ** 9
    forced = (list(range(p + 1)) + [BIG]
              + [BIG + i for i in range(1, n - p - 1)])
    assert len(forced) == n, len(forced)
    return [
        # 决定性反例：答案远大于 nums[p]-nums[0]
        {"args": {"nums": forced, "p": p}},
        # 同一构造的小尺寸版本，便于定位
        {"args": {"nums": [0, 10, 11, 100], "p": 2}},
        {"args": {"nums": [0, 1, 2, 3, 1000, 1001], "p": 3}},
        # 规模类（覆盖计数/差值溢出）
        {"args": {"nums": list(range(n)), "p": p}},
        {"args": {"nums": [BIG - i for i in range(n)], "p": p}},
        {"args": {"nums": [0] * n, "p": p}},
    ]


def gen_1550() -> list[dict]:
    """q1550 threeConsecutiveOdds: 1<=arr.length<=1000, 1<=arr[i]<=1000.

    两类缺口，都要补：

    1. **下溢边界**：模型常写 `0..=arr.len()-3` / `i <= arr.size()-3`，
       n<3 时无符号下溢成巨大值，随后越界访问 -> LeetCode 判 RE。
       而原语料最短只有 n=3，永远碰不到 -> 必须补 n=1、n=2。
    2. **规模**：拉满 n 与取值。

    （C 的 `for(i=2;i<arrSize;i++) arr[i-3]` 在 n>=3 时读 arr[-1]，
      属越界读但无符号检查时结果不变；LeetCode 靠 sanitizer 报 RE，
      本地无 sanitizer，**这类靠加用例修不了**——见文档。）
    """
    out = []
    for n in (1, 2, 3):
        for pat in ([1] * n, [2] * n, [1] * (n - 1) + [2] if n > 1 else [1]):
            out.append({"args": {"arr": list(pat)}})
    out.append({"args": {"arr": [1, 1, 2]}})
    out.append({"args": {"arr": [2, 1, 1]}})
    out += [
        {"args": {"arr": [1] * 1000}},
        {"args": {"arr": [2] * 1000}},
        {"args": {"arr": [1, 1] + [2] * 998}},
        {"args": {"arr": [2] * 997 + [1, 1, 1]}},
        {"args": {"arr": [1, 2] * 500}},
        {"args": {"arr": [999] * 1000}},
    ]
    # de-duplicate while keeping order
    seen, uniq = set(), []
    for c in out:
        k = tuple(c["args"]["arr"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def gen_2179() -> list[dict]:
    """q2179 goodTriplets(nums1, nums2): 3<=n<=1e5，两者都是 0..n-1 的排列。

    失效模式有两类，都要覆盖：
    1. **答案溢出**：全等排列下好三元组数 = C(n,3)，n=1e5 时约 1.67e14，
       远超 int32（返回类型 8 种语言全是 64 位，JS 上限 2^53 也够）。
    2. **超时**：O(n^2)/O(n^3) 的写法在 n=1e5 下必然超时。

    int32 的越界点落在 C(n,3) 首次超过 2^31-1 的 n，程序化求出并给出前后一对，
    这样"刚好越界/刚好不越"都有覆盖。
    """
    def c3(k: int) -> int:
        return k * (k - 1) * (k - 2) // 6

    nb = 3
    while c3(nb) <= 2 ** 31 - 1:
        nb += 1

    n = 10 ** 5
    ident = list(range(n))
    half = ident[n // 2:] + ident[:n // 2]

    def perm(k: int) -> list[int]:
        return list(range(k))

    return [
        {"args": {"nums1": perm(n), "nums2": perm(n)}},          # 答案 C(n,3) 最大
        {"args": {"nums1": perm(n), "nums2": ident[::-1]}},      # 答案 0
        {"args": {"nums1": perm(n), "nums2": half}},             # 半边旋转
        {"args": {"nums1": perm(n), "nums2": ident[1:] + [0]}},  # 单步旋转
        {"args": {"nums1": perm(nb - 1), "nums2": perm(nb - 1)}},  # 刚好不越 int32
        {"args": {"nums1": perm(nb), "nums2": perm(nb)}},          # 刚好越过
        {"args": {"nums1": perm(3000), "nums2": perm(3000)}},
    ]


def gen_2348() -> list[dict]:
    """q2348 zeroFilledSubarray: 1<=n<=1e5, -1e9<=nums[i]<=1e9.

    失效模式：全零子数组个数 = k(k+1)/2，k=1e5 时答案 5,000,050,000，超过 int32。
    以前这类用例会被 `drop_unrepresentable` 直接丢掉（"答案不可表示"）；
    现在类型系统读各语言的**声明类型**后可用——该题返回类型 8 种语言全是 64 位
    （C `long long`、Java/C# `long`、Go `int64`、Rust `i64`）。

    int32 的精确边界落在 k=65535/65536 之间，成对给出：
        65535*65536/2 = 2,147,450,880  < 2^31-1
        65536*65537/2 = 2,147,516,416  > 2^31-1
    """
    n = 10 ** 5
    return [
        {"args": {"nums": [0] * n}},                     # 答案 5,000,050,000
        {"args": {"nums": [0] * 65536}},                 # 刚好越过 int32
        {"args": {"nums": [0] * 65535}},                 # 刚好不越
        {"args": {"nums": [0] * (n // 2) + [1] + [0] * (n // 2 - 1)}},
        {"args": {"nums": [1] * n}},                     # 答案 0
        {"args": {"nums": [0] * (n - 1) + [10 ** 9]}},
    ]


def gen_2140() -> list[dict]:
    """q2140 mostPoints(questions): 1<=n<=1e5, questions[i]=[points, brainpower]，
    1<=points[i], brainpower[i]<=1e5。返回类型 8 语言全是 64 位。

    失效模式：答案是选取若干题的最大总得分，可达 n * max(points) = 1e10，
    超过 int32；同时 O(n^2) 的 DP 在 1e5 下超时。
    """
    n = 10 ** 5
    P = 10 ** 5
    return [
        {"args": {"questions": [[P, 1]] * n}},          # 隔一取一 -> 5e9
        {"args": {"questions": [[P, 0]] * n}},          # 全取 -> 1e10
        {"args": {"questions": [[1, 0]] * n}},          # 小值对照
        {"args": {"questions": [[P, 2]] * n}},
        {"args": {"questions": [[P, 1] for _ in range(50000)]}},
        {"args": {"questions": [[1, 1]] * n}},
    ]


def gen_2588() -> list[dict]:
    """q2588 beautifulSubarrays(nums): 1<=n<=1e5, 0<=nums[i]<=1e6。
    统计 XOR 为 0 的子数组个数（返回类型 8 语言全是 64 位）。

    失效模式：本质是"前缀 XOR 相等的下标对"，全相同时前缀 XOR 在两值间交替，
    答案约 n^2/4 = 2.5e9，超过 int32。O(n^2) 枚举也会超时。
    """
    n = 10 ** 5
    return [
        {"args": {"nums": [1] * n}},                      # 前缀 XOR 交替 -> 2.5e9
        {"args": {"nums": [0] * n}},                      # 全零 -> C(n+1,2) 更大
        {"args": {"nums": [1, 0] * (n // 2)}},
        {"args": {"nums": [10 ** 6] * n}},
        {"args": {"nums": list(range(1, n + 1))}},        # 前缀 XOR 基本互异
        {"args": {"nums": [1] * 1000}},
    ]


def gen_2537() -> list[dict]:
    """q2537 countGood(nums, k): 1<=n<=1e5, 1<=nums[i],k<=1e9。
    统计"至少有 k 对相等元素"的子数组个数（返回类型 8 语言全是 64 位）。

    失效模式：全相同时每个长度>=2 的子数组都满足，答案 = C(n,2) ≈ 5e9，超过 int32。
    """
    n = 10 ** 5
    return [
        {"args": {"nums": [1] * n, "k": 1}},              # 答案 C(n,2) ≈ 5e9
        {"args": {"nums": [1] * n, "k": n}},              # 需整个数组
        {"args": {"nums": [1, 2] * (n // 2), "k": 1}},
        {"args": {"nums": list(range(1, n + 1)), "k": 1}},  # 无重复 -> 0
        {"args": {"nums": [1] * 65536, "k": 1}},          # 越过 int32 的规模
    ]


def gen_2390() -> list[dict]:
    """q2390 removeStars(s): 1<=s.length<=1e5。

    失效模式：朴素实现每删一个 '*' 就整体搬移字符串，O(n^2) 超时；
    题面保证"操作总能执行"，所以不能以 '*' 开头。

    合法且压力最大的形态是 `a*` 重复：一半字符是星号，每次删除都紧跟一个字母。
    """
    n = 10 ** 5
    pairs = n // 2
    return [
        {"args": {"s": "a*" * pairs}},                    # 100000 字符
        {"args": {"s": "a" * pairs + "*" * pairs}},       # 后半全星号
        {"args": {"s": "ab*" * (n // 3)}},
        {"args": {"s": "a" * n}},                         # 无星号
        {"args": {"s": "abc*" * (n // 4)}},
    ]


def gen_2009() -> list[dict]:
    """q2009 minOperations(nums): 1<=n<=1e5, 1<=nums[i]<=1e9。答案 <= n。

    失效模式：把数组变成"连续"的最少操作数，朴素 O(n^2) 在 1e5 下超时。
    值域拉满还能顺带压到排序/去重实现。
    """
    n = 10 ** 5
    return [
        {"args": {"nums": list(range(1, n + 1))}},            # 已连续 -> 0
        {"args": {"nums": [1] * n}},                          # 全同 -> n-1
        {"args": {"nums": list(range(0, 2 * n, 2))}},         # 稀疏
        {"args": {"nums": [10 ** 9 - i for i in range(n)]}},
        {"args": {"nums": sorted((i * 977) % (10 ** 9) for i in range(n))}},
        {"args": {"nums": [1, 10 ** 9] * (n // 2)}},
    ]


def gen_2145() -> list[dict]:
    """q2145 numberOfArrays(differences, lower, upper):
    n<=1e5，|differences[i]|<=1e5，|lower|,|upper|<=1e5。

    失效模式：由差分还原前缀和时，前缀可累积到 n*1e5 = 1e10，**超过 int32**，
    32 位累加器会溢出（实测该题有 3 个 Runtime Error 槽位）。
    """
    n = 10 ** 5
    D = 10 ** 5
    return [
        {"args": {"differences": [D] * n, "lower": -D, "upper": D}},   # 前缀 1e10
        {"args": {"differences": [-D] * n, "lower": -D, "upper": D}},
        {"args": {"differences": [D, -D] * (n // 2), "lower": -D, "upper": D}},
        {"args": {"differences": [D] * n, "lower": -D, "upper": D - 1}},
        {"args": {"differences": [0] * n, "lower": -D, "upper": D}},
        {"args": {"differences": [1] * n, "lower": -D, "upper": D}},
    ]


def gen_1673() -> list[dict]:
    """q1673 mostCompetitive(nums, k): 1<=n<=1e5, 1<=k<=n。

    两类缺口：

    1. **规模**：单调栈，朴素贪心 O(n*k) 在 1e5 下超时。
    2. **小值域并列**：实测模型在**值域小、元素重复多**时会选错
       （`find_divergence.py --qid 1673` 定向搜索找到
       `nums=[9,8,6,8,2,8,2,8,8,0,7], k=3`，参考解 [2,0,7]，模型给别的）。
       这类只有靠"小值域随机对拍"才能发现——放大规模永远碰不到。
    """
    n = 10 ** 5
    k = n // 2
    return [
        {"args": {"nums": list(range(n, 0, -1)), "k": k}},       # 严格递减
        {"args": {"nums": list(range(1, n + 1)), "k": k}},       # 严格递增
        {"args": {"nums": [9] * n, "k": k}},
        {"args": {"nums": [i % 1000 for i in range(n)], "k": k}},
        {"args": {"nums": list(range(n, 0, -1)), "k": n}},       # k=n 全取
        {"args": {"nums": list(range(n, 0, -1)), "k": 1}},
        # 定向搜索找到的并列场景（小值域，重复多）
        {"args": {"nums": [9, 8, 6, 8, 2, 8, 2, 8, 8, 0, 7], "k": 3}},
        {"args": {"nums": [1, 1, 1, 1, 1], "k": 3}},
        {"args": {"nums": [2, 2, 1, 1], "k": 2}},
        {"args": {"nums": [3, 2, 1, 3, 2, 1], "k": 4}},
        {"args": {"nums": [0, 0, 0, 1, 0], "k": 3}},
    ]


def gen_1957() -> list[dict]:
    """q1957 makeFancyString(s): 1<=s.length<=1e5，只含小写字母。

    失效模式：朴素实现每步都做字符串拼接/切片，O(n^2) 超时。
    全同字符是最坏情况（每个位置都要判断）。
    """
    n = 10 ** 5
    return [
        {"args": {"s": "a" * n}},                    # 全同，最坏
        {"args": {"s": "ab" * (n // 2)}},
        {"args": {"s": "aab" * (n // 3)}},
        {"args": {"s": ("abcdefghij" * (n // 10))}},
        {"args": {"s": "a" * (n // 2) + "b" * (n // 2)}},
    ]


def gen_1717() -> list[dict]:
    """q1717 maximumGain(s, x, y): 1<=s.length<=1e5, 1<=x,y<=1e4。

    失效模式：先删高分对再删低分对，朴素的"反复扫描删除"是 O(n^2)；
    x/y 拉满让得分规模也变大。
    """
    n = 10 ** 5
    return [
        {"args": {"s": "ab" * (n // 2), "x": 10 ** 4, "y": 10 ** 4}},
        {"args": {"s": "ba" * (n // 2), "x": 10 ** 4, "y": 10 ** 4}},
        {"args": {"s": "a" * (n // 2) + "b" * (n // 2), "x": 10 ** 4, "y": 10 ** 4}},
        {"args": {"s": "ab" * (n // 2), "x": 1, "y": 10 ** 4}},
        {"args": {"s": "ab" * (n // 2), "x": 10 ** 4, "y": 1}},
        {"args": {"s": "c" * n, "x": 10 ** 4, "y": 10 ** 4}},   # 无分数
    ]


def gen_1014() -> list[dict]:
    """q1014 maxScoreSightseeingPair(values): 2<=n<=5e4, 1<=values[i]<=1000。

    失效模式：得分 values[i]+values[j]+i-j 最大，朴素 O(n^2) 在 5e4 下超时
    （5e4^2 = 2.5e9）。
    """
    n = 5 * 10 ** 4
    return [
        {"args": {"values": [1000] * n}},                  # 最坏规模
        {"args": {"values": [1] * n}},
        {"args": {"values": [1, 1000] * (n // 2)}},
        {"args": {"values": list(range(1, n + 1))}},
        {"args": {"values": [1000 - (i % 1000) for i in range(n)]}},
    ]


SCALE_GENERATORS: dict[int, callable] = {
    2270: gen_2270,
    2187: gen_2187,
    2575: gen_2575,
    1922: gen_1922,
    2616: gen_2616,
    1550: gen_1550,
    2348: gen_2348,
    2179: gen_2179,
    2140: gen_2140,
    2588: gen_2588,
    2537: gen_2537,
    2390: gen_2390,
    2009: gen_2009,
    2145: gen_2145,
    1673: gen_1673,
    1957: gen_1957,
    1717: gen_1717,
    1014: gen_1014,
}


# --------------------------------------------------------------------------

def validate(qid: int, candidates: list[dict], backend: str,
             verbose: bool) -> tuple[list[dict], dict]:
    """跑与主管线相同的校验，返回 (可入库用例, 统计)。"""
    sig = parse_python_snippet(load_snippet(qid, "python3"))
    # 按各语言的**声明类型**判可表示性，否则 64 位的题（如 q1922 的 `long n`）
    # 会在这里被误丢。
    kept, dropped_oom = drop_unrepresentable(sig, candidates, build_entries(qid))
    stats = {"candidates": len(candidates),
             "dropped_unrepresentable": len(dropped_oom)}

    py = python_outputs(qid, kept, backend)
    idx = [i for i, o in enumerate(py) if o is not None]
    stats["dropped_python_failed"] = len(kept) - len(idx)
    cases = [dict(kept[i], expected=py[i]) for i in idx]
    expected = [c["expected"] for c in cases]

    voters: list[list[str]] = [["python3"] for _ in cases]
    for lang in ("c", "cpp", "java", "rust", "csharp"):
        if not cases:
            break
        agreed, reason, crashed = verify_with_lang(
            qid, lang, cases, expected, backend, verbose)
        if not agreed:
            if verbose and reason:
                print(f"    {lang}: 不投票 ({reason[:90]})")
            continue
        for i in agreed:
            voters[i].append(lang)
        if verbose:
            print(f"    {lang}: 认可 {len(agreed)}/{len(cases)}，"
                  f"崩溃用例 {len(crashed)}")

    accepted, rejected = [], {"low_votes": 0, "no_width_safe": 0}
    for i, c in enumerate(cases):
        v = voters[i]
        if len(v) < MIN_VOTES:
            rejected["low_votes"] += 1
            continue
        if not (set(v) & set(WIDTH_SAFE_LANGS)):
            rejected["no_width_safe"] += 1
            continue
        accepted.append(dict(c, votes=v))
    stats.update(rejected)
    stats["accepted"] = len(accepted)
    return accepted, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qids", required=True)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--dry_run", action="store_true",
                    help="只生成并校验，不写入语料")
    ap.add_argument("--apply", action="store_true", help="把通过的用例追加进语料")
    ap.add_argument("--allow-unparsed", action="store_true",
                    help="即使题面有解析不出来的约束也发布（默认拒绝）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    qids = [int(x) for x in args.qids.split(",") if x.strip()]
    for qid in qids:
        gen = SCALE_GENERATORS.get(qid)
        if gen is None:
            print(f"q{qid}: 没有规模生成器，跳过")
            continue
        cand = gen()
        print(f"\nq{qid}: 生成 {len(cand)} 个大规模候选")
        accepted, stats = validate(qid, cand, args.backend, args.verbose)
        print(f"  校验通过 {stats['accepted']}/{stats['candidates']}  {stats}")
        for c in accepted[:3]:
            dims = ", ".join(
                f"{k}={len(v)}" if isinstance(v, (list, str)) else f"{k}={v}"
                for k, v in c["args"].items())
            exp = str(c["expected"])
            print(f"    {dims}  ->  expected={exp[:40]}"
                  f"{'...' if len(exp) > 40 else ''}")

        if args.apply and accepted:
            # ---- B-009：这条入库路径此前**绕过约束检查、也不备份** ----
            # 27 道题有 `.bak_pre_scale`，说明这条路径被大量使用；但它只做
            # `drop_unrepresentable` + 参考解投票，**从不调用约束检查器**，
            # 然后直接 `save_json(old + accepted)`：
            #   - 生成器一旦造出违反题面的输入，非法用例直接入库
            #   - 没有备份 → 无法回滚（规范 7.2「可回滚的暂存与原子替换」）
            #   - 非原子写 → 中断会留下半截语料
            from local.gen_testcases.constraints import check as _c_check
            from local.gen_testcases.constraints import parse as _c_parse
            illegal = [c for c in accepted if _c_check(qid, c)]
            if illegal:
                print(f"  **{len(illegal)} 条候选违反题面约束，全部拒绝入库**")
                for c in illegal[:3]:
                    print(f"    {json.dumps(c.get('args', {}), ensure_ascii=False)[:70]}"
                          f"  <- {_c_check(qid, c)[0][:60]}")
                accepted = [c for c in accepted if not _c_check(qid, c)]
            if not accepted:
                print("  没有被接受的候选，不写盘")
                continue
            # D4（B-106，P2）：这里原来读 `_c_parse(qid).get("_unparsed")`
            # —— **原始**列表，没有过滤 `VERIFIED[qid]["_verified_lines"]`，
            # 于是 q2616 也被这条路径误拦（B 实测 `scale_expand --apply --qids 2616`
            # 被拦、加 --allow-unparsed 才写）。改用过滤后的 `unparsed(qid)`。
            from local.gen_testcases.constraints import unparsed as _c_unparsed
            unp = _c_unparsed(qid)
            if unp and not args.allow_unparsed:
                print(f"  **该题有 {len(unp)} 行约束未能解析，按未知处理，拒绝发布**")
                for line in unp[:2]:
                    print(f"    {line[:86]}")
                print("    （确实要发布请加 --allow-unparsed）")
                continue
            p = TESTCASES_DIR / str(qid) / "cases.json"
            old = load_json(p) if p.exists() else []
            from local.gen_testcases.corpus_io import publish_checked_cases
            old_bytes = p.read_bytes() if p.exists() else None
            old = json.loads(old_bytes) if old_bytes is not None else []
            publish_checked_cases(p, old + accepted, old_bytes, "scale_expand",
                                  allow_unparsed=args.allow_unparsed)
            print(f"  已验证并追加 {len(accepted)} 条 -> {p}（原 {len(old)} 条）")


if __name__ == "__main__":
    main()
