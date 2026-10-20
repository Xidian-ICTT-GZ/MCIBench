"""Grow a frozen corpus with inputs that several language references agree on.

Some admitted problems only have two official examples, and the catalogue refuses a
corpus below three. Lowering that rule would weaken the evidence, so the corpus is
grown instead: candidate inputs are executed by the existing references, and only
inputs where independent languages agree on the answer are kept.

Nothing here invents an expected value; every added case is an output that at least
two independent reference implementations produced.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.gen_testcases.differential import differential_problem
from local.lab.behavior import sha


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qids', required=True)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-cases', type=int, default=8)
    args = parser.parse_args()

    admitted = json.loads(args.admission.read_text(encoding='utf-8'))['problems']
    report = {'version': 'augmented-corpus-v1',
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'max_cases': args.max_cases, 'problems': {}}
    if args.output.exists():
        report = json.loads(args.output.read_text(encoding='utf-8'))

    for raw in args.qids.split(','):
        qid = int(raw)
        if str(qid) in report['problems'] and report['problems'][str(qid)].get('state') == 'ok':
            continue
        official = (admitted.get(str(qid)) or {}).get('cases') or []
        try:
            result = differential_problem(qid, args.max_cases, 'docker', False)
        except Exception as error:                                  # noqa: BLE001
            report['problems'][str(qid)] = {'state': 'failed',
                                            'reason': '%s: %s' % (type(error).__name__, str(error)[:200]),
                                            'official': len(official)}
            continue
        merged, seen = [], set()
        for case in official:
            key = sha(case.get('args'))
            if key in seen:
                continue
            seen.add(key)
            merged.append({'args': case.get('args'), 'expected': case.get('expected'),
                           'origin': 'official_example'})
        added = 0
        for case in result.get('cases') or []:
            key = sha(case.get('args'))
            if key in seen:
                continue
            seen.add(key)
            merged.append({'args': case.get('args'), 'expected': case.get('expected'),
                           'origin': 'cross_verified_generated'})
            added += 1
        report['problems'][str(qid)] = {
            'state': 'ok' if result.get('ok') else 'differential_reported_failure',
            'reason': result.get('reason'),
            'official': len(official), 'generated': added, 'total': len(merged),
            'vote_languages': result.get('vote_langs') or [],
            'cases': merged,
            'cases_sha256': sha([{'args': c['args'], 'expected': c['expected']} for c in merged]),
        }
        print('q%d official=%d generated=%d total=%d languages=%s' % (
            qid, len(official), added, len(merged), result.get('vote_langs')), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    ok = sum(1 for v in report['problems'].values() if v.get('total', 0) >= 3)
    print('problems reaching three or more cases:', ok, '/', len(report['problems']))


if __name__ == '__main__':
    main()
