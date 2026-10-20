"""Functional evidence gates and versioned activation; no formal corpus writes."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from local.common import REPO_ROOT, KEY_TO_LABEL, load_reference, load_snippet, load_ft_test_qids, LANGS
from local.lab import input_contracts as contracts
from local.lab.correctness_assets import fixtures, VERSION as ASSETS_VERSION
from local.lab import audited_judging
from local.lab.behavior import sha

VERSION = 'functional-correctness-audit-v1'
DATA_DIR = REPO_ROOT / 'local/dashboard/packages/server/data/lab_correctness'


def binding(qid, cases, languages, image):
    return {'qid': qid, 'cases_sha256': sha(cases), 'languages': sorted(languages),
            'profile': audited_judging.profile(image), 'contracts_sha256': contracts.fingerprint(),
            'assets_sha256': sha(Path(__file__).with_name('correctness_assets.py').read_text(encoding='utf-8')),
            'audit_sha256': sha(Path(__file__).read_text(encoding='utf-8')),
            'references_sha256': {l: sha(load_reference(qid, l)) for l in languages}}


def scope(qid):
    limits = {3: {'parameter': 's', 'max_length': 2000}, 1014: {'parameter': 'values', 'max_length': 1000}}
    return {'independent_oracle': contracts.VERSION, 'oracle_limit': limits.get(qid),
            'limitations': ['finite_regression_suite_not_correctness_probability', 'leetcode_alignment_not_measured'],
            'input_subset': 'printable_ascii' if qid in (3,125) else 'reviewed_problem_constraints',
            'answer_subset': 'signed_int32_answer' if qid == 91 else None}


def checked_cases(qid, cases):
    """Check every answer within the oracle's scope; count wider reference-only cases."""
    contracts.require(qid)
    checked = outside = 0
    seen = {}
    for case in cases:
        if not contracts.valid(qid, case.get('args')):
            raise ValueError(f'q{qid}: corpus input violates reviewed constraints')
        key = sha(case['args'])
        if key in seen and sha(case['expected']) != seen[key]:
            raise ValueError('conflicting expected answers for the same input')
        seen[key] = sha(case['expected'])
        try:
            expected = contracts.answer(qid, case['args'])
        except ValueError:
            # Only the explicit independent-oracle size/answer bounds are outside.
            a = next(iter(case['args'].values()))
            if (qid == 3 and len(a) > 2000 or qid == 1014 and len(a) > 1000
                    or qid == 91):
                outside += 1
                continue
            raise
        if sha(expected) != sha(case['expected']):
            raise ValueError(f'q{qid}: independent answer conflicts with corpus')
        checked += 1
    return {'oracle_checked': checked, 'outside_oracle_scope': outside}


def _execute(qid, language, code, cases, image, cache_dir, check_cancel):
    check_cancel()
    key = sha({'qid':qid,'snippet':sha(load_snippet(qid,language)),
               'code':sha(code), 'cases':sha(cases), 'profile':audited_judging.profile(image), 'language':language})
    path = Path(cache_dir) / f'{key}.json'
    if path.exists():
        cached = json.loads(path.read_text(encoding='utf-8'))
        if cached.get('key') == key and cached.get('result_sha256') == sha(cached.get('result')):
            return deepcopy(cached['result'])
    with tempfile.TemporaryDirectory(prefix='mci_correctness_') as folder:
        code_path = Path(folder) / f'{qid}_{KEY_TO_LABEL[language]}_1.txt'
        code_path.write_text(code, encoding='utf-8')
        result = audited_judging.run(code_path, cases, check_cancel=check_cancel)
    # Cache successful executions, not infrastructure faults. Every key binds
    # source, input bytes, image and the complete grading configuration.
    from local.lab.testcase_workflow import save
    save(path, {'key':key, 'result':result, 'result_sha256':sha(result)})
    return result


