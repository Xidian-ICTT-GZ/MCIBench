"""Shared validation for observed measurements in persisted evidence."""
import math
import json


def _reject_constant(value):
    raise ValueError('non-finite JSON constant: ' + value)


def load_evidence(text):
    return json.loads(text, parse_constant=_reject_constant)


def valid_measurement(value):
    if type(value) not in (int, float) or value < 0:
        return False
    # Integers are finite without conversion (which can overflow for corrupt data).
    return type(value) is int or math.isfinite(value)
