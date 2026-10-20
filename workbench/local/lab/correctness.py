"""Host-side answer checks of already collected probes; no labels enter the U kernel."""
import json

from local.harness.output_protocol import OutputVerifier, PREFIX

VERSION = 'full-corpus-verdict-v1'


def probe_verdict(qid, cases, outcomes):
    if not cases or len(cases) != len(outcomes):
        raise ValueError('探测输入或执行记录缺失，不能给出完整正确性判定')
    checker = OutputVerifier(qid, cases)
    result = None
    for i, (case, outcome) in enumerate(zip(cases, outcomes)):
        if outcome.get('kind') != 'value':
            status = outcome.get('status')
            if status not in ('Wrong Answer', 'Compile Error', 'Runtime Error', 'Time Limit Exceeded', 'Memory Limit Exceeded'):
                raise ValueError('探测执行证据不完整，不能转换为代码错误')
            result = checker.finish(1, execution_failure=status)
            break
        if 'value' not in outcome:
            raise ValueError('探测记录缺少实际输出')
        values = outcome['value'] if 'ops' in case else [outcome['value']]
        if 'ops' in case and (not isinstance(values, list) or len(values) != len(case['ops'])):
            raise ValueError('设计题探测操作记录不完整')
        for op, value in enumerate(values):
            result = checker.feed(PREFIX + json.dumps({'case': i, 'op': op, 'value': value}, ensure_ascii=False, allow_nan=False))
            if result:
                break
        if result:
            break
    result = result or checker.finish(0)
    return {'state': 'SUCCESS', 'ac_status': result.status, 'total_testcases': len(cases),
            'total_correct': result.total_correct, 'detail': result.detail,
            'source': 'host_check_of_frozen_probe_outputs'}


def combine(validation, probes):
    if validation.get('state') != 'SUCCESS' or probes.get('state') != 'SUCCESS':
        raise ValueError('完整语料判定需要两组完整证据')
    passed_validation = validation['ac_status'] == 'Accepted'
    return {'state': 'SUCCESS', 'ac_status': probes['ac_status'] if passed_validation else validation['ac_status'],
            'total_testcases': validation['total_testcases'] + probes['total_testcases'],
            'total_correct': validation['total_correct'] + (probes['total_correct'] if passed_validation else 0),
            'correctness_order': 'validation_then_probes', 'version': VERSION}
