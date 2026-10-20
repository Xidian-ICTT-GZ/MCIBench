"""Code-MUE kernels; correctness labels never enter the similarity matrix."""
from __future__ import annotations

from collections import Counter
import json
import math
import numpy as np

METHOD = 'code-mue-v1-spec-normalized'


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def normalize_value(value, *, mode='ordered', in_row=False):
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('non-finite behavior value')
        # A transitive partition keeps the equality kernel positive semidefinite.
        return {'float_12_digits': format(value, '.12g')}
    if isinstance(value, list):
        nested = bool(value) and all(isinstance(v, list) for v in value)
        values = [normalize_value(v, mode=mode, in_row=nested or in_row) for v in value]
        if (nested and mode != 'ordered') or (not nested and in_row and mode == 'all_unordered'):
            values.sort(key=stable_json)
        return values
    return value


def token(outcome, *, candidate, probe):
    if outcome['kind'] == 'value':
        return ('value', outcome['semantic_key'])
    if outcome['kind'] == 'exception' and outcome.get('exception_type'):
        return ('exception', outcome['exception_type'])
    # CE, timeouts and unclassified failures must not create false consensus.
    return ('isolated', candidate, probe)


def analyze(candidates):
    n = len(candidates)
    if n < 2:
        return {'method': METHOD, 'uncertainty': None, 'reason': '至少需要两个候选', 'sample_count': n}
    k = len(candidates[0].get('outcomes', []))
    if not k or any(len(c.get('outcomes', [])) != k for c in candidates):
        return {'method': METHOD, 'uncertainty': None, 'reason': '行为签名不完整', 'sample_count': n}
    if any(o['kind'] == 'infrastructure_error' for c in candidates for o in c['outcomes']):
        return {'method': METHOD, 'uncertainty': None, 'reason': '执行环境故障', 'sample_count': n}
    keys = [[token(o, candidate=i, probe=p) for p, o in enumerate(c['outcomes'])]
            for i, c in enumerate(candidates)]
    invalid = [any(o['kind'] == 'compile_error' for o in c['outcomes']) for c in candidates]
    w = np.eye(n)
    for i in range(n):
        for j in range(i):
            if not invalid[i] and not invalid[j]:
                w[i, j] = w[j, i] = sum(a == b for a, b in zip(keys[i], keys[j])) / k
    values, vectors = np.linalg.eigh(w / n)
    if float(values.min()) < -1e-9:
        raise ValueError('behavior kernel is not positive semidefinite')
    values = np.maximum(values, 0)
    values /= values.sum()
    positive = values[values > 1e-15]
    entropy = float(-(positive * np.log(positive)).sum() / math.log(n))
    centrality = np.abs(vectors[:, -1])
    eligible = [i for i, c in enumerate(candidates)
                if not invalid[i] and any(o['kind'] == 'value' for o in c['outcomes'])]
    selected = max(eligible, key=lambda i: (centrality[i], -i)) if eligible else None
    for i, c in enumerate(candidates):
        c['centrality'] = round(float(centrality[i]), 8)
        c['selected'] = i == selected
    return {'method': METHOD, 'uncertainty': round(min(1., max(0., entropy)), 8),
            'sample_count': n, 'probe_count': k, 'matrix': w.tolist(),
            'eigenvalues': values.tolist(), 'selected_candidate': candidates[selected]['id'] if selected is not None else None,
            'mean_pairwise_agreement': round(float((w.sum() - n) / (n * (n - 1))), 8),
            'behavior_groups': len({tuple(row) for row in keys}),
            'outcome_counts': dict(Counter(o['kind'] for c in candidates for o in c['outcomes'])),
            'interpretation': '低不确定性表示当前探测输入下行为集中，不代表代码正确'}


def cross_language(groups):
    out = []
    for i, left in enumerate(groups):
        for right in groups[:i]:
            if left['qid'] != right['qid'] or left['model_id'] != right['model_id']:
                continue
            a, b = left['candidates'], right['candidates']
            if not a or not b or not a[0]['outcomes']:
                continue
            matches = total = 0
            for x in a:
                for y in b:
                    if len(x['outcomes']) != len(y['outcomes']):
                        raise ValueError('cross-language probes differ')
                    for ox, oy in zip(x['outcomes'], y['outcomes']):
                        total += 1
                        matches += int(ox['kind'] == oy['kind'] == 'value' and ox['semantic_key'] == oy['semantic_key'])
            out.append({'qid': left['qid'], 'model_id': left['model_id'],
                        'left': left['language'], 'right': right['language'],
                        'agreement': matches / total, 'comparisons': total,
                        'scope': 'all_candidate_pairs_successful_output_agreement'})
    return out
