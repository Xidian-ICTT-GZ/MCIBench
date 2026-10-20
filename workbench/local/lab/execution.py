"""Integrity-bound compiled artifacts; never cache executions or model sampling."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time

from local.harness import runner
from local.harness.process_capture import capture, STDOUT_LIMIT, STDERR_LIMIT
from local.harness.supervised_runner import StreamReport, decode_stage
from local.lab.behavior import sha

VERSION = 'lab-compiled-artifacts-v2'
COMPILED = {'c', 'cpp', 'csharp', 'java', 'golang', 'rust'}
CAP = 64 * 1024 * 1024
DISK_CAP = 512 * 1024 * 1024


def cache_eligible(language, driver):
    # These macros intentionally observe compilation time; recompile such drivers.
    return language in COMPILED and not any(marker in driver for marker in ('__TIME__', '__DATE__', '__TIMESTAMP__'))


def valid_files(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 512:
        raise ValueError('artifact file count')
    names, total = set(), 0
    for item in items:
        name = item['name']
        path = PurePosixPath(name)
        if not isinstance(name, str) or not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('artifact path')
        if name in names or name == 'manifest.json':
            raise ValueError('duplicate or reserved artifact')
        names.add(name)
        size = item['bytes']
        if type(size) is not int or not 0 <= size <= CAP:
            raise ValueError('artifact size')
        total += size
        if total > CAP or not isinstance(item['sha256'], str) or len(item['sha256']) != 64:
            raise ValueError('artifact integrity metadata')


class CachedExecution:
    """One sandbox at a time; fresh container/process and filesystem on every call."""
    def __init__(self, root, image, *, enabled=True):
        if not image.startswith('sha256:') or len(image) != 71:
            raise ValueError('compiled artifacts require immutable image digest')
        self.root, self.image, self.enabled = Path(root), image, enabled
        self.adapter = Path(__file__).with_name('cache_supervisor.py').resolve()
        self.supervisor = Path(runner.__file__).with_name('container_supervisor.py').resolve()
        self.binding = {'version': VERSION, 'image': image, 'adapter': sha(self.adapter.read_text(encoding='utf-8')),
                        'supervisor': sha(self.supervisor.read_text(encoding='utf-8')), 'csproj': sha(runner._CSPROJ),
                        'memory_mb': runner.DOCKER_MEM_MB, 'cpu': 1, 'pids': 128, 'asan': False}
        self.root.mkdir(parents=True, exist_ok=True)
        self.stored_bytes = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file() and not p.is_symlink())

    def cached(self, folder, key):
        try:
            manifest = json.loads((folder/'manifest.json').read_bytes())
            if manifest['key'] != key or manifest['binding'] != self.binding:
                return False
            valid_files(manifest['files'])
            for item in manifest['files']:
                path = folder / item['name']
                if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
                    return False
                if path.stat().st_size != item['bytes']:
                    return False
                data = path.read_bytes()
                if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    return False
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def publish(self, folder, key, items):
        valid_files(items)
        with tempfile.TemporaryDirectory(prefix='artifact_', dir=self.root) as tmp:
            target = Path(tmp)
            for item in items:
                data = base64.b64decode(item['data'], validate=True)
                if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('artifact transport integrity failure')
                file = target/item['name']
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
            manifest = {'key': key, 'binding': self.binding, 'files': [{k:v for k,v in item.items() if k != 'data'} for item in items]}
            (target/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            # Cache is private, disposable and never mounted writable into submissions.
            if folder.exists():
                resolved, root = folder.resolve(), self.root.resolve()
                if resolved.parent != root:
                    raise ValueError('cache replacement outside intended root')
                shutil.rmtree(resolved)
            target.replace(folder)
            self.stored_bytes += sum(item['bytes'] for item in items) + len(json.dumps(manifest).encode('utf-8'))

    def __call__(self, language, driver, limit, *, backend='docker', run_timeout_s=5,
                 compile_timeout_s=120, output_verifier=None):
        if backend != 'docker' or output_verifier is None:
            raise ValueError('lab artifact execution requires the Docker host output checker')
        started = time.perf_counter()
        key = sha({'binding': self.binding, 'language': language, 'driver': sha(driver),
                   'compile_timeout_s': compile_timeout_s})
        folder = self.root/key
        use_cache = self.enabled and cache_eligible(language, driver)
        hit = use_cache and self.cached(folder, key)
        room = self.stored_bytes <= DISK_CAP-CAP-1024*1024
        mode = 'warm' if hit else 'cold' if use_cache and room else 'uncached'
        with tempfile.TemporaryDirectory(prefix='mci_cached_') as tmp:
            source = Path(tmp)
            (source/runner._SRC_NAME[language]).write_text(driver, encoding='utf-8')
            if language == 'csharp':
                (source/'runner.csproj').write_text(runner._CSPROJ, encoding='utf-8')
            command = ['docker', 'run', '--rm', '-i', '--network', 'none',
                       '--memory', f'{runner.DOCKER_MEM_MB}m', '--memory-swap', f'{runner.DOCKER_MEM_MB}m',
                       '--cpus', '1', '--pids-limit', '128', '--cap-drop', 'ALL',
                       '--cap-add', 'CHOWN', '--cap-add', 'SETUID', '--cap-add', 'SETGID', '--cap-add', 'KILL',
                       '--security-opt', 'no-new-privileges', '-v', f'{source.resolve()}:/input:ro',
                       '-v', f'{self.supervisor}:/mci-supervisor.py:ro', '-v', f'{self.adapter}:/lab-supervisor.py:ro']
            if hit:
                command += ['-v', f'{folder.resolve()}:/artifacts:ro']
            command += ['-w', '/w', self.image, 'python3', '-I', '/lab-supervisor.py', language,
                        str(compile_timeout_s), str(run_timeout_s), str(limit), mode]
            stream = StreamReport(output_verifier)
            captured = capture(command, source, compile_timeout_s+run_timeout_s+30,
                               stdout_limit=4*(STDOUT_LIMIT+STDERR_LIMIT)+2*1024*1024,
                               stderr_limit=STDERR_LIMIT, on_stdout=stream.feed)
        if captured.returncode != 0:
            raise runner.InfrastructureError('lab supervisor incomplete: ' + captured.stderr.decode('utf-8','replace')[:500])
        try:
            report = stream.report
            if stream.wire or report['protocol'] != 2 or report['cache_mode'] != mode:
                raise ValueError('invalid artifact supervisor protocol')
            compiled = decode_stage(report['compile'])
            if compiled['reason'] == 'oom' or runner._looks_like_compiler_oom(compiled['stderr']):
                raise runner.InfrastructureError('compiler memory exhaustion')
            timing = {'cache_mode': mode, 'artifact_key': key, 'compile_ms': compiled['runtime_ms'],
                      'run_ms': None, 'wall_ms': round((time.perf_counter()-started)*1000,3),
                      'startup_transport_ms': None, 'fresh_container': True}
            if compiled['exit_code'] != 0 or compiled['reason'] is not None:
                result = runner.ExecResult('Compile Error', exit_code=compiled['exit_code'], stderr=compiled['stderr'])
            else:
                run = decode_stage(report['run'])
                if run['reason'] == 'host_stop' and output_verifier.terminal is None:
                    raise ValueError('unrequested sandbox stop')
                status = {'timeout':'Time Limit Exceeded', 'oom':'Memory Limit Exceeded', 'output_limit':'Output Limit Exceeded'}.get(run['reason'], 'Runtime Error')
                result = runner.ExecResult(status, exit_code=run['exit_code'], stdout=run['stdout'], stderr=run['stderr'],
                          runtime_ms=run['runtime_ms'], memory_mb=run['memory_mb'] or 0,
                          runtime_available=True, memory_available=run['memory_mb'] is not None,
                          wall_ms=timing['wall_ms'], timing_source='isolated_supervisor', supervisor_protocol=2,
                          output_stream_checked=True)
                timing['run_ms'] = run['runtime_ms']
                if mode == 'cold':
                    self.publish(folder, key, report['artifacts'])
            timing['wall_ms'] = round((time.perf_counter()-started)*1000,3)
            timing['startup_transport_ms'] = max(0, timing['wall_ms'] - timing['compile_ms'] - (timing['run_ms'] or 0))
            result.phase_timing = timing
            return runner._check_outputs(result, output_verifier)
        except (ValueError, TypeError, KeyError) as error:
            raise runner.InfrastructureError('invalid lab artifact evidence: '+str(error)) from error
