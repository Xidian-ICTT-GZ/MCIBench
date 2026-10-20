"""Summarize a migration run: per-language outcome, failure reasons, and coverage.

Reports what happened, not what was hoped for: a combination whose candidates were
all rejected counts as tested and failing, not as a pass, and a blocked combination
is listed separately from a tested one.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

VERDICTS = ('Accepted', 'Wrong Answer', 'Compile Error', 'Runtime Error',
            'Time Limit Exceeded', 'Memory Limit Exceeded')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    run = json.loads(args.run.read_text(encoding='utf-8'))
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    kinds = {row['qid']: row.get('bucket') or row.get('kind') for row in manifest['selected']}
    combos = run['combinations']

    verdicts = Counter()
    languages = Counter()
    by_bucket = Counter()
    rejected_combos = []
    for row in combos:
        statuses = [c.get('ac_status') for c in row['candidates']]
        for status in statuses:
            if status:
                verdicts[status] += 1
        if any(s == 'Accepted' for s in statuses):
            languages[row['language']] += 1
        else:
            rejected_combos.append({'qid': row['qid'], 'language': row['language'],
                                    'verdicts': statuses, 'state': row['state']})
        by_bucket[kinds.get(row['qid']) or 'unknown'] += 1

    expected = len(manifest['selected']) * 8
    summary = {
        'version': 'migration-summary-v1',
        'manifest_sha256': manifest['list_sha256'],
        'model': run.get('model'),
        'problems': len(manifest['selected']),
        'requested_combinations': expected,
        'tested_combinations': len(combos),
        'blocked_combinations': len(run['blocked']),
        'never_attempted': expected - len(combos) - len(run['blocked']),
        'job_states': dict(Counter(row['state'] for row in combos)),
        'combinations_with_a_candidate': sum(1 for row in combos if row['candidates']),
        'combinations_with_an_accepted_candidate': len(languages) and sum(languages.values()),
        'combinations_all_candidates_rejected': len(rejected_combos),
        'accepted_combinations_by_language': dict(languages),
        'candidate_verdicts': dict(verdicts),
        'combinations_by_bucket': dict(by_bucket),
        'rejected_combinations': rejected_combos,
        'average_seconds': round(sum(row['seconds'] for row in combos) / max(1, len(combos)), 1),
    }
    print(json.dumps({k: v for k, v in summary.items() if k != 'rejected_combinations'},
                     ensure_ascii=False, indent=1))
    if rejected_combos:
        print('all-rejected combinations:', [(r['qid'], r['language'], r['verdicts'])
                                             for r in rejected_combos[:8]])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
        print('summary ->', args.output)


if __name__ == '__main__':
    main()
