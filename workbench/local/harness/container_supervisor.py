"""Standalone Linux container supervisor; invoked with Python -I as UID 0.

Compilation and execution run as UID 65534. Only this process writes the Docker
stdout transport; submission streams are captured and encoded as data.
"""
import base64
import ctypes
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

PROTOCOL = 2
UID = 65534
SOURCES = {'python3': 'driver.py', 'javascript': 'driver.js', 'cpp': 'driver.cpp',
           'c': 'driver.c', 'java': 'Judge.java', 'csharp': 'Program.cs',
           'golang': 'driver.go', 'rust': 'driver.rs'}


def drop_privileges():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'no_new_privs failed')
    os.setgroups([])
    os.setgid(UID)
    os.setuid(UID)


def kill_submissions():
    # Dedicated PID namespace: every process of this UID belongs to this job.
    # This also catches children that deliberately create another process group.
    for path in Path('/proc').glob('[0-9]*/status'):
        try:
            uid_line = next(line for line in path.read_text().splitlines() if line.startswith('Uid:'))
            if UID in [int(x) for x in uid_line.split()[1:]]:
                os.kill(int(path.parent.name), signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            pass


def oom_count():
    try:
        fields = dict(line.split() for line in Path('/sys/fs/cgroup/memory.events').read_text().splitlines())
        return int(fields['oom_kill'])
    except (OSError, ValueError, KeyError):
        return None


def measure(command, timeout, stdout_limit, stderr_limit, stream_output=False):
    env = dict(os.environ, HOME='/w', DOTNET_CLI_HOME='/w', TMPDIR='/tmp',
               ASAN_OPTIONS='detect_leaks=0:abort_on_error=0')
    started = time.monotonic()
    before_oom = oom_count()
    process = subprocess.Popen(command, cwd='/w', env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, preexec_fn=drop_privileges)
    selector = selectors.DefaultSelector()
    streams = [process.stdout, process.stderr]
    output = [bytearray(), bytearray()]
    limits = [stdout_limit, stderr_limit]
    for i, stream in enumerate(streams):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, i)
    if stream_output:
        os.set_blocking(sys.stdin.fileno(), False)
        selector.register(sys.stdin, selectors.EVENT_READ, 'control')
    status = usage = None
    reason = None
    stopped = False
    finished = None
    try:
        while any(key.data != 'control' for key in selector.get_map().values()) or status is None:
            now = time.monotonic()
            if status is None:
                pid, raw, ru = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    status, usage, finished = os.waitstatus_to_exitcode(raw), ru, now
                    process.returncode = status  # wait4 already reaped the direct child
            if not stopped and (status is not None or now - started >= timeout or reason):
                if status is None and reason is None:
                    reason = 'timeout'
                kill_submissions()
                stopped = True
                stopped_at = now
            if stopped and now - stopped_at > 5:
                raise RuntimeError('submission processes or pipes did not terminate')
            for key, _ in selector.select(0.01):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == 'control':
                    if b'STOP' in data and reason is None:
                        reason = 'host_stop'
                    continue
                i = key.data
                room = limits[i] - len(output[i])
                output[i].extend(data[:room])
                if len(data) > room and reason is None:
                    reason = 'output_limit'
                if stream_output and i == 0 and len(data) <= room:
                    print(json.dumps({'event': 'output', 'data': base64.b64encode(data).decode('ascii'),
                                      'runtime_ms': (time.monotonic() - started) * 1000}), flush=True)
        after_oom = oom_count()
        if before_oom is not None and after_oom is not None and after_oom > before_oom:
            reason = 'oom'
        return {'exit_code': status, 'reason': reason,
                'runtime_ms': ((finished or time.monotonic()) - started) * 1000,
                'memory_mb': usage.ru_maxrss / 1024 if usage is not None else None,
                'stdout': base64.b64encode(output[0]).decode('ascii'),
                'stderr': base64.b64encode(output[1]).decode('ascii')}
    finally:
        kill_submissions()
        selector.close()
        for stream in streams:
            stream.close()


def main():
    lang, compile_s, run_s, limit, asan, stdout_cap, stderr_cap = sys.argv[1:]
    compile_s, run_s = float(compile_s), float(run_s)
    if lang not in SOURCES or not all(math.isfinite(x) and x > 0 for x in (compile_s, run_s)):
        raise ValueError('invalid execution profile')
    stdout_cap, stderr_cap = int(stdout_cap), int(stderr_cap)
    if not 0 < stdout_cap <= 64 * 1024 * 1024 or not 0 < stderr_cap <= 4 * 1024 * 1024:
        raise ValueError('invalid output profile')
    if os.getuid() != 0:
        raise RuntimeError('supervisor must retain a separate privileged UID')
    for name in [SOURCES[lang]] + (['runner.csproj'] if lang == 'csharp' else []):
        target = Path('/w') / name
        shutil.copyfile(Path('/input') / name, target)
        os.chown(target, UID, UID)
    config = Path('/w/NuGet.Config')
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    os.chown(config, UID, UID)
    os.chown('/w', UID, UID)
    compile_result = measure(['/judge_exec.sh', 'compile', lang, '0', asan],
                             compile_s, stdout_cap, stderr_cap)
    report = {'protocol': PROTOCOL, 'compile': compile_result, 'run': None}
    if compile_result['exit_code'] == 0 and compile_result['reason'] is None:
        commands = {'python3': ['python3', 'driver.py'], 'javascript': ['node', 'driver.js'],
                    'java': ['java', '-cp', '.', 'Judge'],
                    'csharp': ['dotnet', 'bin/Release/net8.0/driver_bin.dll']}
        report['run'] = measure(commands.get(lang, ['./driver_bin']) + [limit],
                                run_s, stdout_cap, stderr_cap, stream_output=True)
    print(json.dumps({'event': 'result', 'report': report}, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
