"""OpenAI-compatible chat completions with private server-side credentials."""
from __future__ import annotations

import json
import re
import hashlib
import math
import ssl
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from local.common import KEY_TO_LABEL, DESCRIPTIONS_DIR, load_snippet
from local.lab.behavior import sha
from local.lab import source_guard
source_guard.register(__file__)
from local.lab.diagnostics import redact, response_preview

DIAGNOSTICS_VERSION = 'generation-diagnostics-v2'
MAX_RESPONSE = 4 * 1024 * 1024
RESPONSE_BUDGET_S = 90
RETRY_HTTP = {408, 429, 500, 502, 503, 504}


class GenerationError(RuntimeError):
    def __init__(self, message, *, code, suggestion, attempts, retryable=False):
        super().__init__(message)
        self.code = code
        self.suggestion = suggestion
        self.attempts = attempts
        self.retryable = retryable


class _CancelledCall(Exception):
    def __init__(self, cause):
        self.cause = cause


def _read_response(response, payload, deadline, *, check_cancel=None, on_progress=None):
    """Retain partial bytes and bound the complete body, including keepalive drips.

    urllib's timeout is per socket operation; a peer sending spaces can otherwise
    keep read(n) alive indefinitely. DNS/connect/headers retain urllib's timeout.
    """
    def cancel():
        if check_cancel:
            try:
                check_cancel()
            except Exception as error:
                raise _CancelledCall(error) from None
    while len(payload) <= MAX_RESPONSE:
        cancel()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('response body budget exhausted')
        connection = response
        for _ in range(5):
            if hasattr(connection, '_sock'):
                connection = connection._sock
                break
            connection = getattr(connection, 'raw', None) or getattr(connection, 'fp', None)
            if connection is None:
                break
        if connection is not None:
            connection.settimeout(remaining)
        read = getattr(response, 'read1', None) or response.read
        chunk = read(min(65536, MAX_RESPONSE + 1 - len(payload)))
        if not chunk:
            return
        payload.extend(chunk)
        if on_progress:
            on_progress({'received_bytes': len(payload), 'remaining_seconds': max(0., deadline-time.monotonic()),
                         'only_whitespace_so_far': not payload.strip()})
        cancel()


def _classification(status):
    if status == 401:
        return 'authentication', '模型 API 认证失败（HTTP 401）', '在模型配置中检查密钥及 API 地址，认证失败不会自动重试。'
    if status == 403:
        return 'permission', '模型 API 拒绝访问（HTTP 403）', '检查该密钥是否有目标模型的访问权限。'
    if status == 429:
        return 'rate_limit', '模型 API 请求受限（HTTP 429）', '等待接口限流恢复，并检查额度；可以稍后复制任务重试。'
    if status in RETRY_HTTP:
        return 'provider_unavailable', f'模型 API 暂时不可用（HTTP {status}）', '已按限制重试；稍后复制任务重试，或检查模型服务状态。'
    return 'request_rejected', f'模型 API 拒绝请求（HTTP {status}）', '检查 API 路径、接口模型名和请求参数；查看已脱敏的响应。'


def _retry_delay(headers, attempt):
    value = headers.get('Retry-After') if headers else None
    if value is not None:
        try:
            delay = float(value)
        except ValueError:
            from email.utils import parsedate_to_datetime
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return min(2 ** (attempt - 1), 4)
        # Do not retry earlier than requested, or block this worker indefinitely.
        return max(0., delay) if math.isfinite(delay) and delay <= 10 else None
    return min(2 ** (attempt - 1), 4)


def _wait(delay, check_cancel):
    remaining = delay
    while remaining > 0:
        if check_cancel:
            check_cancel()
        step = min(remaining, .2)
        time.sleep(step)
        remaining -= step


def _content(message):
    raw = message.get('content')
    if isinstance(raw, list) and all(isinstance(p, dict) and p.get('type') == 'text' and isinstance(p.get('text'), str) for p in raw):
        raw = ''.join(p['text'] for p in raw)
    return raw


def thinking_control(profile, endpoint):
    enabled = profile.get('enable_thinking')
    if enabled is None:
        return {}
    parameter = profile.get('thinking_parameter', 'auto')
    if parameter == 'auto':
        parameter = 'thinking' if urlsplit(endpoint).hostname == 'api.deepseek.com' else 'enable_thinking'
    if parameter == 'thinking':
        return {'thinking': {'type': 'enabled' if enabled else 'disabled'}}
    if parameter == 'enable_thinking':
        return {'enable_thinking': enabled}
    raise ValueError('unsupported thinking parameter')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def prompt_for(qid, language, *, source_language=None, source_code=None):
    folder = DESCRIPTIONS_DIR / str(qid)
    files = sorted(folder.glob('*English*.txt')) or sorted(folder.glob('*.txt'))
    if not files:
        raise ValueError(f'q{qid} 缺少题面')
    description = files[0].read_text(encoding='utf-8')
    snippet = load_snippet(qid, language)
    lead = f'Solve the following programming problem in {KEY_TO_LABEL[language]}.'
    if source_language:
        lead = f'Translate the following {KEY_TO_LABEL[source_language]} solution to {KEY_TO_LABEL[language]}, preserving its behavior.'
    prompt = f'{lead}\nReturn only complete code matching the target interface. No explanation or main function.\n\nProblem:\n{description}\n\nTarget interface:\n{snippet}'
    if source_code is not None:
        prompt += '\n\nSource solution:\n' + source_code
    return prompt


