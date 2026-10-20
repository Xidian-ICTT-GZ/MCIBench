"""Native MySQL lab execution, isolated from the historical eight-language judge.

PyMySQL owns the wire protocol and typed decoding. A byte-only Docker exec
bridge reaches loopback INSIDE a network-disabled disposable MySQL container;
no database port, host file, expected answer or judging code is exposed to SQL.
"""
from datetime import date, datetime, time as datetime_time, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time

from local.lab import source_guard

source_guard.register(__file__)
VERSION = 'native-mysql-isolated-v2'
CLIENT_SHA256 = 'e6b1d89711dd51f8f74b1631fe08f039e7d76cf67a42a323d3178f0f25762ed9'
CLIENT = Path(__file__).with_name('data')/'mysql_client/pymysql-1.1.2-py3-none-any.whl'
CONFIG = Path(__file__).with_name('data')/'mysql_runtime.json'
FLAGS = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
COLLATION = 'utf8mb4_0900_ai_ci'
SQL_MODE = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'


class SQLFailure(Exception):
    def __init__(self, message, status='Runtime Error'):
        super().__init__(message)
        self.status = status


def _docker(*args, timeout=20):
    try:
        r = subprocess.run(['docker', *args], capture_output=True, timeout=timeout, **FLAGS)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('MySQL infrastructure command incomplete: '+type(error).__name__) from None
    if r.returncode:
        raise ValueError('MySQL infrastructure: '+r.stderr.decode('utf8', 'replace')[-1200:])
    return r.stdout.decode('utf8', 'replace').strip()


def identity():
    try:
        row = json.loads(CONFIG.read_text(encoding='utf8'))
        image = row['image']
        if not re.fullmatch(r'docker\.io/library/mysql@sha256:[a-f0-9]{64}', image):
            raise ValueError('MySQL runtime must pin an official image digest')
        info = json.loads(_docker('image', 'inspect', image))[0]
        if image.removeprefix('docker.io/library/') not in info['RepoDigests']:
            raise ValueError('MySQL image digest mismatch')
        if not CLIENT.is_file() or hashlib.sha256(CLIENT.read_bytes()).hexdigest() != CLIENT_SHA256:
            raise ValueError('PyMySQL 1.1.2 wheel missing or fingerprint mismatch')
        source_guard.register(CONFIG)
        source_guard.register(CLIENT)
        return {'version': VERSION, 'image': image, 'image_id': info['Id'],
                'mysql_version': row['mysql_version'], 'client': 'PyMySQL 1.1.2',
                'client_sha256': CLIENT_SHA256, 'executor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'network': 'none', 'transport': 'docker_exec_loopback_socketpair',
                'sql_mode': SQL_MODE, 'collation': COLLATION, 'query_budget_seconds': 5,
                'div_precision_increment':4,'date_codec':'iso-date-and-reviewed-q607-mdy-v1',
                'schema_policy': 'statement_type_families_explicit_keys_v1',
                'limits': ['finite_tests_not_proof', 'unspecified_varchar_lengths_and_decimal_precision_inferred',
                           'leetcode_server_configuration_not_verified']}
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise ValueError('Native MySQL runtime is not prepared: '+type(error).__name__) from None


def _client():
    # Verify before import, including for long-lived workers.
    if not CLIENT.is_file() or hashlib.sha256(CLIENT.read_bytes()).hexdigest() != CLIENT_SHA256:
        raise ValueError('Verified PyMySQL wheel is missing')
    path = str(CLIENT)
    if path not in sys.path:
        sys.path.insert(0, path)
    import pymysql
    if not str(pymysql.__file__).startswith(path):
        raise ValueError('Unexpected MySQL client import origin')
    return pymysql


