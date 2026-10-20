"""Input-only probes through the existing network-isolated judge adapters."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from local.common import load_snippet
from local.gen_testcases.constraints import check
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputCollector
from local.harness.render import extract_plain_entry, list_result_mode
from local.harness.runner import run_submission, InfrastructureError
from local.harness.typespec import parse_python_snippet, PlainSig
from local.lab.metrics import normalize_value, stable_json
from local.lab.probes import select


def sha(value):
    data = value.encode('utf-8') if isinstance(value, str) else stable_json(value).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def partition_cases(qid, cases, count, *, strategy='balanced', return_metadata=False):
    probes, validation, metadata = select(qid, cases, count, strategy=strategy)
    return (probes, validation, metadata) if return_metadata else (probes, validation)


def semantic_key(qid, sig, case, value):
    from local.harness import validators
    if isinstance(sig, PlainSig) and validators.has_validator(qid):
        namespace = {}
        exec(validators.helper('python3', qid), namespace)
        try:
            args = [case['args'][name] for name in validators.VALIDATOR_PARAMS[validators.ANSWER_VALIDATORS[qid]]]
            valid = bool(namespace['_valid'](value, *args))
        except (TypeError, ValueError, KeyError, IndexError, OverflowError):
            valid = False
        if valid:
            return 'specification_valid_output'
    # A design signature is an ordered sequence of operation results.
    mode = list_result_mode(qid) if isinstance(sig, PlainSig) else 'ordered'
    return stable_json(normalize_value(value, mode=mode))


def observe(qid, language, code, probe, *, backend='docker', timeout=5, executor=None):
    if backend != 'docker':
        raise ValueError('交互生成的代码只允许在 Docker 沙箱内执行')
    sig = parse_python_snippet(load_snippet(qid, 'python3'))
    entry = extract_plain_entry(language, load_snippet(qid, language)) if isinstance(sig, PlainSig) else {}
    case = deepcopy(probe)
    # OutputCollector constructs the operation plan; no answers reach the driver.
    case['expected'] = [None] * len(case['ops']) if 'ops' in case else None
    driver = render_output_driver(language, sig, entry, [case], code)
    collector = OutputCollector(qid, [case], signature=sig)
    try:
        result = (executor or run_submission)(language, driver, limit=1, backend='docker',
                                run_timeout_s=timeout, output_verifier=collector)
    except InfrastructureError:
        raise
    outcome = {'kind': 'failure', 'status': result.status,
               'runtime_ms': result.runtime_ms if result.runtime_available else None,
               'memory_mb': result.memory_mb if result.memory_available else None}
    if hasattr(result, 'phase_timing'):
        outcome['timing'] = result.phase_timing
    if result.status == 'Collected':
        value = collector.outputs[0]
        outcome.update(kind='value', value=value, semantic_key=semantic_key(qid, sig, probe, value))
    elif result.status == 'Compile Error':
        outcome['kind'] = 'compile_error'
    elif result.status == 'Time Limit Exceeded':
        outcome['kind'] = 'timeout'
    elif result.status == 'Runtime Error':
        outcome['kind'] = 'exception'
        # Only a recognized runtime diagnostic creates an exception consensus.
        patterns = [r'\b([A-Za-z_][\w.]*(?:Error|Exception))\s*:', r'\b(SIGSEGV|SIGABRT|SIGFPE)\b',
                    r'(?:panic|runtime error):\s*([^\n]{1,80})']
        for pattern in patterns:
            found = re.findall(pattern, result.stderr)
            if found:
                outcome['exception_type'] = found[-1]
                break
    return outcome
