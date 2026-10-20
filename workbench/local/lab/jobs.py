"""Persistent, cancellable generation jobs with independent probe/label inputs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import platform
import threading
import tempfile
import time

from local.common import LANGS, KEY_TO_LABEL, load_reference, load_snippet
from local.harness.identity import judge_source_closure, image_digest, ImageUnavailable
from local.harness import runner
from local.harness.runner import docker_available, InfrastructureError
from local.lab.judging import judge_one, VERSION as LAB_JUDGE_VERSION, fingerprint as lab_judge_fingerprint
from local.lab.catalog import load_cases, require_languages, evidence as corpus_evidence
from local.lab.behavior import observe, partition_cases, sha
from local.lab.generation import generate, prompt_for, GenerationError, DIAGNOSTICS_VERSION
from local.lab.diagnostics import redact
from local.lab.metrics import analyze, cross_language
from local.lab.storage import LabError, ACTIVE
from local.lab.probes import VERSION as PROBE_VERSION
from local.lab.metamorphic import proposals as relation_proposals, evaluate as relation_evaluate
from local.lab.execution import CachedExecution, VERSION as EXECUTION_VERSION
from local.lab.selection import recommend, VERSION as SELECTION_VERSION
from local.lab.correctness import probe_verdict, combine, VERSION as CORRECTNESS_VERSION
from local.lab import audited_judging, correctness_audit

def _executor_record(evidence_row, image):
    """Record the entry that actually produced the corpus verdict.

    The pipeline branches on the correctness profile: audited_judging runs the whole
    frozen corpus, otherwise the verdict is a merge of the validation and probe runs.
    Writing audited_judging unconditionally made a replay judge a different set of
    cases and report a different score, which is worse than refusing.
    """
    profile = (evidence_row or {}).get('profile_version')
    if profile == audited_judging.VERSION:
        entry = 'audited_judging'
        version = audited_judging.VERSION
        digest = sha(Path(audited_judging.__file__).read_text(encoding='utf-8'))
    else:
        entry = 'combined_validation_probes'
        version = 'full-corpus-verdict-v1'
        digest = sha(Path(__file__).read_text(encoding='utf-8'))
    return {'entry': entry, 'version': version, 'sha256': digest, 'image': image}


def _answer_block(evidence_row, cases):
    """The answer a verdict rests on, recorded even when no per-language gate ran.

    The live pipeline used to record only corpus_evidence, so new jobs carried no
    answer basis at all and the report had nothing to show. reference_languages
    stays empty here on purpose: this path has not run a per-language reference
    gate, and an empty list is the honest statement of that.
    """
    from local.lab import answer_evidence as ae
    if not isinstance(evidence_row, dict) or not cases:
        return None
    # The admitted languages come from the catalogue's gate records. Leaving this
    # empty made every new job look like it had no reference run, so rejudge and
    # resume refused them all -- including languages that did pass a gate.
    block = ae.block(cases,
                     evidence_level=evidence_row.get('evidence_level') or 'unknown',
                     source=evidence_row.get('source') or 'problem corpus',
                     limitations=evidence_row.get('limitations') or ())
    # Write real gate rows, not just a language list: the gate reads per-language
    # gate records, so a bare list reads as "no reference run" and blocks rejudge.
    for row in (evidence_row.get('gates') or []):
        if not isinstance(row, dict) or not row.get('language'):
            continue
        verdict = {'state': 'SUCCESS' if row.get('status') == 'Accepted' else 'FAILED',
                   'ac_status': row.get('status'),
                   'total_correct': row.get('correct'),
                   'total_testcases': row.get('total'),
                   '_meta': {'dropped_unrepresentable': row.get('dropped_unrepresentable'),
                             'error': str(row.get('error') or '')[:200]}}
        ae.record_language(block, row['language'], verdict, reference_sha256=None, interface=None)
    return block



class Cancelled(Exception):
    pass


def validate_spec(payload, store, *, trusted_snapshots=False):
    if not isinstance(payload, dict):
        raise LabError('spec 必须为对象')
    from local.lab import workflow
    if payload.get('workflow_version')==workflow.VERSION:
        return workflow.validate(payload,store,trusted_snapshots=trusted_snapshots)
    spec = {k: payload.get(k) for k in ('qids', 'model_ids', 'languages', 'task', 'source_language', 'num_candidates', 'probe_count', 'temperature', 'probe_strategy', 'metamorphic_checks')}
    spec['task'] = spec['task'] or 'gen'
    if 'auto_testcases' in payload:
        if type(payload['auto_testcases']) is not bool:
            raise LabError('自动补充测试必须为布尔值')
        count = payload.get('testcase_count', 30)
        if type(count) is not int or not 12 <= count <= 100:
            raise LabError('补充输入目标数必须在 12–100 之间')
        spec.update(auto_testcases=payload['auto_testcases'], testcase_count=count)
    spec['source_language'] = spec['source_language'] or 'python3'
    spec['num_candidates'] = 5 if spec['num_candidates'] is None else spec['num_candidates']
    spec['probe_count'] = 8 if spec['probe_count'] is None else spec['probe_count']
    spec['temperature'] = 0.7 if spec['temperature'] is None else spec['temperature']
    spec['probe_strategy'] = 'balanced' if spec['probe_strategy'] is None else spec['probe_strategy']
    if spec['probe_strategy'] not in ('balanced', 'hash'):
        raise LabError('探测策略必须是 balanced 或 hash')
    spec['metamorphic_checks'] = True if spec['metamorphic_checks'] is None else spec['metamorphic_checks']
    if type(spec['metamorphic_checks']) is not bool:
        raise LabError('变形关系检查必须是布尔值')
    for key, maximum in (('qids', 10), ('model_ids', 5), ('languages', 8)):
        values = spec[key]
        if not isinstance(values, list) or not 1 <= len(values) <= maximum:
            raise LabError(f'{key} 请选择 1–{maximum} 项')
        if any(type(v) is not (int if key == 'qids' else str) for v in values) or len(set(values)) != len(values):
            raise LabError(f'{key} 存在无效或重复项')
    if any(q <= 0 for q in spec['qids']) or any(lang not in LANGS for lang in spec['languages']):
        raise LabError('题号或目标语言无效')
    for key, lo, hi in (('num_candidates', 2, 25), ('probe_count', 2, 20)):
        if type(spec[key]) is not int or not lo <= spec[key] <= hi:
            raise LabError(f'{key} 必须在 {lo}–{hi} 之间')
    if type(spec['temperature']) not in (int, float) or not 0 < spec['temperature'] <= 2:
        raise LabError('随机采样温度必须大于 0 且不超过 2')
    if spec['task'] not in ('gen', 'trans') or spec['source_language'] not in LANGS:
        raise LabError('任务类型或源语言无效')
    if spec['task'] == 'trans' and spec['source_language'] in spec['languages']:
        raise LabError('转译的目标语言不能包含源语言')
    total = len(spec['qids']) * len(spec['model_ids']) * len(spec['languages']) * spec['num_candidates']
    if total > 200:
        raise LabError(f'本次需生成 {total} 份代码，单任务上限 200；请减少选择或拆分任务')
    for model_id in spec['model_ids']:
        profile = store.profile(model_id)
        if not profile['enabled']:
            raise LabError('所选模型已禁用')
    for qid in spec['qids']:
        cases = load_cases(qid)
        if not cases:
            raise LabError(f'q{qid} 暂无本地测试语料，请选择支持评测的题目')
        try:
            if spec.get('auto_testcases'):
                from local.lab.testcase_workflow import preflight
                preflight(qid, spec['languages'] + ([spec['source_language']] if spec['task'] == 'trans' else []))
            if not spec.get('auto_testcases'):
                require_languages(qid, spec['languages'] + ([spec['source_language']] if spec['task'] == 'trans' else []))
            partition_cases(qid, cases, spec['probe_count'], strategy=spec['probe_strategy'])
            for lang in spec['languages']:
                load_snippet(qid, lang)
                prompt_for(qid, lang)
            if spec['task'] == 'trans':
                load_reference(qid, spec['source_language'])
        except (OSError, ValueError, KeyError) as error:
            raise LabError(f'q{qid} 无法评测：{error}') from None
    return spec


def title_value(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise LabError('任务名称应为 1–120 个字符')
    return value.strip()


class Engine:
    def __init__(self, store):
        self.store = store
        self.store.recover()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='lab-job')
        self.lock = threading.RLock()
        self.events = {}
        self.image = None

    def start(self, ident):
        with self.lock:
            if len(self.events) >= 5:
                raise LabError('已有五个运行或排队任务，请等待完成后再提交', 429)
            job = self.store.job(ident)
            if job['spec'].get('kind') == 'rejudge':
                return self._start_rejudge(ident, job)
            if job['spec'].get('kind') == 'resume':
                return self._start_resume(ident, job)
            validated=validate_spec(job['spec'], self.store, trusted_snapshots=True)
            from local.lab import workflow
            if job['spec'].get('workflow_version')==workflow.VERSION:
                if validated!=job['spec']:
                    self.store.update_job(ident,job['title'],validated)
                self.store.queue(ident)
                event=threading.Event()
                self.events[ident]=event
                from local.lab.pipeline_jobs import run
                self.pool.submit(run,self,ident,event)
                return self.store.job(ident)
            if self.image is None:
                try:
                    self.image = image_digest()
                except ImageUnavailable:
                    raise LabError('无法确认 Docker 判题镜像，请检查 local-judge:1', 503) from None
            # Docker Desktop may list a tag yet fail to run/inspect that tag.
            # Pin the verified immutable image for this private worker process.
            runner.DOCKER_IMAGE = self.image
            try:
                for qid in job['spec']['qids']:
                    if not job['spec'].get('auto_testcases'):
                        require_languages(qid, job['spec']['languages'], image=self.image)
            except ValueError as error:
                raise LabError(str(error)) from None
            ok, _ = docker_available(timeout_s=8)
            if not ok:
                raise LabError('Docker 判题沙箱不可用，请启动 Docker 并准备 local-judge 镜像', 503)
            # Queue state guards profile updates/deletion during this run.
            self.store.queue(ident)
            event = threading.Event()
            self.events[ident] = event
            self.pool.submit(self._run, ident, event)
        return self.store.job(ident)

    def cancel(self, ident):
        with self.lock:
            job = self.store.job(ident)
            if job['state'] not in ACTIVE:
                raise LabError('任务当前没有运行', 409)
            event = self.events.get(ident)
            if event:
                event.set()
            self.store.write_job(ident, state='cancelling', stage='正在取消；当前 API / 沙箱调用结束后停止')
        return self.store.job(ident)

    def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True, cancel_futures=False)

    def _start_rejudge(self, ident, job):
        """Zero model calls: no profile lookup, no generation, no bridge fallback."""
        from local.lab import rejudge
        if self.image is None:
            try:
                self.image = image_digest()
            except ImageUnavailable:
                raise LabError('无法确认 Docker 判题镜像，请检查 local-judge:1', 503) from None
        runner.DOCKER_IMAGE = self.image
        ok, _ = docker_available(timeout_s=8)
        if not ok:
            raise LabError('Docker 判题沙箱不可用，请启动 Docker 并准备 local-judge 镜像', 503)
        self.store.queue(ident)
        event = threading.Event()
        self.events[ident] = event
        self.pool.submit(rejudge.run, self, ident, event)
        return self.store.job(ident)

    def _start_resume(self, ident, job):
        """Judging-only resume: frozen code and corpus, zero model calls."""
        from local.lab import resume
        if self.image is None:
            try:
                self.image = image_digest()
            except ImageUnavailable:
                raise LabError('无法确认 Docker 判题镜像，请检查 local-judge:1', 503) from None
        runner.DOCKER_IMAGE = self.image
        ok, _ = docker_available(timeout_s=8)
        if not ok:
            raise LabError('Docker 判题沙箱不可用，请启动 Docker 并准备 local-judge 镜像', 503)
        self.store.queue(ident)
        event = threading.Event()
        self.events[ident] = event
        self.pool.submit(resume.run, self, ident, event)
        return self.store.job(ident)

    def _run(self, ident, event):
        def check_cancel():
            if event.is_set():
                raise Cancelled()
        result = {'groups': [], 'cross_language': [], 'validation_label_source': 'per_question_corpus_evidence',
                  'leetcode_verdict': None, 'notice': '本地测试通过率不是 LeetCode 通过率；低不确定性不保证正确'}
        phase = 'prepare'
        context = {}
        started = time.perf_counter()
        totals = {'prepare_ms': 0., 'generation_ms': 0., 'probe_ms': 0., 'metamorphic_ms': 0., 'validation_ms': 0., 'full_corpus_ms': 0.}
        try:
            check_cancel()
            job = self.store.job(ident)
            spec = job['spec']
            profiles = {i: self.store.profile(i, private=True) for i in spec['model_ids']}
            snapshots = [{k: v for k, v in p.items() if k != 'api_key'} for p in profiles.values()]
            ok, image = docker_available()
            if not ok:
                raise InfrastructureError('Docker 沙箱不可用')
            result['manifest'] = {'models': snapshots, 'spec': spec, 'image': self.image or image_digest(),
                                  'host_python': platform.python_version(), 'judge_closure': dict(judge_source_closure()),
                                  'catalog_sha256': sha(Path(__file__).with_name('catalog.py').read_text(encoding='utf-8')),
                                  'lab_judge_version': LAB_JUDGE_VERSION, 'lab_judge_sha256': lab_judge_fingerprint(),
                                  'correctness_version': CORRECTNESS_VERSION,
                                  'full_execution_profile': audited_judging.profile(self.image or image_digest()),
                                  'correctness_sha256': sha(Path(__file__).with_name('correctness.py').read_text(encoding='utf-8')),
                                  'metric_sha256': sha(Path(__file__).with_name('metrics.py').read_text(encoding='utf-8')),
                                  'behavior_sha256': sha(Path(__file__).with_name('behavior.py').read_text(encoding='utf-8')),
                                  'generation_sha256': sha(Path(__file__).with_name('generation.py').read_text(encoding='utf-8')),
                                  'generation_diagnostics_version': DIAGNOSTICS_VERSION,
                                  'probe_selection_version': PROBE_VERSION,
                                  'probe_selection_sha256': sha(Path(__file__).with_name('probes.py').read_text(encoding='utf-8')),
                                  'metamorphic_sha256': sha(Path(__file__).with_name('metamorphic.py').read_text(encoding='utf-8')),
                                  'execution_version': EXECUTION_VERSION,
                                  'execution_sha256': sha(Path(__file__).with_name('execution.py').read_text(encoding='utf-8')),
                                  'cache_supervisor_sha256': sha(Path(__file__).with_name('cache_supervisor.py').read_text(encoding='utf-8')),
                                  'selection_policy_version': SELECTION_VERSION,
                                  'selection_policy_sha256': sha(Path(__file__).with_name('selection.py').read_text(encoding='utf-8')),
                                  'probe_timeout_s': 5, 'validation_timeout_s': 5}
            executor = CachedExecution(Path(self.store.path).parent / 'lab_artifacts', result['manifest']['image'])
            if spec.get('auto_testcases'):
                from local.lab.testcase_workflow import build as build_tests
                result['testcase_workflow'] = {'state': 'running', 'target_per_question': spec['testcase_count'], 'events': [], 'questions': []}
                phase = 'testcase_generation'
                def testcase_event(update):
                    result['testcase_workflow']['events'].append(update)
                    self.store.write_job(ident, state='evaluating', stage=f'q{update["qid"]} 自动补充测试：{update["stage"]}', result=result)
                profile = profiles[spec['model_ids'][0]]
                for qid in spec['qids']:
                    context = {'qid': qid, 'model_name': profile['name']}
                    bundle = build_tests(qid, profile, spec['testcase_count'],
                                         spec['languages'] + ([spec['source_language']] if spec['task'] == 'trans' else []),
                                         result['manifest']['image'], on_event=testcase_event, check_cancel=check_cancel)
                    result['testcase_workflow']['questions'].append({'qid': qid, 'state': 'verified',
                         'generated_count': len(bundle['generated_cases']), 'cases_sha256': bundle['cases_sha256'],
                         'requested_target': spec['testcase_count'], 'effective_target': bundle.get('effective_target', spec['testcase_count']),
                         'leetcode_alignment': 'not_measured'})
                result['testcase_workflow']['state'] = 'completed'
            partitions, frozen_probe_cases, frozen_corpora, correctness_evidence = {}, {}, {}, {}
            for qid in spec['qids']:
                require_languages(qid, spec['languages'] + ([spec['source_language']] if spec['task'] == 'trans' else []),
                                  image=result['manifest']['image'])
                prepared_cases = deepcopy(load_cases(qid))
                frozen_corpora[qid] = deepcopy(prepared_cases)
                correctness_evidence[qid] = correctness_audit.evidence(qid,prepared_cases,result['manifest']['image'])
                probes, validation, selection = partition_cases(qid, prepared_cases, spec['probe_count'],
                                                                strategy=spec.get('probe_strategy', 'hash'), return_metadata=True)
                from local.lab.testcase_workflow import read_bundle
                generated_bundle = read_bundle(qid, image=result['manifest']['image'])
                if generated_bundle:
                    private = {sha(c['args']) for c in generated_bundle['generated_cases']}
                    adjusted_count = len(probes)
                    while sum(sha(c['args']) in private for c in validation) < 3 and adjusted_count > 2:
                        adjusted_count -= 1
                        probes, validation, selection = partition_cases(qid, prepared_cases, adjusted_count,
                                    strategy=spec.get('probe_strategy', 'hash'), return_metadata=True)
                    selection['requested_probe_count'] = spec['probe_count']
                    selection['private_validation_count'] = sum(sha(c['args']) in private for c in validation)
                    if selection['private_validation_count'] < 3:
                        raise ValueError('至少保留三个非公开补充输入用于验证，当前语料不足')
                    if len(probes) < spec['probe_count']:
                        selection['warnings'].append('为保留至少三个补充验证输入，已缩减探测数量')
                partitions[qid] = (probes, validation, selection)
                by_input = {sha({k: c[k] for k in ('args', 'ops') if k in c}): c for c in prepared_cases}
                frozen_probe_cases[qid] = [deepcopy(by_input[sha(p)]) for p in probes]
            result['inputs'] = [{'qid': qid, 'probes': probes, 'probe_sha256': sha(probes),
                                'probe_correctness_cases': frozen_probe_cases[qid],
                                'full_corpus': frozen_corpora[qid],
                                'correctness_evidence': correctness_evidence[qid],
                                'corpus_evidence': corpus_evidence(qid),
                                'validation': validation, 'validation_sha256': sha(validation), 'validation_count': len(validation), 'selection': selection}
                                for qid, (probes, validation, selection) in partitions.items()]
            relations = {qid: relation_proposals(qid, probes) if spec.get('metamorphic_checks', False) else []
                         for qid, (probes, _, _) in partitions.items()}
            result['metamorphic_plan'] = [{'qid': qid, 'relations': variants} for qid, variants in relations.items()]
            totals['prepare_ms'] = (time.perf_counter() - started) * 1000
            result['timing'] = {'version': 'lab-stage-timing-v1', 'max_sandbox_concurrency': 1,
                                'generation_cached': False, 'execution_outputs_cached': False, 'phases_ms': totals}
            total = len(spec['qids']) * len(profiles) * len(spec['languages']) * spec['num_candidates']
            done = 0
            for qid in spec['qids']:
                phase = 'prepare'
                context = {'qid': qid}
                probes, validation, selection = partitions[qid]
                source_code = source_outcomes = None
                if spec['task'] == 'trans':
                    source_code = load_reference(qid, spec['source_language'])
                    source_outcomes = []
                    for probe in probes:
                        phase = 'source_probe'
                        context = {'qid': qid, 'language': spec['source_language']}
                        check_cancel()
                        source_outcomes.append(observe(qid, spec['source_language'], source_code, probe, executor=executor))
                    if any(o['kind'] != 'value' for o in source_outcomes):
                        raise RuntimeError(f'q{qid} 源程序未完成探测输入，无法评价转译保持率')
                for model_id, profile in profiles.items():
                    for language in spec['languages']:
                        group = {'qid': qid, 'model_id': model_id, 'model_name': profile['name'],
                                 'language': language, 'candidates': [], 'metrics': None,
                                 'probe_sha256': sha(probes), 'validation_count': len(validation), 'probe_count': len(probes), 'probe_selection': selection,
                                 'corpus_evidence': corpus_evidence(qid), 'corpus_count': len(probes) + len(validation),
                                 'answer_evidence': _answer_block(corpus_evidence(qid), frozen_corpora[qid]),
                                 'executor': _executor_record(correctness_evidence[qid],
                                                              result['manifest']['image'])}
                        group['correctness_evidence'] = deepcopy(correctness_evidence[qid])
                        if correctness_evidence[qid]['profile_version'] == audited_judging.VERSION:
                            group['corpus_count'] = len(frozen_corpora[qid])
                        if source_code is not None:
                            group.update(source_language=spec['source_language'], source_code=source_code,
                                         source_sha256=sha(source_code), source_outcomes=source_outcomes)
                        result['groups'].append(group)
                        prompt = prompt_for(qid, language, source_language=spec['source_language'] if source_code is not None else None,
                                            source_code=source_code)
                        group['prompt'] = prompt
                        for index in range(spec['num_candidates']):
                            check_cancel()
                            phase = 'generation'
                            context = {'qid': qid, 'model_id': model_id, 'model_name': profile['name'],
                                       'language': language, 'candidate_index': index + 1}
                            candidate = {'id': f'{qid}-{model_id}-{language}-{index + 1}', 'index': index + 1,
                                         'code': '', 'raw': '', 'code_sha256': '', 'prompt_sha256': sha(prompt),
                                         'outcomes': [], 'verdict': None, 'generation_state': 'generating',
                                         'generation': {'version': DIAGNOSTICS_VERSION, 'attempts': []}}
                            group['candidates'].append(candidate)
                            stage = f'q{qid} / {profile["name"]} / {KEY_TO_LABEL[language]}：生成候选 {index + 1}/{spec["num_candidates"]}'
                            with self.lock:
                                check_cancel()
                                self.store.write_job(ident, state='generating', stage=stage, progress=int(done / total * 100), result=result)
                            def save_attempt(record):
                                candidate['generation']['attempts'].append(record)
                                note = (f'接口暂时失败，等待 {record["retry_delay_seconds"]:g}s 后重试（{record["attempt"]}/3）'
                                        if record['retry_scheduled'] else record['message'])
                                with self.lock:
                                    self.store.write_job(ident, result=result,
                                                         stage='正在取消；已保留模型响应' if event.is_set() else stage + ' · ' + note)
                            def save_progress(record):
                                candidate['generation']['in_flight'] = record
                                with self.lock:
                                    self.store.write_job(ident, result=result, stage=stage + f' · 接口响应 {record["received_bytes"]} 字节 / 已等待 {record["elapsed_seconds"]:g}s')
                            generation_started = time.perf_counter()
                            try:
                                prediction = generate(profile, prompt, spec['temperature'],
                                                      on_attempt=save_attempt, check_cancel=check_cancel, on_progress=save_progress)
                            except Cancelled:
                                candidate['generation_state'] = 'cancelled'
                                raise
                            except Exception:
                                candidate['generation_state'] = 'failed'
                                raise
                            finally:
                                candidate['generation'].pop('in_flight', None)
                                elapsed = (time.perf_counter()-generation_started)*1000
                                totals['generation_ms'] += elapsed
                                candidate['timing'] = {'generation_ms': elapsed, 'probe_ms': 0., 'metamorphic_ms': 0., 'validation_ms': 0.}
                            candidate.update(prediction, code_sha256=sha(prediction['code']), generation_state='succeeded')
                            check_cancel()
                            with self.lock:
                                check_cancel()
                                self.store.write_job(ident, state='evaluating', stage=stage.replace('生成', '评测'), result=result)
                            for pi, probe in enumerate(probes):
                                phase = 'probe'
                                context['probe_index'] = pi + 1
                                check_cancel()
                                phase_start = time.perf_counter()
                                candidate['outcomes'].append(observe(qid, language, prediction['code'], probe, executor=executor))
                                elapsed = (time.perf_counter()-phase_start)*1000
                                candidate['timing']['probe_ms'] += elapsed
                                totals['probe_ms'] += elapsed
                                self.store.write_job(ident, stage=f'{stage} · 行为探测 {pi + 1}/{len(probes)}', result=result)
                            candidate['metamorphic'] = []
                            for relation in relations[qid]:
                                check_cancel()
                                phase = 'metamorphic'
                                context['probe_index'] = relation['base_probe_index'] + 1
                                phase_start = time.perf_counter()
                                transformed = observe(qid, language, prediction['code'], relation['input'], executor=executor)
                                elapsed = (time.perf_counter()-phase_start)*1000
                                candidate['timing']['metamorphic_ms'] += elapsed
                                totals['metamorphic_ms'] += elapsed
                                candidate['metamorphic'].append(relation_evaluate(relation, candidate['outcomes'][relation['base_probe_index']], transformed))
                                self.store.write_job(ident, stage=stage + ' · 变形关系检查', result=result)
                            check_cancel()
                            phase = 'validation'
                            phase_start = time.perf_counter()
                            with tempfile.TemporaryDirectory(prefix='mci_lab_') as folder:
                                path = Path(folder) / f'{qid}_{KEY_TO_LABEL[language]}_{index + 1}.txt'
                                path.write_text(prediction['code'], encoding='utf-8')
                                verdict = judge_one(path, 'gen', max_cases=len(validation), backend='docker',
                                                    run_timeout_s=5, cases_override=deepcopy(validation))
                            if (verdict['state'] != 'SUCCESS' or verdict['total_testcases'] != len(validation)
                                    or verdict['_meta'].get('dropped_unrepresentable', 0)):
                                raise RuntimeError('独立验证未完成：' + (verdict['_meta'].get('error') or
                                    f'计划 {len(validation)} 条，实际 {verdict["total_testcases"]} 条，表示层丢弃 {verdict["_meta"].get("dropped_unrepresentable", 0)} 条'))
                            candidate['verdict'] = {k: verdict[k] for k in ('state', 'ac_status', 'total_testcases', 'total_correct', 'runtime', 'memory')}
                            candidate['timing']['validation_ms'] = (time.perf_counter()-phase_start)*1000
                            totals['validation_ms'] += candidate['timing']['validation_ms']
                            candidate['validation_passed'] = verdict['ac_status'] == 'Accepted'
                            candidate['probe_verdict'] = probe_verdict(qid, frozen_probe_cases[qid], candidate['outcomes'])
                            combined = combine(candidate['verdict'], candidate['probe_verdict'])
                            if correctness_evidence[qid]['profile_version'] == audited_judging.VERSION:
                                phase = 'full_corpus'
                                check_cancel()
                                phase_start = time.perf_counter()
                                candidate['legacy_corpus_verdict'] = deepcopy(combined)
                                with tempfile.TemporaryDirectory(prefix='mci_full_corpus_') as folder:
                                    full_path = Path(folder) / f'{qid}_{KEY_TO_LABEL[language]}_{index+1}.txt'
                                    full_path.write_text(prediction['code'],encoding='utf-8')
                                    full = audited_judging.run(full_path,frozen_corpora[qid],check_cancel=check_cancel)
                                candidate['corpus_verdict'] = audited_judging.public_verdict(full)
                                candidate['full_execution_evidence'] = full['_meta']
                                candidate['timing']['full_corpus_ms'] = (time.perf_counter()-phase_start)*1000
                                totals['full_corpus_ms'] += candidate['timing']['full_corpus_ms']
                            else:
                                candidate['corpus_verdict'] = combined
                            candidate['corpus_passed'] = candidate['corpus_verdict']['ac_status'] == 'Accepted'
                            if source_outcomes is not None:
                                candidate['translation_preservation'] = sum(
                                    a['kind'] == b['kind'] == 'value' and a['semantic_key'] == b['semantic_key']
                                    for a, b in zip(candidate['outcomes'], source_outcomes)) / len(probes)
                            done += 1
                            self.store.write_job(ident, progress=int(done / total * 100), result=result)
                        check_cancel()
                        phase = 'metrics'
                        group['metrics'] = analyze(group['candidates'])
                        group['validation_pass_rate'] = sum(c['validation_passed'] for c in group['candidates']) / len(group['candidates'])
                        group['local_pass_rate'] = sum(c['corpus_passed'] for c in group['candidates']) / len(group['candidates'])
                        selected = next((c for c in group['candidates'] if c.get('selected')), None)
                        group['selected_validation_passed'] = selected['validation_passed'] if selected else None
                        group['selection_advice'] = recommend(group, expected_count=spec['num_candidates'])
                        group['selection_advice']['provenance'] = 'frozen_at_run'
                        self.store.write_job(ident, result=result)
            result['cross_language'] = cross_language(result['groups'])
            result['timing']['wall_ms'] = (time.perf_counter()-started)*1000
            with self.lock:
                check_cancel()
                self.store.write_job(ident, state='completed', stage='评测完成', progress=100, result=result)
        except Cancelled:
            if result.get('testcase_workflow', {}).get('state') == 'running':
                result['testcase_workflow']['state'] = 'cancelled'
            self.store.write_job(ident, state='cancelled', stage='已取消，保留已完成结果', result=result)
        except Exception as error:
            if result.get('testcase_workflow', {}).get('state') == 'running':
                result['testcase_workflow']['state'] = 'failed'
            secrets = [p.get('api_key', '') for p in locals().get('profiles', {}).values()]
            message = redact(str(error), secrets)
            result['failure'] = {'phase': phase, 'code': getattr(error, 'code', 'execution_environment' if isinstance(error, InfrastructureError) else 'internal_error'),
                                 'message': message[:500], 'context': context,
                                 'suggestion': getattr(error, 'suggestion', '查看失败阶段和已有候选记录；修正配置或环境后复制任务重试。'),
                                 'retryable': getattr(error, 'retryable', False),
                                 'attempt_count': len(getattr(error, 'attempts', []))}
            if isinstance(error, GenerationError) and locals().get('candidate'):
                candidate['generation'] = {'version': DIAGNOSTICS_VERSION, 'attempts': error.attempts}
            result = redact(result, secrets)
            with self.lock:
                state = 'cancelled' if event.is_set() else 'failed'
                self.store.write_job(ident, state=state, stage='已取消' if event.is_set() else '任务失败', error=message[:500], result=result)
        finally:
            with self.lock:
                self.events.pop(ident, None)