class _Bridge:
    """Socket timeouts remain real socket timeouts; threads only relay bytes."""
    def __init__(self, container):
        self.sock, self.relay = socket.socketpair()
        script = 'exec 3<>/dev/tcp/127.0.0.1/3306 || exit 1; cat <&3 & reader=$!; cat >&3; kill "$reader" 2>/dev/null; wait 2>/dev/null'
        self.proc = subprocess.Popen(['docker', 'exec', '-i', container, 'bash', '-c', script],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **FLAGS)
        self.threads = [threading.Thread(target=self._to_server, daemon=True),
                        threading.Thread(target=self._from_server, daemon=True)]
        for t in self.threads:
            t.start()

    def _to_server(self):
        try:
            while data := self.relay.recv(65536):
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try: self.proc.stdin.close()
            except (OSError, ValueError): pass

    def _from_server(self):
        try:
            while data := os.read(self.proc.stdout.fileno(), 65536):
                self.relay.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            try: self.relay.shutdown(socket.SHUT_WR)
            except OSError: pass

    def close(self):
        for s in (self.sock, self.relay):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            s.close()
        if self.proc.poll() is None:
            self.proc.terminate()
        try: self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        for t in self.threads:
            t.join(timeout=1)
        self.proc.stdout.close()


def quote(name):
    if type(name) is not str or not 1 <= len(name) <= 64 or '\x00' in name:
        raise ValueError('invalid MySQL identifier')
    return '`'+name.replace('`', '``')+'`'


def schema(qid, args):
    """Use actual statement type families; never infer TEXT by its values."""
    from local.lab import problem_io as io
    text = io.description(qid)
    declared = {}
    pattern=r'(?:Table\s*:\s*([A-Za-z_]\w*)|Table\s+([A-Za-z_]\w*)\s*:|SQL Schema\s*:\s*([A-Za-z_]\w*))\s*\n'
    for match in re.finditer(pattern, text, re.I):
        table = io.table(text[match.end():])
        name=next(group for group in match.groups() if group)
        declared[name.casefold()] = {str(r[0]).casefold(): str(r[1]).lower() for r in table['rows']}
    keys = io.sql_primary_keys(qid)
    definitions = []
    for name, table in args['tables'].items():
        columns = []
        native_types=[]
        notes = []
        for column in table['columns']:
            raw = declared.get(name.casefold(), {}).get(column.casefold())
            if raw is None:
                raise ValueError('Native MySQL column type has no statement evidence: '+name+'.'+column)
            if raw in ('int', 'integer', 'boolean'): native = 'INT'
            elif raw == 'bigint': native = 'BIGINT'
            elif raw == 'date': native = 'DATE'
            elif raw in ('datetime', 'timestamp'): native = raw.upper()
            elif raw in ('float', 'double'): native = raw.upper()
            elif raw.startswith(('decimal', 'numeric')):
                if re.fullmatch(r'(?:decimal|numeric)\(\d+,\s*\d+\)', raw): native = raw
                else:
                    native = 'DECIMAL(38,10)'
                    notes.append(column+': unspecified decimal precision uses DECIMAL(38,10)')
            elif raw == 'text': native = 'TEXT'
            elif raw.startswith(('varchar', 'char', 'enum')):
                if qid == 627 and column.casefold() == 'sex': native = "ENUM('m','f')"
                elif re.fullmatch(r'(?:var)?char\(\d+\)', raw): native = raw
                else:
                    native = 'VARCHAR(255)'
                    notes.append(column+': unspecified text/enum width uses VARCHAR(255)')
            else:
                raise ValueError('Unreviewed native MySQL type: '+raw)
            columns.append(quote(column)+' '+native)
            native_types.append(native)
        for key in keys:
            if key['table'].casefold() == name.casefold():
                columns.append('PRIMARY KEY ('+','.join(quote(c) for c in key['columns'])+')')
        definitions.append({'table': name, 'ddl': 'CREATE TABLE '+quote(name)+' ('+','.join(columns)+')', 'column_types':native_types,'limits': notes})
    return definitions