def clean_code(raw):
    # Only unwrap a complete Markdown fence; never rewrite indentation or logic.
    match = re.fullmatch(r'\s*```[^\n]*\n(.*?)\n```\s*', raw, re.S)
    return match.group(1) if match else raw.strip('\r\n')


def generate(profile, prompt, temperature, *, on_attempt=None, check_cancel=None, max_attempts=3, on_progress=None, purpose='solution'):
    source_guard.check()
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError('max_attempts must be between 1 and 3')
    if purpose not in ('solution', 'test_inputs', 'contract', 'adapter', 'gate_mutation', 'validator'):
        raise ValueError('unknown generation purpose')
    endpoint = profile['api_url'].rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'
    systems={
        'solution':'You are a programming assistant. Return executable solution code only.',
        'test_inputs':'You design valid programming test inputs. Return only the requested JSON. Never provide expected answers or executable code.',
        'contract':'Normalize only the supplied public problem examples. Return the exact requested JSON schema; do not solve the problem or invent example values.',
        'adapter':'Write only the requested JSON invocation/serialization adapter. Do not implement the solution algorithm or fabricate outputs.',
        'gate_mutation':'Create an intentionally functionally incorrect but compiling and terminating test-only implementation as requested. This is a mutation-testing fixture, not a correct solution. Return only code.',
        'validator':'Write only a Python input-constraint validator. It must return exactly True or False for one input object. Never solve the programming task or return its answer, traversal, counts, arrays or strings. Check legality only.',
    }
    body = {'model': profile['model_name'], 'messages': [
        {'role': 'system', 'content':systems[purpose]},
        {'role': 'user', 'content': prompt}], 'temperature': temperature,
        'max_tokens': profile['max_tokens'], 'stream': False}
    body.update(thinking_control(profile, endpoint))
    headers = {'Content-Type': 'application/json'}
    if profile.get('api_key'):
        headers['Authorization'] = 'Bearer ' + profile['api_key']
    opener = build_opener(ProxyHandler({}), NoRedirect())
    attempts = []
    secrets = (profile.get('api_key', ''),)
    for number in range(1, max_attempts + 1):
        if check_cancel:
            check_cancel()
        started = time.monotonic()
        record = {'attempt': number, 'purpose': purpose, 'started_at': datetime.now(timezone.utc).isoformat(),
                  'request': {'endpoint': endpoint, 'model': profile['model_name'],
                              'temperature': temperature, 'max_tokens': profile['max_tokens'],
                              'enable_thinking': profile.get('enable_thinking'), 'prompt_sha256': sha(prompt)},
                  'http_status': None, 'finish_reason': None, 'usage': {},
                  'content_chars': 0, 'reasoning_chars': 0, 'retry_scheduled': False}
        record['request']['thinking_control'] = thinking_control(profile, endpoint)
        payload = bytearray()
        cancelled = None
        response_headers = None
        retryable = False
        prediction = None
        code, message, suggestion = 'invalid_response', '模型 API 响应格式无效', '需要兼容 chat/completions 接口；查看已脱敏响应。'
        try:
            request = Request(endpoint, data=json.dumps(body).encode('utf-8'), headers=headers, method='POST')
            with opener.open(request, timeout=RESPONSE_BUDGET_S) as response:
                record['http_status'] = response.status
                response_headers = response.headers
                def progress(fields):
                    if on_progress:
                        on_progress({'attempt': number, 'http_status': record['http_status'],
                                     'elapsed_seconds': round(time.monotonic()-started, 2),
                                     'response_budget_seconds': RESPONSE_BUDGET_S, **fields})
                progress({'received_bytes': 0, 'only_whitespace_so_far': True, 'remaining_seconds': max(0., RESPONSE_BUDGET_S-(time.monotonic()-started))})
                _read_response(response, payload, started+RESPONSE_BUDGET_S,
                               check_cancel=check_cancel, on_progress=progress)
            if len(payload) > MAX_RESPONSE:
                code, message, suggestion = 'response_too_large', '模型返回内容超过 4MB', '检查模型接口是否返回异常内容；已保存有长度标记的响应摘录。'
            else:
                data = json.loads(payload, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                choice = data['choices'][0]
                model_message = choice['message']
                raw = _content(model_message)
                reasoning = model_message.get('reasoning_content', model_message.get('reasoning', ''))
                record.update(finish_reason=choice.get('finish_reason'), usage=redact(data.get('usage', {}), secrets),
                              content_chars=len(raw) if isinstance(raw, str) else 0,
                              reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0)
                if model_message.get('refusal') or choice.get('finish_reason') == 'content_filter':
                    code, message, suggestion = 'refusal', '模型未提供可执行代码（拒绝生成）', '查看已脱敏响应，核对题面与模型的生成限制。'
                elif not isinstance(raw, str) or not raw.strip():
                    if record['reasoning_chars'] and choice.get('finish_reason') == 'length':
                        code, message, suggestion = 'reasoning_budget_exhausted', '推理内容用尽输出预算，未返回代码', '复制任务后适当增大模型 max_tokens；模型支持时可关闭思考模式。采样配置不会自动改变。'
                    elif record['reasoning_chars']:
                        code, message, suggestion = 'reasoning_only', '模型只返回推理内容，未返回代码', '核对模型接口的内容字段和思考模式配置；查看已脱敏响应。'
                    else:
                        code, message, suggestion = 'empty_content', '模型没有返回代码文本', '核对停止原因、token 用量和响应字段；内容为空不会自动补造代码。'
                elif any(key and key in raw for key in secrets):
                    code, message, suggestion = 'credential_echo', '模型响应包含配置密钥，已阻止执行并脱敏', '检查服务是否错误回显请求；候选没有进入执行或正确性统计。'
                else:
                    cleaned = clean_code(raw)
                    if not cleaned.strip():
                        code, message, suggestion = 'empty_code', '模型返回了空代码块', '查看原始响应；空代码块不会进入执行或正确性统计。'
                    else:
                        prediction = {'raw': raw, 'code': cleaned, 'raw_sha256': sha(raw),
                                      'finish_reason': choice.get('finish_reason'), 'usage': redact(data.get('usage', {}), secrets)}
                        code, message, suggestion = 'ok', '已返回代码', ''
        except HTTPError as error:
            record['http_status'] = error.code
            response_headers = error.headers
            try:
                _read_response(error, payload, started+RESPONSE_BUDGET_S, check_cancel=check_cancel)
            except _CancelledCall as stopped:
                cancelled = stopped.cause
                record['response_read_failed'] = True
            except OSError:
                record['response_read_failed'] = True
            finally:
                error.close()
            code, message, suggestion = _classification(error.code)
            retryable = error.code in RETRY_HTTP
        except _CancelledCall as stopped:
            cancelled = stopped.cause
            record['response_read_failed'] = True
            code, message, suggestion = 'cancelled', '模型响应读取已取消', '保留已读取响应；未生成或补造代码。'
        except URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                code, message, suggestion = 'tls_verification', '模型 API 证书校验失败', '检查接口证书和地址；不会关闭证书校验或自动重试。'
            else:
                code, message, suggestion = 'connection', '模型 API 连接失败或超时', '检查 API 地址与网络；瞬时连接失败会有限重试。'
                retryable = True
        except TimeoutError:
            record['response_read_failed'] = True
            code, message, suggestion = 'timeout', '模型 API 调用超时', '检查模型服务状态；超时会有限重试。'
            retryable = True
        except OSError:
            record['response_read_failed'] = True
            code, message, suggestion = 'connection', '读取模型响应时连接中断', '模型服务连接中断，会有限重试；原请求参数保持不变。'
            retryable = True
        except (KeyError, IndexError, TypeError, AttributeError, ValueError, RecursionError):
            pass  # Keep the invalid-response classification and captured response.
        if cancelled is not None:
            retryable = False
            code, message, suggestion = 'cancelled', '模型响应读取已取消', '保留已读取响应；未生成或补造代码。'
        record.update(duration_ms=round((time.monotonic() - started) * 1000, 2),
                      code=code, message=message, suggestion=suggestion, retryable=retryable,
                      response_bytes=len(payload), response_sha256=hashlib.sha256(payload).hexdigest(),
                      request_id=redact(response_headers.get('X-Request-ID') or response_headers.get('Request-ID'), secrets) if response_headers else None)
        declared = response_headers.get('Content-Length', '') if response_headers else ''
        record['response_declared_bytes'] = int(declared) if declared.isdigit() else None
        record['response_read_complete'] = record['http_status'] is not None and not record.get('response_read_failed') and len(payload) <= MAX_RESPONSE
        record.update(response_preview(payload, secrets))
        delay = _retry_delay(response_headers, number) if retryable and number < max_attempts else None
        record.update(retry_scheduled=delay is not None, retry_delay_seconds=delay)
        attempts.append(record)
        if on_attempt:
            on_attempt(redact(record, secrets))
        if cancelled is not None:
            raise cancelled
        if check_cancel:
            check_cancel()
        if prediction is not None:
            prediction['generation'] = {'version': DIAGNOSTICS_VERSION, 'attempts': redact(attempts, secrets)}
            return prediction
        if delay is None:
            raise GenerationError(message, code=code, suggestion=suggestion, attempts=redact(attempts, secrets), retryable=retryable) from None
        _wait(delay, check_cancel)
    raise AssertionError('generation loop must return or raise')
