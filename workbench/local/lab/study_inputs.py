"""Independent small-domain oracles for a frozen, exploratory existing-topic study."""
from __future__ import annotations

from collections import Counter, deque
import itertools
import random

from local.common import load_snippet
from local.harness.typespec import parse_python_snippet, PlainSig
from local.gen_testcases.constraints import check
from local.lab.probes import inputs, digest

QIDS = (781, 1103, 1277, 1287, 1323, 1394, 1399, 1493, 1695, 1702,
        1793, 1884, 1920, 1935, 1963, 1969, 2073, 2094, 2138, 2225)


def oracle(qid, values):
    a = values[0]
    if qid == 781:
        return sum(((count + answer) // (answer + 1)) * (answer + 1) for answer, count in Counter(a).items())
    if qid == 1103:
        candies, people = values
        out = [0] * people
        turn = 0
        while candies:
            amount = min(candies, turn + 1)
            out[turn % people] += amount
            candies -= amount
            turn += 1
        return out
    if qid == 1277:
        return sum(all(a[i + x][j + y] == 1 for x in range(k) for y in range(k))
                   for k in range(1, min(len(a), len(a[0])) + 1)
                   for i in range(len(a) - k + 1) for j in range(len(a[0]) - k + 1))
    if qid == 1287:
        return next(value for value, count in Counter(a).items() if 4 * count > len(a))
    if qid == 1323:
        text = str(a)
        return max([a] + [int(text[:i] + '9' + text[i+1:]) for i, c in enumerate(text) if c == '6'])
    if qid == 1394:
        return max([value for value, count in Counter(a).items() if value == count] or [-1])
    if qid == 1399:
        counts = Counter(sum(map(int, str(n))) for n in range(1, a + 1))
        return sum(size == max(counts.values()) for size in counts.values())
    if qid == 1493:
        longest = 0
        for deleted in range(len(a)):
            run = 0
            for bit in a[:deleted] + a[deleted+1:]:
                run = run + 1 if bit == 1 else 0
                longest = max(longest, run)
        return longest
    if qid == 1695:
        return max(sum(a[i:j]) for i in range(len(a)) for j in range(i+1, len(a)+1)
                   if len(set(a[i:j])) == j - i)
    if qid == 1702:
        seen, queue = {a}, deque([a])
        while queue:
            text = queue.popleft()
            for i in range(len(text) - 1):
                pair = text[i:i+2]
                if pair not in ('00', '10'):
                    continue
                changed = text[:i] + ('10' if pair == '00' else '01') + text[i+2:]
                if changed not in seen:
                    seen.add(changed)
                    queue.append(changed)
        return max(seen)
    if qid == 1793:
        k = values[1]
        return max(min(a[i:j]) * (j-i) for i in range(k+1) for j in range(k+1, len(a)+1))
    if qid == 1884:
        attempts = 0
        while attempts * (attempts + 1) // 2 < a:
            attempts += 1
        return attempts
    if qid == 1920:
        return [a[a[i]] for i in range(len(a))]
    if qid == 1935:
        return sum(not (set(word) & set(values[1])) for word in a.split(' '))
    if qid == 1963:
        def balanced(text):
            depth = 0
            for c in text:
                depth += 1 if c == '[' else -1
                if depth < 0:
                    return False
            return depth == 0
        queue, seen = deque([(a, 0)]), {a}
        while queue:
            text, distance = queue.popleft()
            if balanced(text):
                return distance
            for i in range(len(text)):
                for j in range(i+1, len(text)):
                    if text[i] == text[j]:
                        continue
                    chars = list(text)
                    chars[i], chars[j] = chars[j], chars[i]
                    changed = ''.join(chars)
                    if changed not in seen:
                        seen.add(changed)
                        queue.append((changed, distance+1))
        raise ValueError('unbalanced bracket counts')
    if qid == 1969:
        mod = 1000000007
        return ((2**a - 1) * pow(2**a - 2, 2**(a-1) - 1, mod)) % mod
    if qid == 2073:
        tickets, target = list(a), values[1]
        queue, elapsed = deque(range(len(tickets))), 0
        while queue:
            index = queue.popleft()
            tickets[index] -= 1
            elapsed += 1
            if tickets[index] == 0:
                if index == target:
                    return elapsed
            else:
                queue.append(index)
    if qid == 2094:
        return sorted({100*a[i] + 10*a[j] + a[k] for i, j, k in itertools.permutations(range(len(a)), 3)
                       if a[i] and a[k] % 2 == 0})
    if qid == 2138:
        text, k, fill = values
        return [text[i:i+k].ljust(k, fill) for i in range(0, len(text), k)]
    if qid == 2225:
        players = {p for match in a for p in match}
        losses = Counter(loser for _, loser in a)
        return [sorted(p for p in players if losses[p] == count) for count in (0, 1)]
    raise ValueError(f'no reviewed independent oracle for q{qid}')


def positional_cases(qid, seed):
    rng = random.Random(seed + qid)
    if qid == 1323:
        return [(int(''.join(chars)),) for length in range(1, 5) for chars in itertools.product('69', repeat=length)]
    if qid in (1493, 1702):
        return [(list(map(int, bits)) if qid == 1493 else ''.join(bits),)
                for length in range(1, 7) for bits in itertools.product('01', repeat=length)]
    if qid == 1963:
        out = []
        for length in (2, 4, 6, 8):
            for positions in itertools.combinations(range(length), length//2):
                chosen = set(positions)
                out.append((''.join('[' if i in chosen else ']' for i in range(length)),))
        return out
    if qid == 1969:
        return [(p,) for p in range(1, 61)]
    out = []
    for _ in range(64):
        n = rng.randint(1, 18)
        if qid == 781:
            item = ([rng.randint(0, 7) for _ in range(n)],)
        elif qid == 1103:
            item = (rng.randint(1, 1000), rng.randint(1, 12))
        elif qid == 1277:
            item = ([[rng.randint(0, 1) for _ in range(rng.randint(1, 6))] for _ in range(rng.randint(1, 6))],)
            width = len(item[0][0])
            item = ([[rng.randint(0, 1) for _ in range(width)] for _ in item[0]],)
        elif qid == 1287:
            n = rng.randint(5, 24)
            winner = rng.randint(0, 100)
            item = (sorted([winner] * (n//4+1) + list(range(1000, 1000+n-n//4-1))),)
        elif qid == 1394:
            item = ([rng.randint(1, 9) for _ in range(n)],)
        elif qid == 1399:
            item = (rng.randint(1, 10000),)
        elif qid == 1695:
            item = ([rng.randint(1, 9) for _ in range(n)],)
        elif qid == 1793:
            item = ([rng.randint(1, 30) for _ in range(n)], rng.randrange(n))
        elif qid == 1884:
            item = (rng.randint(1, 1000),)
        elif qid == 1920:
            permutation = list(range(n))
            rng.shuffle(permutation)
            item = (permutation,)
        elif qid == 1935:
            words = [''.join(rng.choice('abcde') for _ in range(rng.randint(1, 6))) for _ in range(rng.randint(1, 8))]
            item = (' '.join(words), ''.join(rng.sample('abcde', rng.randint(0, 5))))
        elif qid == 2073:
            item = ([rng.randint(1, 9) for _ in range(n)], rng.randrange(n))
        elif qid == 2094:
            item = ([rng.randint(0, 9) for _ in range(rng.randint(3, 10))],)
        elif qid == 2138:
            item = (''.join(rng.choice('abcxyz') for _ in range(n)), rng.randint(1, 9), rng.choice('az'))
        elif qid == 2225:
            pairs = [(a, b) for a in (1, 2, 10, 20, 100) for b in (1, 2, 10, 20, 100) if a != b]
            item = ([list(pair) for pair in rng.sample(pairs, rng.randint(1, len(pairs)))],)
        else:
            raise ValueError(f'unsupported question {qid}')
        out.append(item)
    return out


def cases_for(qid, seed, probe_inputs):
    signature = parse_python_snippet(load_snippet(qid, 'python3'))
    if not isinstance(signature, PlainSig):
        raise ValueError('study requires plain, reviewed interfaces')
    names = [p.name for p in signature.params]
    forbidden = {digest(p) for p in probe_inputs}
    unique = {}
    for positional in positional_cases(qid, seed):
        if len(positional) != len(names):
            raise ValueError('independent oracle signature mismatch')
        case = {'args': dict(zip(names, positional)), 'expected': oracle(qid, positional)}
        errors = check(qid, case, sig_params=signature.params)
        if errors:
            raise ValueError(f'q{qid} independent input is not verified legal: {errors}')
        key = digest(inputs(case))
        if key not in forbidden:
            unique[key] = case
    if len(unique) < 10:
        raise ValueError(f'q{qid} has too few independent validation inputs')
    return [unique[key] for key in sorted(unique)]
