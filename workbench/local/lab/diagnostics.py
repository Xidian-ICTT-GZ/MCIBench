"""Credential-free provider evidence; never modify a submitted program."""
from __future__ import annotations

import json
import re


SENSITIVE_FIELDS = {'api_key', 'apikey', 'authorization', 'access_token', 'refresh_token',
                    'password', 'secret', 'client_secret'}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {redact(str(k), secrets): '[redacted]' if str(k).lower() in SENSITIVE_FIELDS else redact(v, secrets)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            value = value.replace(secret, '[redacted]')
            escaped = json.dumps(secret)[1:-1]
            value = value.replace(escaped, '[redacted]')
    value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [redacted]', value)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[redacted]', value)


def response_preview(payload, secrets=(), *, limit=256 * 1024):
    text = payload.decode('utf-8', errors='replace')
    try:
        safe = redact(json.loads(text), secrets)
        text = json.dumps(safe, ensure_ascii=False, indent=2, allow_nan=False)
    except (ValueError, RecursionError):
        text = redact(text, secrets)
    return {'response_body': text[:limit], 'response_capture_truncated': len(text) > limit,
            'response_capture_limit_chars': limit}
