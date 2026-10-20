"""A fresh, full-corpus execution with one grading configuration, lab only."""
from copy import deepcopy
from pathlib import Path
import platform
from local.lab import judging
from local.lab.behavior import sha
from local.harness.identity import judge_source_closure

VERSION = 'full-corpus-executed-v2'
TIMEOUT = 5


def profile(image):
    return {'version': VERSION, 'image': image, 'host_python': platform.python_version(),
            'judge_closure': dict(judge_source_closure()), 'numeric_checker_sha256': judging.fingerprint(),
            'execution_checker_sha256': sha(Path(__file__).read_text(encoding='utf-8')),
            'run_timeout_s': TIMEOUT, 'case_order': 'frozen_corpus_order',
            'asan': 'required_for_accepted_c_and_cpp', 'truncation': False}


def run(path, cases, *, task='gen', check_cancel=lambda: None):
    if not cases:
        raise ValueError('完整复判需要非空冻结语料')
    declared = judging.legacy.parse_code_filename(path.name)
    if not declared:
        raise ValueError('完整复判源码名称无效')
    language = declared.get('tgt',declared.get('lang'))
    needs_asan = language in ('c','cpp')
    if needs_asan and not judging.legacy.ASAN_CONFIRM:
        raise ValueError('完整复判不允许关闭 ASan')
    check_cancel()
    result = judging.judge_one(path, task, len(cases), 'docker',
                               run_timeout_s=TIMEOUT, cases_override=deepcopy(cases))
    check_cancel()
    meta = result.get('_meta', {})
    if (result.get('state') != 'SUCCESS' or result.get('total_testcases') != len(cases)
            or meta.get('dropped_unrepresentable', 0)):
        raise ValueError('完整复判证据不完整：' + str(meta.get('error', result.get('state'))))
    correct = result.get('total_correct')
    if type(correct) is not int or not 0 <= correct <= len(cases):
        raise ValueError('完整复判计数无效')
    if result['ac_status'] == 'Accepted' and (correct != len(cases)
            or needs_asan and (meta.get('asan_required') is not True or meta.get('asan_status') != 'passed')
            or meta.get('asan_required') and meta.get('asan_status') != 'passed'):
        raise ValueError('完整复判缺少全部通过或 ASan 证据')
    result['version'] = VERSION
    result['cases_sha256'] = sha(cases)
    result['correctness_order'] = 'frozen_corpus_order'
    return result


def public_verdict(result):
    return {k: result[k] for k in ('state', 'ac_status', 'total_testcases', 'total_correct',
                                   'runtime', 'memory', 'version', 'cases_sha256', 'correctness_order')}
