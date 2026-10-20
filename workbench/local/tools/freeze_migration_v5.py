"""Freeze the migration sample from problems the catalogue can actually admit.

v4 required "harness-supported signature + eight references + no corpus", and 21 of
its problems then turned out to have only two official examples, which the catalogue
refuses (it needs three, and it also requires a plain signature). Those problems
could never run, so the pool rule was defective rather than strict.

v5 adds the admission requirement to the pool rule. The requested mix cannot survive
that: design problems are DesignSig (86 of 94), which the catalogue never admits, and
only two tree/linked-list problems qualify. The shortfall is recorded, not hidden.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import glob
import hashlib
import json
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.harness.identity import image_digest, judge_source_closure
from local.lab.behavior import sha
from local.lab.input_contracts import QIDS as AUDITED_QIDS

TARGETS = {'function': 20, 'tree_linked_list': 6, 'design': 4}
TOTAL = 30
RESERVE = 30
LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')


def used_qids():
    used = set(int(q) for q in AUDITED_QIDS)
    for pattern in ('local/results/corpus_changes/**/*.json', 'local/results/gap_workflow/**/*.json',
                    'local/docs/reviews/**/audit/**/*.json'):
        for path in glob.glob(str(ROOT / pattern), recursive=True):
            try:
                text = Path(path).read_text(encoding='utf-8', errors='replace')[:400000]
            except OSError:
                continue
            for hit in re.finditer(r'"qid"\s*:\s*(\d+)', text):
                used.add(int(hit.group(1)))
    return used


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261018)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding='utf-8'))
    inventory = {int(row['qid']) for row in json.loads(args.inventory.read_text(encoding='utf-8'))['candidates']}
    used = used_qids()
    pool, excluded = [], Counter()
    for row in matrix['rows']:
        if not row['signature_supported']:
            excluded['harness_cannot_serialise'] += 1
            continue
        if len(row['reference_languages']) < 8:
            excluded['fewer_than_eight_references'] += 1
            continue
        if row['packageable']:
            excluded['already_has_corpus'] += 1
            continue
        if row['qid'] not in inventory:
            excluded['catalogue_cannot_admit'] += 1
            continue
        if row['qid'] in used:
            excluded['used_in_development'] += 1
            continue
        pool.append(row)

    pool.sort(key=lambda r: r['qid'])
    rng = random.Random(args.seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)

    def bucket(kind):
        return 'tree_linked_list' if kind in ('tree', 'linked_list') else kind

    by_bucket = defaultdict(list)
    for row in shuffled:
        by_bucket[bucket(row['kind'])].append(row)

    chosen, shortfall = [], {}
    for name, want in TARGETS.items():
        rows = by_bucket.get(name, [])[:want]
        chosen.extend(rows)
        if len(rows) < want:
            shortfall[name] = {'wanted': want, 'available': len(rows)}
    taken = {row['qid'] for row in chosen}
    for row in by_bucket.get('function', []):
        if len(chosen) >= TOTAL:
            break
        if row['qid'] not in taken:
            chosen.append(row)
            taken.add(row['qid'])
    chosen.sort(key=lambda r: r['qid'])
    reserve = [row for row in shuffled if row['qid'] not in taken][:RESERVE]

    manifest = {
        'version': 'migration-freeze-v5',
        'frozen_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'seed': args.seed,
        'pool_rule': ('catalogue-admissible (>=3 official cases, plain signature) + eight references '
                      '+ no corpus yet + never used in development'),
        'pool': len(pool),
        'available_by_bucket': {name: len(by_bucket.get(name, [])) for name in TARGETS},
        'excluded': dict(excluded),
        'requested_mix': TARGETS,
        'achieved_mix': dict(Counter(bucket(r['kind']) for r in chosen)),
        'shortfall': shortfall,
        'deviation': ('请求的 6 树链表 + 4 设计在本平台不可达：设计类 86/94 是 DesignSig，'
                      '目录从不接纳；树链表只有 2 题同时满足可进目录、八语言参考与至少 3 条用例。'
                      '因此本样本以普通函数补足 30 题。'),
        'frozen': {'image': image_digest(), 'judge_closure': dict(judge_source_closure()),
                   'sampling_script_sha256': sha(Path(__file__).read_text(encoding='utf-8'))},
        'selected': [{'qid': r['qid'], 'kind': r['kind'], 'bucket': bucket(r['kind']),
                      'scope': r['scope'], 'interface': r['interface']} for r in chosen],
        'reserve': [{'qid': r['qid'], 'kind': r['kind']} for r in reserve],
        'list_sha256': hashlib.sha256(json.dumps([r['qid'] for r in chosen]).encode()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    print('pool:', len(pool), '| by bucket:', manifest['available_by_bucket'])
    print('selected:', len(chosen), '| mix:', manifest['achieved_mix'])
    print('shortfall:', shortfall)
    print('reserve:', len(reserve))
    print('list sha256:', manifest['list_sha256'][:16])


if __name__ == '__main__':
    main()
