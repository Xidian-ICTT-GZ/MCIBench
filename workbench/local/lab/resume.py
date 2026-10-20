"""Resume a recoverable job by re-executing the judging half from frozen evidence.

Scope is deliberately narrow and explicit:

  * reuse complete candidate code and the parent's frozen corpus snapshot;
  * replay through the SAME execution entry the parent used (the entry is chosen
    from the frozen interface, never guessed);
  * re-execute native/portable gates, probes, validation and the full corpus;
  * never resample a candidate and never rebuild a corpus (that needs model calls
    and a cross-resume call budget that does not exist yet);
  * block, with a reason, whenever a reused artefact is missing, incomplete, was
    invalidated, or no longer binds to its contract/package.

The model call count of a resume is therefore zero by construction.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import tempfile
from pathlib import Path

from local.harness.identity import image_digest
from local.lab import answer_evidence, correctness_audit, counterexample, interface_policy
from local.lab import portable_judging as judging
from local.lab import execution_plan as plan_module
from local.lab.behavior import sha
from local.lab.metrics import analyze
from local.lab.pipeline_jobs import execute as run_full
from local.lab.pipeline_jobs import observe as run_observe
from local.lab.pipeline_jobs import partitions, public_verdict
from local.harness.identity import image_digest, judge_source_closure
from local.lab.rejudge import invalidations
from local.lab.storage import LabError, now

VERSION = 'resume-frozen-judging-v2'
KIND = 'resume'
RECOVERABLE = ('failed', 'cancelled', 'interrupted')
# 'id' is kept: downstream translation-source lookup reads it directly.
ADOPT = ('id', 'code', 'code_sha256', 'raw', 'raw_sha256', 'finish_reason', 'prompt_sha256', 'usage', 'index')


class _Cancelled(Exception):
    pass


def _fail(message, status=409):
    raise LabError(message, status)


def _corpus(parent, qid):
    entries = (parent.get('result') or {}).get('inputs') or []
    entry = next((item for item in entries if item.get('qid') == qid), None)
    if not entry or not entry.get('full_corpus'):
        return None
    return entry


def _check_group(group, entry):
    """Corpus, contract, package, plan and invalidation must agree."""
    qid = group.get('qid')
    retired = invalidations(qid, sha(entry['full_corpus']))
    if retired:
        _fail('q%s 的冻结语料已被判定失效（%s），恢复不能继续签发判定' % (
            qid, '；'.join(str(item.get('reason')) for item in retired)))
    problems = plan_module.dependency_problems(group, entry, qid)
    if problems:
        _fail('q%s 的冻结依赖不一致，不能据它签发新判定：%s' % (qid, '；'.join(problems)))
    try:
        _interface, _origin = interface_policy.resolve(
            group, derive=lambda: plan_module.packages.code_interface(
                group.get('qid'), group.get('language')))
        _route = interface_policy.route(_interface)
    except interface_policy.UnknownInterface:
        _route = None
    missing_answer = answer_evidence.group_problems(
        group, group.get('language'), entry.get('full_corpus'), route=_route)
    if missing_answer:
        _fail('q%s/%s 缺少可用的独立答案依据，不能签发新判定：%s'
              % (qid, group.get('language'), '；'.join(missing_answer)))
    try:
        plan, path = plan_module.resolve(group, entry.get('full_corpus'))
    except plan_module.Blocked as error:
        _fail('q%s/%s 无法按冻结接口复用原执行入口（%s）：%s。不默认改用 portable 驱动，'
              '因为那可能解析到辅助函数并把错误的目标函数判成 AC。'
              % (qid, group.get('language'), error.code, error))
    return plan, path


def _candidates(group):
    kept, missing = [], []
    for candidate in group.get('candidates') or []:
        code = candidate.get('code')
        index = candidate.get('index')
        if not isinstance(code, str) or not code.strip():
            missing.append('候选%s 无源代码' % index)
        elif sha(code) != candidate.get('code_sha256'):
            missing.append('候选%s 源码哈希不符' % index)
        elif candidate.get('generation_state', 'succeeded') != 'succeeded':
            missing.append('候选%s 生成未完成' % index)
        elif candidate.get('finish_reason') == 'length':
            missing.append('候选%s 输出被截断' % index)
        else:
            kept.append({k: candidate.get(k) for k in ADOPT})
    if not kept:
        missing.append('该组没有可复用的完整候选')
    if missing:
        _fail('q%s/%s 无法恢复：%s。恢复不重新采样代码，请复制任务重新生成。' % (
            group.get('qid'), group.get('language'), '；'.join(missing)))
    return kept


def prepare(parent, payload):
    if parent.get('state') not in RECOVERABLE:
        _fail('只有失败、取消或中断的任务可以恢复；当前状态为 %s' % parent.get('state'))
    spec = parent.get('spec') or {}
    groups = (parent.get('result') or {}).get('groups') or []
    if not groups:
        _fail('父任务没有候选组，无法判断可复用阶段')

    planned = []
    for group in groups:
        qid = group.get('qid')
        entry = _corpus(parent, qid)
        if entry is None:
            _fail('q%s 的冻结语料快照缺失；重建语料需要模型调用与累计预算，恢复暂不支持' % qid)
        plan, path = _check_group(group, entry)
        candidates = _candidates(group)
        planned.append({'qid': qid, 'language': group.get('language'),
                        'model_id': group.get('model_id'), 'model_name': group.get('model_name'),
                        'interface': group.get('interface'), 'candidates': candidates,
                        'native_plan': plan, 'execution_path': path,
                        'source_language': group.get('source_language'),
                        'source_code': group.get('source_code'),
                        'source_sha256': group.get('source_sha256'),
                        'source_snapshot': group.get('source_snapshot'),
                        'input_contract': group.get('input_contract'),
                        'answer_evidence': deepcopy(group.get('answer_evidence')),
                        'corpus_sha256': sha(entry['full_corpus'])})

    reused = sum(len(item['candidates']) for item in planned)
    # Empty model_ids on purpose: the judging half needs no model configuration, so a
    # deleted or disabled profile must not block a resume of already generated code.
    child = deepcopy(spec)
    child.update(kind=KIND, workflow_version=VERSION, model_ids=[],
                 resume_models=[{'id': item['model_id'], 'name': item['model_name']} for item in planned],
                 resume_parent_job_id=parent['id'],
                 resume_plan=planned,
                 resume_reused_candidates=reused,
                 model_budget={'state': 'zero_model',
                               'reason': '判题段恢复复用父任务已生成的代码与冻结语料，不调用模型',
                               'policy': 'generation_and_corpus_rebuild_are_not_resumed'},
                 created_at=now())
    # Bind the executor identity: a judge upgrade is a new round, not a cache hit.
    executor = {'resume_version': VERSION,
                'portable_version': judging.VERSION,
                'execution_plan_sha256': sha(Path(plan_module.__file__).read_text(encoding='utf-8')),
                'image': image_digest(),
                'run_timeout_s': 5}
    child['resume_executor'] = executor
    child['request_key'] = sha({'kind': KIND, 'parent': parent['id'],
                                'executor': executor,
                                # Keyed on the judged bytes, not on candidate labels: a
                                # changed source is a new round, not a cached result.
                                'reused': [(item['qid'], item['language'], item['execution_path'],
                                            item['corpus_sha256'],
                                            [c.get('code_sha256') for c in item['candidates']])
                                           for item in planned]})
    return child, {'reused_candidates': reused, 'groups': len(planned),
                   'model_calls_expected': 0, 'corpus': 'frozen_parent_snapshot'}


def title_for(spec, summary):
    return '恢复 · %s · 复用 %d 候选 · 零模型' % (
        (spec.get('resume_parent_job_id') or '')[:8], summary['reused_candidates'])


def _resolve_plans(spec, parent):
    """Server-side re-derivation of the frozen plan at execution time."""
    planned = []
    for item in spec['resume_plan']:
        qid = item['qid']
        entry = _corpus(parent, qid)
        if entry is None:
            raise ValueError('q%d 冻结语料在恢复执行时已不可用' % qid)
        if sha(entry['full_corpus']) != item['corpus_sha256']:
            raise ValueError('q%d 冻结语料在执行前发生变化，拒绝继续' % qid)
        retired = invalidations(qid, item['corpus_sha256'])
        if retired:
            raise ValueError('q%d 冻结语料已被判定失效' % qid)
        planned.append(dict(item, entry=entry))
    return planned


def _audited_verdict(item, code, subset, cancelled, suffix=''):
    """Judge a subset through the program that produced the parent verdict."""
    from local.common import KEY_TO_LABEL
    from local.lab import audited_judging
    with tempfile.TemporaryDirectory(prefix='mci_resume_') as folder:
        path = Path(folder) / ('%s_%s_%s%s.txt' % (item['qid'], KEY_TO_LABEL[item['language']],
                                                   item['candidates'][0].get('index') or 1, suffix))
        path.write_text(code, encoding='utf-8')
        return audited_judging.run(path, deepcopy(subset), check_cancel=cancelled)


def _combined_candidate(engine, item, code, cases, entry, cancelled):
    """Reproduce the combined verdict the live pipeline stores.

    Validation is re-judged, the probes are re-observed through the cached executor and
    the two verdicts are merged -- the same four steps the pipeline takes.
    """
    from local.common import KEY_TO_LABEL
    from local.lab.behavior import observe
    from local.lab.execution import CachedExecution
    from local.lab.jobs import combine, probe_verdict
    from local.lab.judging import judge_one as validation_judge

    # Reuse the parent's frozen slices: re-partitioning could judge a different set of
    # cases and silently report a different score.
    entry = entry or {}
    probes = entry.get('probes') or []
    validation = entry.get('validation') or []
    probe_cases = entry.get('probe_correctness_cases') or []
    executor = CachedExecution(Path(engine.store.path).parent / 'lab_artifacts',
                               (item.get('image') or image_digest()))
    outcomes = []
    for probe in probes:
        cancelled()
        outcomes.append(observe(item['qid'], item['language'], code, probe, executor=executor))
    cancelled()
    record = {'outcomes': outcomes}
    with tempfile.TemporaryDirectory(prefix='mci_resume_') as folder:
        path = Path(folder) / ('%s_%s_%s.txt' % (item['qid'], KEY_TO_LABEL[item['language']],
                                                 item['candidates'][0].get('index') or 1))
        path.write_text(code, encoding='utf-8')
        verdict = validation_judge(path, 'gen', len(validation), 'docker', run_timeout_s=5,
                                   cases_override=deepcopy(validation))
    # The raw verdict has no version/cases_sha256, so the pipeline's nine-key projection
    # cannot be used here; take the fields a validation run actually carries.
    record['verdict'] = {k: verdict[k] for k in ('state', 'ac_status', 'total_testcases', 'total_correct',
                                                 'runtime', 'memory') if k in verdict}
    record['validation_passed'] = verdict['state'] == 'SUCCESS' and verdict['ac_status'] == 'Accepted'
    probes_result = probe_verdict(item['qid'], probe_cases, outcomes) if probes else None
    record['probe_verdict'] = probes_result
    merged = combine(record['verdict'], probes_result)
    record['corpus_verdict'] = merged
    record['corpus_passed'] = merged['ac_status'] == 'Accepted'
    record['full_execution_evidence'] = None
    record['corpus_counterexample'] = counterexample.describe(
        lambda subset, collect=False: {'state': 'not_collected'}, cases, merged)
    record['judging_state'] = 'completed'
    return record


def run(engine, ident, event):
    from local.lab import source_guard
    store = engine.store
    try:
        job = store.job(ident)
        spec = job['spec']
        parent = store.job(spec['resume_parent_job_id'], include_deleted=True)
        store.write_job(ident, state='evaluating', stage='恢复：复用已生成代码与冻结语料', progress=5)
        if event.is_set():
            raise _Cancelled()
        source_guard.check()
        planned = _resolve_plans(spec, parent)

        def cancelled():
            if event.is_set():
                raise _Cancelled()

        result = {'kind': KIND, 'version': VERSION, 'resumed_from': spec['resume_parent_job_id'],
                  'model_calls': 0, 'groups': [], 'inputs': [],
                  'notice': '恢复只重新执行判题段；代码与冻结语料来自父任务，未重新生成。'}
        total = sum(len(item['candidates']) for item in planned)
        done = 0
        for item in planned:
            qid, language = item['qid'], item['language']
            entry = item['entry']
            cases = deepcopy(entry['full_corpus'])
            comparison = entry.get('comparison') or None
            # Keep the snapshot complete so the resumed job can itself be rejudged
            # or resumed again, and so translation sources stay addressable.
            result['inputs'].append({key: deepcopy(entry.get(key)) for key in
                                     ('qid', 'full_corpus', 'comparison', 'input_contract',
                                      'package_sha256', 'probe_sha256', 'validation_sha256',
                                      'validation_count', 'answer_evidence')})
            probes, validation, metadata = partitions(cases, spec.get('probe_count') or 8,
                                                      qid=qid, strategy=spec.get('probe_strategy') or 'hash')
            group = {'qid': qid, 'model_id': item['model_id'], 'model_name': item['model_name'],
                     # A resumed verdict has to be traceable to the image it ran on, so the
                     # executors are recorded here exactly as the generation path does.
                     'executor': {'entry': item['execution_path'], 'version': VERSION,
                                  'image': image_digest()},
                     'judge_closure_files': len(judge_source_closure()),
                     'language': language, 'interface': item['interface'],
                     'input_contract': item['input_contract'],
                     'answer_evidence': deepcopy(item.get('answer_evidence')),
                     'source_language': item.get('source_language'),
                     'source_code': item.get('source_code'), 'source_sha256': item.get('source_sha256'),
                     'corpus_count': len(cases), 'validation_count': len(validation),
                     'probe_count': len(probes), 'probe_selection': metadata,
                     'execution_path': item['execution_path'],
                     'resumed_candidates': len(item['candidates']), 'candidates': []}
            if item.get('native_plan'):
                group['native_adapter'] = item['native_plan']
            try:
                group['correctness_evidence'] = correctness_audit.evidence(qid, cases, engine.image)
            except Exception as error:                            # noqa: BLE001 - evidence, not a verdict
                group['correctness_evidence'] = {'state': 'unavailable', 'error': str(error)[:200]}
            for candidate in item['candidates']:
                cancelled()
                store.write_job(ident, state='evaluating', progress=min(95, 5 + int(90 * done / max(1, total))),
                                stage='q{0} / {1}：候选{2} 完整复判'.format(qid, language, candidate.get('index')))
                record = deepcopy(candidate)
                record['source_candidate_id'] = candidate.get('id')
                record['generation'] = {'reused_from': spec['resume_parent_job_id'], 'resume': 'reused_complete_code'}
                audited = item['execution_path'] == plan_module.AUDITED
                combined = item['execution_path'] == plan_module.COMBINED

                def judge(subset, collect=False):
                    if audited:
                        return _audited_verdict(item, record['code'], subset, cancelled)
                    return run_full(qid, language, record['code'], subset, comparison,
                                    item.get('native_plan'), check_cancel=cancelled, collect=collect)

                try:
                    if combined:
                        record.update(_combined_candidate(engine, item, record['code'], cases,
                                                         entry, cancelled))
                        group['candidates'].append(record)
                        done += 1
                        continue
                    if audited:
                        # Behaviour probes render a portable driver, which cannot run a
                        # LeetCode-style candidate; leave them empty rather than wrong.
                        record['outcomes'] = []
                        record['behaviour_note'] = 'audited 入口下不做行为探测'
                    else:
                        record['outcomes'] = run_observe(qid, language, record['code'], probes, comparison,
                                                         cancelled, item.get('native_plan'))
                    if validation:
                        verdict = judge(validation)
                        record['verdict'] = public_verdict(verdict)
                        record['validation_passed'] = (verdict['state'] == 'SUCCESS'
                                                       and verdict['ac_status'] == 'Accepted')
                    if not audited:
                        record['probe_verdict'] = public_verdict(judge(probes))
                    full = judge(deepcopy(cases))
                    record['corpus_verdict'] = public_verdict(full)
                    record['corpus_counterexample'] = counterexample.describe(judge, cases, record['corpus_verdict'])
                    record['full_execution_evidence'] = full.get('_meta')
                    record['corpus_passed'] = (full['state'] == 'SUCCESS' and full['ac_status'] == 'Accepted')
                    record['judging_state'] = 'completed'
                except _Cancelled:
                    raise
                except Exception as error:                        # noqa: BLE001 - recorded, never AC
                    record['judging_state'] = 'incomplete'
                    record['judging_failure'] = {'message': '%s: %s' % (type(error).__name__, str(error)[:300])}
                group['candidates'].append(record)
                done += 1
            group['metrics'] = analyze(group['candidates'])
            complete = [c for c in group['candidates'] if c.get('judging_state') == 'completed']
            group['judging_state'] = 'completed' if len(complete) == len(group['candidates']) else 'incomplete'
            group['local_pass_rate'] = (sum(c.get('corpus_passed', False) for c in complete) / len(complete)
                                        if complete else None)
            result['groups'].append(group)
        result['manifest'] = {'resume': {'parent_job_id': spec['resume_parent_job_id'],
                                         'reused_candidates': spec['resume_reused_candidates'],
                                         'reused_corpus': 'parent_frozen_snapshot',
                                         'model_calls': 0,
                                         'policy': spec['model_budget']['policy']}}
        store.write_job(ident, state='completed', stage='恢复完成', progress=100, result=result)
    except _Cancelled:
        store.write_job(ident, state='cancelled', stage='恢复已取消', error='用户取消')
    except Exception as error:                                     # noqa: BLE001 - must land in the record
        store.write_job(ident, state='failed', stage='恢复失败',
                        error='%s: %s' % (type(error).__name__, str(error)[:400]))
    finally:
        # Release the concurrency slot: without this every finished resume keeps a
        # seat and blocks later jobs.
        with engine.lock:
            engine.events.pop(ident, None)
