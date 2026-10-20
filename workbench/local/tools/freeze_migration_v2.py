"""Freeze the migration sample from the problems that actually have lab packages.

The catalog's scope field is stale: it still calls 2744 problems "pending" while
124 of them already carry a lab package with cases and gate records. The pool is
therefore derived from packages on disk, not from the scope column.

Required mix is 20 function / 6 tree-or-linked-list / 4 design. The packaged pool
does not contain that many of the structural kinds, so the shortfall is recorded
in the manifest instead of being papered over by picking unpackageable problems.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.harness.identity import image_digest, judge_source_closure
from local.lab import catalog as catalog_mod
from local.lab import problem_packages as packages
from local.lab.behavior import sha
from local.lab.input_contracts import QIDS as AUDITED_QIDS

DEFAULT_SEED = 20261018
TARGETS = {'function': 20, 'tree_linked_list': 6, 'design': 4}
RESERVE = 30
# SQL / shell / dataframe answers are established per dialect, not per language,
# so they are a separate protocol validation and not part of this sample.
EXCLUDED_KINDS = ('database', 'shell', 'dataframe')


def kind_of(problem):
    tags = {str(t).lower() for t in (problem.get('tags') or [])}
    if 'design' in tags:
        return 'design'
    if tags & {'tree', 'binary tree', 'binary search tree'}:
        return 'tree'
    if 'linked list' in tags:
        return 'linked_list'
    return 'function'


def bucket(kind):
    return 'tree_linked_list' if kind in ('tree', 'linked_list') else kind


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    problems = {p['qid']: p for p in catalog_mod.catalog()['problems']}
    audited = set(int(q) for q in AUDITED_QIDS)
    pool, excluded = [], Counter()
    for path in sorted(packages.DATA_DIR.glob('*.json')):
        if not path.stem.isdigit():
            continue
        qid = int(path.stem)
        problem = problems.get(qid)
        if problem is None:
            excluded['not_in_catalog'] += 1
            continue
        kind = kind_of(problem)
        if kind in EXCLUDED_KINDS:
            excluded['answer_is_per_dialect'] += 1
            continue
        if qid in audited:
            excluded['used_by_audit_set'] += 1
            continue
        row = json.loads(path.read_text(encoding='utf-8'))
        cases = row.get('cases') or []
        if not cases:
            excluded['no_cases'] += 1
            continue
        pool.append({'qid': qid, 'kind': kind, 'bucket': bucket(kind),
                     'difficulty': problem.get('difficulty'),
                     'cases': len(cases), 'cases_sha256': sha(cases),
                     'evidence_level': row.get('evidence_level'),
                     'reference_languages': row.get('reference_languages') or [],
                     'package_sha256': row.get('package_sha256')})

    pool.sort(key=lambda row: row['qid'])
    rng = random.Random(args.seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)

    by_bucket = defaultdict(list)
    for row in shuffled:
        by_bucket[row['bucket']].append(row)
    available = {name: len(by_bucket.get(name, [])) for name in TARGETS}

    chosen, shortfall = [], {}
    for name, want in TARGETS.items():
        rows = by_bucket.get(name, [])
        take = rows[:want]
        chosen.extend(take)
        if len(take) < want:
            shortfall[name] = {'wanted': want, 'available': len(take)}
    # Fill the deficit from the remaining plain-function problems, in seeded order.
    target_total = sum(TARGETS.values())
    used = {row['qid'] for row in chosen}
    for row in by_bucket.get('function', []):
        if len(chosen) >= target_total:
            break
        if row['qid'] not in used:
            chosen.append(row)
            used.add(row['qid'])

    remaining = [row for row in shuffled if row['qid'] not in used]
    reserve = remaining[:RESERVE]
    chosen.sort(key=lambda row: row['qid'])

    manifest = {
        'version': 'migration-freeze-v2',
        'frozen_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'seed': args.seed,
        'pool_source': 'lab packages on disk (the catalog scope column is stale)',
        'pool_size': len(pool),
        'excluded': dict(excluded),
        'available_by_bucket': available,
        'requested_mix': TARGETS,
        'achieved_mix': dict(Counter(row['bucket'] for row in chosen)),
        'shortfall': shortfall,
        'note': ('可评测池不足以满足 6 树链表 + 4 设计：池内仅 5 个树/链表与 1 个设计。'
                 '补足需要先为这些题造语料与独立答案，本轮环境无模型，无法生成。'),
        'frozen': {'image': image_digest(), 'judge_closure': dict(judge_source_closure()),
                   'sampling_script_sha256': sha(Path(__file__).read_text(encoding='utf-8'))},
        'selected': chosen,
        'reserve': [{'qid': row['qid'], 'kind': row['kind'], 'bucket': row['bucket']} for row in reserve],
        'list_sha256': hashlib.sha256(json.dumps([row['qid'] for row in chosen]).encode()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')

    print('pool:', len(pool), '| excluded:', dict(excluded))
    print('available by bucket:', available)
    print('selected:', len(chosen), '| mix:', dict(Counter(row['bucket'] for row in chosen)))
    print('shortfall:', shortfall)
    print('reserve:', len(reserve))
    print('list sha256:', manifest['list_sha256'][:16])
    print('output ->', args.output)


if __name__ == '__main__':
    main()
