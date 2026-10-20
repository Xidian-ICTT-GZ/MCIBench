"""Rejudge a saved candidate against its frozen corpus. Never calls a model.

The child job is self-contained: code bytes, corpus, comparison, the original
execution interface and the configuration are frozen at creation time from
server-side evidence. Nothing is re-derived from the candidate under test.

A rejudge never silently changes execution entry point. If the parent used a
native adapter and that adapter cannot be replayed from its frozen receipt, the
request is blocked instead of falling back to the portable JSON driver, because
the portable driver may resolve a different function and turn a wrong target
function into a false AC.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import tempfile
from pathlib import Path

from local.harness.identity import image_digest
from local.lab import answer_evidence, counterexample, interface_policy
from local.lab import execution_plan as plan_module
from local.lab import portable_judging as judging
from local.lab.behavior import sha
from local.lab.judging import VERSION as LAB_JUDGE_VERSION
from local.lab.pipeline_jobs import execute as run_full
from local.lab.pipeline_jobs import public_verdict
from local.lab.storage import LabError, now

VERSION = 'rejudge-frozen-corpus-v2'
KIND = 'rejudge'
MODES = ('frozen', 'current')
REGISTRY = Path(__file__).with_name('data') / 'evidence_advisories.json'


class _Cancelled(Exception):
    pass


def _route_of(group):
    try:
        interface, _origin = interface_policy.resolve(
            group, derive=lambda: plan_module.packages.code_interface(
                group.get('qid'), group.get('language')))
        return interface_policy.route(interface)
    except interface_policy.UnknownInterface:
        return None


def _fail(message, status=409):
    raise LabError(message, status)


def invalidations(qid, corpus_sha):
    """Corpus snapshots retired by a later review must never be re-judged."""
    try:
        registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return []
    if registry.get('version') != 1:
        return []
    hits = []
    for issue in registry.get('issues') or []:
        if type(issue) is not dict or issue.get('qid') != qid:
            continue
        if str(issue.get('cases_sha256')) == corpus_sha:
            hits.append({'qid': qid, 'language': issue.get('language'),
                         'reason': issue.get('reason') or 'invalidated_corpus',
                         'executor_sha256': issue.get('executor_sha256')})
    return hits


def _corpus(parent, qid, mode):
    """Return (cases, identity). Frozen mode never recomputes an answer."""
    if mode == 'current':
        from local.judge import load_cases
        cases = load_cases(qid)
        if not cases:
            _fail('q%d 当前没有已发布语料，无法复判' % qid)
        return cases, {'mode': 'current', 'source': 'published_corpus',
                       'sha256': sha(cases), 'comparison': None}, None
    entries = (parent.get('result') or {}).get('inputs') or []
    entry = next((item for item in entries if item.get('qid') == qid), None)
    if not entry:
        _fail('父任务没有保存 q%d 的冻结语料快照，请改用当前语料' % qid)
    cases = entry.get('full_corpus')
    if not isinstance(cases, list) or not cases:
        _fail('父任务的冻结语料不完整（缺少带答案的 full_corpus），请改用当前语料')
    return cases, {'mode': 'frozen', 'source': 'parent_snapshot',
                   'sha256': sha(cases),
                   'validation_sha256': entry.get('validation_sha256'),
                   'package_sha256': entry.get('package_sha256'),
                   'comparison': entry.get('comparison')}, entry


def prepare(parent, payload):
    """Build a frozen rejudge spec from server-side evidence only."""
    if not isinstance(payload, dict):
        _fail('请求必须是对象')
    group_index = payload.get('group')
    candidate_index = payload.get('candidate')
    mode = payload.get('corpus_mode') or 'frozen'
    if mode not in MODES:
        _fail('corpus_mode 必须是 frozen 或 current')
    if type(group_index) is not int or type(candidate_index) is not int:
        _fail('请选择候选组与候选')
    groups = (parent.get('result') or {}).get('groups') or []
    if not groups:
        _fail('父任务还没有候选结果，无法复判')
    if not 0 <= group_index < len(groups):
        _fail('候选组不存在', 404)
    group = groups[group_index]
    candidates = group.get('candidates') or []
    if not 0 <= candidate_index < len(candidates):
        _fail('候选不存在', 404)
    candidate = candidates[candidate_index]

    reasons = []
    code = candidate.get('code')
    if not isinstance(code, str) or not code.strip():
        reasons.append('源代码缺失')
    elif sha(code) != candidate.get('code_sha256'):
        reasons.append('源代码与保存的哈希不符')
    if candidate.get('generation_state', 'succeeded') != 'succeeded':
        reasons.append('生成未成功完成')
    if candidate.get('finish_reason') == 'length':
        reasons.append('生成被输出上限截断')
    qid = group.get('qid')
    language = group.get('language')
    if type(qid) is not int or qid <= 0:
        reasons.append('题目标识无效')
    if not isinstance(language, str) or not language:
        reasons.append('语言无效')
    if reasons:
        _fail('无法复判：' + '；'.join(reasons))

    cases, identity, entry = _corpus(parent, qid, mode)
    corpus_sha = identity['sha256']
    if entry is not None:
        # Corpus, contract and package must still describe one coherent set:
        # "the snapshot exists" alone does not prove the reference gate held.
        problems = plan_module.dependency_problems(group, entry, qid)
        if problems:
            _fail('冻结依赖不一致，不能据它签发新判定：' + '；'.join(problems))
    # No independent answer for this language means no new verdict for it.
    missing_answer = answer_evidence.group_problems(
        group, group.get('language'), cases, route=_route_of(group))
    if missing_answer:
        _fail('q%s/%s 缺少可用的独立答案依据，不能签发新判定：%s'
              % (qid, group.get('language'), '；'.join(missing_answer)))
    retired = invalidations(qid, corpus_sha)
    if retired:
        _fail('该冻结语料已被后续审查判定失效（%s），不能再签发新判定；请补入有效反例后重新建立语料' %
              '；'.join(str(item.get('reason')) for item in retired))

    try:
        # The entry is chosen from the frozen interface, never guessed: a native
        # task must not silently fall back to the portable driver.
        plan, path = plan_module.resolve(group, cases)
    except plan_module.Blocked as error:
        _fail('无法按冻结接口复用原执行入口（%s）：%s。不默认改用 portable 驱动，'
              '因为那可能解析到辅助函数并把错误的目标函数判成 AC。' % (error.code, error))

    # The combined verdict is built from two slices plus the probes; freezing only
    # the full corpus cannot reproduce it.
    slices = {}
    if path == plan_module.COMBINED:
        inputs = {row.get('qid'): row for row in ((parent.get('result') or {}).get('inputs') or [])
                  if isinstance(row, dict)}
        row = inputs.get(qid) or {}
        slices = {'validation': row.get('validation') or [],
                  'probes': row.get('probes') or [],
                  'probe_cases': row.get('probe_correctness_cases') or []}
        missing = [name for name, value in slices.items() if not value]
        if missing:
            _fail('父任务缺少合并判定所需的输入（%s），无法按原入口重放' % '、'.join(missing))

    comparison = identity.get('comparison') or None
    executor = {'path': path,
                'adapter_sha256': (plan or {}).get('adapter_sha256'),
                'receipt_sha256': (plan or {}).get('receipt_sha256'),
                'plan_binding_sha256': sha((plan or {}).get('binding') or {}),
                'lab_judge_version': LAB_JUDGE_VERSION,
                'portable_version': judging.VERSION,
                'image': image_digest(),
                'comparison_sha256': sha(comparison or {}),
                'run_timeout_s': 5,
                'execution_plan_sha256': sha(Path(plan_module.__file__).read_text(encoding='utf-8'))}
    frozen = {
        'comparison': comparison,
        # The verdict must point at the answer it rests on, not only at the code.
        'answer_evidence': deepcopy(identity.get('answer_evidence') or group.get('answer_evidence')),
        'execution_path': path,
        'adapter_sha256': executor['adapter_sha256'],
        'receipt_sha256': executor['receipt_sha256'],
        'truncation': False,
        'version': VERSION,
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    spec = {
        'kind': KIND,
        'workflow_version': VERSION,
        # Zero model calls. An empty list also keeps store.queue() unchanged.
        'model_ids': [],
        'parent_job_id': parent['id'],
        'group_index': group_index,
        'candidate_index': candidate_index,
        'candidate_id': candidate.get('id'),
        'candidate_index_value': candidate.get('index'),
        'qid': qid,
        'language': language,
        'task': group.get('task') or 'gen',
        'corpus_mode': mode,
        'corpus': cases,
        'corpus_sha256': corpus_sha,
        **slices,
        'corpus_identity': identity,
        'code': code,
        'code_sha256': candidate.get('code_sha256'),
        'native_plan': plan,
        'executor': executor,
        'frozen': frozen,
        'parent_evidence': {
            'judge_version': (candidate.get('full_execution_evidence') or {}).get('driver_version'),
            'corpus_verdict_version': (candidate.get('corpus_verdict') or {}).get('version'),
            'input_contract_sha256': sha((group.get('input_contract') or {})),
        },
        # Keyed on the judged bytes and the executor: a judge upgrade is a new round, not a cached hit.
        'request_key': sha({'parent': parent['id'], 'candidate': candidate.get('id'),
                            'code': candidate.get('code_sha256'), 'mode': mode,
                            'corpus': corpus_sha, 'executor': executor, 'version': VERSION}),
        'created_at': now(),
    }
    return spec


def title_for(spec):
    mode = '冻结语料' if spec['corpus_mode'] == 'frozen' else '当前语料'
    entry = '原生驱动' if spec['frozen']['execution_path'] == 'native_deterministic' else 'portable'
    return '复判 · q%s/%s · 候选%s · %s · %s' % (
        spec['qid'], spec['language'], spec.get('candidate_index_value') or '?', mode, entry)


def _run_audited(spec, cases, cancelled, suffix=''):
    """Replay through the program that produced the parent verdict."""
    from local.common import KEY_TO_LABEL
    from local.lab import audited_judging
    with tempfile.TemporaryDirectory(prefix='mci_rejudge_') as folder:
        path = Path(folder) / ('%s_%s_%s%s.txt' % (spec['qid'], KEY_TO_LABEL[spec['language']],
                                                   spec.get('candidate_index_value') or 1, suffix))
        path.write_text(spec['code'], encoding='utf-8')
        return audited_judging.run(path, deepcopy(cases), check_cancel=cancelled)


def _run_combined(engine, spec, cancelled):
    """Reproduce the combined verdict: observe probes, re-judge validation, merge.

    This is the entry the live pipeline actually uses (no problem carries an audited
    profile), so a replay that ignores it would answer a different question.
    """
    from local.common import KEY_TO_LABEL
    from local.lab.behavior import observe
    from local.lab.judging import judge_one as validation_judge

    def step():
        if cancelled():
            raise _Cancelled()

    validation = spec.get('validation') or []
    probes = spec.get('probes') or []
    probe_cases = spec.get('probe_cases') or []
    # The pipeline observes each probe through a cached executor; without it the
    # observation falls back to the portable driver, which cannot run a LeetCode-style
    # candidate, and the merge then refuses for lack of probe records.
    from local.lab.execution import CachedExecution
    executor = CachedExecution(Path(engine.store.path).parent / 'lab_artifacts',
                               (spec.get('frozen') or {}).get('image') or image_digest())
    outcomes = []
    for probe in probes:
        step()
        try:
            outcomes.append(observe(spec['qid'], spec['language'], spec['code'], probe,
                                    executor=executor))
        except Exception as error:                             # noqa: BLE001 - recorded, not invented
            raise ValueError('探测执行失败，不能给出完整正确性判定：%s' % error) from error
    step()
    with tempfile.TemporaryDirectory(prefix='mci_rejudge_') as folder:
        path = Path(folder) / ('%s_%s_%s.txt' % (spec['qid'], KEY_TO_LABEL[spec['language']],
                                                 spec.get('candidate_index_value') or 1))
        path.write_text(spec['code'], encoding='utf-8')
        verdict = validation_judge(path, 'gen', len(validation), 'docker', run_timeout_s=5,
                                   cases_override=deepcopy(validation))
    step()
    from local.lab.jobs import combine, probe_verdict
    probes_result = probe_verdict(spec['qid'], probe_cases, outcomes) if probes else None
    return combine(verdict, probes_result)


def run(engine, ident, event):
    """Execute a frozen rejudge through the same entry the parent used."""
    from local.lab import source_guard
    store = engine.store
    try:
        job = store.job(ident)
        spec = job['spec']
        store.write_job(ident, state='evaluating', stage='完整语料复判：执行冻结语料', progress=5)
        if event.is_set():
            raise _Cancelled()
        source_guard.check()
        retired = invalidations(spec['qid'], spec['corpus_sha256'])
        if retired:
            raise ValueError('冻结语料已被判定失效：%s' % '；'.join(str(item.get('reason')) for item in retired))
        cases = spec['corpus']
        def cancelled():
            if event.is_set():
                raise _Cancelled()
        comparison = spec.get('comparison') or (spec.get('frozen') or {}).get('comparison')
        path_now = (spec.get('frozen') or {}).get('execution_path')
        audited = path_now == plan_module.AUDITED
        combined = path_now == plan_module.COMBINED
        if combined:
            result = _run_combined(engine, spec, cancelled)
        elif audited:
            result = _run_audited(spec, cases, cancelled)
        else:
            result = run_full(spec['qid'], spec['language'], spec['code'], cases, comparison,
                              spec.get('native_plan'), check_cancel=cancelled, full=True)
        if event.is_set():
            raise _Cancelled()
        # The combined verdict has no runtime/memory fields; the pipeline stores it
        # as-is, so projecting it like a single run would raise KeyError.
        verdict = result if combined else public_verdict(result)
        if combined or audited:
            # Both entries report a verdict, not per-case outputs, so a missing actual
            # value is recorded as not collected rather than invented.
            first = counterexample.describe(
                lambda subset, collect=False: (_run_combined(engine, spec, cancelled) if combined
                                               else _run_audited(spec, subset, cancelled, '_ce')),
                cases, verdict)
        else:
            first = counterexample.describe(
                lambda subset, collect=False: run_full(
                    spec['qid'], spec['language'], spec['code'], subset, comparison,
                    spec.get('native_plan'), check_cancel=cancelled, collect=collect),
                cases, verdict)
        payload = {
            'kind': KIND,
            'version': VERSION,
            'parent_job_id': spec['parent_job_id'],
            'candidate': {'id': spec['candidate_id'], 'index': spec.get('candidate_index_value'),
                          'language': spec['language'], 'qid': spec['qid'],
                          'code_sha256': spec['code_sha256']},
            'corpus': {'mode': spec['corpus_mode'], 'cases': len(cases),
                       'sha256': spec['corpus_sha256'],
                       'validation_sha256': (spec.get('corpus_identity') or {}).get('validation_sha256'),
                       'package_sha256': (spec.get('corpus_identity') or {}).get('package_sha256')},
            'config': spec['frozen'],
            'executor': spec.get('executor') or {'path': 'portable_json'},
            'verdict': verdict,
            'judge_meta': {k: v for k, v in (result.get('_meta') or {}).items()
                           if k in ('driver_version', 'driver_sha256', 'adapter', 'adapter_sha256',
                                    'comparison', 'execution_supervisor', 'asan_required', 'error',
                                    'numeric_recheck')},
            'first_failure': first,
            'model_calls': 0,
            'note': ('复判未调用模型，结果单独保存；不进入父任务的 U、矩阵、中心候选与选码指标。'
                     '父任务原样保留。'),
        }
        store.write_job(ident, state='completed', stage='复判完成', progress=100, result=payload)
    except _Cancelled:
        store.write_job(ident, state='cancelled', stage='复判已取消', error='用户取消')
    except Exception as error:                                     # noqa: BLE001 - must land in the record
        store.write_job(ident, state='failed', stage='复判失败',
                        error='%s: %s' % (type(error).__name__, str(error)[:400]))
    finally:
        # Release the concurrency slot: without this every finished rejudge
        # keeps a seat and the fifth one blocks all later jobs.
        with engine.lock:
            engine.events.pop(ident, None)
