"""Reviewed input contracts and independent finite-input answer computations.

These lab-only contracts never relax the formal FT100 publication rules.
Unreviewed problems are queued for review, not assigned guessed constraints.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from local.common import DESCRIPTIONS_DIR

def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

VERSION = 'reviewed-input-and-oracle-v1'
QIDS = (3, 7, 12, 20, 33, 41, 91, 125, 128, 172, 231, 263, 292, 509, 1014)
BINDINGS = Path(__file__).with_name('data') / 'input_contracts.json'


def description(qid):
    files = sorted((DESCRIPTIONS_DIR / str(qid)).glob('*English*.txt'))
    if not files:
        raise ValueError(f'q{qid} 缺英文题面')
    return files[0].read_text(encoding='utf-8')


def require(qid):
    rows = json.loads(BINDINGS.read_text(encoding='utf-8'))
    if qid not in QIDS or str(qid) not in rows:
        raise ValueError(f'q{qid} 待补经过审查的输入约束与独立答案算法')
    if rows[str(qid)]['description_sha256'] != sha(description(qid)):
        raise ValueError(f'q{qid} 题面变化，输入约束和独立答案算法需要复核')
    return rows[str(qid)]


def _integer(value, lo, hi):
    return type(value) is int and lo <= value <= hi


def _text(value, lo, hi, alphabet=None):
    return (type(value) is str and lo <= len(value) <= hi
            and (alphabet is None or all(ch in alphabet for ch in value)))


def _array(value, lo, hi, vmin, vmax):
    return type(value) is list and lo <= len(value) <= hi and all(_integer(v, vmin, vmax) for v in value)


def valid(qid, args):
    """Complete reviewed constraints for this initial set; exact parameter names."""
    if type(args) is not dict:
        return False
    names = {3: ['s'], 7: ['x'], 12: ['num'], 20: ['s'], 33: ['nums', 'target'],
             41: ['nums'], 91: ['s'], 125: ['s'], 128: ['nums'], 172: ['n'],
             231: ['n'], 263: ['n'], 292: ['n'], 509: ['n'], 1014: ['values']}
    if qid not in names or set(args) != set(names[qid]):
        return False
    a = next(iter(args.values()))
    if qid == 3:
        # Printable ASCII is a conservative subset of the stated symbols.
        return _text(a, 0, 50000) and all(32 <= ord(ch) <= 126 for ch in a)
    if qid in (7, 231, 263):
        return _integer(a, -2**31, 2**31 - 1)
    if qid == 12:
        return _integer(a, 1, 3999)
    if qid == 20:
        return _text(a, 1, 10000, '()[]{}')
    if qid == 33:
        nums, target = args['nums'], args['target']
        return (_array(nums, 1, 5000, -10000, 10000) and len(set(nums)) == len(nums)
                and sum(nums[i] > nums[(i+1) % len(nums)] for i in range(len(nums))) <= 1
                and _integer(target, -10000, 10000))
    if qid == 41:
        return _array(a, 1, 100000, -2**31, 2**31 - 1)
    if qid == 91:
        return _text(a, 1, 100, '0123456789')
    if qid == 125:
        return _text(a, 1, 200000) and all(32 <= ord(ch) <= 126 for ch in a)
    if qid == 128:
        return _array(a, 0, 100000, -10**9, 10**9)
    if qid == 172:
        return _integer(a, 0, 10000)
    if qid == 292:
        return _integer(a, 1, 2**31 - 1)
    if qid == 509:
        return _integer(a, 0, 30)
    if qid == 1014:
        return _array(a, 2, 50000, 1, 1000)
    return False


def answer(qid, args):
    if not valid(qid, args):
        raise ValueError('输入违反已审查的题面约束')
    a = next(iter(args.values()))
    if qid == 3:
        # Count each starting position until the first repetition.
        if len(a) > 2000:
            raise ValueError('q3 独立穷举答案限定长度 2000，规模输入待补验证算法')
        best = 0
        for start in range(len(a)):
            seen = set()
            for ch in a[start:]:
                if ch in seen:
                    break
                seen.add(ch)
            best = max(best, len(seen))
        return best
    if qid == 7:
        value = int(str(abs(a))[::-1]) * (-1 if a < 0 else 1)
        return value if -2**31 <= value < 2**31 else 0
    if qid == 12:
        tables = (('', 'M', 'MM', 'MMM'), ('', 'C', 'CC', 'CCC', 'CD', 'D', 'DC', 'DCC', 'DCCC', 'CM'),
                  ('', 'X', 'XX', 'XXX', 'XL', 'L', 'LX', 'LXX', 'LXXX', 'XC'),
                  ('', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX'))
        return ''.join(table[(a // 10**(3-i)) % 10] for i, table in enumerate(tables))
    if qid == 20:
        stack = []
        for ch in a:
            if ch in '([{':
                stack.append(ch)
            elif not stack or stack.pop() != {')': '(', ']': '[', '}': '{'}[ch]:
                return False
        return not stack
    if qid == 33:
        return args['nums'].index(args['target']) if args['target'] in args['nums'] else -1
    if qid == 41:
        seen = set(a)
        return next(v for v in range(1, len(a)+2) if v not in seen)
    if qid == 91:
        ways = [1, int(a[0] != '0')]
        for i in range(1, len(a)):
            ways.append((ways[-1] if a[i] != '0' else 0) + (ways[-2] if 10 <= int(a[i-1:i+1]) <= 26 else 0))
        result = ways[-1]
        if result >= 2**31:
            raise ValueError('q91 该输入答案超出跨语言 int32 范围，暂不发布')
        return result
    if qid == 125:
        text = ''.join(ch.lower() for ch in a if ch.isascii() and ch.isalnum())
        return text == text[::-1]
    if qid == 128:
        values = sorted(set(a))
        best = streak = 0
        previous = None
        for value in values:
            streak = streak + 1 if previous is not None and value == previous + 1 else 1
            best = max(best, streak)
            previous = value
        return best
    if qid == 172:
        total = 0
        for value in range(5, a+1, 5):
            while value % 5 == 0:
                total += 1
                value //= 5
        return total
    if qid == 231:
        return a in {2**i for i in range(31)}
    if qid == 263:
        if a <= 0:
            return False
        for divisor in (2, 3, 5):
            while a % divisor == 0:
                a //= divisor
        return a == 1
    if qid == 292:
        return a % 4 != 0
    if qid == 509:
        left, right = 0, 1
        for _ in range(a):
            left, right = right, left+right
        return left
    if qid == 1014:
        # All pairs for a bounded independent oracle, not the reference's O(n) strategy.
        if len(a) > 1000:
            raise ValueError('q1014 独立穷举答案限定长度 1000，规模输入待补验证算法')
        return max(a[i]+a[j]+i-j for i in range(len(a)) for j in range(i+1, len(a)))
    raise ValueError('no independent oracle')


def fingerprint():
    return sha(Path(__file__).read_text(encoding='utf-8') + BINDINGS.read_text(encoding='utf-8'))
