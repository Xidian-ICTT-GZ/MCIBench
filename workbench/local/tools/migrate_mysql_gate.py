"""Explicit migration of a native MySQL gate after a reviewed corpus change.

revalidate_mysql_gates refuses a changed case set on purpose. This tool is the
sanctioned migration: it archives the old gate, re-executes the retained native
reference over the current package corpus, and publishes only on Accepted.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from local.harness.identity import image_digest
from local.lab import mysql_packages as gates, problem_packages as packages, portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import lock, save


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qid', type=int, required=True)
    parser.add_argument('--reason', required=True, help='why the case set changed (recorded)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    qid = args.qid
    image = image_digest()
    with lock(qid, gates.DATA_DIR):
        path = gates.DATA_DIR / f'{qid}.json'
        old = json.loads(path.read_text(encoding='utf8'))
        signed = deepcopy(old)
        digest = signed.pop('sha256')
        if digest != sha(signed):
            raise ValueError('prior gate is not signed as expected')
        if old['verdict']['ac_status'] != 'Accepted':
            raise ValueError('prior gate was not Accepted; this is not a migration')
        if sha(old['oracle']['code']) != old['oracle']['code_sha256']:
            raise ValueError('retained native reference source drift')
        descriptor = packages.describe(qid)
        package = packages.read(qid, image, descriptor=descriptor)
        if not package:
            raise ValueError('base package must pass current revalidation first')
        if sha(package['cases']) == old['binding']['cases_sha256']:
            raise ValueError('cases did not change; use revalidate_mysql_gates instead')

        current = gates.binding(qid, descriptor, package)
        verdict = judging.execute(qid, 'mysql', old['oracle']['code'], package['cases'], package['comparison'])
        record = {'qid': qid, 'previous_gate_sha256': digest,
                  'previous_cases_sha256': old['binding']['cases_sha256'],
                  'new_cases_sha256': sha(package['cases']),
                  'previous_case_count': old['binding'].get('case_count'),
                  'new_case_count': len(package['cases']),
                  'verdict': verdict, 'passed': verdict['ac_status'] == 'Accepted'}
        save(args.output, {'scope': 'explicit_native_gate_migration', 'reason': args.reason,
                           'image': image, 'checks': [record]})
        if not record['passed']:
            raise ValueError('native reference failed on the migrated corpus; no gate published')
        if current != gates.binding(qid, descriptor, package):
            raise ValueError('runtime changed during the native gate migration')
        archive = gates.DATA_DIR / 'archive' / str(qid) / (digest + '.json')
        if not archive.exists():
            save(archive, old)
        row = {'binding': current, 'oracle': old['oracle'], 'verdict': verdict,
               'migration': {'reason': args.reason,
                             'previous_gate_sha256': digest,
                             'previous_cases_sha256': old['binding']['cases_sha256'],
                             'new_cases_sha256': sha(package['cases']),
                             'previous_case_count': old['binding'].get('case_count'),
                             'new_case_count': len(package['cases']),
                             'migrated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                             'source_unchanged': True}}
        row['sha256'] = sha(row)
        save(path, row)
        print(json.dumps({'qid': qid, 'cases': len(package['cases']),
                          'verdict': verdict['ac_status'], 'correct': verdict['total_correct'],
                          'archive': str(archive.relative_to(ROOT)), 'gate_sha256': row['sha256']},
                         ensure_ascii=False))


if __name__ == '__main__':
    main()
