"""Answer-blind, deterministic coverage selection with reserved validation inputs."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import math

from local.gen_testcases.constraints import check, parse
from local.lab.metrics import stable_json
from local.lab import input_contracts
from local.lab import source_guard
source_guard.register(__file__)

VERSION = 'coverage-balanced-probes-v2-reviewed-contracts'


def inputs(case):
    return {k: deepcopy(case[k]) for k in ('args', 'ops') if k in case}


def digest(value):
    return hashlib.sha256(stable_json(value).encode('utf-8')).hexdigest()


def numbers(value):
    if type(value) in (int, float):
        yield value
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from numbers(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from numbers(child)


def features(value, rules):
    tags = set()
    def walk(item, path, rule):
        if isinstance(item, dict):
            for key, child in sorted(item.items()):
                walk(child, str(key) if not path else path + '.' + str(key), rules.get(key, {}) if path == '' else {})
            return
        if isinstance(item, (list, str)):
            length = len(item)
            tags.add(f'length:{path}:{0 if length == 0 else int(math.log10(length)) + 1}')
            for bound in ('min_len', 'max_len'):
                if isinstance(rule.get(bound), (int, float)) and length == rule[bound]:
                    tags.add(f'boundary:{path}:{bound}')
            if isinstance(item, list) and item:
                primitive = all(type(x) in (int, float, str, bool) for x in item)
                if primitive:
                    unique = len(set(item))
                    tags.add(f'structure:{path}:' + ('all_equal' if unique == 1 else 'unique' if unique == length else 'duplicates'))
                    if all(type(x) in (int, float) for x in item):
                        if all(a <= b for a, b in zip(item, item[1:])):
                            tags.add(f'structure:{path}:ascending')
                        if all(a >= b for a, b in zip(item, item[1:])):
                            tags.add(f'structure:{path}:descending')
                else:
                    tags.add(f'structure:{path}:nested')
                    sizes = [len(x) for x in item if isinstance(x, (list, dict, str))]
                    if sizes:
                        tags.add(f'structure:{path}:' + ('regular_rows' if min(sizes) == max(sizes) else 'ragged_rows'))
            if isinstance(item, str) and item:
                tags.add(f'structure:{path}:' + ('one_character' if len(set(item)) == 1 else 'multiple_characters'))
                if any(a == b for a, b in zip(item, item[1:])):
                    tags.add(f'structure:{path}:adjacent_repetition')
        values = list(numbers(item))
        if values:
            for label, predicate in (('zero', lambda n: n == 0), ('negative', lambda n: n < 0), ('positive', lambda n: n > 0)):
                if any(predicate(n) for n in values):
                    tags.add(f'value:{path}:{label}')
            magnitude = max(abs(n) for n in values)
            tags.add(f'value:{path}:magnitude:{0 if magnitude < 1 else int(math.log10(magnitude)) + 1}')
            for bound in ('min_v', 'max_v'):
                if rule.get(bound) is not None and any(n == rule[bound] for n in values):
                    tags.add(f'boundary:{path}:{bound}')
    # Only inputs reach feature extraction; expected answers are never read here.
    for name, value_part in sorted(value.items()):
        if name == 'args' and isinstance(value_part, dict):
            walk(value_part, '', {})
        else:
            walk(value_part, name, {})
    return tags


def select(qid, cases, count, *, strategy='balanced', prevalidated=False):
    if strategy not in ('balanced', 'hash') or type(count) is not int or count < 2:
        raise ValueError('invalid probe strategy or count')
    # New all-catalog packages already passed their own constraint gates. Do
    # not run the old heuristic parser as a second, contradictory admission
    # filter on node/table inputs. Default behavior for old jobs is unchanged.
    rules = parse(qid) if not prevalidated or qid in input_contracts.QIDS else {}
    unique = {}
    rejected = duplicates = 0
    reviewed = qid in input_contracts.QIDS
    if reviewed:
        input_contracts.require(qid)
        # The source text flattens 2^31 into "231"; do not label 231 as an int32 boundary.
        if qid in (7, 41, 231, 263, 292):
            name = 'x' if qid == 7 else 'nums' if qid == 41 else 'n'
            rules = deepcopy(rules)
            rules.setdefault(name, {}).update(min_v=1 if qid == 292 else -2**31, max_v=2**31-1)
    for case in cases:
        sample = inputs(case)
        if not sample or (not prevalidated and (not input_contracts.valid(qid, sample.get('args')) if reviewed else bool(check(qid, sample, rules=rules)))):
            rejected += 1
            continue
        key = stable_json(sample)
        if key in unique:
            duplicates += 1
            if stable_json(unique[key].get('expected')) != stable_json(case.get('expected')):
                raise ValueError('相同输入存在冲突的验证答案，请先审查语料')
            continue
        unique[key] = deepcopy(case)
    legal = sorted(unique.values(), key=lambda case: digest(inputs(case)))
    n = len(legal)
    if n < 3:
        raise ValueError(f'q{qid} 至少需要三个不同的可用输入')
    reserved = 1 if strategy == 'hash' else min(n - 2, max(min(3, n - 2), math.ceil(n * .3)))
    k = min(count, n - reserved)
    feature_sets = [features(inputs(case), rules) for case in legal]
    frequencies = Counter(tag for values in feature_sets for tag in values)
    covered = set()
    selected = []
    selection = []
    for _ in range(k):
        remaining = [i for i in range(n) if i not in selected]
        if strategy == 'hash':
            chosen = remaining[0]
        else:
            def score(index):
                new = feature_sets[index] - covered
                weight = sum((3 if tag.startswith('boundary:') else 1) / frequencies[tag] for tag in new)
                distance = min((1 - len(feature_sets[index] & feature_sets[j]) / max(1, len(feature_sets[index] | feature_sets[j])) for j in selected), default=0)
                return weight, distance, -index
            chosen = max(remaining, key=score)
        new = feature_sets[chosen] - covered
        selected.append(chosen)
        covered.update(feature_sets[chosen])
        selection.append({'input_sha256': digest(inputs(legal[chosen])), 'features': sorted(feature_sets[chosen]),
                          'new_features': sorted(new)})
    probes = [inputs(legal[i]) for i in selected]
    validation = [case for i, case in enumerate(legal) if i not in selected]
    warnings = []
    if len(validation) < 3:
        warnings.append('独立验证输入少于三个，正确性证据有限')
    if k < count:
        warnings.append(f'为保留验证输入，探测数从 {count} 调整为 {k}')
    metadata = {'version': VERSION, 'strategy': strategy, 'requested_probe_count': count, 'actual_probe_count': k,
                'unique_legal_input_count': n, 'rejected_input_count': rejected, 'duplicate_input_count': duplicates,
                'validation_reserved_minimum': reserved, 'validation_count': len(validation),
                'features_available': len(frequencies), 'features_covered': len(covered),
                'selected': selection, 'warnings': warnings, 'answers_used_for_selection': False}
    return probes, validation, metadata
