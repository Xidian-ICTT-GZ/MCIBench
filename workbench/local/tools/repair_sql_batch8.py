"""Explicitly migrate four reviewed SQL profiles, preserving inputs and attempts."""
import argparse
from copy import deepcopy
import inspect
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages as packages, sql_answers as sql, problem_io as io
from local.lab import sql_review_batch8 as reviewed, portable_judging as judging, mysql_packages
from local.lab.behavior import sha
from local.lab.testcase_workflow import lock, save


def validator_source(qid):
    return ('from datetime import datetime\nimport re\nQIDS={1934,3374,3436,3451}\n'
            f'MAX_ROWS={reviewed.MAX_ROWS}\nMAX_TEXT={reviewed.MAX_TEXT}\nMAX_TOTAL_TEXT={reviewed.MAX_TOTAL_TEXT}\n'
            "LETTERS=set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')\n" + inspect.getsource(reviewed.valid) +
            f'\ndef solve(data):\n try:return valid({qid},data) is True\n except (ValueError,TypeError,KeyError,IndexError):return False\n')


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    runner.DOCKER_IMAGE = image_digest()
    proof = json.loads((args.output.parent / 'proposed-reviewed-reference-gates.json').read_text(encoding='utf8'))
    assert len(proof['checks']) == 12 and all(c['passed'] for c in proof['checks'])
    report = {'version': sql.VERSION, 'checks': [], 'model_calls_in_this_command': 0, 'historical_jobs_unchanged': True}
    for qid in (1934, 3374, 3436, 3451):
        with lock(qid, packages.DATA_DIR):
            path = packages.DATA_DIR / f'{qid}.json'
            checkpoint = packages.DATA_DIR / 'pending' / f'{qid}.json'
            already_migrated = False
            if path.exists():
                old = json.loads(path.read_text(encoding='utf8'))
                if old.get('reviewed_migration', {}).get('version') == sql.VERSION:
                    if packages.read(qid, runner.DOCKER_IMAGE):
                        print(qid, 'already migrated; original receipt retained', flush=True)
                        continue
                    already_migrated = True
                unsigned = deepcopy(old)
                digest = unsigned.pop('package_sha256')
                assert digest == sha(unsigned)
                save(packages.DATA_DIR / 'archive' / str(qid) / (digest + '.json'), old)
                retained = deepcopy([c for c in old['cases'] if c.get('origin') == 'model_input_independent_execution'])
                assert old['generated_count'] == len(retained) == 12
                draft = json.loads(checkpoint.read_text(encoding='utf8')) if checkpoint.exists() else {}
            else:
                assert qid == 3451
                old = json.loads(checkpoint.read_text(encoding='utf8'))
                already_migrated = old.get('reviewed_migration', {}).get('version') == sql.VERSION
                if already_migrated and old['binding'] == packages.binding(qid, runner.DOCKER_IMAGE, packages.describe(qid)):
                    print(qid, 'reviewed resume checkpoint already current; retained', flush=True)
                    continue
                digest = sha(old)
                retained = deepcopy(old['accepted'])
                assert len(retained) == 9
                draft = deepcopy(old)
            archive = args.output.parent / 'before' / 'attempts'
            archive.mkdir(parents=True, exist_ok=True)
            if checkpoint.exists() and not (archive / f'{qid}-pending.json').exists():
                shutil.copy2(checkpoint, archive / f'{qid}-pending.json')
            for folder in (packages.DATA_DIR / 'attempts', mysql_packages.DATA_DIR / 'attempts'):
                for item in folder.glob(f'{qid}-*.json'):
                    dest = archive / (folder.parent.name + '-' + item.name)
                    if not dest.exists():
                        shutil.copy2(item, dest)
            descriptor = packages.describe(qid)
            binding = packages.binding(qid, runner.DOCKER_IMAGE, descriptor)
            if already_migrated:
                expected_old = deepcopy(descriptor)
                if qid == 3374:
                    expected_old['comparison']['unordered_rows'] = False
                assert old['descriptor'] == descriptor or qid == 3374 and old['descriptor'] == expected_old
            seen = {sha(c['args']) for c in descriptor['official']}
            corrections = []
            for index, case in enumerate(retained):
                assert case['origin'] == 'model_input_independent_execution'
                assert sql.valid(qid, case['args']) is True
                io.check_database_input(qid, case['args'], descriptor['official'][0]['args'])
                assert sha(case['args']) not in seen
                seen.add(sha(case['args']))
                expected = sql.answer(qid, case['args'])
                if not judging.compare(qid, expected, case, descriptor['comparison']):
                    corrections.append({'model_input_index': index, 'input_sha256': sha(case['args']),
                                        'previous_expected': case['expected'], 'reviewed_expected': expected,
                                        'basis': descriptor.get('statement_revision')})
                case['expected'] = expected
            assert len(corrections) == (3 if qid == 3374 and not already_migrated else 0)
            extras = []
            reviewed_cases = next(c['cases'] for c in proof['checks'] if c['qid'] == qid)
            for case in reviewed_cases:
                if sha(case['args']) in seen:
                    continue
                assert sql.valid(qid, case['args']) is True
                extra = {'args': deepcopy(case['args']), 'expected': sql.answer(qid, case['args']),
                         'origin': 'reviewed_batch8_boundary'}
                assert judging.compare(qid, extra['expected'], case, descriptor['comparison'])
                extras.append(extra)
                seen.add(sha(case['args']))
            cases = deepcopy(descriptor['official']) + retained + extras
            validator = validator_source(qid)
            constraint_gate = judging.execute(0, 'python3', validator,
                [{'args': c['args'], 'expected': True} for c in cases] + [{'args': [], 'expected': False}, {'args': None, 'expected': False}])
            assert constraint_gate['ac_status'] == 'Accepted', (qid, constraint_gate)
            oracles, gates = [], []
            for language in ('python3', 'sqlite', 'mysql'):
                code = sql.reference(qid, language)
                assert code and any(p['qid'] == qid and p['language'] == language and p['source_sha256'] == sha(code) for p in proof['checks'])
                verdict = judging.execute(qid, language, code, cases, descriptor['comparison'])
                gates.append({'language': language, 'verdict': verdict})
                save(args.output, {**report, 'in_progress': {'qid': qid, 'gates': gates}})
                assert verdict['ac_status'] == 'Accepted', (qid, language, verdict)
                oracles.append({'language': language, 'code': code, 'code_sha256': sha(code),
                                'origin': 'reviewed_sql_reference', 'controller_version': sql.VERSION})
            assert binding == packages.binding(qid, runner.DOCKER_IMAGE, descriptor)
            migration = {'version': sql.VERSION, 'previous_package_or_pending_sha256': digest,
                         'retained_model_input_sha256': [sha(c['args']) for c in retained],
                         'target_model_input_count': 12, 'retained_model_input_count': len(retained),
                         'needs_model_input_resume': len(retained) < 12, 'completed_model_input_count': len(retained),
                         'answer_corrections': corrections, 'statement_revision': descriptor.get('statement_revision'),
                         'historical_result_unchanged': True}
            if already_migrated:
                migration = deepcopy(old['reviewed_migration'])
                migration.setdefault('binding_refreshes', []).append({'previous_signed_or_pending_sha256': digest,
                    'descriptor_sha256': sha(descriptor),
                    'reason': 'current_sources_and_explicit_unordered_word_query_result_contract'})
            validator_record = {'code': validator, 'code_sha256': sha(validator), 'gate': constraint_gate,
                                'origin': 'reviewed_self_contained_input_scope'}
            if len(retained) < 12:
                draft.update(version=packages.VERSION, qid=qid, binding=binding, descriptor=descriptor,
                             accepted=retained, oracles=oracles, validator=validator_record, state='building',
                             reviewed_migration=migration, reviewed_extras=extras)
                save(checkpoint, draft)
            else:
                row = {**deepcopy(old), 'binding': binding, 'descriptor': descriptor, 'comparison': descriptor['comparison'],
                       'cases': cases, 'cases_sha256': sha(cases), 'generated_count': len(retained),
                       'validator': validator_record, 'oracles': oracles, 'gates': gates, 'gates_passed': True,
                       'reference_languages': [o['language'] for o in oracles], 'reviewed_migration': migration,
                       'reviewed_added_case_count': len(extras), 'evidence_level': 'reviewed_sql_controller_and_executed_oracles',
                       'constraint_evidence': 'reviewed_sql_input_scope',
                       'oracle_scope': {'max_rows': sql.MAX_ROWS[qid], 'version': sql.VERSION,
                                        'description': sql.note(qid), **reviewed.scope(qid)},
                       'limitations': ['finite_tests_not_proof', 'explicit_reviewed_input_scope', 'LC_environment_equivalence_not_established']}
                if descriptor.get('statement_revision'):
                    row['statement_revision'] = deepcopy(descriptor['statement_revision'])
                row.pop('package_sha256', None)
                row['package_sha256'] = sha(row)
                save(path, row)
            native = mysql_packages.DATA_DIR / f'{qid}.json'
            if native.exists():
                signed = json.loads(native.read_text(encoding='utf8'))
                unsigned = deepcopy(signed)
                old_sha = unsigned.pop('sha256')
                assert old_sha == sha(unsigned)
                save(mysql_packages.DATA_DIR / 'archive' / str(qid) / (old_sha + '.json'), signed)
            report['checks'].append({'qid': qid, 'retained_model_inputs': len(retained),
                                     'reviewed_added_inputs': len(extras), 'case_count_before_resume': len(cases),
                                     'answer_corrections': corrections, 'validator_gate': constraint_gate,
                                     'gates': gates, 'needs_model_input_resume': len(retained) < 12, 'passed': True})
            save(args.output, report)
            print(qid, 'retained', len(retained), 'reviewed', len(extras), 'corrections', len(corrections), 'PASS', flush=True)
    print('Explicit migrations verified; q3451 retains a three-input model gap.', flush=True)


if __name__ == '__main__':
    main()
