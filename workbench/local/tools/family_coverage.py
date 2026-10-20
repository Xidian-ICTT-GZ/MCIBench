"""Representative coverage across the four interface families.

For exposed representative problems (plain function, tree, linked list, design),
try to prepare and execute each language WITHOUT a model first. The point is to
record honestly which cells the engine can do on its own and which need a generated
adapter, instead of asserting "eight languages" from the plain-function success.

Cells are:
  reference_ok   the reference executed through the resolved entry and passed
  gate_failed    it executed but did not match the expected outputs (kept as evidence)
  needs_model    preparing this cell requires a generated adapter or reference
  no_reference   no independent reference for that language
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import load_reference
from local.harness.identity import image_digest, judge_source_closure
from local.lab import interface_policy, native_adapters, native_structural
from local.lab import problem_io, problem_packages as packages

LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')
REPRESENTATIVES = {
    # q42 is packaged but its template asset is missing from the repository, so it
    # measures a missing asset rather than the engine; q443 is a clean representative.
    'function': (443,),
    'tree': (117, 94),
    'linked_list': (2, 142),
    'design': (146,),
}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = image_digest()
    report = {'version': 'family-coverage-v1',
              'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'image': image, 'judge_closure': dict(judge_source_closure()),
              'families': {}}
    for family, qids in REPRESENTATIVES.items():
        rows = []
        for qid in qids:
            package_path = packages.DATA_DIR / ('%s.json' % qid)
            if not package_path.exists():
                rows.append({'qid': qid, 'state': 'no_package'})
                continue
            package = json.loads(package_path.read_text(encoding='utf-8'))
            descriptor = {'qid': qid, 'kind': problem_io.kind(qid), 'official': package['cases'],
                          'comparison': package.get('comparison') or {'mode': 'ordered'},
                          'interface_note': None, 'warnings': []}
            try:
                interface = packages.code_interface(qid, 'python3')
                route = interface_policy.route(interface)
            except interface_policy.UnknownInterface:
                interface, route = None, 'blocked'
            row = {'qid': qid, 'interface': interface, 'route': route, 'cases': len(package['cases']),
                   'cells': {}}
            for language in LANGUAGES:
                try:
                    reference = load_reference(qid, language)
                except (OSError, ValueError, KeyError):
                    row['cells'][language] = {'state': 'no_reference'}
                    continue
                # Deterministic structural bridges cover shapes the model-free path
                # cannot: no profile is needed, and the plan records that mutation
                # coverage is absent.
                deterministic = native_structural.prepare_reference_only(
                    qid, language, descriptor, package, image)
                if deterministic is not None:
                    row['cells'][language] = {
                        'state': 'reference_ok' if deterministic['passed'] else 'gate_failed',
                        'plan': 'bridge', 'admission': deterministic['admission'],
                        'ac_status': deterministic['reference_gate']['ac_status'],
                        'correct': deterministic['reference_gate']['correct'],
                        'total': deterministic['reference_gate']['total'],
                        'dropped_unrepresentable': deterministic['reference_gate']['dropped_unrepresentable'],
                        'error': deterministic['reference_gate']['error']}
                    continue
                try:
                    plan = native_adapters.prepare(qid, language, descriptor, package, None, image)
                except TypeError as error:
                    if 'NoneType' in str(error):
                        row['cells'][language] = {'state': 'needs_model',
                                                  'reason': 'adapter_or_reference_requires_a_profile'}
                    else:
                        row['cells'][language] = {'state': 'error', 'reason': str(error)[:150]}
                    continue
                except Exception as error:                          # noqa: BLE001
                    row['cells'][language] = {'state': 'error',
                                              'reason': '%s: %s' % (type(error).__name__, str(error)[:150])}
                    continue
                try:
                    verdict = native_adapters.execute(qid, language, reference, package['cases'],
                                                      descriptor['comparison'], plan, full=True)
                except Exception as error:                          # noqa: BLE001
                    row['cells'][language] = {'state': 'error', 'plan': plan.get('kind'),
                                              'reason': '%s: %s' % (type(error).__name__, str(error)[:150])}
                    continue
                meta = verdict.get('_meta') or {}
                ok = (verdict.get('ac_status') == 'Accepted'
                      and verdict.get('total_correct') == verdict.get('total_testcases')
                      and not meta.get('dropped_unrepresentable'))
                row['cells'][language] = {
                    'state': 'reference_ok' if ok else 'gate_failed',
                    'plan': plan.get('kind'),
                    'ac_status': verdict.get('ac_status'),
                    'correct': verdict.get('total_correct'),
                    'total': verdict.get('total_testcases'),
                    'dropped_unrepresentable': meta.get('dropped_unrepresentable'),
                    'error': (meta.get('error') or '')[:200]}
            rows.append(row)
        report['families'][family] = rows

    states = Counter(cell['state'] for rows in report['families'].values()
                     for row in rows for cell in row.get('cells', {}).values())
    report['summary'] = dict(states)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('cell states:', dict(states))
    for family, rows in report['families'].items():
        for row in rows:
            cells = row.get('cells') or {}
            if not cells:
                print('  %-12s q%-5s %s' % (family, row['qid'], row.get('state')))
                continue
            ok = [lang for lang, cell in cells.items() if cell['state'] == 'reference_ok']
            print('  %-12s q%-5s route=%-9s ok=%d %s' % (family, row['qid'], row['route'], len(ok), ok))
    print('output ->', args.output)


if __name__ == '__main__':
    main()
