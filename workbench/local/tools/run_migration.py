"""Run the frozen migration sample: re-gate every problem/language with no model calls.

For each selected problem and each language that has an independent reference, the
saved cases are re-executed against the reference through the normal portable
entry, after checking that the reference, snippet and case bytes still match the
binding recorded when the corpus was admitted. Languages without a reference are
written down as blocked, never skipped silently and never counted as a pass.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import KEY_TO_LABEL, load_reference, load_snippet
from local.harness import runner
from local.harness.identity import image_digest
from local.judge import judge_one
from local.lab import problem_packages as packages
from local.lab.behavior import sha

EXTENSION = ROOT / 'local/lab/data/catalog_extension.json'
ALL_LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')


def load_extension():
    data = json.loads(EXTENSION.read_text(encoding='utf-8'))
    return {int(item['qid']): item for item in data.get('problems') or []}


def cases_for(qid, extension):
    """Cases come from the extension catalog or, for packaged problems, the package."""
    entry = extension.get(qid)
    if entry is not None:
        return entry.get('cases') or [], entry.get('cases_sha256'), entry.get('languages') or []
    path = packages.DATA_DIR / ('%s.json' % qid)
    if not path.exists():
        return None, None, []
    row = json.loads(path.read_text(encoding='utf-8'))
    return row.get('cases') or [], row.get('cases_sha256'), row.get('reference_languages') or []


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0, help='stop after N combinations (0 = all)')
    parser.add_argument('--resume', action='store_true', help='keep results already in --output')
    parser.add_argument('--all-languages', action='store_true',
                        help='gate every language that has a reference, not only those already admitted')
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    extension = load_extension()
    runner.DOCKER_IMAGE = image_digest()
    report = {'version': 'migration-run-v1', 'image': runner.DOCKER_IMAGE,
              'manifest_sha256': manifest['list_sha256'], 'seed': manifest['seed'],
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'combinations': [], 'blocked': []}
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding='utf-8'))
        report.setdefault('combinations', [])
        report.setdefault('blocked', [])

    done = {(row['qid'], row['language']) for row in report['combinations']}
    blocked = {(row['qid'], row['language']) for row in report['blocked']}
    ran = 0
    for item in manifest['selected']:
        qid = item['qid']
        cases, cases_sha, admitted_languages = cases_for(qid, extension)
        if not cases:
            report['blocked'].append({'qid': qid, 'language': None, 'reason': 'no_cases'})
            continue
        # The admission binding is the proof that the corpus still belongs to this source set.
        if cases_sha and sha(cases) != cases_sha:
            report['blocked'].append({'qid': qid, 'language': None, 'reason': 'cases_sha256_mismatch'})
            continue
        entry = {'cases': cases, 'languages': admitted_languages}
        admitted = set(admitted_languages)
        for language in ALL_LANGUAGES:
            if (qid, language) in done or (qid, language) in blocked:
                continue
            if language not in admitted and not args.all_languages:
                # The corpus was never admitted for this language: there is no
                # independent answer evidence, so no verdict may be issued.
                report['blocked'].append({'qid': qid, 'language': language,
                                          'reason': 'language_not_admitted_by_reference_gate'})
                continue
            reference = None
            try:
                reference = load_reference(qid, language)
            except (OSError, ValueError, KeyError):
                reference = None
            expected_snippets = (entry.get('bindings') or {}).get('snippets_sha256') or {}
            if reference is None:
                report['blocked'].append({'qid': qid, 'language': language,
                                          'reason': 'no_independent_reference_for_language'})
                continue
            if language not in expected_snippets and not args.all_languages:
                report['blocked'].append({'qid': qid, 'language': language,
                                          'reason': 'snippet_not_bound_at_admission'})
                continue
            if language in expected_snippets:
                try:
                    if sha(load_snippet(qid, language)) != expected_snippets[language]:
                        report['blocked'].append({'qid': qid, 'language': language,
                                                  'reason': 'snippet_sha256_mismatch'})
                        continue
                except (OSError, ValueError, KeyError) as error:
                    report['blocked'].append({'qid': qid, 'language': language,
                                              'reason': 'snippet_unreadable: %s' % type(error).__name__})
                    continue
            # The authoritative gate is the formal judge with the admitted cases,
            # exactly as catalogue admission ran it. Using another entry here would
            # measure a different program than the one that was admitted.
            try:
                with tempfile.TemporaryDirectory(prefix='migration_') as folder:
                    path = Path(folder) / ('%s_%s_1.txt' % (qid, KEY_TO_LABEL[language]))
                    path.write_text(reference, encoding='utf-8')
                    verdict = judge_one(path, 'gen', len(entry['cases']), 'docker',
                                        cases_override=entry['cases'])
            except Exception as error:                             # noqa: BLE001 - recorded, not raised
                report['combinations'].append({'qid': qid, 'language': language, 'gate': 'error',
                                               'reason': '%s: %s' % (type(error).__name__, str(error)[:300])})
            else:
                report['combinations'].append({
                    'qid': qid, 'language': language, 'gate': verdict['ac_status'],
                    'state': verdict.get('state'),
                    'correct': verdict.get('total_correct'), 'total': verdict.get('total_testcases'),
                    'dropped_unrepresentable': (verdict.get('_meta') or {}).get('dropped_unrepresentable'),
                    'error': (verdict.get('_meta') or {}).get('error', '')[:300]})
            ran += 1
            args.output.parent.mkdir(parents=True, exist_ok=True)
            report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
            if args.limit and ran >= args.limit:
                break
        if args.limit and ran >= args.limit:
            break

    # Blocked rows are appended without a write of their own, so the final state
    # must be persisted once more after the loop.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    accepted = sum(1 for row in report['combinations'] if row.get('gate') == 'Accepted')
    print('combinations run:', len(report['combinations']), '| accepted:', accepted)
    print('blocked rows:', len(report['blocked']))
    print('output ->', args.output)


if __name__ == '__main__':
    main()
