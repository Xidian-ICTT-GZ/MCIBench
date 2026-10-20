"""Trusted, host-side checking of untrusted return-value records.

Expected values never need to be sent to the submission. This protocol is being
integrated across language adapters; it does not authenticate runtime telemetry.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from decimal import Decimal
from local.harness.typespec import Int, Float, Bool, Str, ListT, PlainSig, parse_python_snippet

PREFIX = 'MCIBENCH_OUTPUT_V1 '
PROTOCOL = 1


@dataclass(frozen=True)
class OutputVerdict:
    status: str
    total_correct: int
    failed_case: int | None = None
    detail: str = ''


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key')
        out[key] = value
    return out


def _nonfinite(value):
    raise ValueError('non-finite JSON number: ' + value)


def _typed_value(value, typ, depth=0):
    """Normalize the wire value without losing integer precision or bool identity."""
    if depth > 64:
        raise ValueError('output nesting limit exceeded')
    if typ is None:
        if value is not None:
            raise TypeError('void output must be null')
        return None
    if isinstance(typ, ListT):
        if type(value) is not list:
            raise TypeError('array output required')
        return [_typed_value(v, typ.inner, depth + 1) for v in value]
    if isinstance(typ, Int):
        if type(value) is int:
            return value
        if isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
            if value.adjusted() > 4300:
                raise ValueError('integer output exceeds protocol limit')
            return int(value)
        raise TypeError('integer output required; booleans are not integers')
    if isinstance(typ, Float):
        if type(value) not in (int, Decimal):
            raise TypeError('numeric output required')
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('non-finite output')
        return number
    if isinstance(typ, Bool) and type(value) is bool:
        return value
    if isinstance(typ, Str) and type(value) is str:
        return value
    raise TypeError('output does not match return signature')


class OutputVerifier:
    """Consume records in order; only the host can declare Accepted.

    A wrong answer is terminal immediately, preserving first-failure semantics
    even if the process later hangs or crashes. Runtime/compile failures before
    that remain failures. A successful exit without all records is not Accepted.
    """
    def __init__(self, qid: int, cases: list[dict], *, signature=None):
        from local.harness.render import _eqv_helper
        from local.harness import validators
        from local.common import load_snippet
        signature = signature or parse_python_snippet(load_snippet(qid, 'python3'))
        methods = {} if isinstance(signature, PlainSig) else {name: ret for name, _, ret in signature.methods}

        self.cases = deepcopy(cases)
        self.events = []
        self.position = 0
        self.completed = 0
        self.terminal = None
        namespace = {}
        # Only repository-owned checker source is executed, never submission text
        # or stdout. The host namespace is inaccessible to the sandboxed process.
        exec(_eqv_helper('python3', qid), namespace)
        self.equal = namespace['_eqv']
        self.validator = None
        if validators.has_validator(qid):
            exec(validators.helper('python3', qid), namespace)
            self.validator = namespace['_valid']
            self.validator_params = validators.VALIDATOR_PARAMS[validators.ANSWER_VALIDATORS[qid]]
        for case_index, case in enumerate(self.cases):
            if 'ops' in case:
                if not case['ops'] or len(case['ops']) != len(case['args']) or len(case['ops']) != len(case['expected']):
                    raise ValueError('invalid design-case operation matrix')
                for op_index, expected in enumerate(case['expected']):
                    op = case['ops'][op_index]
                    ret = None if op == signature.class_name else methods[op]
                    self.events.append((case_index, op_index, expected, op_index == len(case['ops']) - 1, ret))
            else:
                self.events.append((case_index, 0, case['expected'], True, signature.ret))
        if not self.events:
            raise ValueError('empty output plan cannot prove acceptance')

    def feed(self, line: str) -> OutputVerdict | None:
        if self.terminal is not None or not line.startswith(PREFIX):
            return self.terminal
        try:
            if len(line) > 16 * 1024 * 1024:
                raise ValueError('output record limit exceeded')
            event = json.loads(line[len(PREFIX):], object_pairs_hook=_object,
                               parse_constant=_nonfinite, parse_float=Decimal)
            if not isinstance(event, dict) or set(event) != {'case', 'op', 'value'}:
                raise ValueError('invalid output envelope')
            if type(event['case']) is not int or type(event['op']) is not int:
                raise ValueError('non-integer output position')
            if self.position >= len(self.events):
                raise ValueError('extra output record')
            case, op, expected, final_op, ret = self.events[self.position]
            if (event['case'], event['op']) != (case, op):
                raise ValueError('missing, duplicate or out-of-order output record')
            try:
                got = _typed_value(event['value'], ret)
            except TypeError:
                self.terminal = OutputVerdict('Wrong Answer', self.completed, case, 'return type mismatch')
                return self.terminal
            source = self.cases[case]
            if self.validator is not None and 'ops' not in source:
                try:
                    accepted = bool(self.validator(got, *(source['args'][p] for p in self.validator_params)))
                except (TypeError, ValueError, IndexError, KeyError, OverflowError):
                    accepted = False
            else:
                accepted = self.equal(got, expected)
            if not accepted:
                self.terminal = OutputVerdict('Wrong Answer', self.completed, case, 'host output comparison failed')
                return self.terminal
            self._record_value(case, op, got)
            self.position += 1
            if final_op:
                self.completed += 1
        except (ValueError, TypeError, RecursionError, OverflowError) as exc:
            self.terminal = OutputVerdict('Runtime Error', self.completed, detail='output protocol: ' + str(exc))
        return self.terminal

    def _record_value(self, case, op, value):
        pass

    def finish(self, exit_code: int, *, execution_failure: str | None = None) -> OutputVerdict:
        if self.terminal is not None:
            return self.terminal
        if execution_failure:
            return OutputVerdict(execution_failure, self.completed)
        if exit_code != 0:
            return OutputVerdict('Runtime Error', self.completed, detail=f'unexpected process exit {exit_code}')
        if self.position != len(self.events):
            return OutputVerdict('Runtime Error', self.completed, detail='output stream ended before all planned results')
        return OutputVerdict('Accepted', self.completed)


class OutputCollector(OutputVerifier):
    """Typed reference-output collection; never declares an answer Accepted.

    Values collected here are proposals for cross-language validation, not
    verification evidence. A missing or malformed operation invalidates the run.
    """
    def __init__(self, qid, cases, *, signature=None):
        plan = deepcopy(cases)
        for case in plan:
            case['expected'] = [None] * len(case['ops']) if 'ops' in case else None
        super().__init__(qid, plan, signature=signature)
        self.validator = None
        self.equal = lambda got, expected: True
        self.outputs = [[] if 'ops' in case else None for case in plan]

    def _record_value(self, case, op, value):
        if 'ops' in self.cases[case]:
            self.outputs[case].append(value)
        else:
            self.outputs[case] = value

    def finish(self, exit_code, *, execution_failure=None):
        result = super().finish(exit_code, execution_failure=execution_failure)
        if result.status == 'Accepted':
            return OutputVerdict('Collected', result.total_correct)
        return result
