"""Run the acceptance checks in one pass and print a verdict per item.

Each check answers one line of the acceptance wording; a check that cannot be
verified reports FAIL rather than being skipped, so the output cannot be read as
a clean bill of health when something is missing.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.harness.identity import image_digest, judge_source_closure
from local.lab import catalog


def check_closure():
    closure = dict(judge_source_closure())
    return len(closure) == 25, '%d files, image %s' % (len(closure), image_digest()[:19])


def check_history():
    path = ROOT / 'local/docs/reviews/20261018-system-handoff/baseline/baseline.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    m = data['historical_metrics']
    expected = {'N': 7148, 'TP': 4196, 'FN': 43, 'FP': 70, 'TN': 2839}
    actual = {k: m[k] for k in expected}
    return actual == expected, 'N=%d TP=%d FN=%d FP=%d TN=%d' % tuple(actual[k] for k in expected)


def check_catalog():
    data = json.loads((ROOT / 'local/lab/data/catalog_extension.json').read_text(encoding='utf-8'))
    bad = []
    for row in data['problems']:
        qid = int(row['qid'])
        try:
            checked = catalog.extension_row(qid)
            cases = catalog.load_cases(qid)
        except Exception as error:                                  # noqa: BLE001 - reported
            bad.append('%s: %s' % (qid, error))
            continue
        if not cases or len(cases) < 3:
            bad.append('%s: cases' % qid)
        elif any(not any(g['language'] == lang and g['status'] == 'Accepted' and g['correct'] == g['total']
                         for g in checked['gates']) for lang in checked['languages']):
            bad.append('%s: gate' % qid)
    return not bad, '%d entries, %d failing' % (len(data['problems']), len(bad))


def check_accounting():
    run = json.loads((ROOT / 'local/docs/reviews/20261018-migration/migration-v5.json').read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'local/docs/reviews/20261018-migration/manifest-v5.json').read_text(encoding='utf-8'))
    expected = len(manifest['selected']) * 8
    total = len(run['combinations']) + len(run['blocked'])
    without_candidate = [r for r in run['combinations'] if not r['candidates']]
    without_reason = [b for b in run['blocked'] if not str(b.get('reason') or '').strip()]
    ok = total == expected and not without_candidate and not without_reason
    return ok, 'tested=%d blocked=%d total=%d expected=%d no-candidate=%d no-reason=%d' % (
        len(run['combinations']), len(run['blocked']), total, expected,
        len(without_candidate), len(without_reason))


def check_chain():
    base = ROOT / 'local/docs/reviews/20261018-migration'
    chain = json.loads((base / 'closure-chain.json').read_text(encoding='utf-8'))
    prov = json.loads((base / 'closure-provenance.json').read_text(encoding='utf-8'))
    ce = json.loads((base / 'closure-counterexample.json').read_text(encoding='utf-8'))
    stages = {'generate', 'rejudge', 'resume', 'translate'}
    have = stages <= set(chain)
    provenance_ok = all(row.get('image') for row in prov['rows'])
    return have and provenance_ok and bool(ce.get('first_failure')), \
        'stages=%d provenance_rows=%d counterexample=%s' % (
            len(stages & set(chain)), len(prov['rows']), 'yes' if ce.get('first_failure') else 'no')


def check_reports():
    base = ROOT / 'local/docs/reviews/20261018-migration'
    reports = sorted(base.glob('closure-report-*.html'))
    if not reports:
        return False, 'no reports'
    missing = [p.name for p in reports
               if not any(token in p.read_text(encoding='utf-8') for token in ('答案依据', 'Answer evidence'))]
    return not missing, '%d reports, %d without answer evidence' % (len(reports), len(missing))


CHECKS = (('judge closure untouched', check_closure),
          ('historical metrics unchanged', check_history),
          ('catalogue internally consistent', check_catalog),
          ('migration accounting closed', check_accounting),
          ('chain and provenance present', check_chain),
          ('reports carry answer evidence', check_reports))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--strict', action='store_true', help='exit non-zero when a check fails')
    args = parser.parse_args()
    failures = 0
    for name, check in CHECKS:
        try:
            ok, detail = check()
        except Exception as error:                                  # noqa: BLE001 - reported
            ok, detail = False, '%s: %s' % (type(error).__name__, str(error)[:120])
        failures += 0 if ok else 1
        print('%-32s %-4s %s' % (name, 'PASS' if ok else 'FAIL', detail))
    print('\n%d/%d checks passed' % (len(CHECKS) - failures, len(CHECKS)))
    if args.strict and failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
