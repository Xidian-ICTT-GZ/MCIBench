"""LLM proposes inputs; reviewed contracts, independent oracles and sandboxes admit them."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import tempfile
import uuid

from local.common import DESCRIPTIONS_DIR, KEY_TO_LABEL, LANGS, REPO_ROOT, load_reference, load_snippet
from local.harness.identity import judge_source_closure
from local.lab.judging import judge_one, fingerprint as numeric_checker_fingerprint
from local.lab.behavior import sha
from local.lab.generation import generate
from local.lab import input_contracts as contracts
from local.gen_testcases.extract_examples import extract_from_prompt

VERSION = 'llm-input-oracle-reference-workflow-v1'
DATA_DIR = REPO_ROOT / 'local/dashboard/packages/server/data/lab_corpus'
MAX_EXPANDED_ITEMS = 300000
MAX_RESPONSE_BYTES = 1_000_000


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复 JSON 字段')
        result[key] = value
    return result


def expand(value, budget=None, depth=0):
    """Bounded declarative recipes; no model-generated code is executed."""
    budget = budget if budget is not None else [MAX_EXPANDED_ITEMS]
    budget[0] -= 1
    if budget[0] < 0 or depth > 20:
        raise ValueError('输入构造超出大小或嵌套预算')
    if type(value) is list:
        return [expand(v, budget, depth+1) for v in value]
    if type(value) is dict:
        if len(value) != 1:
            raise ValueError('只接受声明式输入构造')
        key, args = next(iter(value.items()))
        if key == '$range' and type(args) is list and len(args) in (2, 3) and all(type(x) is int for x in args):
            items = range(*args)
            if len(items) > budget[0]:
                raise ValueError('范围构造超过输入预算')
            budget[0] -= len(items)
            return list(items)
        if key in ('$repeat', '$text') and type(args) is list and len(args) == 2 and type(args[1]) is int and 0 <= args[1] <= MAX_EXPANDED_ITEMS:
            item, count = args
            if key == '$text':
                if type(item) is not str or len(item)*count > budget[0]:
                    raise ValueError('文本构造超过输入预算')
                budget[0] -= len(item)*count
                return item*count
            item = expand(item, budget, depth+1)
            cost = max(1, len(json.dumps(item, ensure_ascii=False))) * count
            if cost > budget[0]:
                raise ValueError('重复构造超过输入预算')
            budget[0] -= cost
            return [deepcopy(item) for _ in range(count)]
        raise ValueError('未知输入构造；不执行任意代码')
    if type(value) not in (str, int, bool, type(None)):
        raise ValueError('仅接受有限 JSON 基本值')
    if type(value) is str:
        budget[0] -= len(value)
    if budget[0] < 0:
        raise ValueError('输入超出预算')
    return value


def parse_proposals(raw, qid, exclude=()):
    if type(raw) is not str or len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
        raise ValueError('测试输入响应超过大小预算')
    data = json.loads(raw, object_pairs_hook=_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非有限数值')))
    if type(data) is not dict or set(data) != {'cases'} or type(data['cases']) is not list or len(data['cases']) > 100:
        raise ValueError('模型必须返回 {"cases":[{"args":{...},"category":"..."}]}，最多 100 条')
    seen, accepted, rejected, budget = set(exclude), [], [], [MAX_EXPANDED_ITEMS]
    for index, proposal in enumerate(data['cases']):
        try:
            if type(proposal) is not dict or not set(proposal) <= {'args', 'category'} or type(proposal.get('args')) is not dict:
                raise ValueError('只接受输入和覆盖类别；模型不得提供 expected 或答案')
            args = {key: expand(v, budget) for key, v in proposal['args'].items()}
            if not contracts.valid(qid, args):
                raise ValueError('输入违反已审查的题面约束')
            key = sha(args)
            if key in seen:
                raise ValueError('重复输入或已公开示例')
            expected = contracts.answer(qid, args)
            seen.add(key)
            accepted.append({'args': args, 'expected': expected,
                             '_category': str(proposal.get('category', 'unspecified'))[:40]})
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            rejected.append({'index': index, 'reason': str(error)[:200]})
    return accepted, rejected


def preflight(qid, languages=('python3', 'cpp')):
    contracts.require(qid)
    for lang in set(languages) | {'python3', 'cpp'}:
        load_reference(qid, lang)
        load_snippet(qid, lang)
    return True


def source_binding(qid, languages, base, *, _judge_closure=None):
    return {'description_sha256': sha(contracts.description(qid)), 'contracts_sha256': contracts.fingerprint(),
            'judge_closure': dict(judge_source_closure()) if _judge_closure is None else dict(_judge_closure), 'host_python': platform.python_version(),
            'snippets_sha256': {l: sha(load_snippet(qid, l)) for l in LANGS},
            'references_sha256': {l: sha(load_reference(qid, l)) for l in languages},
            'base_sha256': sha(base)}


_BASE_UNSET=object()


def read_bundle(qid, *, data_dir=None, image=None, _base_cases=_BASE_UNSET, _judge_closure=None):
    path = Path(data_dir or DATA_DIR) / f'{qid}.json'
    if not path.exists():
        return None
    try:
        from local.lab.catalog import base_cases
        row = json.loads(path.read_text(encoding='utf-8'))
        base=(base_cases(qid) or []) if _base_cases is _BASE_UNSET else _base_cases
        expected_binding=(source_binding(qid,row['languages'],base) if _judge_closure is None else
                          source_binding(qid,row['languages'],base,_judge_closure=_judge_closure))
        if (row['version'] != VERSION or row['qid'] != qid or len(row['generated_cases']) < 12
                or row['binding'] != expected_binding
                or row['cases_sha256'] != sha(row['cases']) or row['generated_sha256'] != sha(row['generated_cases'])
                or (image is not None and row['image'] != image)):
            return None
        if row.get('numeric_checker_sha256') and row['numeric_checker_sha256'] != numeric_checker_fingerprint():
            return None
        contracts.require(qid)
        public = {sha(c['args']) for c in extract_from_prompt(contracts.description(qid))}
        if any(not contracts.valid(qid, c['args']) or sha(c['args']) in public for c in row['generated_cases']):
            return None
        if len({sha(c['expected']) for c in row['generated_cases']}) < 2:
            return None
        generated = {sha(c) for c in row['generated_cases']}
        if len({sha(c['args']) for c in row['generated_cases']}) != len(generated) or not generated <= {sha(c) for c in row['cases']}:
            return None
        if not {'python3', 'cpp'} <= set(row['languages']):
            return None
        if any(not any(g['language'] == l and g['state'] == 'SUCCESS' and g['status'] == 'Accepted'
                       and g['total'] == g['correct'] == len(row['cases']) and not g['dropped'] for g in row['gates']) for l in row['languages']):
            return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None


@contextmanager
def lock(qid, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{qid}.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError(f'q{qid} 测试构建已被另一进程锁定；异常退出后的锁需核实再清理') from None
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    pending.replace(path)


def brief(value):
    if isinstance(value, (str, list)) and len(value) > 64:
        return {'length': len(value), 'prefix': value[:16], 'suffix': value[-16:]}
    return value


def build(qid, profile, target, languages, image, *, data_dir=None, on_event=None, check_cancel=lambda: None):
    """Resume verified inputs, make at most three bounded API calls, publish only a complete gate."""
    preflight(qid, languages)
    if type(target) is not int or not 12 <= target <= 100:
        raise ValueError('补充输入目标数必须在 12–100 之间')
    requested_target = target
    if qid == 509:
        # Only 31 legal inputs exist. The three public examples must not make a
        # requested 30 *additional* inputs into an impossible completion target.
        public_count = len({c['args']['n'] for c in extract_from_prompt(contracts.description(qid))})
        target = min(target, 31-public_count)
    from local.common import load_ft_test_qids
    if qid in load_ft_test_qids():
        languages = list(LANGS)
    languages = [l for l in LANGS if l in set(languages) | {'python3', 'cpp'}]
    directory = Path(data_dir or DATA_DIR)
    def emit(stage, **fields):
        check_cancel()
        if on_event:
            on_event({'qid': qid, 'stage': stage, **fields})
    with lock(qid, directory):
        old = read_bundle(qid, data_dir=directory, image=image)
        if old and len(old['generated_cases']) >= target and set(languages) <= set(old['languages']):
            emit('reused_verified_corpus', generated_count=len(old['generated_cases']))
            return old
        from local.lab.catalog import base_cases
        base = base_cases(qid) or extract_from_prompt(contracts.description(qid))
        binding = source_binding(qid, languages, base_cases(qid) or [])
        # An oracle must also reproduce every official example before it can label new inputs.
        for case in extract_from_prompt(contracts.description(qid)):
            if sha(contracts.answer(qid, case['args'])) != sha(case['expected']):
                raise ValueError('独立答案算法与官方示例冲突，禁止自动构建')
        model = {k: profile[k] for k in ('id', 'name', 'model_name', 'api_url') if k in profile}
        generated = deepcopy(old['generated_cases']) if old else []
        pending_path = directory / 'pending' / f'{qid}.json'
        if pending_path.exists():
            pending = json.loads(pending_path.read_text(encoding='utf-8'))
            if pending.get('binding') == binding and pending.get('image') == image and pending.get('model') == model:
                public_keys = {sha(c['args']) for c in base + generated}
                for case in pending.get('cases', []):
                    if sha(case['args']) not in public_keys and contracts.valid(qid, case['args']) and sha(contracts.answer(qid, case['args'])) == sha(case['expected']):
                        generated.append(case)
                        public_keys.add(sha(case['args']))
        excluded = {sha(c['args']) for c in base + generated}
        trace = {'version': VERSION, 'qid': qid, 'target': target, 'attempts': [], 'rejected': [],
                 'model': model,
                 'generation_used_for_answers': False, 'binding': binding}
        draft = directory / 'attempts' / f'{qid}-{uuid.uuid4().hex}.json'
        save(draft, trace)
        for round_index in range(3):
            missing = target - len(generated)
            diverse = len({sha(c['expected']) for c in generated}) >= 2
            if missing <= 0 and diverse:
                break
            missing = max(4, missing) if not diverse else missing
            emit('requesting_test_inputs', round=round_index+1, generated_count=len(generated), target=target)
            prior = json.dumps([{k: brief(v) for k, v in c['args'].items()} for c in base + generated], ensure_ascii=False)[:16000]
            prompt = (f'Design {missing} DIFFERENT legal test inputs for problem q{qid}. '
                      'Return a JSON object with ONLY a cases list. Each item has args matching the interface parameter names '
                      'and optional category (boundary, adversarial, random, scale). NO expected outputs, solutions or explanations. '
                      'The following inputs are FORBIDDEN: these are ALL public and previously accepted inputs '
                      '(long values summarized by length/prefix/suffix). Generate DIFFERENT inputs: ' + prior + '\n'
                      'Cover boundary values, edge structures, repetition and scale; obey every problem constraint. '
                      'Include both successful and failing logical branches, not only one kind of input. '
                      'NEVER print a literal string or array longer than 64 items: MUST use the compact recipes below. '
                      'Large arrays may use {"$range":[start,stop,step]} or {"$repeat":[value,count]}; '
                      'strings may use {"$text":[text,count]}. No other recipes or executable code. '
                      'For q20, for example, {"$text":["()",5000]} represents a balanced string of length 10000. '
                      'Independent exhaustive oracles currently limit q3 string length to 2000 and q1014 array length to 1000.\n'
                      'JSON example schema: {"cases":[{"args":{"PARAMETER":VALUE},"category":"boundary"}]}\n'
                      + contracts.description(qid) + '\nInterface:\n' + load_snippet(qid, 'python3'))
            def attempt(record):
                trace['attempts'].append(record)
                save(draft, trace)
                emit('test_input_response', attempt=record)
            response = generate(profile, prompt, .7, purpose='test_inputs', max_attempts=1, check_cancel=check_cancel,
                                on_attempt=attempt, on_progress=lambda fields: emit('test_input_progress', **fields))
            if response.get('finish_reason') != 'stop':
                raise ValueError('测试输入响应未完整结束；不接收被截断的 JSON')
            accepted, rejected = parse_proposals(response['code'], qid, excluded)
            trace['rejected'].extend(rejected)
            for case in accepted[:missing]:
                category = case.pop('_category')
                generated.append(case)
                excluded.add(sha(case['args']))
                trace.setdefault('categories', []).append(category)
            trace['accepted_count'] = len(generated)
            save(pending_path, {'binding': binding, 'image': image, 'model': model, 'cases': generated})
            save(draft, trace)
        if len(generated) < target:
            raise ValueError(f'仅有 {len(generated)}/{target} 条合格补充输入，保留候选记录，未修改正式评测语料')
        if len({sha(c['expected']) for c in generated}) < 2:
            raise ValueError('补充输入未覆盖至少两种不同的预期结果，整批保留待完善，不发布单一分支测试')
        cases = deepcopy(base) + generated
        gates = []
        with tempfile.TemporaryDirectory(prefix='mci_generated_reference_') as tmp:
            for language in languages:
                emit('reference_gate', language=language, generated_count=len(generated))
                code = Path(tmp) / f'{qid}_{KEY_TO_LABEL[language]}_1.txt'
                code.write_text(load_reference(qid, language), encoding='utf-8')
                verdict = judge_one(code, 'gen', len(cases), 'docker', cases_override=cases)
                gate = {'language': language, 'state': verdict['state'], 'status': verdict['ac_status'],
                        'total': verdict['total_testcases'], 'correct': verdict['total_correct'],
                        'dropped': verdict['_meta'].get('dropped_unrepresentable', 0),
                        'detail': verdict['_meta'].get('error', '')[:500]}
                gates.append(gate)
                trace['gates'] = gates
                save(draft, trace)
                if gate['state'] != 'SUCCESS' or gate['status'] != 'Accepted' or gate['total'] != gate['correct'] or gate['total'] != len(cases) or gate['dropped']:
                    raise ValueError(f'{language} 门禁未通过：计划 {len(cases)} 条，实际 {gate["total"]} 条，'
                                     f'表示层丢弃 {gate["dropped"]} 条，状态 {gate["status"]}；整批隔离，未发布')
        check_cancel()
        if binding != source_binding(qid, languages, base_cases(qid) or []):
            raise ValueError('验证期间题面、约束、参考解或基础语料变化，请重做门禁')
        row = {'version': VERSION, 'qid': qid, 'created_at': datetime.now(timezone.utc).isoformat(),
               'languages': languages, 'image': image, 'binding': binding, 'gates': gates,
               'cases': cases, 'cases_sha256': sha(cases), 'generated_cases': generated, 'generated_sha256': sha(generated),
               'model': trace['model'], 'attempt_file': str(draft.relative_to(directory)),
               'independent_oracle': contracts.VERSION, 'llm_provided_expected': False,
               'leetcode_alignment': 'not_measured', 'workflow_sha256': sha(Path(__file__).read_text(encoding='utf-8'))}
        row['numeric_checker_sha256'] = numeric_checker_fingerprint()
        row['requested_target'] = requested_target
        row['effective_target'] = target
        row['finite_domain_exhaustive'] = qid == 509 and len({c['args']['n'] for c in cases}) == 31
        row['parent_cases_sha256'] = old['cases_sha256'] if old else None
        row['generation_history'] = (old.get('generation_history', [{'model': old['model'], 'attempt_file': old['attempt_file'], 'generated_sha256': old['generated_sha256']}]) if old else []) + [
            {'model': trace['model'], 'attempt_file': row['attempt_file'], 'generated_sha256': row['generated_sha256']}]
        # Once activated, a reviewed question cannot grow its corpus without
        # passing the same functional/positive gates. Keep the old bundle intact
        # on failure; model responses never bypass these gates.
        from local.lab import correctness_audit
        previous_audit = correctness_audit.receipt(qid,old['cases'],image) if old else None
        functional_audit = None
        if previous_audit and previous_audit.get('passed') and previous_audit.get('promoted'):
            emit('functional_regression_gate')
            functional_audit = correctness_audit.audit(qid,cases,languages,image,
                cache_dir=directory/'functional_executions',check_cancel=check_cancel)
            report_path=directory/'functional_reports'/f'{qid}-{functional_audit["report_sha256"]}.json'
            save(report_path,functional_audit)
            trace['functional_report_file']=str(report_path.relative_to(directory))
            trace['functional_report_sha256']=functional_audit['report_sha256']
            trace['state']='functional_gate_passed' if functional_audit['passed'] else 'functional_gate_failed'
            save(draft,trace)
            if not functional_audit['passed']:
                raise ValueError('补充测试未通过功能错误与正确改写门禁，保留旧语料')
            row['functional_report_sha256'] = functional_audit['report_sha256']
        check_cancel()
        save(directory / f'{qid}.json', row)
        if functional_audit:
            correctness_audit.save_receipt(functional_audit,promoted=True)
        pending_path.unlink(missing_ok=True)
        trace['state'] = 'published'
        save(draft, trace)
        emit('published_generated_tests', generated_count=len(generated), total_count=len(cases))
        return row
