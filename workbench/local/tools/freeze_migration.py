"""Freeze the migration-validation sample before any run.

Rules are fixed here so the sample cannot be re-drawn after seeing results:
pool = catalog problems that are still evaluable AND were never used in
development evidence; order = seeded shuffle over sorted qids; selection =
proportional to the available difficulty mix; reserve = the next slice of the
same shuffled order.

The manifest records the real capability of each problem, so a language that has
no independent reference is written down as blocked instead of being silently
skipped or counted as a pass.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.lab import catalog as catalog_mod
from local.lab.input_contracts import QIDS as AUDITED_QIDS

DEFAULT_SEED = 20261018
TARGET = 30
RESERVE = 30
# The task book asks for 20 function / 6 tree-linkedlist / 4 design. Only plain
# function problems exist in the untouched evaluable pool, so the mix is recorded
# as what is achievable rather than invented.
WANTED_MIX = {'function': 20, 'tree': 6, 'linked_list': 4}


# Evidence that means "work was done on this problem", not a catalog listing
# that merely enumerates it. Reading catalog dumps marked every problem as used
# and emptied the eligible pool, so they are deliberately excluded here.
WORK_MARKERS = (
    'local/results/corpus_changes/**/*.json',
    'local/results/gap_workflow/**/*.json',
    'local/docs/reviews/**/audit/**/*.json',
    'local/docs/reviews/**/final-evidence.json',
    'local/docs/reviews/**/acceptance.json',
    'local/docs/reviews/**/live-smoke.json',
)


def evidence_qids():
    """Problems that already received development work."""
    used = set(int(q) for q in AUDITED_QIDS)
    for pattern in WORK_MARKERS:
        for path in glob.glob(str(ROOT / pattern), recursive=True):
            try:
                text = Path(path).read_text(encoding='utf-8', errors='replace')[:400000]
            except OSError:
                continue
            for match in re.finditer(r'"qid"\s*:\s*(\d+)', text):
                used.add(int(match.group(1)))
    return used


def kind_of(problem):
    tags = {str(t).lower() for t in (problem.get('tags') or [])}
    if 'design' in tags:
        return 'design'
    if tags & {'tree', 'binary tree', 'binary search tree'}:
        return 'tree'
    if 'linked list' in tags:
        return 'linked_list'
    if problem.get('problem_kind') == 'database':
        return 'database'
    return 'function'


def allocate(counts, target):
    """Largest-remainder allocation so the sample keeps the pool's mix."""
    total = sum(counts.values()) or 1
    exact = {key: counts[key] * target / total for key in counts}
    base = {key: int(value) for key, value in exact.items()}
    left = target - sum(base.values())
    for key in sorted(exact, key=lambda k: (-(exact[k] - base[k]), k))[:left]:
        base[key] += 1
    return base


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--target', type=int, default=TARGET)
    parser.add_argument('--reserve', type=int, default=RESERVE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    catalog = catalog_mod.catalog()
    used = evidence_qids()
    pool = []
    excluded = Counter()
    for problem in catalog['problems']:
        if problem.get('scope') != 'extension':
            excluded['scope_' + str(problem.get('scope'))] += 1
            continue
        if not problem.get('ready') or not problem.get('corpus_cases'):
            excluded['not_evaluable'] += 1
            continue
        if problem['qid'] in used:
            excluded['used_in_development'] += 1
            continue
        if problem.get('evidence_level') == 'independent_oracle_and_references':
            # A hand-built independent oracle is development work on that problem.
            excluded['hand_built_oracle'] += 1
            continue
        pool.append(problem)

    pool.sort(key=lambda p: p['qid'])
    rng = random.Random(args.seed)
    shuffled = list(pool)
    rng.shuffle(shuffled)

    by_difficulty = Counter(str(p.get('difficulty')) for p in shuffled)
    quota = allocate(by_difficulty, min(args.target, len(shuffled)))
    chosen, reserve = [], []
    taken = Counter()
    for problem in shuffled:
        difficulty = str(problem.get('difficulty'))
        if len(chosen) < args.target and taken[difficulty] < quota.get(difficulty, 0):
            chosen.append(problem)
            taken[difficulty] += 1
        else:
            reserve.append(problem)
    # Any shortfall in a stratum is filled from the remaining pool, in order.
    for problem in reserve[:]:
        if len(chosen) >= args.target:
            break
        chosen.append(problem)
        reserve.remove(problem)

    def capability(problem):
        languages = list(problem.get('available_languages') or [])
        return {'qid': problem['qid'], 'difficulty': problem.get('difficulty'),
                'kind': kind_of(problem), 'tags': problem.get('tags') or [],
                'corpus_cases': problem.get('corpus_cases'),
                'evidence_level': problem.get('evidence_level'),
                'judgeable_languages': languages,
                'blocked_languages': [lang for lang in ('python3', 'c', 'cpp', 'java', 'javascript',
                                                        'csharp', 'golang', 'rust') if lang not in languages],
                'blocked_reason': None if len(languages) >= 8 else '没有该语言的独立参考与语料，无法签发判定'}

    selected = [capability(p) for p in sorted(chosen, key=lambda p: p['qid'])]
    reserved = [{'qid': p['qid'], 'difficulty': p.get('difficulty'), 'kind': kind_of(p)}
                for p in sorted(reserve[:args.reserve], key=lambda p: p['qid'])]

    feasible = sum(len(item['judgeable_languages']) for item in selected)
    blocked = sum(len(item['blocked_languages']) for item in selected)
    manifest = {
        'version': 'migration-freeze-v1',
        'frozen_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'seed': args.seed,
        'pool': {'catalog_total': len(catalog['problems']), 'eligible_untouched': len(pool),
                 'excluded': dict(excluded)},
        'rules': {
            'scope': 'extension only (ft100 is development data, pending has no corpus)',
            'exclusion': 'qid referenced by any review/audit evidence, or in the audited 15-question set',
            'order': 'seeded shuffle over qid-sorted pool',
            'selection': 'largest-remainder allocation by difficulty',
            'reserve': 'next %d in the same shuffled order' % args.reserve,
            'no_redraw': 'reserve questions replace a failed question only before its first run',
        },
        'wanted_mix': WANTED_MIX,
        'achieved_mix': dict(Counter(item['kind'] for item in selected)),
        'language_coverage': {
            'per_problem': sorted({tuple(item['judgeable_languages']) for item in selected} and
                                  {str(item['judgeable_languages']) for item in selected}),
            'feasible_combinations': feasible,
            'blocked_combinations': blocked,
            'requested_combinations': len(selected) * 8,
            'note': ('八语言要求目前无法满足：未接触的可评测题池只有 python3/cpp 的独立参考。'
                     '其余 6 种语言记为 blocked_language，不计入通过，也不静默跳过。'),
        },
        'selected': selected,
        'reserve': reserved,
        'list_sha256': hashlib.sha256(json.dumps([item['qid'] for item in selected]).encode()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')

    print('eligible untouched pool:', len(pool))
    print('excluded:', dict(excluded))
    print('selected:', len(selected), '| reserve:', len(reserved))
    print('difficulty of selected:', dict(Counter(str(item['difficulty']) for item in selected)))
    print('kinds:', dict(Counter(item['kind'] for item in selected)))
    print('feasible combos:', feasible, '| blocked combos:', blocked, '| requested:', len(selected) * 8)
    print('list sha256:', manifest['list_sha256'][:16])
    print('manifest ->', args.output)


if __name__ == '__main__':
    main()
