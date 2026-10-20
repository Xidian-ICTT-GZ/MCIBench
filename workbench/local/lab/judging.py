"""Versioned lab-only correction for the legacy symmetric int32 filter.

The fixed historical judge remains unchanged. Only reviewed, fully representable
cases containing INT32_MIN qualify for an unfiltered host-checked replay.
"""
from __future__ import annotations

from pathlib import Path

from local import judge as legacy
from local.common import load_snippet
from local.gen_testcases.differential import _case_bytes, DRIVER_SIZE_BUDGET
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier
from local.harness.render import extract_plain_entry
from local.harness.runner import run_submission
from local.harness.typespec import PlainSig, parse_python_snippet
from local.lab import input_contracts as contracts
from local.lab.behavior import sha

VERSION = 'lab-int32-min-recheck-v1'


def fingerprint():
    return sha(Path(__file__).read_text(encoding='utf-8'))


def integers(value):
    if type(value) is int:
        yield value
    elif isinstance(value, (dict, list)):
        for child in value.values() if isinstance(value, dict) else value:
            yield from integers(child)


def judge_one(code_path, task, max_cases, backend, run_timeout_s=5, cases_override=None):
    out = legacy.judge_one(code_path, task, max_cases, backend, run_timeout_s, cases_override)
    dropped = out['_meta'].get('dropped_unrepresentable', 0)
    if not dropped or cases_override is None or backend != 'docker':
        return out
    qid, lang = out['_meta']['qid'], out['_meta']['lang']
    if qid not in contracts.QIDS:
        return out
    contracts.require(qid)
    values = list(integers(cases_override))
    if (not values or -2**31 not in values or any(not -2**31 <= n < 2**31 for n in values)
            or not all(contracts.valid(qid, c.get('args')) for c in cases_override)
            or sum(_case_bytes(c) for c in cases_override) > DRIVER_SIZE_BUDGET):
        return out  # Never turn a true overflow or an unreviewed input into an accepted literal.
    sig = parse_python_snippet(load_snippet(qid, 'python3'))
    if not isinstance(sig, PlainSig):
        return out
    source = code_path.read_text(encoding='utf-8')
    driver = render_output_driver(lang, sig, extract_plain_entry(lang, load_snippet(qid, lang)), cases_override, source)
    result = run_submission(lang, driver, limit=len(cases_override), backend='docker',
                            run_timeout_s=run_timeout_s, output_verifier=OutputVerifier(qid, cases_override, signature=sig))
    n = len(cases_override)
    out.update(state='SUCCESS', ac_status=result.status, total_testcases=n,
               total_correct=max(0, min(n, result.total_correct if result.total_correct is not None else n if result.status == 'Accepted' else 0)),
               runtime=f'{result.runtime_ms:.0f} ms' if result.runtime_available else '',
               memory=f'{result.memory_mb:.1f} MB' if result.memory_available else '')
    out['_meta'].update(dropped_unrepresentable=0, numeric_recheck={'version': VERSION, 'source_sha256': fingerprint(), 'legacy_dropped': dropped},
                        error=result.log[:500], execution_supervisor=result.supervisor_protocol,
                        timing={'runtime_ms': result.runtime_ms if result.runtime_available else None,
                                'memory_mb': result.memory_mb if result.memory_available else None,
                                'wall_ms': result.wall_ms, 'source': result.timing_source,
                                'scope': 'complete unfiltered lab replay; excludes compilation and ASan'})
    if out['_meta'].get('asan_required') and out['ac_status'] == 'Accepted':
        out['_meta']['asan_status'] = 'pending'
        legacy._confirm_asan(out, lang, driver, n, backend, run_timeout_s, qid=qid, cases=cases_override)
    return out
