"""Host decoder for the privileged container supervisor's isolated report."""
import base64
import json
import math
from pathlib import Path
import time
from local.harness.process_capture import capture, STDOUT_LIMIT, STDERR_LIMIT

from local.harness.container_supervisor import PROTOCOL as SUPERVISOR_PROTOCOL


class StreamReport:
    """Decode root-generated envelopes; submission bytes never become metadata."""
    def __init__(self, verifier):
        self.verifier = verifier
        self.wire = bytearray()
        self.pending = bytearray()
        self.report = None
        self.failure_ms = None
        self.last_ms = 0.0
        self.stopped = False

    def check_output(self, data, runtime_ms, final=False):
        from local.harness.output_protocol import OutputVerdict
        self.pending.extend(data)
        while b'\n' in self.pending:
            line, _, rest = self.pending.partition(b'\n')
            self.pending = bytearray(rest)
            self.verifier.feed(line.decode('utf-8', 'replace'))
            if self.verifier.terminal:
                break
        if len(self.pending) > 16 * 1024 * 1024:
            self.verifier.terminal = OutputVerdict('Output Limit Exceeded', self.verifier.completed,
                                                   detail='output line limit exceeded')
        if final and self.pending and self.verifier.terminal is None:
            self.verifier.feed(self.pending.decode('utf-8', 'replace'))
            self.pending.clear()
        if self.verifier.terminal is not None and self.failure_ms is None:
            self.failure_ms = runtime_ms
            self.pending.clear()

    def feed(self, data):
        self.wire.extend(data)
        stop = False
        while b'\n' in self.wire:
            line, _, rest = self.wire.partition(b'\n')
            self.wire = bytearray(rest)
            message = json.loads(line)
            if self.report is not None:
                raise ValueError('data after final supervisor report')
            if message.get('event') == 'output':
                elapsed = message['runtime_ms']
                if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < self.last_ms:
                    raise ValueError('invalid streaming timing')
                self.last_ms = elapsed
                payload = base64.b64decode(message['data'], validate=True)
                if len(payload) > 65536:
                    raise ValueError('oversized output envelope')
                if not self.stopped:
                    self.check_output(payload, elapsed)
                    if self.verifier.terminal is not None:
                        self.stopped = True
                        stop = True
            elif message.get('event') == 'result':
                self.report = message['report']
                self.check_output(b'', self.last_ms, final=True)
            else:
                raise ValueError('unknown supervisor event')
        return b'STOP\n' if stop else None


def run_supervised(lang, workdir, limit, compile_timeout_s, run_timeout_s, asan=False, output_verifier=None):
    from local.harness import runner
    script = Path(__file__).with_name('container_supervisor.py').resolve()
    command = ['docker', 'run', '--rm', '-i', '--network', 'none',
               '--memory', f'{runner.DOCKER_MEM_MB}m', '--memory-swap', f'{runner.DOCKER_MEM_MB}m',
               '--cpus', '1', '--pids-limit', '128', '--cap-drop', 'ALL',
               '--cap-add', 'CHOWN', '--cap-add', 'SETUID', '--cap-add', 'SETGID', '--cap-add', 'KILL',
               '--security-opt', 'no-new-privileges',
               '-v', f'{Path(workdir).resolve()}:/input:ro',
               '-v', f'{script}:/mci-supervisor.py:ro', '-w', '/w', runner.DOCKER_IMAGE,
               'python3', '-I', '/mci-supervisor.py', lang, str(compile_timeout_s), str(run_timeout_s),
               str(limit), 'asan' if asan else '', str(STDOUT_LIMIT), str(STDERR_LIMIT)]
    start = time.perf_counter()
    # Both compile and run records may contain captured streams encoded in base64.
    wire_limit = 3 * ((STDOUT_LIMIT + STDERR_LIMIT) * 4 // 3 + 32) + 1024 * 1024
    stream = StreamReport(output_verifier)
    result = capture(command, Path(workdir), compile_timeout_s + run_timeout_s + 30,
                     stdout_limit=wire_limit, stderr_limit=STDERR_LIMIT, on_stdout=stream.feed)
    wall_ms = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        raise runner.InfrastructureError('supervisor unavailable/incomplete: ' +
                                         result.stderr.decode('utf-8', 'replace')[:1000])
    try:
        report = stream.report
        if stream.wire or not isinstance(report, dict):
            raise ValueError('incomplete supervisor transport')
        if type(report['protocol']) is not int or report['protocol'] != SUPERVISOR_PROTOCOL:
            raise ValueError('unknown supervisor protocol')
        compiled = decode_stage(report['compile'])
        if compiled['reason'] == 'oom' or runner._looks_like_compiler_oom(compiled['stderr']):
            raise runner.InfrastructureError('compiler memory exhaustion: ' + compiled['stderr'][:500])
        if compiled['exit_code'] != 0 or compiled['reason'] is not None:
            return runner.ExecResult('Compile Error', exit_code=compiled['exit_code'],
                                     stdout=compiled['stdout'], stderr=compiled['stderr'], wall_ms=wall_ms,
                                     log='compile failed: ' + compiled['stderr'][:2000],
                                     timing_source='isolated_supervisor', supervisor_protocol=SUPERVISOR_PROTOCOL)
        run = decode_stage(report['run'])
    except (ValueError, KeyError, TypeError) as error:
        raise runner.InfrastructureError('invalid supervisor report: ' + str(error)) from error
    status = {'timeout': 'Time Limit Exceeded', 'oom': 'Memory Limit Exceeded',
              'output_limit': 'Output Limit Exceeded'}.get(run['reason'], 'Runtime Error')
    if run['reason'] == 'host_stop' and output_verifier.terminal is None:
        raise runner.InfrastructureError('unrequested supervisor stop')
    # No exit code, including 0 and 42, can declare AC here. The host checker does.
    return runner.ExecResult(status, exit_code=run['exit_code'], stdout=run['stdout'], stderr=run['stderr'],
                             runtime_ms=min(run['runtime_ms'], stream.failure_ms) if stream.failure_ms is not None else run['runtime_ms'],
                             memory_mb=run['memory_mb'] or 0.0,
                             runtime_available=True, memory_available=run['memory_mb'] is not None,
                             wall_ms=wall_ms, log=run['stderr'][:2000],
                             timing_source='isolated_supervisor', supervisor_protocol=SUPERVISOR_PROTOCOL,
                             output_stream_checked=True)


def decode_stage(stage):
    if not isinstance(stage, dict) or type(stage.get('exit_code')) is not int:
        raise ValueError('missing stage completion')
    if stage.get('reason') not in (None, 'timeout', 'oom', 'output_limit', 'host_stop'):
        raise ValueError('unknown stage termination')
    for key in ('runtime_ms', 'memory_mb'):
        value = stage.get(key)
        if value is None and key == 'memory_mb':
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid measured ' + key)
    out = dict(stage)
    for key, cap in (('stdout', STDOUT_LIMIT), ('stderr', STDERR_LIMIT)):
        value = stage[key]
        if not isinstance(value, str) or len(value) > (cap + 2) // 3 * 4:
            raise ValueError('invalid encoded stream size')
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) > cap:
            raise ValueError('decoded stream exceeds limit')
        out[key] = decoded.decode('utf-8', 'replace')
    return out
