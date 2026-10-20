"""Admit a frozen sample's corpus from official examples, gated per language.

No model is involved. Each problem's official examples are extracted from its
statement, then every language that has an independent reference must reproduce
them exactly. A language that fails, drops a case it cannot represent, or is
missing stays out of the answer evidence -- it does not become a pass.

A problem is only admitted when at least two languages independently pass, which is
the same dual-reference rule catalogue admission uses.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import KEY_TO_LABEL, load_reference
from local.gen_testcases.extract_examples import extract_from_prompt
from local.harness import runner
from local.harness.identity import image_digest
from local.judge import judge_one
from local.lab import answer_evidence as ae
from local.lab import problem_io
from local.lab.behavior import sha
from local.lab.native_adapters import signature

LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')
MIN_LANGUAGES = 2


def clean_cases(qid):
    text = problem_io.description(qid)
    extracted = extract_from_prompt(text)
    sig = signature(qid)
    # Design problems expose an operation sequence, not a parameter list, so the
    # "args must match the signature" filter only applies to plain signatures.
    params = {p.name for p in sig.params} if hasattr(sig, 'params') else None
    unique = {}
    for case in extracted:
        args = case.get('args') or {}
        if params is not None and set(args) != params:
            continue
        unique.setdefault(sha(args), case)
    return list(unique.values()), sha(extracted)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    runner.DOCKER_IMAGE = image_digest()
    report = {'version': 'frozen-admission-v1', 'image': runner.DOCKER_IMAGE,
              'manifest_sha256': manifest['list_sha256'],
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'problems': {}}
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding='utf-8'))

    done = 0
    for item in manifest['selected']:
        qid = item['qid']
        key = str(qid)
        if key in report['problems'] and report['problems'][key].get('state') == 'admitted':
            continue
        entry = {'qid': qid, 'kind': item['kind'], 'cases': None, 'cases_sha256': None,
                 'gates': {}, 'state': 'pending', 'reason': None}
        try:
            cases, raw_sha = clean_cases(qid)
        except Exception as error:                                 # noqa: BLE001
            entry.update(state='blocked', reason='extraction_failed: %s: %s'
                         % (type(error).__name__, str(error)[:200]))
            report['problems'][key] = entry
            continue
        entry['cases'] = cases
        entry['cases_sha256'] = sha(cases)
        entry['raw_cases_sha256'] = raw_sha
        if not cases:
            entry.update(state='blocked', reason='no_official_example_matches_the_signature')
            report['problems'][key] = entry
            continue
        block = ae.block(cases, evidence_level='official_examples_only',
                         source='statement official examples, gated per language')
        for language in LANGUAGES:
            try:
                reference = load_reference(qid, language)
            except (OSError, ValueError, KeyError):
                entry['gates'][language] = {'gate': 'no_reference'}
                continue
            try:
                with tempfile.TemporaryDirectory(prefix='admit_') as folder:
                    path = Path(folder) / ('%s_%s_1.txt' % (qid, KEY_TO_LABEL[language]))
                    path.write_text(reference, encoding='utf-8')
                    verdict = judge_one(path, 'gen', len(cases), 'docker', cases_override=cases)
            except Exception as error:                             # noqa: BLE001
                entry['gates'][language] = {'gate': 'error',
                                            'reason': '%s: %s' % (type(error).__name__, str(error)[:200])}
                continue
            meta = verdict.get('_meta') or {}
            row = ae.record_language(block, language, verdict,
                                     reference_sha256=sha(reference),
                                     interface=item.get('interface'),
                                     snippet_sha256=item.get('python_snippet_sha256'),
                                     cases_sha256=entry['cases_sha256'])
            entry['gates'][language] = {'gate': row['gate'], 'correct': row['correct'],
                                        'total': row['total'],
                                        'dropped': row['dropped_unrepresentable'],
                                        'error': row['error']}
            done += 1
            args.output.parent.mkdir(parents=True, exist_ok=True)
            report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
        summary = ae.summary(block)
        entry['answer_evidence'] = block
        entry['passing_languages'] = summary['passing_languages']
        if len(summary['passing_languages']) >= MIN_LANGUAGES:
            entry['state'] = 'admitted'
        else:
            entry['state'] = 'blocked'
            entry['reason'] = ('only %d language(s) reproduced the official examples'
                               % len(summary['passing_languages']))
        report['problems'][key] = entry
        if args.limit and len(report['problems']) >= args.limit:
            break

    report['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    states = Counter(entry['state'] for entry in report['problems'].values())
    report['summary'] = {
        'problems': len(report['problems']),
        'admitted': states.get('admitted', 0),
        'blocked': states.get('blocked', 0),
        'languages_passing': dict(Counter(lang for entry in report['problems'].values()
                                          for lang in entry.get('passing_languages') or [])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('admitted:', report['summary']['admitted'], '/', report['summary']['problems'])
    print('languages passing:', report['summary']['languages_passing'])
    print('gates run:', done)
    print('output ->', args.output)


if __name__ == '__main__':
    main()