def input_rows(qid,table,definition):
    """Normalize a DATE value only with declared type and reviewed format evidence."""
    rows=[];changes=0
    for row in table['rows']:
        converted=[]
        for cell,native in zip(row,definition['column_types']):
            result=cell
            if native=='DATE' and cell is not None:
                match=re.fullmatch(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',cell)
                if match:result=date(*(int(v) for v in match.groups())).isoformat()
                elif qid==607:
                    match=re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})',cell)
                    if not match:raise ValueError('q607 DATE format is outside the reviewed ISO/MDY codec')
                    month,day,year=(int(v) for v in match.groups());result=date(year,month,day).isoformat()
                else:raise ValueError('DATE format is outside the reviewed ISO codec; input remains ungraded')
            changes+=result!=cell
            converted.append(result)
        rows.append(converted)
    return rows,changes


def value(cell):
    if type(cell) is Decimal:
        if not cell.is_finite(): raise ValueError('nonfinite MySQL output')
        if cell == cell.to_integral_value(): return int(cell)
        number = float(cell)
        if not math.isfinite(number): raise ValueError('nonfinite MySQL output')
        return number
    if type(cell) in (date, datetime, datetime_time): return cell.isoformat(sep=' ') if type(cell) is datetime else cell.isoformat()
    if type(cell) is timedelta:
        seconds = int(cell.total_seconds())
        return ('-' if seconds < 0 else '')+f'{abs(seconds)//3600:02}:{abs(seconds)//60%60:02}:{abs(seconds)%60:02}'
    if type(cell) is bytes:
        return cell.decode('utf8')
    if cell is None or type(cell) in (str, int, bool) or type(cell) is float and math.isfinite(cell): return cell
    raise ValueError('unsupported MySQL output type')


def command(code):
    """Identify the actual top-level command, including WITH ... DELETE/UPDATE."""
    tokens = re.findall(r"/\*.*?\*/|--[^\n]*|\#[^\n]*|'(?:\\.|''|[^'])*'|\"(?:\\.|\"\"|[^\"])*\"|`(?:``|[^`])*`|[A-Za-z_]+|[()]", code, re.S)
    depth = 0
    best=None
    for token in tokens:
        if token == '(': depth += 1
        elif token == ')': depth -= 1
        elif token.upper() in ('SELECT', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'REPLACE', 'DROP', 'ALTER', 'SET', 'CALL', 'EXPLAIN'):
            # A native query expression can be (SELECT ... LIMIT ...) UNION
            # (SELECT ... LIMIT ...). Choose the first command at the shallowest
            # depth; a SELECT inside a WITH clause cannot impersonate UPDATE.
            if best is None or depth<best[0]:best=(depth,token.upper())
    return best[1] if best else ''


