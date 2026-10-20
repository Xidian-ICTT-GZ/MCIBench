"""Turn a rejected verdict into a usable counterexample.

The judge stops at the first failing case and reports only the count, so the
value the program actually produced has never been recorded. This re-executes
that single case with collection enabled, through the same entry, and stores the
observed output next to the expected one. If collection is impossible the record
says so instead of pretending the case is fully explained.
"""
from __future__ import annotations

VERSION = 'counterexample-v1'


def describe(run, cases, verdict):
    """Return {case, args, expected, actual, actual_source} or None if it passed.

    run(cases, collect=True) must execute through the same entry as the verdict.
    """
    if not isinstance(verdict, dict) or verdict.get('ac_status') == 'Accepted':
        return None
    index = verdict.get('total_correct')
    if type(index) is not int or not 0 <= index < len(cases):
        return None
    case = cases[index]
    record = {'version': VERSION, 'case': index + 1,
              'args': case.get('args'), 'expected': case.get('expected')}
    try:
        collected = run([case], collect=True)
    except Exception as error:                                     # noqa: BLE001 - evidence, not a verdict
        record.update(actual=None, actual_source='collection_failed',
                      actual_error='%s: %s' % (type(error).__name__, str(error)[:200]))
        return record
    outputs = (collected or {}).get('outputs') or []
    if outputs:
        record.update(actual=outputs[0], actual_source='collected',
                      actual_status=(collected or {}).get('ac_status'))
    else:
        # A crash or timeout produces no value at all; say that explicitly.
        record.update(actual=None, actual_source='not_collected',
                      actual_status=(collected or {}).get('ac_status'))
    return record
