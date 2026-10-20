"""Reviewed input/output relations; these are risk checks, not correctness labels."""
from __future__ import annotations

from copy import deepcopy
from collections import Counter

from local.gen_testcases.constraints import check
from local.lab.probes import digest


def rotate(text):
    return ''.join(chr((ord(c) - ord('a') + 1) % 26 + ord('a')) for c in text)


def proposals(qid, probes, limit=2):
    out = []
    seen = {digest(p) for p in probes}
    for index, probe in enumerate(probes):
        args = probe.get('args', {})
        variants = []
        if qid == 1014 and isinstance(args.get('values'), list) and args['values']:
            values = args['values']
            variants.append(('reverse_values', {'values': list(reversed(values))}, '反转数组，最优得分应保持不变', 0))
            offset = 1 if max(values) < 1000 else -1 if min(values) > 1 else None
            if offset is not None:
                variants.append(('shift_values', {'values': [v + offset for v in values]}, '所有元素平移 c，最优得分应平移 2c', offset))
        elif qid == 1957 and isinstance(args.get('s'), str) and args['s'] and all('a' <= c <= 'z' for c in args['s']):
            text = args['s']
            variants += [('reverse_string', {'s': text[::-1]}, '反转输入字符串，结果也应反转', 0),
                         ('rename_letters', {'s': rotate(text)}, '对字母做一一重命名，结果应做相同重命名', 0)]
        for name, transformed, rule, offset in variants:
            case = {'args': transformed}
            key = digest(case)
            if key in seen or check(qid, case):
                continue
            seen.add(key)
            out.append({'name': name, 'rule': rule, 'base_probe_index': index,
                        'base_input_sha256': digest(probe), 'input': case, 'input_sha256': key, 'offset': offset})
    # Prefer distinct reviewed relations before repeating the same relation.
    counts = Counter()
    ranked = []
    for row in out:
        ranked.append((counts[row['name']], row['base_probe_index'], row['name'], row))
        counts[row['name']] += 1
    return [row[3] for row in sorted(ranked, key=lambda item: item[:3])][:limit]


def evaluate(proposal, base, transformed):
    record = {**deepcopy(proposal), 'base_outcome': deepcopy(base), 'outcome': deepcopy(transformed),
              'state': 'not_evaluable', 'passed': None, 'label_source': 'reviewed_metamorphic_relation_not_correctness_oracle'}
    if base['kind'] != 'value':
        record['reason'] = '原输入未成功返回值，不能检查输出关系'
        return record
    if transformed['kind'] != 'value':
        record.update(state='execution_failure', reason='变形输入未成功返回值，保留执行故障证据')
        return record
    value = base['value']
    name = proposal['name']
    if name == 'reverse_values' and type(value) in (int, float):
        expected = value
    elif name == 'shift_values' and type(value) in (int, float):
        expected = value + 2 * proposal['offset']
    elif name == 'reverse_string' and isinstance(value, str):
        expected = value[::-1]
    elif name == 'rename_letters' and isinstance(value, str) and all('a' <= c <= 'z' for c in value):
        expected = rotate(value)
    else:
        record['reason'] = '原输出不满足关系所需的类型或字符范围'
        return record
    passed = transformed['value'] == expected
    record.update(state='passed' if passed else 'violated', passed=passed, relation_expected=expected)
    return record