class Session:
    def __init__(self, qid, *, check_cancel=lambda: None):
        self.qid, self.check_cancel = qid, check_cancel
        self.container = 'mcibench-mysql-'+secrets.token_hex(8)
        self.password = secrets.token_hex(24)
        self.user_password = secrets.token_hex(24)
        self.root = None
        self.bridges = []
        self.started = False
        self.runtime_ms = 0.
        self.columns = []
        self.schemas = []
        self.environment = identity()
        self.client = _client()

    def connect(self, user, password, database=None, timeout=5):
        bridge = _Bridge(self.container)
        self.bridges.append(bridge)
        connection = self.client.connections.Connection(user=user, password=password, database=database,
            charset='utf8mb4', autocommit=True, read_timeout=timeout, write_timeout=timeout,
            connect_timeout=timeout, local_infile=False, defer_connect=True,
            cursorclass=self.client.cursors.Cursor if user=='root' else self.client.cursors.SSCursor)
        try: connection.connect(sock=bridge.sock)
        except BaseException:
            bridge.close()
            self.bridges.remove(bridge)
            raise
        return connection, bridge

    def __enter__(self):
        try:
            self.check_cancel()
            _docker('run', '-d', '--name', self.container, '--network', 'none',
                '--user', '999:999', '--cpus', '1', '--memory', '768m', '--pids-limit', '192',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
                '--tmpfs', '/var/lib/mysql:rw,nosuid,size=256m,uid=999,gid=999',
                '--tmpfs', '/var/run/mysqld:rw,nosuid,size=16m,uid=999,gid=999',
                '--tmpfs', '/tmp:rw,nosuid,size=32m,mode=1777',
                '-e', 'MYSQL_ROOT_PASSWORD='+self.password, '-e', 'MYSQL_ROOT_HOST=%',
                '-e', 'MYSQL_INITDB_SKIP_TZINFO=1', self.environment['image'],
                '--default-authentication-plugin=mysql_native_password', '--performance-schema=OFF',
                '--innodb-buffer-pool-size=32M', '--innodb-redo-log-capacity=16M',
                '--innodb-log-buffer-size=8M', '--max-connections=8', '--mysqlx=0',
                '--skip-log-bin', '--local-infile=0', '--secure-file-priv=NULL', '--skip-name-resolve')
            self.started = True
            inspected=json.loads(_docker('inspect',self.container))[0]
            host=inspected['HostConfig']
            isolation={'network':host['NetworkMode'],'read_only_rootfs':host['ReadonlyRootfs'],
                       'user':inspected['Config']['User'],'cap_drop':host.get('CapDrop',[]),
                       'memory_bytes':host['Memory'],'nano_cpus':host['NanoCpus'],
                       'host_binds':host.get('Binds') or [],'published_ports':host.get('PortBindings') or {},
                       'mount_types':[mount['Type'] for mount in inspected.get('Mounts',[])]}
            if (isolation['network']!='none' or not isolation['read_only_rootfs'] or isolation['user']!='999:999'
                    or 'ALL' not in [c.upper() for c in isolation['cap_drop']] or isolation['host_binds']
                    or isolation['published_ports'] or any(t!='tmpfs' for t in isolation['mount_types'])):
                raise ValueError('MySQL container isolation configuration mismatch')
            self.environment['verified_isolation']=isolation
            deadline = time.monotonic()+100
            while time.monotonic() < deadline:
                self.check_cancel()
                try:
                    self.root, _ = self.connect('root', self.password, timeout=2)
                    break
                except (self.client.Error, OSError):
                    state = json.loads(_docker('inspect', self.container))[0]['State']
                    if not state['Running']: raise ValueError('MySQL server exited during initialization')
                    time.sleep(.3)
            if self.root is None: raise ValueError('MySQL infrastructure initialization timed out')
            with self.root.cursor() as cursor:
                cursor.execute('SELECT VERSION()')
                actual = cursor.fetchone()[0]
                if actual != self.environment['mysql_version']:
                    raise ValueError('MySQL server version does not match pinned runtime')
                cursor.execute("CREATE USER 'candidate'@'%%' IDENTIFIED WITH mysql_native_password BY %s", (self.user_password,))
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.root is not None:
            try: self.root.close()
            except Exception: pass
        for bridge in self.bridges:
            bridge.close()
        self.bridges.clear()
        if self.started:
            try: _docker('rm', '-f', self.container)
            finally: self.started = False

    def __exit__(self, *args):
        self.close()

    def run_case(self, code, args, comparison, index):
        self.check_cancel()
        remaining = 5-self.runtime_ms/1000
        if remaining <= 0: raise SQLFailure('MySQL corpus execution budget exhausted', 'Time Limit Exceeded')
        mutation = bool(comparison.get('mutation'))
        operation = comparison.get('mutation_operation', 'delete').upper()
        actual_command = command(code)
        function = self.qid == 177 and actual_command == 'CREATE'
        if mutation and actual_command != operation:
            raise SQLFailure('A '+operation+' mutation statement is required')
        if not mutation and actual_command != 'SELECT' and not function:
            raise SQLFailure('A read-only SELECT query is required')
        database = 'case_'+secrets.token_hex(8)
        definitions = schema(self.qid, args)
        self.schemas.append({'case': index, 'tables': definitions})
        try:
            with self.root.cursor() as cursor:
                cursor.execute('CREATE DATABASE '+quote(database)+' CHARACTER SET utf8mb4 COLLATE '+COLLATION)
                cursor.execute('USE '+quote(database))
                for definition in definitions:
                    cursor.execute(definition['ddl'])
                    table = args['tables'][definition['table']]
                    if table['rows']:
                        rows,changed=input_rows(self.qid,table,definition)
                        definition['normalized_date_cells']=changed
                        cursor.executemany('INSERT INTO '+quote(definition['table'])+' VALUES ('+','.join(['%s']*len(table['columns']))+')', rows)
                cursor.execute("GRANT SELECT ON "+quote(database)+".* TO 'candidate'@'%'")
                if mutation:
                    if operation not in ('DELETE', 'UPDATE'): raise ValueError('Unsupported MySQL mutation')
                    cursor.execute('GRANT '+operation+' ON '+quote(database)+'.'+quote(comparison['result_table'])+" TO 'candidate'@'%'")
                if function:
                    cursor.execute('GRANT CREATE ROUTINE, EXECUTE ON '+quote(database)+".* TO 'candidate'@'%'")
        except self.client.Error as error:
            raise ValueError('Native MySQL input/schema initialization failed: '+str(error)[:700]) from None
        connection, bridge = self.connect('candidate', self.user_password, database, timeout=max(.05, remaining))
        connection_id = connection.thread_id()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION sql_mode=%s', (SQL_MODE,))
                cursor.execute('SET SESSION div_precision_increment=4')
                cursor.execute('SET SESSION max_execution_time=%s', (max(1, int(remaining*1000)),))
                for name, parameter in args.items():
                    if name != 'tables':
                        if not re.fullmatch(r'[A-Za-z_]\w*', name): raise ValueError('Invalid scalar parameter name')
                        cursor.execute('SET @'+name+'=%s', (parameter,))
                started = time.perf_counter()
                try:
                    cursor.execute(code)
                    if function:
                        cursor.execute('SELECT getNthHighestSalary(%s) AS result', (args['n'],))
                    elif mutation:
                        cursor.execute('SELECT * FROM '+quote(comparison['result_table']))
                    if cursor.description is None: raise SQLFailure('SQL did not produce a result table')
                    columns = [c[0] for c in cursor.description]
                    fields = [{'name': f.name, 'mysql_type': f.type_code, 'flags': f.flags, 'charset': f.charsetnr,
                               'length': f.length, 'scale': f.scale} for f in cursor._result.fields]
                    rows = []
                    size = 0
                    for row in cursor:
                        self.check_cancel()
                        converted = [value(cell) for cell in row]
                        size += len(json.dumps(converted, ensure_ascii=False).encode('utf8'))
                        if size > 16*1024*1024 or len(rows) >= 100000:
                            raise SQLFailure('MySQL output exceeds result budget')
                        rows.append(converted)
                    self.columns.append({'case': index, 'fields': fields})
                except self.client.Error as error:
                    number = error.args[0] if error.args else None
                    if number in (2006, 2013):
                        state = json.loads(_docker('inspect', self.container))[0]['State']
                        if state.get('OOMKilled'):
                            raise SQLFailure('MySQL query exceeded container memory budget', 'Memory Limit Exceeded') from None
                        if not state['Running'] or time.perf_counter()-started < remaining*.9:
                            raise ValueError('MySQL connection/execution infrastructure incomplete') from None
                    status = 'Time Limit Exceeded' if number in (3024, 1317, 2013) else 'Runtime Error'
                    raise SQLFailure(str(error)[:1500], status) from None
                finally:
                    self.runtime_ms += (time.perf_counter()-started)*1000
                if self.runtime_ms > 5000:
                    raise SQLFailure('MySQL corpus execution budget exhausted', 'Time Limit Exceeded')
                self.check_cancel()
                return {'columns': columns, 'rows': rows}
        finally:
            # Closing a timed-out client must not leave its query running.
            try:
                with self.root.cursor() as cursor: cursor.execute('KILL CONNECTION '+str(int(connection_id)))
            except self.client.Error: pass
            try: connection.close()
            except self.client.Error: pass
            bridge.close()
            self.bridges.remove(bridge)
            with self.root.cursor() as cursor:
                cursor.execute('DROP DATABASE '+quote(database))
                cursor.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'candidate'@'%'")
