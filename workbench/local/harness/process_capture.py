"""Bounded process output capture with cleanup of task-owned Docker containers."""
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

STDOUT_LIMIT = 64 * 1024 * 1024
STDERR_LIMIT = 4 * 1024 * 1024
OUTPUT_LIMIT_RC = -1000


class ProcessCleanupError(RuntimeError):
    pass


@dataclass
class Capture:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limited: bool = False
    container_name: str | None = None


def capture(cmd, cwd: Path, timeout_s: float, *, stdout_limit=STDOUT_LIMIT,
            stderr_limit=STDERR_LIMIT, on_stdout=None):
    """Drain both pipes concurrently; retained bytes never exceed their limits.

    Docker cleanup uses a host-generated unique name, never submission output or
    a file in the submission's writable mount. No other containers are touched.
    """
    if timeout_s <= 0 or stdout_limit <= 0 or stderr_limit <= 0:
        raise ValueError('capture limits must be positive')
    command = list(cmd)
    container = None
    if len(command) > 1 and Path(command[0]).stem.lower() == 'docker' and command[1] == 'run':
        container = 'mcibench-' + uuid.uuid4().hex
        command[2:2] = ['--name', container]
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               stdin=subprocess.PIPE if on_stdout else subprocess.DEVNULL, **options)
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    failures = []
    def drain(stream, index, limit):
        try:
            while True:
                data = stream.read1(65536)
                if not data:
                    break
                room = limit - len(buffers[index])
                buffers[index].extend(data[:room])
                if len(data) > room:
                    overflow.set()
                if index == 0 and on_stdout is not None and not overflow.is_set():
                    control = on_stdout(data)
                    if control:
                        try:
                            process.stdin.write(control)
                            process.stdin.flush()
                        except BrokenPipeError:
                            pass  # The process may have completed before the stop request.
        except Exception as exc:
            failures.append(str(exc))
        finally:
            stream.close()
    threads = [threading.Thread(target=drain, args=(process.stdout, 0, stdout_limit), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, 1, stderr_limit), daemon=True)]
    for thread in threads:
        thread.start()
    started = time.monotonic()
    timed_out = False

    def stop_owned_process():
        cleanup_error = None
        if container is not None:
            try:
                removed = subprocess.run(['docker', 'rm', '--force', container],
                                         capture_output=True, timeout=15,
                                         **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
                missing = any(marker in removed.stderr.lower() for marker in (b'no such container', b'no such object'))
                if removed.returncode and not missing:
                    cleanup_error = removed.stderr.decode('utf-8', 'replace')[:300]
            except Exception as exc:
                cleanup_error = str(exc)
        if process.poll() is None:
            if os.name == 'nt':
                killed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                if killed.returncode and process.poll() is None:
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise ProcessCleanupError('owned process did not terminate') from exc
        if cleanup_error:
            raise ProcessCleanupError('owned container cleanup failed: ' + cleanup_error)

    try:
        while process.poll() is None or any(t.is_alive() for t in threads):
            if overflow.is_set() or failures or time.monotonic() - started >= timeout_s:
                timed_out = not overflow.is_set()
                stop_owned_process()
                break
            overflow.wait(0.02)
    except BaseException:
        stop_owned_process()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=5)
        if process.stdin is not None:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
    if any(t.is_alive() for t in threads):
        raise ProcessCleanupError('output pipe remained open after process cleanup')
    if failures:
        raise ProcessCleanupError('output capture failed: ' + '; '.join(failures))
    limited = overflow.is_set()
    code = OUTPUT_LIMIT_RC if limited else 124 if timed_out else process.returncode
    return Capture(code, bytes(buffers[0]), bytes(buffers[1]), timed_out, limited, container)