def audit(qid, cases, languages, image, *, cache_dir, check_cancel=lambda:None, on_event=lambda e:None):
    from local.gen_testcases.extract_examples import extract_from_prompt
    if not {'python3','cpp'} <= set(languages):
        raise ValueError('functional audit requires Python3 and C++ reference gates')
    if qid in load_ft_test_qids() and set(languages) != set(LANGS):
        raise ValueError('historical questions retain the eight-language reference gate')
    start_binding = binding(qid, cases, languages, image)
    counts = checked_cases(qid, cases)
    assets = fixtures(qid)
    witness_cases = []
    for asset in assets:
        if asset['role'] == 'incorrect':
            args = asset['witness']
            case = {'args':args, 'expected':contracts.answer(qid, args)}
            if sha(case) not in {sha(c) for c in witness_cases}:
                witness_cases.append(case)
    official = extract_from_prompt(contracts.description(qid))
    checked_cases(qid, official)
    correct_cases = deepcopy(cases)
    keys = {sha(c['args']) for c in correct_cases}
    for case in official + witness_cases:
        if sha(case['args']) not in keys:
            correct_cases.append(case); keys.add(sha(case['args']))
    row = {'version':VERSION, 'assets_version':ASSETS_VERSION, 'qid':qid, 'binding':start_binding,
           'scope':scope(qid), 'answer_checks':counts, 'references':[], 'fixtures':[],
           'passed':False, 'promoted':False, 'created_at':datetime.now(timezone.utc).isoformat()}
    for language in languages:
        check_cancel();on_event({'qid':qid,'stage':'reference','language':language})
        result = _execute(qid,language,load_reference(qid,language),correct_cases,image,cache_dir,check_cancel)
        row['references'].append({'language':language, 'case_count':len(correct_cases),
                                   'verdict':audited_judging.public_verdict(result)})
    for asset in assets:
        check_cancel();on_event({'qid':qid,'stage':'fixture','id':asset['id']})
        entry = {k:v for k,v in asset.items() if k != 'code'}
        if asset['role'] == 'incorrect':
            case = {'args':asset['witness'], 'expected':contracts.answer(qid,asset['witness'])}
            witness = _execute(qid,asset['language'],asset['code'],[case],image,cache_dir,check_cancel)
            entry.update(witness_expected=case['expected'], witness_verdict=audited_judging.public_verdict(witness),
                         non_equivalent_verified=witness['ac_status']=='Wrong Answer')
        result = _execute(qid,asset['language'],asset['code'],
                          correct_cases if asset['role']=='correct' else cases,image,cache_dir,check_cancel)
        entry['corpus_verdict'] = audited_judging.public_verdict(result)
        entry['state'] = ('passed' if result['ac_status']=='Accepted' else 'false_rejection') if asset['role']=='correct' else (
            'unverified_mutant' if not entry['non_equivalent_verified'] else
            'killed' if result['ac_status']=='Wrong Answer' else
            'survived' if result['ac_status']=='Accepted' else 'execution_failure_not_functional_kill')
        row['fixtures'].append(entry)
    incorrect = [f for f in row['fixtures'] if f['role']=='incorrect']
    correct = [f for f in row['fixtures'] if f['role']=='correct']
    eligible = [f for f in incorrect if f['non_equivalent_verified']]
    killed = sum(f['state']=='killed' for f in eligible)
    row['summary'] = {'incorrect_total':len(incorrect), 'verified_non_equivalent':len(eligible), 'killed':killed,
                      'survived':sum(f['state']=='survived' for f in eligible),
                      'pending':sum(f['state'] not in ('killed','survived') for f in incorrect),
                      'detection_rate':killed/len(eligible) if eligible else None,
                      'correct_total':len(correct), 'correct_passed':sum(f['state']=='passed' for f in correct)}
    row['passed'] = (len(incorrect)==len(eligible)==killed==4 and len(correct)==4
                     and all(f['state']=='passed' for f in correct)
                     and all(r['verdict']['ac_status']=='Accepted' for r in row['references']))
    if binding(qid,cases,languages,image) != start_binding:
        raise ValueError('audit inputs or sources changed during execution')
    row['report_sha256'] = sha(row)
    return row


def save_receipt(row, *, promoted=False, data_dir=None):
    from local.lab.testcase_workflow import save
    value = deepcopy(row)
    value['promoted'] = bool(promoted and value['passed'])
    value.pop('report_sha256',None)
    value['report_sha256'] = sha(value)
    save(Path(data_dir or DATA_DIR)/f"{value['qid']}.json",value)


def receipt(qid, cases, image=None, *, data_dir=None):
    if qid not in contracts.QIDS:
        return None
    try:
        row = json.loads((Path(data_dir or DATA_DIR)/f'{qid}.json').read_text(encoding='utf-8'))
        digest = row.pop('report_sha256')
        if digest != sha(row) or row.get('version') != VERSION:
            return None
        b = row['binding']
        if binding(qid,cases,b['languages'],image or b['profile']['image']) != b:
            return None
        row['report_sha256'] = digest
        return row
    except (OSError,ValueError,KeyError,TypeError):
        return None


def evidence(qid, cases, image=None):
    row = receipt(qid,cases,image)
    out = {'state':'not_audited','profile_version':'full-corpus-verdict-v1',
           'case_count':len(cases),'cases_sha256':sha(cases), 'leetcode_alignment':'not_measured'}
    if qid in contracts.QIDS:
        out['scope'] = scope(qid)
    if row:
        out.update(state='verified' if row['passed'] else 'gaps_found',
                   profile_version=audited_judging.VERSION if row['passed'] and row['promoted'] else 'full-corpus-verdict-v1',
                   mutation_summary=row['summary'],answer_checks=row['answer_checks'],reference_gate_count=len(row['references']),
                   report_sha256=row['report_sha256'], promoted=row['promoted'])
    return out
