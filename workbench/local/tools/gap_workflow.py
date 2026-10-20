"""Checkpointed, bounded discrepancy repair. No scheduler or LC submissions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from contextlib import contextmanager, closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'local/dashboard/packages/server/data/local.db'
RESULTS = ROOT / 'local/results/all_models'
CORPUS = ROOT / 'local/testcases'
JOBS = ROOT / 'local/results/gap_workflow'
SCOPE = "lc_origin='submissions' AND local_origin='all_models' AND identity_status='current' AND task='gen' AND in_ft_test=1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def require_dashboard():
    """Fail before publication if its required served verification is unavailable."""
    url='http://127.0.0.1:8090/api/v1/version'
    try:
        expected=json.loads((ROOT/'local/dashboard/packages/server/build-manifest.json').read_bytes())['build_id']
        with urllib.request.urlopen(url,timeout=5) as response:served=json.load(response)
        if not expected or served.get('build_id')!=expected:
            raise ValueError('served build differs from the local build manifest')
    except Exception as exc:
        raise RuntimeError(f'Dashboard preflight failed before any publication: {exc}') from exc


def route(row):
    if row['klass'] == 'false_ac':
        return {'Wrong Answer': 'wa', 'Runtime Error': 'crash',
                'Time Limit Exceeded': 'performance'}.get(row['leetcode'], 'environment')
    return 'diagnose'


def plan(db=DB):
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            f"SELECT s.*,p.split AS eval_split FROM slots s JOIN problems p ON p.qid=s.qid WHERE {SCOPE} "
            "AND klass IN ('false_ac','false_wa') ORDER BY s.qid,s.model,s.lang,s.cand")]
        covered = [dict(r) for r in con.execute(
            f"SELECT s.* FROM slots s JOIN problems p ON p.qid=s.qid WHERE {SCOPE} "
            "AND leetcode<>'' ORDER BY s.qid,s.model,s.lang,s.cand")]
        skipped = [dict(r) for r in con.execute(
            "SELECT s.qid,s.model,s.lang,s.cand,s.identity_status,s.identity_reason FROM slots s "
            "JOIN problems p ON p.qid=s.qid WHERE lc_origin='submissions' AND in_ft_test=1 "
            "AND identity_status<>'current'")]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = set()
        if 'local_results' in tables:
            versions = {r[0] for r in con.execute(
                "SELECT DISTINCT json_extract(identity_json,'$.config.host_python') "
                "FROM local_results WHERE identity_status='current' AND task='gen' "
                "AND run_name=model||'_local'") if r[0]}
        if len(versions) > 1:
            raise ValueError('Multiple production Python versions; freeze separate evaluation batches first.')
    tasks = []
    for row in rows:
        branch = route(row)
        # Unknown and retrospective holdout labels never authorize targeted fuzzing.
        if branch in ('wa','crash','performance') and row['eval_split'] != 'dev':
            branch = 'holdout_readonly'
        tasks.append({'id': f"{row['qid']}-{row['model']}-{row['lang']}-{row['cand']}",
                      'branch': branch, 'slot': row, 'status': 'pending'})
    return {'schema': 1, 'created_at': datetime.now().isoformat(),
            'python': next(iter(versions), platform.python_version()), 'tasks': tasks, 'covered_slots': covered,
            'skipped_slots': skipped, 'commands': [], 'refresh_qids': [], 'refresh_done': False}


def code_path(slot):
    from local.common import KEY_TO_LABEL
    return RESULTS / slot['model'] / 'codes' / f"{slot['qid']}_{KEY_TO_LABEL[slot['lang']]}_{slot['cand']}.txt"


def assert_current(slot):
    from local.dashboard.scripts.import_local_results import inspect_result
    path = RESULTS / slot['model'] / 'results' / str(slot['qid']) / f"{slot['qid']}_{slot['lang']}_{slot['cand']}.json"
    payload = json.loads(path.read_bytes())
    status, reason = inspect_result(payload, model=slot['model'], qid=slot['qid'],
                                    lang=slot['lang'], cand=slot['cand'])
    if status != 'current':
        raise ValueError(f'raw baseline is {status}: {reason}')


def check_result(out, identity, n):
    from local.harness.identity import result_errors
    errors = result_errors(out, identity)
    if out.get('total_testcases') != n:
        errors.append('requested corpus not fully covered')
    if errors:
        raise ValueError(', '.join(errors))
    return out


def observe(slot, cases, *, diagnostic=False):
    from local.dashboard.scripts.judge_all_models import ORIG_DB
    from local.harness.identity import verification_identity
    from local.judge import judge_one
    path = code_path(slot)
    context = dict(qid=slot['qid'], model=slot['model'], lang=slot['lang'],
                   attempt=slot['cand'], task=slot['task'], code_path=path,
                   config={'max_cases': 1000, 'run_timeout_s': 5})
    before = verification_identity(ORIG_DB, **context)
    out = judge_one(path, 'gen', 1000, 'docker', 5, cases_override=cases)
    from local.harness.identity import result_errors
    errors = result_errors(out, before)
    if out.get('total_testcases') != len(cases):
        errors.append('requested corpus not fully covered')
    if not diagnostic:
        check_result(out, before, len(cases))
    if verification_identity(ORIG_DB, **context) != before:
        raise ValueError('identity changed during execution')
    return {'identity': before, 'result': out, 'result_validation_errors': errors,
            'cases_sha256': sha(json.dumps(cases, sort_keys=True).encode())}


def gate(verification, references, target=None):
    if verification.get('skipped') or verification.get('planned', 0) == 0:
        raise ValueError('empty/incomplete verification plan')
    if verification['executed'] != verification['planned'] or any(
            verification.get(k, 0) for k in ('missing', 'judge_error', 'broken', 'regressed')):
        raise ValueError('coverage or nonregression gate failed')
    from local.common import LANGS
    if len(references) != 8 or {r.get('lang') for r in references} != set(LANGS) or any(r.get('status_full') != 'Accepted' for r in references):
        raise ValueError('eight-language reference gate failed')
    from local.harness.evidence import valid_measurement
    if any(not valid_measurement(r.get('runtime_ms')) for r in references):
        raise ValueError('reference timing evidence missing')
    if target is not None:
        hits = [r for r in verification['results'] if all(r[k] == target[k] for k in ('model', 'lang', 'cand', 'task'))]
        if len(hits) != 1 or hits[0]['outcome'] != 'fixed':
            raise ValueError('target was not fixed under the production profile')


def _candidate_failure_case(evidence, out, cases):
    """失败用例只在**语料被完整覆盖、且判定为 WA** 时才是可用证据。

    judge_one 的 drop_unrepresentable 会删掉目标语言表示不了的用例，此时
    total_correct 是**删减后**的下标；直接拿去索引原始列表会指向未执行的输入
    （交接文档第五之 10 的同类错误）。所以覆盖校验不可少，宁可不给下标。
    """
    k = out.get('total_correct')
    if evidence.get('result_validation_errors'):
        return None
    if out.get('total_testcases') != len(cases):
        return None
    if out.get('ac_status') != 'Wrong Answer' or not isinstance(k, int):
        return None
    return cases[k] if 0 <= k < len(cases) else None


def diagnose(slot, directory):
    cases = json.loads((CORPUS / str(slot['qid']) / 'cases.json').read_bytes())
    save(directory / 'cases.json', cases)
    shutil.copy2(code_path(slot), directory / 'submission.txt')
    evidence = observe(slot, cases, diagnostic=True)
    out = evidence['result']
    # First nonpassing index is only a candidate; timeout and compiler failures
    # do not identify a single failing input (see _candidate_failure_case).
    evidence['candidate_failure_case'] = _candidate_failure_case(evidence, out, cases)
    evidence['lc_comparison'] = {'status': slot['leetcode'], 'submitted_code_hash': None,
                                 'same_lc_source_confirmed': False}
    error = str((out.get('_meta') or {}).get('error', ''))
    hint = 'Inspect driver, constraints, expected output and original LC submission.'
    if 'IndentationError' in error:
        hint = 'Compare source indentation with the LC submission; do not automatically strip or rewrite evaluated code.'
    elif out.get('ac_status') == 'Time Limit Exceeded':
        hint = 'Reproduce identical code/input at multiple diagnostic budgets; keep the formal budget unchanged.'
    elif out.get('ac_status') == 'Compile Error':
        hint = 'Compare exact source, compiler version, entry signature and dependencies.'
    evidence['next_action'] = hint
    save(directory / 'diagnostic.json', evidence)
    return {'status': 'diagnostic_incomplete' if evidence.get('result_validation_errors') else 'diagnosed', 'verdict': out.get('ac_status'),
            'note': 'Evidence collected; root cause and LC source equivalence remain unconfirmed.'}


def repair_wa(task, job, directory, args):
    def stage(name):
        task['stage'] = name
        save(args.job / 'job.json', job)
        print('  stage:', name, flush=True)
    from local.common import LANGS, load_snippet
    from local.gen_testcases.auto_fuzz import gen_args, parse_rules, violates_constraints
    from local.gen_testcases.routed_inputs import SUPPORTED, generate
    from local.gen_testcases.constraints import unparsed
    from local.gen_testcases.differential import python_outputs
    from local.gen_testcases.shrink import shrink_case
    from local.gen_testcases.scale_expand import validate
    from local.gen_testcases.validate import golden_one
    from local.gen_testcases.apply_found import verify_candidate
    from local.harness.typespec import DesignSig, parse_python_snippet
    slot = task['slot']; qid = slot['qid']; path = CORPUS / str(qid) / 'cases.json'
    old = path.read_bytes(); baseline = json.loads(old)
    stage('constraints_and_baseline')
    save(directory / 'cases.json', baseline)
    from local.gen_testcases.constraints import check
    invalid = [i for i,c in enumerate(baseline) if check(qid,c)]
    if invalid:
        return {'status': 'blocked_invalid_baseline', 'indices': invalid}
    if unparsed(qid):
        return {'status': 'blocked_constraints', 'unparsed': unparsed(qid)}
    sig = parse_python_snippet(load_snippet(qid, 'python3'))
    if isinstance(sig, DesignSig):
        return {'status': 'unsupported_design', 'note': 'Requires an operation-sequence generator.'}
    base = observe(slot, baseline)
    save(directory / 'baseline.json', base)
    if base['result']['ac_status'] != 'Accepted':
        return {'status': 'baseline_changed', 'verdict': base['result']['ac_status']}
    rules = parse_rules(qid); rng = random.Random(args.seed + qid)
    stage('generate_and_search')
    seen = {json.dumps(c['args'], sort_keys=True) for c in baseline}
    candidates = []
    branch=task.get('branch','wa')
    modes=('large',) if branch=='performance' else ('small','boundary','large') if branch=='crash' and qid in SUPPORTED else ('small','boundary')
    external=getattr(args,'candidate_file',None)
    candidate_dir=getattr(args,'candidate_dir',None)
    if candidate_dir:
        external=Path(candidate_dir)/f'{qid}.json'
        if not external.is_file():raise ValueError(f'No reviewed input file for q{qid}')
    if getattr(args, 'llm_corpus', False):
        from local.lab.testcase_workflow import read_bundle
        from local.harness.identity import image_digest
        reviewed = read_bundle(qid, image=image_digest())
        if not reviewed:
            return {'status': 'blocked_llm_corpus', 'reason': 'No fresh oracle/reference-verified generated corpus; run llm_testcases first.'}
        for generated in reviewed['generated_cases']:
            case = {'args': generated['args']}
            key = json.dumps(case['args'], sort_keys=True)
            if key not in seen and violates_constraints(qid, case) is None:
                candidates.append(case)
                seen.add(key)
        save(directory / 'generated-source.json', {'cases_sha256': reviewed['cases_sha256'],
             'generated_sha256': reviewed['generated_sha256'], 'model': reviewed['model'],
             'oracle': reviewed['independent_oracle'], 'leetcode_alignment': 'not_measured'})
        modes = ('llm_verified_inputs',)
    elif external:
        proposal=json.loads(Path(external).read_bytes())
        if proposal.get('qid')!=qid:raise ValueError('candidate problem differs from task')
        case={'args':proposal['case']['args']}
        if violates_constraints(qid,case):raise ValueError('external candidate violates constraints')
        if json.dumps(case['args'],sort_keys=True) not in seen:candidates=[case]
        modes=('external',)
    else:
        for mode in modes:
            for _ in range(1 if mode=='large' else args.samples):
                case = {'args': generate(qid,rng,mode) if qid in SUPPORTED else gen_args(qid, sig, rules, rng, mode)}
                key = json.dumps(case['args'], sort_keys=True)
                if key not in seen and violates_constraints(qid, case) is None:
                    seen.add(key); candidates.append(case)
    if not candidates:
        return {'status': 'no_legal_candidates'}
    # Batch below max_cases; never truncate the appended search corpus.
    outputs = python_outputs(qid, candidates, 'docker')
    if len(outputs) != len(candidates):
        raise ValueError('reference collection incomplete')
    save(directory / 'search-summary.json', {'seed': args.seed + qid, 'modes': list(modes),
                                           'samples_per_mode': 1 if branch=='performance' or external else args.samples, 'legal_unique': len(candidates),
                                           'reference_unavailable': sum(o is None for o in outputs),
                                           'production_budget_s': 5})
    candidates = [dict(c, expected=o) for c, o in zip(candidates, outputs) if o is not None]
    if not candidates:
        return {'status': 'blocked_oracle', 'reason': 'No candidate has a collected reference answer.'}
    batch_size = min(32, 1000 - len(baseline))
    if batch_size <= 0:
        return {'status': 'blocked_case_limit'}
    found = None
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start+batch_size]
        ev = observe(slot, baseline + batch)
        save(directory/f'search-trial-{start:04}.json',{'baseline_cases':len(baseline),
              'added_cases':batch,'observation':ev})
        out = ev['result']; k = out['total_correct']
        allowed={'Time Limit Exceeded'} if branch=='performance' else {'Wrong Answer','Runtime Error'} if branch=='crash' else {'Wrong Answer'}
        # Crashes can lose buffered output, so total_correct is not a reliable
        # input locator. One reviewed external input following an accepted
        # identical baseline can be rechecked directly through every gate.
        single_external_failure=bool(external and len(batch)==1 and branch in ('wa','crash')
                                     and out['ac_status'] in ('Wrong Answer','Runtime Error'))
        if not single_external_failure and (out['ac_status'] not in allowed or not len(baseline) <= k < len(baseline)+len(batch)):
            continue
        if single_external_failure:
            ev['failure_locator']='single external input versus accepted baseline; not inferred from total_correct'
        save(directory / 'search_failure.json', ev)
        stage('preserve_performance_input' if branch=='performance' else 'recheck_external_candidate' if external else 'shrink')
        found = batch[0] if single_external_failure else batch[k-len(baseline)] if branch=='performance' or external else shrink_case(
            qid, batch[k-len(baseline)], code_path(slot), slot['lang'], baseline,
            rounds=3, workers=2, valid=lambda c: violates_constraints(qid, c) is None)
        if found is not None:
            break
    if found is None:
        return {'status': 'no_counterexample', 'searched': len(candidates)}
    # Shrinker uses a different diagnostic timeout; production-profile gate below
    # is mandatory and cannot be bypassed.
    kept, votes = validate(qid, [found], 'docker', verbose=False)
    save(directory / 'candidate.json', {'cases': kept, 'votes': votes})
    if len(kept) != 1 or violates_constraints(qid, kept[0]) is not None:
        return {'status': 'blocked_oracle'}
    from local.gen_testcases.small_oracles import evaluate
    # 先取 oracle 源码哈希再评估：若该文件在评估期间被外部编辑，说明记录的版本
    # 与产生 status 的版本不一致，宁可中止（历史盲点正是『发布后 oracle 才被扩展』）。
    oracle_path = ROOT / 'local/gen_testcases/small_oracles.py'
    oracle_sha = sha(oracle_path.read_bytes())
    oracle = evaluate(qid, kept[0])
    if sha(oracle_path.read_bytes()) != oracle_sha:
        raise ValueError('oracle source changed during evaluation; re-run the task')
    # 记录这份独立 oracle 结论针对的候选**文件字节**，避免"复核针对的是另一份候选"。
    # 与 independent-recheck 的绑定口径一致：sha256(candidate.json 文件内容)。
    candidate_path = directory / 'candidate.json'
    oracle['candidate_sha256'] = sha(candidate_path.read_bytes())
    # 记录 oracle 的**源码版本**：只绑定候选字节不足以判断证据随时间是否变化。
    oracle['oracle_sha256'] = oracle_sha
    save(directory / 'independent-oracle.json', oracle)
    if oracle['status'] == 'disagrees':
        return {'status': 'blocked_oracle', 'reason': 'Independent brute force disagrees.'}
    # 只有**意见分歧**才阻断。unsupported 表示该输入超出有界 oracle 的范围，属于**记录**
    # 而非拒绝：TLE 路径本就只要求『原语料 AC + 三次 TLE + 参考解在预算内 + 全部门禁』，
    # 未要求独立 oracle。直接拒绝会误杀文档承诺可发布的合法反例（实测 17 题中有 8 题的
    # performance large 输入落在 oracle 范围之外）。这里显式留痕，随 publication 记录。
    oracle_unverified = bool(oracle['status'] != 'verified')
    candidate = baseline + kept
    if branch=='performance':
        repeats=[]
        for _ in range(2):
            repeats.append({'baseline':observe(slot,baseline),'candidate':observe(slot,candidate)})
        save(directory/'timeout-repeats.json',repeats)
        if any(r['baseline']['result']['ac_status']!='Accepted' or
               r['candidate']['result']['ac_status']!='Time Limit Exceeded' for r in repeats):
            return {'status':'unstable_timeout','note':'Formal budget unchanged.'}
    stage('eight_language_references')
    refs = [golden_one(qid, lang, candidate, 'docker') for lang in LANGS]
    if branch=='performance' and any(r.get('runtime_ms') is None or r['runtime_ms']>=5000 for r in refs):
        save(directory/'references.json',refs)
        return {'status':'blocked_reference_budget'}
    covered = [s for s in job['covered_slots'] if s['qid'] == qid]
    frozen = [(s['model'], s['lang'], s['cand'], s['task'], s['leetcode']) for s in covered]
    stage('nonregression')
    vr = verify_candidate(qid, candidate, 'docker', workers=2,
                          run_timeout_s=5, baseline_corpus=baseline, slot_plan=frozen)
    save(directory / 'gate.json', {'references': refs, 'verification': vr,
                                  'scope': 'frozen current comparable slots; missing-source slots excluded'})
    if vr.get('planned') != len(frozen):
        raise ValueError('some frozen LC verdicts were not eligible for verification')
    gate(vr, refs, slot)
    target_evidence = next(r for r in vr['results'] if all(r[k] == slot[k] for k in ('model', 'lang', 'cand', 'task')))
    if target_evidence['identity'] != base['identity']:
        raise ValueError('target identity changed since baseline')
    from local.dashboard.scripts.judge_all_models import ORIG_DB
    from local.harness.identity import verification_identity
    for entry in vr['results']:
        context = dict(qid=qid, model=entry['model'], lang=entry['lang'], attempt=entry['cand'],
                       task=entry['task'], code_path=code_path({**entry, 'qid': qid}),
                       config={'max_cases': 1000, 'run_timeout_s': 5})
        if verification_identity(ORIG_DB, **context) != entry['identity']:
            raise ValueError('covered submission changed after verification')
    if path.read_bytes() != old:
        raise ValueError('corpus changed during verification')
    if not args.publish:
        return {'status': 'verified_proposal', 'added': len(kept)}
    from local.gen_testcases.corpus_io import publish_cases
    meta_path = path.with_name('meta.json')
    meta = json.loads(meta_path.read_bytes()) if meta_path.exists() else {}
    new_sha = sha(json.dumps(candidate, ensure_ascii=False, indent=1).encode())
    meta['n_cases'] = len(candidate)
    # 注意：此处的 status 是**准入状态**（约束检查 + 模型非退化 + 参考解全过 + 槽位冻结计划），
    # 不等于『这条用例有独立答案』。后者单独由 no_independent_answer / independent_oracle 表达，
    # 因为 corpus_admission() 只消费 status 与 new_sha256。
    publication = {'status': 'verified', 'operation': 'gap_workflow', 'job': str(directory),
                   'recorded_at': datetime.now().isoformat(), 'old_sha256': sha(old),
                   'new_sha256': new_sha, 'verification': vr, 'reference_validation': refs,
                   # 显式记录本条用例是否有独立答案，而不是让读者从 oracle 文件推断。
                   'no_independent_answer': oracle_unverified,
                   'independent_oracle': {'status': oracle['status'],
                                          'candidate_sha256': oracle['candidate_sha256'],
                                          'oracle_sha256': oracle['oracle_sha256']},
                   'scope': 'current comparable submissions with source',
                   'excluded_missing_source': [s for s in job['skipped_slots'] if s['qid'] == qid]}
    meta.setdefault('publications', []).append(publication)
    # Persist intention BEFORE mutation; recovery verifies the publication hash.
    backup_database(args.job)
    task['publication'] = publication; task['status'] = 'publishing'
    save(args.job / 'job.json', job)
    publish_cases(path, candidate, meta, old)
    invalidate([qid],args.job)
    return {'status': 'published', 'added': len(kept)}


def command(job, directory, module, *arguments):
    cmd = [sys.executable, '-B', '-X', 'utf8', '-u', '-m', module, *arguments]
    entry = {'command': cmd, 'state': 'running'}
    job['commands'].append(entry); save(directory / 'job.json', job)
    log = directory / f"command-{len(job['commands']):03}.log"
    with log.open('w', encoding='utf-8') as out:
        result = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    entry.update(state='completed' if result.returncode == 0 else 'failed', exit_code=result.returncode, log=str(log))
    save(directory / 'job.json', job)
    if result.returncode:
        raise RuntimeError(f'{module} exited {result.returncode}; see {log}')


def cleanup(entry,job,args):
    from local.gen_testcases.constraints import check,unparsed
    from local.gen_testcases.validate import golden_one
    from local.gen_testcases.apply_found import verify_candidate
    from local.gen_testcases.corpus_io import publish_cases
    from local.common import LANGS
    from local.harness.identity import verification_identity
    from local.dashboard.scripts.judge_all_models import ORIG_DB
    qid=entry['qid'];path=CORPUS/str(qid)/'cases.json';old=path.read_bytes();baseline=json.loads(old)
    version=sha((ROOT/'local/gen_testcases/constraints.py').read_bytes())
    if unparsed(qid):return {'status':'blocked_constraints','unparsed':unparsed(qid)}
    invalid=[{'index':i,'reasons':check(qid,c),'case':c} for i,c in enumerate(baseline) if check(qid,c)]
    if not invalid:return {'status':'already_legal'}
    candidate=[c for c in baseline if not check(qid,c)]
    if not candidate:raise ValueError('cleanup would remove all cases')
    directory=args.job/f'cleanup-{qid}';directory.mkdir(parents=True,exist_ok=True)
    save(directory/'invalid-cases.json',invalid);save(directory/'baseline.json',baseline)
    added=[];extra_evidence=None;targets=[]
    if getattr(args,'cleanup_add_candidates',False):
        # Cleanup and a reviewed counterexample may form one atomic change,
        # but adding inputs is still restricted to dev and must fix a target.
        targets=[t['slot'] for t in job['tasks'] if t['slot']['qid']==qid
                 and t['slot']['eval_split']=='dev' and t['branch'] in ('wa','crash','performance')]
        if not targets:raise ValueError('cleanup cannot add targeted inputs outside dev')
        proposal_path=Path(args.candidate_dir)/f'{qid}.json'
        proposal=json.loads(proposal_path.read_bytes())
        if proposal.get('qid')!=qid:raise ValueError('cleanup input problem differs')
        case={'args':proposal['case']['args']}
        if check(qid,case):raise ValueError('cleanup candidate violates constraints')
        from local.gen_testcases.differential import python_outputs
        from local.gen_testcases.small_oracles import evaluate
        from local.gen_testcases.scale_expand import validate
        outputs=python_outputs(qid,[case],'docker')
        if len(outputs)!=1 or outputs[0] is None:raise ValueError('cleanup candidate reference unavailable')
        case['expected']=outputs[0]
        oracle_path=ROOT/'local/gen_testcases/small_oracles.py'
        oracle_sha=sha(oracle_path.read_bytes())
        oracle=evaluate(qid,case)
        if sha(oracle_path.read_bytes())!=oracle_sha:raise ValueError('oracle source changed during evaluation')
        if oracle['status']!='verified':raise ValueError('cleanup candidate lacks an independent verified answer')
        oracle['oracle_sha256']=oracle_sha
        oracle['no_independent_answer']=False  # 该路径要求 verified，恒为 False，显式写明形状一致
        kept,votes=validate(qid,[case],'docker',verbose=False)
        if len(kept)!=1 or check(qid,kept[0]):raise ValueError('cleanup candidate differential gate failed')
        if any(c['args']==kept[0]['args'] for c in candidate):raise ValueError('cleanup candidate already in corpus')
        added=kept;candidate+=added
        # candidate_sha256 绑定的是**被追加的用例集合**的稳定序列化，而不是记录文件整体：
        # 记录文件里包含 candidate_sha256 自身，用文件哈希会自相矛盾（reviewer 06）。
        # 可复算公式：sha256(json.dumps(added, ensure_ascii=False, indent=2))
        # 与 repair_wa 的 candidate.json 文件字节哈希不同，但两者都是"独立可复算的候选字节指纹"，
        # 且都随 publication 一起留档。
        oracle['candidate_sha256'] = sha(json.dumps(added, ensure_ascii=False, indent=2).encode())
        extra_evidence={'input_path':str(proposal_path),'input_sha256':sha(proposal_path.read_bytes()),
                        'cases':added,'oracle':oracle,'votes':votes}
        save(directory/'added-candidate.json',extra_evidence)
    refs=[golden_one(qid,lang,candidate,'docker') for lang in LANGS]
    covered=[s for s in job['covered_slots'] if s['qid']==qid]
    frozen=[(s['model'],s['lang'],s['cand'],s['task'],s['leetcode']) for s in covered]
    vr=verify_candidate(qid,candidate,'docker',workers=2,baseline_corpus=baseline,slot_plan=frozen)
    save(directory/'gate.json',{'references':refs,'verification':vr,'constraint_version':version})
    gate(vr,refs)
    if added and not any(r.get('outcome')=='fixed' and any(
            all(r[k]==s[k] for k in ('model','lang','cand','task')) for s in targets) for r in vr['results']):
        raise ValueError('cleanup addition did not fix any frozen dev target')
    if vr['planned']!=len(frozen):raise ValueError('frozen plan not fully verified')
    for item in vr['results']:
        ctx=dict(qid=qid,model=item['model'],lang=item['lang'],attempt=item['cand'],task=item['task'],
                 code_path=code_path({**item,'qid':qid}),config={'max_cases':1000,'run_timeout_s':5})
        if verification_identity(ORIG_DB,**ctx)!=item['identity']:raise ValueError('verification inputs changed')
    if path.read_bytes()!=old or version!=sha((ROOT/'local/gen_testcases/constraints.py').read_bytes()):
        raise ValueError('corpus or constraint checker changed')
    if not args.publish:return {'status':'verified_proposal','removed':len(invalid),'added':len(added)}
    mp=path.with_name('meta.json');meta=json.loads(mp.read_bytes()) if mp.exists() else {}
    publication={'status':'verified','operation':'constraint_cleanup_with_counterexample' if added else 'constraint_cleanup','recorded_at':datetime.now().isoformat(),
                 'old_sha256':sha(old),'new_sha256':sha(json.dumps(candidate,ensure_ascii=False,indent=1).encode()),
                 'removed_invalid':invalid,'constraint_version':version,'verification':vr,'reference_validation':refs,
                 'added_candidate':extra_evidence,
                 # 与 repair_wa 的 publication 顶层形状保持一致，避免审计脚本对 cleanup 记录
                 # 取 publications[-1]['no_independent_answer'] 得到 None（reviewer 09）。
                 # cleanup 追加路径强制 verified，所以这里恒为 False。
                 'no_independent_answer':False,
                 'independent_oracle':({'status':extra_evidence['oracle']['status'],
                                        'candidate_sha256':extra_evidence['oracle']['candidate_sha256'],
                                        'oracle_sha256':extra_evidence['oracle']['oracle_sha256']}
                                       if extra_evidence else None),
                 'scope':'frozen comparable submissions with source'}
    meta['n_cases']=len(candidate);meta.setdefault('publications',[]).append(publication)
    backup_database(args.job)
    entry.update(status='publishing',publication=publication);save(args.job/'job.json',job)
    publish_cases(path,candidate,meta,old)
    invalidate([qid],args.job)
    return {'status':'published','removed':len(invalid),'added':len(added),'recovered':vr.get('recovered',0)}


def refresh(job, directory):
    qids = sorted(set(job['refresh_qids']))
    if not qids or job['refresh_done']:
        return
    archive = directory / 'before-refresh'; archive.mkdir(exist_ok=True)
    for model in RESULTS.iterdir():
        for qid in qids:
            source = model / 'results' / str(qid)
            dest = archive / model.name / str(qid)
            if source.exists() and not dest.exists():
                shutil.copytree(source, dest)
    if not (archive / 'golden_check.json').exists():
        shutil.copy2(ROOT / 'local/results/golden_check.json', archive / 'golden_check.json')
    backup_database(directory)
    invalidate(qids, directory)
    command(job, directory, 'local.gen_testcases.validate', '--max_workers', '2')
    command(job, directory, 'local.dashboard.scripts.judge_all_models', '--all', '--qids', ','.join(map(str, qids)), '--max_workers', '2')
    command(job, directory, 'local.dashboard.scripts.import_local_results')
    command(job, directory, 'local.tools.gen_status_table', '--write')
    command(job, directory, 'local.tools.verify_release')
    job['refresh_done'] = True; save(directory / 'job.json', job)


def backup_database(directory):
    archive=directory/'before-refresh';archive.mkdir(parents=True,exist_ok=True)
    backup=archive/'local.db'
    if not backup.exists():
        with closing(sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)) as source,closing(sqlite3.connect(backup)) as dest:
            source.backup(dest)


def invalidate(qids, directory):
    """Do not display old corpus verdicts as current during a long refresh."""
    placeholders = ','.join('?' for _ in qids)
    reason = 'corpus changed by gap_workflow; formal reevaluation pending'
    with closing(sqlite3.connect(DB, timeout=30)) as con:
        with con:
            con.execute(f"UPDATE slots SET identity_status='stale',stale=1,identity_reason=? "
                        f"WHERE qid IN ({placeholders}) AND local_origin='all_models' "
                        "AND identity_status='current'", [reason, *qids])
            con.execute(f"UPDATE local_results SET identity_status='stale',identity_reason=? "
                        f"WHERE qid IN ({placeholders}) AND task='gen' AND run_name=model||'_local' "
                        "AND identity_status='current'", [reason, *qids])
    save(directory / 'invalidation.json', {'qids': qids, 'reason': reason})


@contextmanager
def lock():
    JOBS.mkdir(parents=True, exist_ok=True)
    path = JOBS / '.workflow.lock'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=['plan', 'run', 'cleanup'])
    ap.add_argument('--job', type=Path)
    ap.add_argument('--branch', choices=['wa', 'forward', 'candidates', 'reverse', 'crash', 'performance', 'environment', 'diagnose', 'all'], default='all')
    ap.add_argument('--limit', type=int, default=3)
    ap.add_argument('--samples', type=int, default=80)
    ap.add_argument('--seed', type=int, default=20261013)
    ap.add_argument('--publish', action='store_true')
    ap.add_argument('--qids', default='', help='Optional comma-separated problem filter')
    ap.add_argument('--cleanup-qids',default='',help='Run gated cleanup for these explicit qids before forward tasks')
    ap.add_argument('--cleanup-add-candidates',action='store_true',help='Atomically add reviewed dev counterexamples during cleanup; all gates remain mandatory')
    proposals=ap.add_mutually_exclusive_group()
    proposals.add_argument('--candidate-file',type=Path,help='Reviewed input proposal; answers and all gates are recomputed')
    proposals.add_argument('--candidate-dir',type=Path,help='Reviewed <qid>.json inputs; missing files block rather than fall back')
    proposals.add_argument('--llm-corpus',action='store_true',help='Search verified LLM-generated inputs; all existing dev-only, eight-reference and zero-regression publication gates remain mandatory')
    args = ap.parse_args()
    if args.mode=='cleanup' and not args.qids:ap.error('cleanup requires explicit --qids')
    if args.cleanup_qids and args.mode!='run':ap.error('--cleanup-qids is only valid in run mode')
    if args.cleanup_add_candidates and (not args.candidate_dir or not (args.mode=='cleanup' or args.cleanup_qids)):
        ap.error('--cleanup-add-candidates requires --candidate-dir and explicit cleanup qids')
    if args.limit < 1 or not 1 <= args.samples <= 300:
        ap.error('limit must be positive; samples must be 1..300')
    args.job = (args.job or JOBS / datetime.now().strftime('%Y%m%d-%H%M%S')).resolve()
    with lock():
        path = args.job / 'job.json'
        job = json.loads(path.read_bytes()) if path.exists() else plan()
        save(path, job)
        if args.mode == 'plan':
            from collections import Counter
            print(json.dumps({'job': str(args.job), 'branches': dict(Counter(t['branch'] for t in job['tasks'])),
                              'skipped_missing_or_unverifiable': len(job['skipped_slots'])}, ensure_ascii=False))
            return
        if platform.python_version() != job['python']:
            raise SystemExit(f"Use Python {job['python']}; current {platform.python_version()}")
        if args.publish:require_dashboard()
        from local.harness.identity import image_digest
        from local.harness import runner
        runner.DOCKER_IMAGE = image_digest()
        print('Docker image:', runner.DOCKER_IMAGE, flush=True)
        if args.mode=='cleanup' or args.cleanup_qids:
            cleanup_qids=args.qids if args.mode=='cleanup' else args.cleanup_qids
            for qid in sorted({int(q) for q in cleanup_qids.split(',') if q.strip()}):
                entry=next((x for x in job.setdefault('cleanups',[]) if x['qid']==qid),None)
                if entry is None:
                    entry={'qid':qid,'status':'pending'};job['cleanups'].append(entry)
                if entry['status'] in ('publishing','published'):
                    if entry['status']=='published' and job['refresh_done']:continue
                    if sha((CORPUS/str(qid)/'cases.json').read_bytes())!=entry['publication']['new_sha256']:
                        raise RuntimeError('Interrupted cleanup publication needs reconciliation')
                    entry['status']='published'
                elif entry['status']=='pending':
                    print('cleanup',qid,flush=True)
                    try:entry.update(cleanup(entry,job,args))
                    except Exception as exc:
                        if entry['status']=='publishing':raise
                        entry.update(status='blocked',error=f'{type(exc).__name__}: {exc}')
                if entry['status']=='published' and qid not in job['refresh_qids']:
                    job['refresh_qids'].append(qid);job['refresh_done']=False
                save(path,job);print(' ->',entry['status'],flush=True)
            if args.mode=='cleanup':
                refresh(job,args.job)
                return
        done = 0
        selected_qids = {int(q) for q in args.qids.split(',') if q.strip()}
        for task in job['tasks']:
            if task['status'] == 'running':
                task['status'] = 'pending'
                task['interrupted_stage'] = task.get('stage')
            if task['status'] in ('publishing', 'published'):
                if (task['status'] == 'published' and job['refresh_done']
                        and task['slot']['qid'] in job['refresh_qids']):
                    continue  # A later completed batch may legitimately change this corpus.
                publication = task.get('publication', {})
                p = CORPUS / str(task['slot']['qid']) / 'cases.json'
                if publication.get('new_sha256') != sha(p.read_bytes()):
                    raise RuntimeError('Interrupted publication needs reconciliation; no blind retry')
                task['status'] = 'published'
                if task['slot']['qid'] not in job['refresh_qids']:
                    job['refresh_qids'].append(task['slot']['qid']); job['refresh_done'] = False
                continue
            if task['status'] != 'pending' or done >= args.limit:
                continue
            if selected_qids and task['slot']['qid'] not in selected_qids:
                continue
            if task['slot']['qid'] in job['refresh_qids'] and not job['refresh_done']:
                continue  # Reimport before acting on another stale classification.
            if args.branch == 'wa' and task['branch'] != 'wa':
                continue
            if args.branch == 'forward' and task['branch'] not in ('wa','crash'):
                continue
            if args.branch == 'candidates' and task['branch'] not in ('wa','crash','performance'):
                continue
            if args.branch == 'diagnose' and task['branch'] == 'wa':
                continue
            if args.branch == 'reverse' and task['slot']['klass'] != 'false_wa':
                continue
            if args.branch in ('crash', 'performance', 'environment') and task['branch'] != args.branch:
                continue
            directory = args.job / task['id']; directory.mkdir(exist_ok=True)
            print(task['id'], task['branch'], flush=True)
            task['status'] = 'running'
            save(path, job)
            try:
                assert_current(task['slot'])
                task.update(repair_wa(task, job, directory, args) if task['branch'] in ('wa','crash','performance')
                            and task['slot']['eval_split']=='dev' and args.branch!='diagnose'
                            else diagnose(task['slot'], directory))
            except Exception as exc:
                if task['status'] != 'publishing':
                    task.update(status='blocked', error=f'{type(exc).__name__}: {exc}')
                save(path, job)
                if task['status'] == 'publishing':
                    raise
            if task['status'] == 'published':
                job['refresh_qids'].append(task['slot']['qid']); job['refresh_done'] = False
            save(path, job); done += 1
            print(' ->', task['status'], flush=True)
        refresh(job, args.job)
        from collections import Counter
        print('Task states:', dict(Counter(t['status'] for t in job['tasks'])), flush=True)
        print('Checkpoint:', path, flush=True)


if __name__ == '__main__':
    main()
