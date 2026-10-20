"""Private loopback service, reached through the dashboard's same-origin proxy."""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sqlite3
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, parse_qs

from local.common import LANGS, KEY_TO_LABEL
from local.lab.jobs import Engine, validate_spec, title_value
from local.lab.storage import Store, LabError
from local.lab.comparison import compare
from local.lab.catalog import catalog

_CATALOG_CACHE = {"at": 0.0, "payload": None}
_CATALOG_TTL = 60.0
_CATALOG_LOCK = threading.Lock()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, benchmark_db, token):
        super().__init__(address, Handler)
        self.store = store
        self.engine = Engine(store)
        self.benchmark_db = benchmark_db
        self.token = token


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Request URLs/bodies and credentials must not enter logs.

    def send_json(self, status, data):
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        if status >= 400:
            self.send_header('Connection', 'close')
            self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_html(self, status, text):
        payload = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        # Defence in depth: the report is inert even if an escape is ever missed.
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise LabError('请求必须使用 application/json', 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise LabError('请求长度无效') from None
        if not 0 < length <= 1024 * 1024:
            raise LabError('请求正文为空或超过 1MB', 413)
        try:
            result = json.loads(self.rfile.read(length), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        except (ValueError, UnicodeError):
            raise LabError('JSON 请求无效') from None
        if not isinstance(result, dict):
            raise LabError('JSON 正文应为对象')
        return result

    def dispatch(self):
        try:
            supplied = self.headers.get('X-Lab-Token', '')
            if not supplied or not hmac.compare_digest(supplied, self.server.token):
                raise LabError('服务仅接受仪表盘代理请求', 403)
            url = urlsplit(self.path)
            path = url.path.removeprefix('/api/v1/lab').strip('/')
            parts = path.split('/')
            method = self.command
            store = self.server.store
            # Consume every action body, including run/cancel/clone. Leaving '{}'
            # unread corrupts the next request on the proxy's keep-alive connection.
            payload = self.body() if int(self.headers.get('Content-Length', '0')) > 0 else {}
            # The only caller holding the private worker token is the Go ingress,
            # which strips any browser-supplied identity and then sets this header
            # from the authenticated session. A browser cannot reach this point.
            operator = (self.headers.get('X-Operator') or '').strip()[:64]
            if path == 'health' and method == 'GET':
                self.send_json(200, {'status': 'ready', 'metric': 'code-mue-v1-spec-normalized',
                                     'languages': [{'key': l, 'label': KEY_TO_LABEL[l]} for l in LANGS]})
                return
            if path == 'shutdown' and method == 'POST':
                self.send_json(200, {'status': 'stopping'})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == 'catalog' and method == 'GET':
                now = time.monotonic()
                with _CATALOG_LOCK:
                    cached = _CATALOG_CACHE['payload']
                    if cached is not None and now - _CATALOG_CACHE['at'] < _CATALOG_TTL:
                        payload = cached
                    else:
                        payload = catalog()
                        _CATALOG_CACHE['payload'] = payload
                        _CATALOG_CACHE['at'] = now
                self.send_json(200, payload)
                return
            if path == 'sources' and method == 'GET':
                from local.lab.workflow import sources
                query=parse_qs(url.query)
                try:qid=int(query.get('qid',[''])[0])
                except ValueError:raise LabError('请选择题目') from None
                self.send_json(200,{'data':sources(store,qid,query.get('language',[None])[0])})
                return
            if parts[0] == 'models':
                ident = parts[1] if len(parts) == 2 else None
                if path == 'models' and method == 'GET':
                    self.send_json(200, {'data': store.profiles()})
                elif path == 'models' and method == 'POST':
                    self.send_json(201, store.save_profile(payload))
                elif ident and method == 'GET':
                    self.send_json(200, store.profile(ident))
                elif ident and method in ('PUT', 'PATCH'):
                    self.send_json(200, store.save_profile(payload, ident))
                elif ident and method == 'DELETE':
                    store.delete_profile(ident)
                    self.send_json(200, {'deleted': True})
                else:
                    raise LabError('接口不存在', 404)
                return
            if parts[0] == 'jobs':
                ident = parts[1] if len(parts) >= 2 else None
                action = parts[2] if len(parts) == 3 else None
                if path == 'jobs' and method == 'GET':
                    query = parse_qs(url.query)
                    keyword = query.get('q', [''])[0]
                    state_filter = query.get('state', [''])[0]
                    limit = max(1, min(200, int(query.get('limit', ['20'])[0] or 20)))
                    offset = max(0, int(query.get('offset', ['0'])[0] or 0))
                    self.send_json(200, {'data': store.jobs(keyword, state_filter, limit, offset),
                                         'total': store.jobs_total(keyword, state_filter)})
                elif path == 'jobs' and method == 'POST':
                    body = payload
                    spec = validate_spec(body.get('spec', {}), store)
                    if operator:
                        spec = dict(spec, operator=operator)
                    self.send_json(201, store.create_job(title_value(body.get('title')), spec))
                elif ident and not action and method == 'GET':
                    self.send_json(200, store.job(ident))
                elif ident and action == 'compare' and method == 'GET':
                    query = parse_qs(url.query)
                    try:
                        indices = [int(query[k][0]) for k in ('group', 'left', 'right')]
                    except (KeyError, ValueError):
                        raise LabError('请选择候选组、行和列') from None
                    self.send_json(200, compare(store.job(ident), *indices))
                elif ident and not action and method in ('PUT', 'PATCH'):
                    body = payload
                    if 'spec' in body:
                        from local.lab import workflow
                        spec=(workflow.validate_update(body['spec'],store,ident) if body['spec'].get('workflow_version')==workflow.VERSION
                              else validate_spec(body['spec'],store))
                    else:spec=None
                    self.send_json(200, store.update_job(ident, title_value(body.get('title')), spec))
                elif ident and not action and method == 'DELETE':
                    store.delete_job(ident)
                    self.send_json(200, {'deleted': True})
                elif ident and action == 'run' and method == 'POST':
                    self.send_json(202, self.server.engine.start(ident))
                elif ident and action == 'cancel' and method == 'POST':
                    self.send_json(202, self.server.engine.cancel(ident))
                elif ident and action == 'resume' and method == 'POST':
                    from local.lab import resume
                    parent = store.job(ident, include_deleted=True)
                    spec, summary = resume.prepare(parent, payload)
                    if operator:
                        spec = dict(spec, operator=operator)
                    job, created = store.create_job_once(resume.title_for(spec, summary), spec)
                    self.send_json(201 if created else 200, {**job, 'resume_summary': summary})
                elif ident and action == 'report' and method == 'GET':
                    query = parse_qs(url.query)
                    if query.get('format', ['html'])[0] != 'html':
                        raise LabError('报告只支持 format=html；结构化数据请使用 JSON 导出')
                    from local.lab import report
                    job = store.job(ident, include_deleted=True)
                    children = [row['id'] for row in store.jobs()
                                if (row.get('spec') or {}).get('parent_job_id') == ident]
                    advisories = [str(item) for item in (job.get('evidence_advisories') or [])]
                    self.send_html(200, report.render(job, lang=query.get('lang', ['en'])[0],
                                                      children=children, advisories=advisories))
                elif ident and action == 'rejudge' and method == 'POST':
                    from local.lab import rejudge
                    # Server-side evidence only; a soft-deleted parent stays readable.
                    parent = store.job(ident, include_deleted=True)
                    spec = rejudge.prepare(parent, payload)
                    if operator:
                        spec = dict(spec, operator=operator)
                    job, created = store.create_job_once(rejudge.title_for(spec), spec)
                    self.send_json(201 if created else 200, job)
                elif ident and action == 'clone' and method == 'POST':
                    job = store.job(ident)
                    legacy = dict(job['spec'])
                    legacy.setdefault('probe_strategy', 'hash')
                    legacy.setdefault('metamorphic_checks', False)
                    spec = validate_spec(legacy, store, trusted_snapshots=True)
                    self.send_json(201, store.create_job(title_value(job['title'][:114] + ' · 副本'), spec))
                else:
                    raise LabError('接口不存在', 404)
                return
            raise LabError('接口不存在', 404)
        except LabError as error:
            self.send_json(error.status, {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except (sqlite3.Error, OSError):
            self.send_json(500, {'error': '本地数据服务不可用，请检查数据库和目录权限'})
        except Exception:
            self.send_json(500, {'error': '服务处理失败，请检查任务参数和服务状态'})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = dispatch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--benchmark-db', type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get('MCIBENCH_LAB_TOKEN', '')
    if not token:
        raise SystemExit('MCIBENCH_LAB_TOKEN is required')
    server = Server(('127.0.0.1', args.port), Store(args.data.resolve()), args.benchmark_db.resolve(), token)
    print(json.dumps({'port': server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.engine.close()
        server.server_close()


if __name__ == '__main__':
    main()
