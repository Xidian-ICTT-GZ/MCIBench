"""Separate persistent lab database; benchmark imports cannot replace it."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
from urllib.parse import urlparse
import uuid


class LabError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


ACTIVE = ('queued', 'generating', 'evaluating', 'cancelling')


class Store:
    def __init__(self, path):
        self.path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript('''
              CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, data TEXT NOT NULL, api_key TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, state TEXT NOT NULL, spec TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '{}', progress INTEGER NOT NULL DEFAULT 0,
                stage TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                request_key TEXT NOT NULL DEFAULT '');
            ''')
            columns = {row[1] for row in con.execute('PRAGMA table_info(jobs)')}
            if 'request_key' not in columns:
                con.execute("ALTER TABLE jobs ADD COLUMN request_key TEXT NOT NULL DEFAULT ''")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS jobs_request_key "
                        "ON jobs(request_key) WHERE request_key != ''")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        try:
            with con:
                yield con
        finally:
            con.close()

    def profiles(self):
        with self.connect() as con:
            return [self.public_profile(r) for r in con.execute('SELECT * FROM profiles ORDER BY created_at')]

    def public_profile(self, row):
        data = json.loads(row['data'])
        data.setdefault('thinking_parameter', 'auto')
        data.update(id=row['id'], created_at=row['created_at'], updated_at=row['updated_at'],
                    credential_configured=bool(row['api_key'] or (data.get('key_env') and os.environ.get(data['key_env']))))
        return data

    def profile(self, ident, *, private=False):
        with self.connect() as con:
            row = con.execute('SELECT * FROM profiles WHERE id=?', (ident,)).fetchone()
        if not row:
            raise LabError('模型配置不存在', 404)
        data = self.public_profile(row)
        if private:
            data['api_key'] = row['api_key'] or os.environ.get(data.get('key_env', ''), '')
        return data

    def in_use(self, ident, con):
        for row in con.execute("SELECT spec FROM jobs WHERE deleted=0 AND state IN ('queued','generating','evaluating','cancelling')"):
            if ident in json.loads(row['spec'])['model_ids']:
                return True
        return False

    def save_profile(self, payload, ident=None):
        old = self.profile(ident, private=True) if ident else {}
        allowed = ('name', 'model_name', 'api_url', 'key_env', 'enabled', 'enable_thinking', 'max_tokens', 'thinking_parameter')
        data = {k: payload.get(k, old.get(k)) for k in allowed}
        for field in ('name', 'model_name', 'api_url'):
            if not isinstance(data[field], str) or not data[field].strip() or len(data[field]) > 500:
                raise LabError(f'{field} 必须为非空字符串')
            data[field] = data[field].strip()
        url = urlparse(data['api_url'])
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise LabError('API 地址必须是无账号、查询参数的 HTTP(S) 地址')
        if url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise LabError('远程模型 API 必须使用 HTTPS')
        data['key_env'] = data['key_env'] or ''
        if not isinstance(data['key_env'], str) or (data['key_env'] and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', data['key_env'])):
            raise LabError('密钥环境变量名称无效')
        data['enabled'] = True if data['enabled'] is None else data['enabled']
        if type(data['enabled']) is not bool or (data['enable_thinking'] is not None and type(data['enable_thinking']) is not bool):
            raise LabError('enabled / enable_thinking 必须是布尔值')
        data['thinking_parameter'] = 'auto' if data['thinking_parameter'] is None else data['thinking_parameter']
        if not isinstance(data['thinking_parameter'], str) or data['thinking_parameter'] not in ('auto', 'thinking', 'enable_thinking'):
            raise LabError('思考参数格式必须为 auto、thinking 或 enable_thinking')
        data['max_tokens'] = 4096 if data['max_tokens'] is None else data['max_tokens']
        if type(data['max_tokens']) is not int or not 128 <= data['max_tokens'] <= 16384:
            raise LabError('max_tokens 必须在 128–16384 之间')
        key = payload.get('api_key', '')
        if not isinstance(key, str) or len(key) > 8192:
            raise LabError('API 密钥格式无效')
        # Empty password means preserve; an explicit flag clears it.
        saved_key = ''
        if ident:
            with self.connect() as con:
                saved_key = con.execute('SELECT api_key FROM profiles WHERE id=?', (ident,)).fetchone()['api_key']
        key = '' if payload.get('clear_api_key') else (key.strip() or saved_key)
        ident = ident or uuid.uuid4().hex
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if self.in_use(ident, con):
                raise LabError('模型正在被任务使用，完成或取消任务后再修改', 409)
            con.execute('''INSERT INTO profiles VALUES (?,?,?,?,?)
                           ON CONFLICT(id) DO UPDATE SET data=excluded.data,api_key=excluded.api_key,updated_at=excluded.updated_at''',
                        (ident, json.dumps(data, ensure_ascii=False), key, old.get('created_at', now()), now()))
        return self.profile(ident)

    def delete_profile(self, ident):
        self.profile(ident)
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if self.in_use(ident, con):
                raise LabError('模型正在被任务使用', 409)
            con.execute('DELETE FROM profiles WHERE id=?', (ident,))

    def jobs(self, query='', state='', limit=100, offset=0):
        with self.connect() as con:
            rows = con.execute('''SELECT * FROM jobs WHERE deleted=0 AND title LIKE ? AND (?='' OR state=?)
                                  ORDER BY created_at DESC LIMIT ? OFFSET ?''',
                               ('%' + query + '%', state, state, int(limit), int(offset))).fetchall()
        return [self.job_row(r, detail=False) for r in rows]

    def jobs_total(self, query='', state=''):
        with self.connect() as con:
            row = con.execute('''SELECT COUNT(*) FROM jobs WHERE deleted=0 AND title LIKE ? AND (?='' OR state=?)''',
                              ('%' + query + '%', state, state)).fetchone()
        return int(row[0])

    def job_row(self, row, *, detail=True):
        result = dict(row)
        result['spec'] = json.loads(result['spec'])
        if detail:
            result['result'] = json.loads(result['result'])
            from local.lab.selection import decorate_job
            decorate_job(result)
            from local.lab.evidence_advisories import for_job
            advisories=for_job(result)
            if advisories:result['evidence_advisories']=advisories
        else:
            result.pop('result')
        result.pop('deleted')
        return result

    def job(self, ident, *, include_deleted=False):
        with self.connect() as con:
            row = con.execute('SELECT * FROM jobs WHERE id=? AND (? OR deleted=0)',
                              (ident, 1 if include_deleted else 0)).fetchone()
        if not row:
            raise LabError('评测任务不存在', 404)
        return self.job_row(row)

    # A finished-but-dead attempt must not permanently own its key. Only these
    # states count as "this request is already handled"; failed, cancelled and
    # soft-deleted rows yield to a new round.
    REUSABLE = ('draft', 'queued', 'generating', 'evaluating', 'cancelling', 'completed')

    def create_job_once(self, title, spec):
        """Atomic, single-operation idempotency.

        Returns (job, created). A concurrent duplicate of the *same* operation
        returns the existing job. A new round of the same operation (after a
        failure, a cancellation or a soft delete) gets a fresh key suffix, so a
        dead attempt can never make the candidate permanently untestable.
        """
        spec = dict(spec or {})
        base = str(spec.get('request_key') or '')
        existing = created = None
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for attempt in range(1, 33):
                key = base if attempt == 1 else '%s#%d' % (base, attempt)
                row = con.execute('SELECT id, state, deleted FROM jobs WHERE request_key=?', (key,)).fetchone()
                if row is not None:
                    if row['deleted'] == 0 and row['state'] in self.REUSABLE:
                        existing = row['id']
                        break
                    continue                     # dead attempt: move to the next round
                payload = dict(spec, request_key=key)
                ident = uuid.uuid4().hex
                try:
                    con.execute('INSERT INTO jobs (id,title,state,spec,created_at,updated_at,request_key)'
                                ' VALUES (?,?,?,?,?,?,?)',
                                (ident, title, 'draft', json.dumps(payload, ensure_ascii=False),
                                 now(), now(), key))
                except sqlite3.IntegrityError:
                    continue
                created = ident
                break
        # Read back only after the transaction committed, otherwise a second
        # connection cannot see the new row.
        if existing is not None:
            return self.job(existing), False
        if created is not None:
            return self.job(created), True
        raise LabError('同一请求已存在过多轮次，无法创建新任务', 409)

    def find_by_request_key(self, key):
        """Idempotency guard: a double click must not create two identical children."""
        if not key:
            return None
        with self.connect() as con:
            rows = con.execute("SELECT * FROM jobs WHERE deleted=0 AND state NOT IN ('cancelled','failed')"
                               " ORDER BY created_at DESC LIMIT 200").fetchall()
        for row in rows:
            try:
                if json.loads(row['spec']).get('request_key') == key:
                    return self.job_row(row)
            except (ValueError, TypeError):
                continue
        return None

    def create_job(self, title, spec):
        ident = uuid.uuid4().hex
        with self.connect() as con:
            con.execute('INSERT INTO jobs (id,title,state,spec,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                        (ident, title, 'draft', json.dumps(spec, ensure_ascii=False), now(), now()))
        return self.job(ident)

    def update_job(self, ident, title, spec=None):
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT state FROM jobs WHERE id=? AND deleted=0', (ident,)).fetchone()
            if not row:
                raise LabError('评测任务不存在', 404)
            if row['state'] in ACTIVE:
                raise LabError('运行中的任务不能修改', 409)
            if spec is not None and row['state'] != 'draft':
                raise LabError('已运行任务只能改名称；修改参数请复制为新任务', 409)
            if spec is None:
                con.execute('UPDATE jobs SET title=?,updated_at=? WHERE id=?', (title, now(), ident))
            else:
                con.execute('UPDATE jobs SET title=?,spec=?,updated_at=? WHERE id=?',
                            (title, json.dumps(spec, ensure_ascii=False), now(), ident))
        return self.job(ident)

    def delete_job(self, ident):
        with self.connect() as con:
            cursor = con.execute("UPDATE jobs SET deleted=1,updated_at=? WHERE id=? AND deleted=0 AND state NOT IN ('queued','generating','evaluating','cancelling')", (now(), ident))
            if cursor.rowcount != 1:
                self.job(ident)
                raise LabError('请先取消正在运行的任务', 409)

    def write_job(self, ident, **fields):
        allowed = {'state', 'stage', 'progress', 'error', 'result'}
        if set(fields) - allowed:
            raise ValueError('invalid job update')
        if 'result' in fields:
            fields['result'] = json.dumps(fields['result'], ensure_ascii=False, allow_nan=False)
        fields['updated_at'] = now()
        with self.connect() as con:
            con.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=? AND deleted=0',
                        (*fields.values(), ident))

    def queue(self, ident):
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT state,spec FROM jobs WHERE id=? AND deleted=0', (ident,)).fetchone()
            if not row:
                raise LabError('任务不存在', 404)
            if row['state'] != 'draft':
                raise LabError('只有草稿可运行；再次运行请复制任务', 409)
            for model_id in json.loads(row['spec'])['model_ids']:
                model = con.execute('SELECT data FROM profiles WHERE id=?', (model_id,)).fetchone()
                if not model or not json.loads(model['data'])['enabled']:
                    raise LabError('所选模型配置已删除或禁用')
            con.execute("UPDATE jobs SET state='queued',stage='等待执行',updated_at=? WHERE id=?", (now(), ident))

    def recover(self):
        with self.connect() as con:
            con.execute("UPDATE jobs SET state='interrupted',stage='服务重启中断',error='服务重启；已有结果保留，可复制为新任务重试',updated_at=? WHERE state IN ('queued','generating','evaluating','cancelling')", (now(),))
