"""Freeze the migration sample from problems the harness can actually run.

Pool = signature supported by the formal harness AND references in all eight
languages AND no corpus yet AND never used in development. That intersection is
the only set where "new problem, same engine" can be tested at all; a problem with
no corpus cannot be judged, and a problem whose types the harness cannot serialise
cannot be executed.

The required mix is 20 function / 6 tree-or-linked-list / 4 design. The pool has
no linked-list problem with eight references, so that sub-bucket is reported as a
shortfall rather than filled with an unexecutable problem.
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

from local.common import load_reference, load_snippet
from local.gen_testcases import design_cases
from local.gen_testcases.extract_examples import extract_from_prompt
from local.lab import problem_io
from local.lab.native_adapters import signature
from local.harness.identity import image_digest, judge_source_closure
from local.lab.behavior import sha
from local.lab.input_contracts import QIDS as AUDITED_QIDS

DEFAULT_SEED = 20261018
TARGETS = {'function': 20, 'tree_linked_list': 6, 'design': 4}
RESERVE = 30
LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')
WORK_MARKERS = ('local/results/corpus_changes/**/*.json', 'local/results/gap_workflow/**/*.json',
                'local/docs/reviews/**/audit/**/*.json')


def extractable(qid):
    """Can a corpus be built from the statement at all?

    A problem whose statement yields no usable case cannot be judged, so this is a
    pool rule, not a result. v3 omitted it and selected design problems that turned
    out to have no examples.
    """
    try:
        if design_cases.design_seed_cases(qid):
            return True
    except Exception:                                          # noqa: BLE001
        pass
    try:
        cases = extract_from_prompt(problem_io.description(qid))
        sig = signature(qid)
        params = {p.name for p in sig.params} if hasattr(sig, 'params') else None
        for case in cases:
            args = case.get('args') or {}
            if params is None or set(args) == params:
                return True
    except Exception:                                          # noqa: BLE001
        pass
    return False


def bucket(kind):
    return 'tree_linked_list' if kind in ('tree', 'linked_list') else kind


def used_qids():
    used = set(int(q) for q in AUDITED_QIDS)
    for pattern in WORK_MARKERS:
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
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding='utf-8'))
    used = used_qids()
    eligible, excluded = [], Counter()
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
        if row['qid'] in used:
            excluded['used_in_development'] += 1
            continue
        if not extractable(row['qid']):
            excluded['no_extractable_official_examples'] += 1
            continue
        eligible.append({'qid': row['qid'], 'kind': row['kind'], 'bucket': bucket(row['kind']),
                         'scope': row['scope'], 'interface': row['interface']})

    eligible.sort(key=lambda row: row['qid'])
    rng = random.Random(args.seed)
    shuffled = list(eligible)
    rng.shuffle(shuffled)
    by_bucket = defaultdict(list)
    for row in shuffled:
        by_bucket[row['bucket']].append(row)
    available = {name: len(by_bucket.get(name, [])) for name in TARGETS}

    chosen, shortfall = [], {}
    for name, want in TARGETS.items():
        rows = by_bucket.get(name, [])[:want]
        chosen.extend(rows)
        if len(rows) < want:
            shortfall[name] = {'wanted': want, 'available': len(rows)}
    used_ids = {row['qid'] for row in chosen}
    for row in by_bucket.get('function', []):
        if len(chosen) >= sum(TARGETS.values()):
            break
        if row['qid'] not in used_ids:
            chosen.append(row)
            used_ids.add(row['qid'])
    chosen.sort(key=lambda row: row['qid'])
    reserve = [row for row in shuffled if row['qid'] not in used_ids][:RESERVE]

    frozen_rows = []
    for row in chosen:
        try:
            python_snippet = load_snippet(row['qid'], 'python3')
            snippet_sha = sha(python_snippet)
        except (OSError, ValueError, KeyError):
            snippet_sha = None
        frozen_rows.append({
            'qid': row['qid'], 'kind': row['kind'], 'bucket': row['bucket'], 'scope': row['scope'],
            'interface': row['interface'], 'python_snippet_sha256': snippet_sha,
            'references_sha256': {lang: sha(load_reference(row['qid'], lang)) for lang in LANGUAGES},
        })

    manifest = {
        'version': 'migration-freeze-v4',
        'frozen_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'seed': args.seed,
        'pool_rule': ('harness-supported signature + eight-language references + no corpus yet '
                      '+ never used in development'),
        'eligible_pool': len(eligible),
        'available_by_bucket': available,
        'excluded': dict(excluded),
        'requested_mix': TARGETS,
        'achieved_mix': dict(Counter(row['bucket'] for row in chosen)),
        'shortfall': shortfall,
        'note': ('池内没有链表题具备八语言参考，因此树链表子桶只有树题；'
                 '这不是选题偏好，是能力面事实。'),
        'frozen': {'image': image_digest(), 'judge_closure': dict(judge_source_closure()),
                   'sampling_script_sha256': sha(Path(__file__).read_text(encoding='utf-8')),
                   'capability_matrix_sha256': sha(args.matrix.read_text(encoding='utf-8'))},
        'selected': frozen_rows,
        'reserve': [{'qid': row['qid'], 'kind': row['kind'], 'bucket': row['bucket']} for row in reserve],
        'list_sha256': hashlib.sha256(json.dumps([row['qid'] for row in chosen]).encode()).hexdigest(),
        'corpus_status': 'absent: official examples still have to be extracted and gated',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')

    print('eligible pool:', len(eligible), '| excluded:', dict(excluded))
    print('available by bucket:', available)
    print('selected:', len(chosen), '| mix:', dict(Counter(row['bucket'] for row in chosen)))
    print('shortfall:', shortfall, '| reserve:', len(reserve))
    print('list sha256:', manifest['list_sha256'][:16])
    print('output ->', args.output)


if __name__ == '__main__':
    main()
