"""Turn gate rows into per-problem answer evidence.

One answer per problem (the frozen expected outputs, identified by their sha) and
one gate row per language that actually reproduced it. Languages without a
reference stay absent, which downstream reads as "no evidence", never as a pass.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import load_reference, load_snippet
from local.lab import answer_evidence as ae
from local.lab import problem_packages as packages
from local.lab.behavior import sha

EXTENSION = ROOT / 'local/lab/data/catalog_extension.json'


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--gates', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    gates = json.loads(args.gates.read_text(encoding='utf-8'))
    extension = {int(x['qid']): x for x in
                 json.loads(EXTENSION.read_text(encoding='utf-8'))['problems']}
    by_qid = {}
    for row in gates.get('combinations') or []:
        by_qid.setdefault(row['qid'], []).append(row)

    problems = {}
    for item in manifest['selected']:
        qid = item['qid']
        entry = extension.get(qid)
        if entry is None:
            continue
        # The shared answer: identical for every language by construction.
        block = ae.block(entry['cases'], evidence_level=entry.get('evidence_level'),
                         source=entry.get('source'),
                         limitations=entry.get('limitations') or ())
        for row in by_qid.get(qid, []):
            language = row['language']
            try:
                reference_sha = sha(load_reference(qid, language))
            except (OSError, ValueError, KeyError):
                reference_sha = None
            try:
                snippet_sha = sha(load_snippet(qid, language))
            except (OSError, ValueError, KeyError):
                snippet_sha = None
            verdict = {'state': row.get('state'), 'ac_status': row.get('gate'),
                       'total_correct': row.get('correct'), 'total_testcases': row.get('total'),
                       '_meta': {'dropped_unrepresentable': row.get('dropped_unrepresentable'),
                                 'error': row.get('error') or ''}}
            ae.record_language(block, language, verdict, reference_sha256=reference_sha,
                               interface=packages.code_interface(qid, language),
                               snippet_sha256=snippet_sha,
                               cases_sha256=entry.get('cases_sha256'))
        problems[str(qid)] = block

    summaries = {qid: ae.summary(block) for qid, block in problems.items()}
    state = Counter()
    for summary in summaries.values():
        for language in summary['passing_languages']:
            state[language] += 1
    out = {'version': 'answer-evidence-set-v1',
           'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'manifest_sha256': manifest['list_sha256'],
           'gates_file': args.gates.name,
           'problems': problems,
           'summary': summaries,
           'passing_by_language': dict(state)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    print('problems with an answer block:', len(problems))
    print('languages passing, per problem:', dict(state))
    print('answer source levels:', dict(Counter(b['evidence_level'] for b in problems.values())))
    print('output ->', args.output)


if __name__ == '__main__':
    main()
