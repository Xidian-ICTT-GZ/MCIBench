"""Type-directed input generation, verified by independent language references.

Two official examples are not enough for the catalogue's three-case minimum, and the
existing generator has no input source for these problems. This builds inputs from the
signature's types, then keeps only those where python3 and at least one other language
reference agree on the answer. Nothing is invented: an added case carries an output
that independent implementations produced.
"""
import argparse
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import LANGS, load_snippet
from local.gen_testcases.differential import python_outputs, verify_with_lang
from local.harness.typespec import Bool, Float, Int, ListT, Str, parse_python_snippet
from local.lab.behavior import sha


def values_for(typ, rng):
    if isinstance(typ, Int):
        return [0, 1, 2, 3, 5, 10, 100, -1, rng.randint(2, 50), rng.randint(50, 500)]
    if isinstance(typ, Float):
        return [0.0, 1.0, 2.5, -1.5, 10.0]
    if isinstance(typ, Bool):
        return [True, False]
    if isinstance(typ, Str):
        return ['a', 'ab', 'abc', 'xyz', 'A1', 'aab']
    if isinstance(typ, ListT):
        inner = typ.inner
        if isinstance(inner, Int):
            return [[], [1], [1, 2], [2, 1, 3], [1, 1, 2], [-1, 0, 1], [5, 3, 8, 1],
                    [0], [7, 7, 7], list(range(6)), [rng.randint(0, 9) for _ in range(4)]]
        if isinstance(inner, Str):
            return [[], ['a'], ['a', 'b', 'c'], ['aa', 'bb'], ['x']]
        if isinstance(inner, ListT):
            return [[], [[0, 1]], [[0, 1], [1, 2]], [[0, 1], [1, 2], [2, 0]],
                    [[0, 1], [2, 3]], [[1, 2], [2, 3], [3, 1]]]
    return None


def generate(qid, cap, rng):
    sig = parse_python_snippet(load_snippet(qid, 'python3'))
    pools = []
    for param in sig.params:
        pool = values_for(param.typ, rng)
        if not pool:
            return None
        pools.append((param.name, pool))
    cases, seen = [], set()
    for combination in itertools.islice(itertools.product(*[p for _, p in pools]), cap * 4):
        args = {name: value for (name, _), value in zip(pools, combination)}
        key = json.dumps(args, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        cases.append({'args': args})
        if len(cases) >= cap:
            break
    return cases


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qids', required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cap', type=int, default=24)
    parser.add_argument('--seed', type=int, default=20261018)
    args = parser.parse_args()

    admitted = json.loads(args.admission.read_text(encoding='utf-8'))['problems']
    report = {'version': 'generated-input-corpus-v1',
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'cap': args.cap, 'seed': args.seed, 'problems': {}}
    if args.output.exists():
        report = json.loads(args.output.read_text(encoding='utf-8'))

    for raw in args.qids.split(','):
        qid = int(raw)
        existing = report['problems'].get(str(qid)) or {}
        if existing.get('total', 0) >= 3:
            continue
        rng = random.Random(args.seed + qid)
        cases = generate(qid, args.cap, rng)
        if not cases:
            report['problems'][str(qid)] = {'state': 'unsupported_signature', 'total': 0}
            continue
        try:
            outputs = python_outputs(qid, cases, 'docker')
        except Exception as error:                                  # noqa: BLE001
            report['problems'][str(qid)] = {'state': 'python_failed',
                                            'reason': '%s: %s' % (type(error).__name__, str(error)[:160]),
                                            'total': 0}
            continue
        keep = [(case, out) for case, out in zip(cases, outputs) if out is not None]
        if not keep:
            report['problems'][str(qid)] = {'state': 'no_runnable_input', 'total': 0}
            continue
        probe = [case for case, _ in keep]
        expected = [out for _, out in keep]
        votes = [1] * len(probe)
        agreeing = []
        for language in LANGS:
            if language == 'python3':
                continue
            try:
                agreed, reason, _crashed = verify_with_lang(qid, language, probe, expected, 'docker', False)
            except Exception:                                       # noqa: BLE001
                continue
            if agreed:
                agreeing.append(language)
                for index in agreed:
                    votes[index] += 1
        official = (admitted.get(str(qid)) or {}).get('cases') or []
        merged, seen = [], set()
        for case in official:
            key = sha(case.get('args'))
            if key in seen:
                continue
            seen.add(key)
            merged.append({'args': case.get('args'), 'expected': case.get('expected'),
                           'origin': 'official_example'})
        added = 0
        for index, (case, output) in enumerate(keep):
            if votes[index] < 2:
                continue
            key = sha(case['args'])
            if key in seen:
                continue
            seen.add(key)
            merged.append({'args': case['args'], 'expected': output,
                           'origin': 'generated_cross_verified'})
            added += 1
        report['problems'][str(qid)] = {
            'state': 'ok', 'official': len(official), 'generated': added,
            'total': len(merged), 'vote_languages': agreeing,
            'cases': merged,
            'cases_sha256': sha([{'args': c['args'], 'expected': c['expected']} for c in merged]),
        }
        print('q%d official=%d generated=%d total=%d agree=%s' % (
            qid, len(official), added, len(merged), agreeing), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    ready = sum(1 for v in report['problems'].values() if v.get('total', 0) >= 3)
    print('problems reaching three or more cases:', ready, '/', len(report['problems']))


if __name__ == '__main__':
    main()
