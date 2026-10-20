# -*- coding: utf-8 -*-
"""Compile + run a rendered driver for one language, mapping outcomes to status.

Two backends:
  - host: uses the toolchains installed on this machine (dev iteration).
  - docker: runs inside the local judge image (production, offline-safe).

Outcome mapping (LeetCode vocabulary, consumed by judge.py):
  Compile Error / Time Limit Exceeded / Memory Limit Exceeded /
  Runtime Error / Wrong Answer / Accepted
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

LANGS = ["python3", "c", "cpp", "csharp", "java", "javascript", "golang", "rust"]

DOCKER_IMAGE = "local-judge:1"
# The container cap must fit COMPILATION, not just the graded run. Compiling is
# memory-hungry and measured peaks are ~1.11 GB for C (with the bundled
# uthash.h) and ~0.96 GB for C++ on q47's driver. With the old 512 MB cap the
# OOM killer took cc1/cc1plus, and the submission was blamed with a bogus
# "Compile Error" -- q47's C and C++ references failed exactly this way.
# Trade-off: a program that genuinely needs 512 MB-1.5 GB is no longer flagged
# Memory Limit Exceeded. That cost is small (MLE was 4 of 15,400 audited slots)
# next to silently mislabelling correct code as non-compiling.
DOCKER_MEM_MB = 1536
# Compile failure sentinel for the single-container path: exit code + stderr
# marker, so a user program that happens to exit 90 cannot be mistaken for it.
_CE_EXIT = 90
_CE_MARKER = "__LJ_COMPILE_FAIL__"

# Signatures of the Docker CLI failing to reach the daemon. Without this the
# CLI's exit code 1 falls through map_status() and is reported as "Runtime
# Error" -- indistinguishable from the submission crashing -- so a daemon outage
# during a long audit would silently be recorded as thousands of REs.
_INFRA_SIGNS = (
    "failed to connect to the docker api",
    "cannot connect to the docker daemon",
    "error during connect",
    "is the docker daemon running",
    "dockerdesktoplinuxengine",
)

# AddressSanitizer's report banner. Used to tell "real undefined behaviour"
# apart from an ordinary crash so it can be mapped to LeetCode's Runtime Error.
_SANITIZER_SIGN = "AddressSanitizer"

# 编译器因内存不足被 OOM killer 杀死，或工具链自己报内存耗尽。
# 这类失败**不是提交的问题**：同一份代码在内存充足时能正常编译。若不区分，
# 判题器会把好代码记成 "Compile Error" —— 与"docker 掉线被记成 Runtime Error"
# 同属静默污染。实测来源：主机 VmmemWSL 占用过高时 gcc/g++ 被 kill。
_OOM_SIGNS = (
    "killed signal terminated program cc1",
    "killed signal terminated program cc1plus",
    "fatal error: killed",
    "virtual memory exhausted",
    "cannot allocate memory",
    "outofmemoryexception",              # Roslyn (C#)
    "java.lang.outofmemoryerror",        # javac
)


def _looks_like_compiler_oom(text: str) -> bool:
    low = text.lower()
    return any(s in low for s in _OOM_SIGNS)


class InfrastructureError(RuntimeError):
    """The judging sandbox itself is unavailable (Docker daemon down, etc.).

    Deliberately outside the verdict vocabulary: callers must abort rather than
    record a verdict, because no verdict was actually produced.
    """


def docker_available(timeout_s: int = 30) -> tuple[bool, str]:
    """Preflight: can we reach the Docker daemon and see the judge image?"""
    try:
        p = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, timeout=timeout_s)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    if p.returncode != 0:
        return False, p.stderr.decode("utf-8", "replace").strip()[:200]
    try:
        q = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE],
                           capture_output=True, timeout=timeout_s)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    if q.returncode != 0:
        return False, f"image {DOCKER_IMAGE} not present"
    return True, p.stdout.decode("utf-8", "replace").strip()


def _looks_like_infra_failure(text: str) -> bool:
    low = text.lower()
    return any(s in low for s in _INFRA_SIGNS)


def _docker_base(workdir: Path) -> list[str]:
    return ["docker", "run", "--rm", "--network", "none",
            "--memory", f"{DOCKER_MEM_MB}m", "--memory-swap", f"{DOCKER_MEM_MB}m",
            "--cpus", "1", "--pids-limit", "128",
            "-v", f"{workdir}:/w", "-w", "/w", DOCKER_IMAGE]


# /usr/bin/time -v prints:
#   Elapsed (wall clock) time (h:mm:ss or m:ss): 0:00.03
#   Maximum resident set size (kbytes): 9124
# The parenthesised unit hint must be matched, otherwise the elapsed-time regex
# never fires and every judged submission reports a runtime of 0 ms.
_TIME_RE = re.compile(r"Elapsed \(wall clock\) time \([^)]*\): (?:(\d+):)?([\d.]+)")
_MEM_RE = re.compile(r"Maximum resident set size \(kbytes\): (\d+)")


@dataclass
class ExecResult:
    status: str                      # Accepted / Wrong Answer / ... ("" if not run)
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    runtime_ms: float = 0.0
    memory_mb: float = 0.0
    runtime_available: bool = False
    memory_available: bool = False
    wall_ms: Optional[float] = None
    failed_case: Optional[int] = None
    total_correct: Optional[int] = None
    output_protocol: Optional[int] = None
    timing_source: str = "unavailable"
    supervisor_protocol: Optional[int] = None
    output_stream_checked: bool = False
    log: str = field(default_factory=str)

    @property
    def accepted(self) -> bool:
        return self.status == "Accepted"


_SRC_NAME = {
    "python3": "driver.py", "c": "driver.c", "cpp": "driver.cpp",
    "csharp": "Program.cs", "java": "Judge.java", "javascript": "driver.js",
    "golang": "driver.go", "rust": "driver.rs",
}
_BIN_NAME = "driver_bin"

# Judged C# projects have zero PackageReferences, so restore needs no network
# (the judge image clears all NuGet sources).
_CSPROJ = (
    '<Project Sdk="Microsoft.NET.Sdk">\n'
    "  <PropertyGroup>\n"
    "    <OutputType>Exe</OutputType>\n"
    "    <TargetFramework>net8.0</TargetFramework>\n"
    "    <Nullable>disable</Nullable>\n"
    "    <ImplicitUsings>disable</ImplicitUsings>\n"
    "    <AssemblyName>driver_bin</AssemblyName>\n"
    "  </PropertyGroup>\n"
    "</Project>\n")


def _bin_name() -> str:
    import os
    return _BIN_NAME + (".exe" if os.name == "nt" else "")


def _run_cmd(cmd: list[str], cwd: Path, timeout_s: int) -> tuple[int, str, str]:
    from local.harness.process_capture import capture, ProcessCleanupError
    try:
        result = capture(cmd, cwd, timeout_s)
    except ProcessCleanupError as error:
        raise InfrastructureError(str(error)) from error
    error = result.stderr.decode('utf-8', 'replace')
    if result.output_limited:
        error += '\nHost output capture limit exceeded'
    elif result.timed_out:
        error += f'\nHost timeout after {timeout_s}s'
    return result.returncode, result.stdout.decode('utf-8', 'replace'), error


def compile_source(lang_key: str, workdir: Path, src: Path,
                   timeout_s: int = 120) -> tuple[int, str]:
    """Compile src into workdir; returns (exit_code, stderr)."""
    if lang_key in ("python3", "javascript"):
        return 0, ""
    def _cc(cmd: list[str]) -> tuple[int, str]:
        rc, out, err = _run_cmd(cmd, workdir, timeout_s)
        return rc, (out + "\n" + err).strip()

    if lang_key == "c":
        return _cc(["gcc", "-O2", "-o", _bin_name(), str(src), "-lm"])
    if lang_key == "cpp":
        return _cc(["g++", "-O2", "-o", _bin_name(), str(src)])
    if lang_key == "java":
        return _cc(["javac", "-encoding", "UTF-8", "Judge.java"])
    if lang_key == "golang":
        return _cc(["go", "build", "-o", _bin_name(), str(src)])
    if lang_key == "rust":
        return _cc(["rustc", "-O", "--edition", "2021", "-o", _bin_name(), str(src)])
    if lang_key == "csharp":
        (workdir / "runner.csproj").write_text(_CSPROJ, encoding="utf-8")
        return _cc(["dotnet", "build", "-c", "Release", "-v", "q",
                    "--ignore-failed-sources", "runner.csproj"])
    raise ValueError(f"unknown lang {lang_key}")


def run_binary(lang_key: str, workdir: Path, limit: int,
               timeout_s: int = 20) -> tuple[int, str, str]:
    """Run the compiled binary with the case limit as argv[1]."""
    import os
    if lang_key == "python3":
        cmd = ["python", "driver.py", str(limit)]
    elif lang_key == "javascript":
        cmd = ["node", "driver.js", str(limit)]
    elif lang_key == "java":
        cmd = ["java", "-cp", ".", "Judge", str(limit)]
    elif lang_key == "csharp":
        cmd = ["dotnet", "bin/Release/net8.0/driver_bin.dll", str(limit)]
    elif lang_key in ("c", "cpp", "golang", "rust"):
        exe = _bin_name()
        cmd = [str(workdir / exe), str(limit)]
    else:
        raise ValueError(f"unknown lang {lang_key}")
    return _run_cmd(cmd, workdir, timeout_s)


RC_DONE = 42          # 驱动"跑完全部用例"的约定退出码（见 map_status 的说明）


def map_status(compile_rc: int, compile_err: str, run_rc: int, stdout: str,
               n_cases: Optional[int] = None) -> tuple[str, Optional[int]]:
    """Map compile/run outcomes to (ac_status, failed_case).

    **完成判定只看退出码 RC_DONE(42)，不看 stdout。**

    此前是「退出码 0 且 stdout 最后一行 == "OK"」。那是可以伪造的：提交与驱动
    **同进程**，提交自己 `print("OK"); exit(0)` 即可在**零用例验证**的情况下拿到
    Accepted（审查代理 A 实测 T4；主代理复现 Accepted 1/1）。当时那句
    "取最后一行避免用户代码自己打印 OK"的注释是错的——它只防住"中途打印 OK"，
    防不住"把 OK 当最后一行"。

    改用约定退出码后，提交的**自然**提前退出（`exit(0)`、`return` 出 main、
    abort、崩溃）都不会产生 42，所以「随便打印一句」不再能伪造完成。

    **残余风险（不掩盖）**：提交与驱动同进程，**蓄意** `exit(42)` 仍可伪造。
    根治需要判题器侧自己掌握结论（"编译一次、运行时读数据"的架构，见
    harness/dataio.py 的编码通路）。这里只把门槛从"一句 print"提高到"蓄意伪造"。

    stdout 仍然保留 "OK" 一行，仅用于日志可读性，**不参与判定**。
    """
    if compile_rc != 0:
        return "Compile Error", None
    from local.harness.process_capture import OUTPUT_LIMIT_RC
    if run_rc == OUTPUT_LIMIT_RC:
        return "Output Limit Exceeded", None
    if run_rc == 124:
        return "Time Limit Exceeded", None
    if run_rc == 137:
        return "Memory Limit Exceeded", None
    if run_rc == RC_DONE:
        return "Accepted", None
    if run_rc == 3:
        # `FAIL <idx>` 的 idx 是**从共享 stdout 解析出来的、用户可控的整数**。
        #
        # 两个方向都被实测利用过：
        #   - 提交在 driver 之前打印 `FAIL k`（A-006）：取第一条会给错值
        #   - 提交用 atexit 在 driver 之后打印 `FAIL 999`（A-006b，A 实测复现）：
        #     取最后一条会给出 `total_correct=999 > total_testcases=26`
        #
        # 所以两者都不够。这里改成：**只在 `n_cases` 已知时接受落在 [0, n_cases]
        # 内的行，取最后一条**。driver 的 FAIL 是失败那一刻打印、随后立即 exit(3)，
        # 落在范围内且必然是最后一条合法的；越界的伪造行被直接忽略。
        #
        # 残余风险（不掩盖）：提交若在 driver 之后打印一个**范围内**的假 idx，
        # 仍能带偏 total_correct。彻底根治要把判定结论放到提交写不到的通道
        # （与 A-001 的架构问题同源）。AC/WA 分类不受影响，只有 total_correct。
        failed = None
        for line in stdout.splitlines():
            if line.startswith("FAIL"):
                parts = line.split()
                if len(parts) > 1 and parts[1].lstrip("-").isdigit():
                    k = int(parts[1])
                    if n_cases is None or 0 <= k <= n_cases:
                        failed = k
        return "Wrong Answer", failed
    # 退出码 0 落在这里：程序正常结束但**没跑完**用例（驱动被打断）。
    return "Runtime Error", None


def run_submission(lang_key: str, driver_text: str, limit: int,
                   compile_timeout_s: int = 120, run_timeout_s: int = 20,
                   workdir: Optional[Path] = None,
                   backend: str = "host",
                    asan: bool = False, output_verifier=None) -> ExecResult:
    """Render-and-run is done by the caller; this compiles+runs a driver text.

    backend: "host" uses local toolchains (dev); "docker" runs sandboxed in the
    judge image with no network, 1.5GB cgroup limit and per-run timeouts.

    `asan` adds -fsanitize=address for C/C++ (no-op elsewhere). LeetCode reports
    Runtime Error for out-of-bounds reads that a plain build silently tolerates,
    so this is used as a *confirmation* pass on otherwise-accepted C/C++ runs.

    When `workdir` is omitted a private temporary directory is created and
    removed again on every exit path. It used to be leaked: judging ~6,400
    submissions left 12.8 GB of driver sources and compiled binaries in %TEMP%.
    """
    tmp_ctx = None
    if workdir is None:
        import tempfile
        tmp_ctx = tempfile.TemporaryDirectory(prefix="lj_", ignore_cleanup_errors=True)
        workdir = Path(tmp_ctx.name)
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
    try:
        src = workdir / _SRC_NAME[lang_key]
        src.write_text(driver_text, encoding="utf-8")
        if lang_key == "csharp":
            (workdir / "runner.csproj").write_text(_CSPROJ, encoding="utf-8")

        if backend == "docker":
            if output_verifier is not None:
                from local.harness.supervised_runner import run_supervised
                result = run_supervised(lang_key, workdir, limit, compile_timeout_s,
                                        run_timeout_s, asan=asan, output_verifier=output_verifier)
            else:
                result = _run_docker(lang_key, workdir, limit, compile_timeout_s,
                                     run_timeout_s, asan=asan)
            return _check_outputs(result, output_verifier, asan)

        t0 = time.time()
        compile_rc, compile_err = compile_source(lang_key, workdir, src, compile_timeout_s)
        runtime_ms = (time.time() - t0) * 1000
        if compile_rc != 0:
            status, failed = map_status(compile_rc, compile_err, 0, "")
            return ExecResult(status=status, exit_code=compile_rc, stderr=compile_err,
                              runtime_ms=runtime_ms,
                              log=f"compile failed:\n{compile_err[:2000]}")

        t0 = time.time()
        run_rc, stdout, run_err = run_binary(lang_key, workdir, limit, run_timeout_s)
        runtime_ms = (time.time() - t0) * 1000
        status, failed = map_status(0, "", run_rc, stdout, n_cases=limit)
        result = ExecResult(status=status, exit_code=run_rc, stdout=stdout, stderr=run_err,
                            runtime_ms=runtime_ms, runtime_available=True, failed_case=failed,
                            log=f"run stderr:\n{run_err[:2000]}", timing_source="host_timer")
        return _check_outputs(result, output_verifier, asan)
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def _check_outputs(result, verifier, asan=False):
    """Only the trusted host verifier may accept an output-protocol submission."""
    if verifier is None:
        return result
    from local.harness.output_protocol import PROTOCOL
    result.output_protocol = PROTOCOL
    if result.status == 'Compile Error':
        result.total_correct = 0
        return result
    if not result.output_stream_checked:
        for line in result.stdout.splitlines():
            verifier.feed(line)
    failure = (result.status if result.status in ('Time Limit Exceeded', 'Memory Limit Exceeded',
                                                  'Output Limit Exceeded') else None)
    if asan and _SANITIZER_SIGN in result.stderr:
        failure = 'Runtime Error'
    verdict = verifier.finish(result.exit_code, execution_failure=failure)
    result.status = verdict.status
    result.failed_case = verdict.failed_case
    result.total_correct = verdict.total_correct
    if verdict.detail:
        result.log = verdict.detail + '\n' + result.log
    return result


def _run_docker(lang_key: str, workdir: Path, limit: int,
                compile_timeout_s: int, run_timeout_s: int,
                asan: bool = False) -> ExecResult:
    """Compile and run inside ONE container.

    This used to be two `docker run` invocations -- one to compile, a second to
    run -- which roughly doubles wall time because container startup dominates
    on Windows. Compile failure is signalled by a sentinel exit code plus a
    stderr marker so the two outcomes stay distinguishable (a user program
    exiting 90 by chance will not print the marker).

    `asan` turns on AddressSanitizer for C/C++ (ignored for other languages).
    """
    base = _docker_base(workdir)
    san = "asan" if asan else ""
    # judge_exec.sh 的签名是 <mode> <lang> [limit] [asan]。compile 模式不需要
    # limit，但位置参数必须占住，否则 "asan" 会落进 limit 的位置、编译拿不到标志。
    script = (
        f"timeout {compile_timeout_s} /judge_exec.sh compile {lang_key} 0 {san} "
        f"|| {{ echo {_CE_MARKER} >&2; exit {_CE_EXIT}; }}; "
        f"exec timeout {run_timeout_s} /usr/bin/time -v "
        f"/judge_exec.sh run {lang_key} {limit} {san}"
    )
    started = time.perf_counter()
    rc, out, err = _run_cmd(base + ["bash", "-c", script], workdir,
                            compile_timeout_s + run_timeout_s + 30)
    wall_ms = (time.perf_counter() - started) * 1000
    if _looks_like_infra_failure(out + "\n" + err):
        raise InfrastructureError(
            f"docker daemon unreachable: {(err or out).strip()[:300]}")
    if rc == _CE_EXIT and _CE_MARKER in err:
        log = (out + "\n" + err).strip()
        # 先排除"编译器被 OOM 杀死"：那不是提交编译不过，而是环境没内存。
        # 记成 Compile Error 会把正确代码判错，所以宁可报错中止。
        if _looks_like_compiler_oom(log):
            try:
                wd_bytes = sum(f.stat().st_size for f in workdir.iterdir()
                               if f.is_file())
            except OSError:
                wd_bytes = -1
            raise InfrastructureError(
                f"compiler killed for memory, not a submission error "
                f"(host memory pressure? workdir={wd_bytes}B): {log[:300]}")
        return ExecResult(status="Compile Error", exit_code=rc, stderr=log, wall_ms=wall_ms,
                          log=f"compile failed:\n{log[:2000]}")
    if asan and _SANITIZER_SIGN in err:
        # ASan found real undefined behaviour (out-of-bounds etc). LeetCode
        # reports Runtime Error for these; a plain build silently tolerates them.
        return ExecResult(status="Runtime Error", exit_code=rc, stdout=out,
                          stderr=err, log=f"sanitizer:\n{err[:2000]}")
    # n_cases=limit：Docker 路径**才是实际使用的路径**，必须同样做范围过滤，
    # 否则 A-006b 的越界伪造（FAIL 999）在这里原样透出（我第一版漏了这处，
    # 端到端复现仍是 total_correct=26 而不是正确的 0）。
    status, failed = map_status(0, "", rc, out, n_cases=limit)
    runtime_ms, memory_mb = _parse_time_v(err)
    return ExecResult(status=status, exit_code=rc, stdout=out, stderr=err,
                      runtime_ms=runtime_ms, memory_mb=memory_mb, wall_ms=wall_ms,
                      runtime_available=bool(_TIME_RE.search(err)),
                      memory_available=bool(_MEM_RE.search(err)),
                      failed_case=failed, log=f"run stderr:\n{err[:2000]}")


def _parse_time_v(stderr: str) -> tuple[float, float]:
    rt, mem = 0.0, 0.0
    m = _TIME_RE.search(stderr)
    if m:
        minutes = int(m.group(1) or 0)
        rt = minutes * 60.0 + float(m.group(2))
        rt = rt * 1000.0
    m = _MEM_RE.search(stderr)
    if m:
        mem = int(m.group(1)) / 1024.0
    return rt, mem
