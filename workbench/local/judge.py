# -*- coding: utf-8 -*-
"""Local judge: drop-in replacement for the LeetCode submission scripts.

Reads generated code files, renders per-language test drivers with the local
test corpus, runs them in the Docker sandbox, and writes result JSONs that are
byte-compatible with the historical LeetCode submission results:

    Submit_Result/Submit_Results_<NAME>/<qid>/<qid>_<langkey>_<n>.json       (gen)
    Submit_Result/Submit_Results_Trans_<NAME>/<qid>/<qid>_<src>_<tgt>_<n>.json (trans)

Result JSON (9 fields, always emitted):
    {submit_id, state, ac_status, total_testcases, total_correct,
     runtime, runtime_percentile, memory, memory_percentile}

Downstream (compute_passk.py / clean_results.py / DB import / dashboard) is
unchanged. Resume by result-file existence, like the old scripts.

Usage (run from the directory that contains Submit_Gen/Submit_Trans, typically
SFT_Full or the repo root):
    python local/judge.py -submit_gen <run_name>
    python local/judge.py -submit_trans <run_name> -id_list "40,624"
    python local/judge.py -submit_gen <run_name> --max_cases 30 --max_workers 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from local.common import KEY_TO_LABEL, LABEL_TO_KEY, TESTCASES_DIR, load_json  # noqa: E402
from local.gen_testcases.design_cases import DESIGN_QIDS  # noqa: E402

# 放在**模块级**（而不是 judge_one 内部）是为了让它可被测试打补丁 ——
# 分块路径的回归测试要临时调小预算来强制走那条路径（见 tests/test_chunked_judging.py）。
from local.gen_testcases.differential import (DRIVER_SIZE_BUDGET,  # noqa: E402
                                              chunk_indices)
from local.harness.render import (extract_plain_entry, render_design_driver,  # noqa: E402
                                  render_plain_driver)
from local.harness.runner import (DOCKER_IMAGE, InfrastructureError, ExecResult,  # noqa: E402
                                  run_submission)
from local.harness.typespec import (DesignSig, PlainSig, UnsupportedProblemError,
                                    drop_unrepresentable,
                                    parse_python_snippet)  # noqa: E402

from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputVerifier, PROTOCOL

JUDGE_VERSION = "0.2.0"

# ASan 确认 pass：常规判定为 Accepted 的 C/C++ 提交再跑一次 AddressSanitizer，
# 命中未定义行为（越界读写等）就改判 Runtime Error，以对齐 LeetCode 的口径
# （LeetCode 对越界读报 RE，普通编译会静默容忍）。
#
# 实测取舍（务必按需关闭）：
#   - 有效性：合成用例（q1550 的 arr[-1] 写法）能被正确抓成 RE ✓
#   - 收益  ：在 1215 个"本地判 Accepted"的 C/C++ 槽位里按题分层抽样 90 条，
#             命中 **0 条** —— 这个漏洞真实存在，但当前语料没有被触发
#   - 代价  ：被接受的 C/C++ 提交要多一次容器往返（约 2×，占 8 语言中的 2 种）
# 默认开启，因为"UB 被判 AC"会静默抬高分数；跑大批量任务可用 --no_asan 关掉。
ASAN_CONFIRM = True

GEN_FILE_RE = re.compile(r"^(\d+)_([A-Za-z0-9+#]+)(?:_(\d+))?\.txt$")
TRANS_FILE_RE = re.compile(r"^(\d+)_([A-Za-z0-9+#]+)_([A-Za-z0-9+#]+)(?:_(\d+))?\.txt$")


def parse_code_filename(name: str) -> Optional[dict]:
    """Mirror CodeTest6's flat filename contract."""
    m = GEN_FILE_RE.match(name)
    if m and m.group(2) in LABEL_TO_KEY:
        return {"qid": int(m.group(1)), "lang": LABEL_TO_KEY[m.group(2)],
                "cand": int(m.group(3) or 1), "task": "gen"}
    m = TRANS_FILE_RE.match(name)
    if m and m.group(2) in LABEL_TO_KEY and m.group(3) in LABEL_TO_KEY:
        return {"qid": int(m.group(1)), "src": LABEL_TO_KEY[m.group(2)],
                "tgt": LABEL_TO_KEY[m.group(3)], "cand": int(m.group(4) or 1),
                "task": "trans"}
    return None


def load_cases(qid: int) -> Optional[list[dict]]:
    p = TESTCASES_DIR / str(qid) / "cases.json"
    if p.exists():
        return load_json(p)
    return None


def _clamp_failed(failed: int, n: int) -> int:
    """把 `failed_case` 夹到 `[0, n)`。

    A-006b（审查代理 A 实测复现、主代理复核确认）：`failed_case` 是**从 stdout 解析
    出来的、用户可控的整数**，没有任何上界校验。A 的复现件用
    `atexit.register(lambda: print("FAIL 999"))` —— driver 打印 `FAIL 0` 并 `exit(3)`
    之后，atexit 处理器再打印 `FAIL 999`；因为 `map_status` 现在取**最后一条** FAIL 行
    （A-006 的修法），于是得到：

        ac_status=Wrong Answer, total_testcases=26, **total_correct=999**

    `total_correct > total_testcases` 是不可能值，会污染指标与 `correct += failed_case`
    的分块累计。

    **注意**：这个缺陷是我修 A-006 时引入的 —— 取第一条时该反例给 0（正确值），
    取最后一条时给 999。两个方向都可被蓄意利用，所以**根治办法是夹取**，
    而不是在"取第一条/最后一条"之间选。

    夹到 `n`（而不是 `n-1`）：driver 在**第 k 例失败**前已经通过了 k 例，
    索引 k 对应的 `total_correct` 就是 k；k == n 时全部通过（那种情况走 Accepted 分支）。
    """
    if failed is None:
        return 0
    return max(0, min(int(failed), int(n)))


def _confirm_asan(out: dict, lang: str, driver: str, n_cases: int,
                  backend: str, run_timeout_s: float, *, qid: int, cases: list[dict], case_offset: int = 0) -> bool:
    """Return true only when the sanitizer check completed and accepted."""
    meta = out["_meta"]
    attempts = meta.setdefault("asan_attempts", [])
    for attempt in range(2):
        try:
            checked = run_submission(lang, driver, limit=n_cases, backend=backend,
                                     run_timeout_s=run_timeout_s, asan=True,
                                     output_verifier=OutputVerifier(qid, cases))
        except Exception as error:
            attempts.append({"status": "infrastructure_error", "error": str(error)})
            if attempt == 0:
                continue
            meta["asan_status"] = "infrastructure_error"
            meta["asan_error"] = f"{type(error).__name__}: {error}"
            out["state"] = "INCOMPLETE"
            return False
        attempts.append({"status": checked.status, "supervisor_protocol": checked.supervisor_protocol})
        if checked.status == "Accepted":
            meta["asan_status"] = "passed"
            return True
        if (checked.status == "Wrong Answer" and checked.output_protocol == PROTOCOL
                and type(checked.total_correct) is int
                and 0 <= checked.total_correct < n_cases):
            # A host-checked wrong value is a completed negative observation,
            # even without an ASan diagnostic (e.g. uninitialized heap data).
            # Do not claim a sanitizer-diagnosed memory violation.
            meta["asan_status"] = "output_mismatch"
            meta["error"] = "ASan execution output rejected by host checker: " + checked.log[:400]
            meta["asan_failed_case"] = case_offset + checked.total_correct
            out["ac_status"] = "Wrong Answer"
            out["total_correct"] = case_offset + checked.total_correct
            return False
        if checked.status == "Runtime Error" and "AddressSanitizer" in (checked.stderr or ""):
            meta["asan_status"] = "failed"
            meta["asan"] = "undefined behaviour detected"
            meta["error"] = (checked.log or "")[:500]
            out["ac_status"] = "Runtime Error"
            return False
        # A timeout, failed sanitizer compilation or unexplained crash is not
        # evidence that the required check passed, nor a normal-submission TLE.
        meta["asan_status"] = "timeout" if checked.status == "Time Limit Exceeded" else "incomplete"
        meta["asan_error"] = f"ASan check did not complete: {checked.status}: {checked.log[:300]}"
        out["state"] = "INCOMPLETE"
        return False
    return False


def judge_one(code_path: Path, task: str, max_cases: int, backend: str,
              run_timeout_s: int = 5,
              cases_override: Optional[list[dict]] = None) -> dict:
    """Judge one code file; returns the 9-field result dict + meta.

    `cases_override` lets the coverage audit judge the same submission against a
    different case set (e.g. the un-truncated one) through this exact code path,
    so the two verdicts are comparable.
    """
    meta = parse_code_filename(code_path.name)
    assert meta, f"unparseable code filename: {code_path.name}"
    qid = meta["qid"]
    lang = meta["tgt"] if task == "trans" else meta["lang"]
    cases = cases_override if cases_override is not None else load_cases(qid)
    out = {
        "submit_id": 0, "state": "SUCCESS", "ac_status": "Accepted",
        "total_testcases": 0, "total_correct": 0,
        "runtime": "0 ms", "runtime_percentile": 0.0,
        "memory": "0 MB", "memory_percentile": 0.0,
        "_meta": {"qid": qid, "lang": lang, "task": task,
                  "code": str(code_path), "error": "",
                  "asan_required": bool(ASAN_CONFIRM and lang in ("c", "cpp") and backend == "docker"),
                  "asan_status": "not_applicable", "output_protocol": PROTOCOL},
    }
    if cases is None:
        out["state"] = "UNKNOWN"
        out["ac_status"] = "Wrong Answer"
        out["_meta"]["error"] = f"no test corpus for qid {qid}"
        return out
    if cases_override is None:
        cases = cases[:max_cases]  # production truncation; an override is used as-is
    user_code = code_path.read_text(encoding="utf-8", errors="replace")

    from local.common import load_snippet
    from local.harness.render import build_entries
    try:
        sig = parse_python_snippet(load_snippet(qid, "python3"))
        # Defensive: a corpus value no target language can represent makes the
        # generated driver fail to compile, and the submission would be blamed
        # with a spurious Compile Error. Drop such cases here so a stale corpus
        # cannot distort the score.
        # `entries` lets the check honour each language's DECLARED type, so a
        # value that is 64-bit everywhere (q1922's `long n`) is kept.
        cases, dropped_oom = drop_unrepresentable(sig, cases, build_entries(qid))
        out["_meta"]["dropped_unrepresentable"] = len(dropped_oom)
        if not cases:
            out["state"] = "UNKNOWN"
            out["ac_status"] = "Compile Error"
            out["_meta"]["error"] = (
                f"all {len(dropped_oom)} cases unrepresentable in target languages")
            return out
        if qid in DESIGN_QIDS:
            assert isinstance(sig, DesignSig)
            entry = {}
            drv = render_output_driver(lang, sig, entry, cases, user_code)
        else:
            assert isinstance(sig, PlainSig)
            entry = extract_plain_entry(lang, load_snippet(qid, lang))
            drv = render_output_driver(lang, sig, entry, cases, user_code)
    except UnsupportedProblemError as e:
        # The harness cannot build a driver for this problem shape (unsupported
        # signature, or a design problem with no op table). ac_status must stay
        # inside the canonical vocabulary -- clean_results.py raises on anything
        # else -- but `state` marks it so it is not read as "the submission
        # failed to compile", which is what used to happen silently.
        out["state"] = "UNSUPPORTED"
        out["ac_status"] = "Compile Error"
        out["_meta"]["error"] = f"unsupported problem: {e}"
        out["_meta"]["unsupported"] = True
        return out
    except Exception as e:  # noqa: BLE001
        out["ac_status"] = "Compile Error"
        out["state"] = "INCOMPLETE"
        out["_meta"]["error"] = f"driver render failed: {type(e).__name__}: {e}"
        return out

    # Compile/run budget: a corpus holding large-scale cases makes a
    # multi-megabyte driver. Measured on q2270 (30 small + 10 large cases,
    # 4.7 MB driver): python3 hit the 512 MB run cap and Roslyn OOM'd compiling
    # C#. Chunk the corpus so each driver stays within budget -- results merge as
    # "first failing case wins", matching the single-driver semantics.
    # 显式传预算（而不是用 chunk_indices 的默认值），这样测试可以临时调小它
    # 来**强制走分块路径** —— 否则分块相关的问题永远不会被测到。
    groups = chunk_indices(cases, DRIVER_SIZE_BUDGET)
    if len(groups) > 1:
        # Charge measured execution only. Compilation, rendering and container
        # startup are excluded just as they are on the unchunked path.
        # Separate processes still reset submission state; record that limitation.
        total_runtime_ms = 0.0
        peak_mem_mb = 0.0
        runtime_observed = memory_observed = True
        total_wall_ms = 0.0
        wall_observed = True
        chunk_rows: list[dict] = []
        supervisor_protocols = set()
        timing_sources = set()
        res = None
        correct = 0
        for ci, idxs in enumerate(groups):
            sub = [cases[i] for i in idxs]
            share = run_timeout_s - total_runtime_ms / 1000.0
            if share <= 0:
                res = ExecResult("Time Limit Exceeded", log="Aggregate execution budget exhausted")
                break
            try:
                if qid in DESIGN_QIDS:
                    d = render_output_driver(lang, sig, entry, sub, user_code)
                else:
                    d = render_output_driver(lang, sig, entry, sub, user_code)
            except Exception as e:  # noqa: BLE001
                out["state"] = "INCOMPLETE"
                out["ac_status"] = "Compile Error"
                out["_meta"]["error"] = f"driver render failed: {type(e).__name__}: {e}"
                return out
            res = run_submission(lang, d, limit=len(sub), backend=backend,
                                 run_timeout_s=share, output_verifier=OutputVerifier(qid, sub, signature=sig))
            supervisor_protocols.add(res.supervisor_protocol)
            timing_sources.add(res.timing_source)
            runtime_observed = runtime_observed and res.runtime_available
            memory_observed = memory_observed and res.memory_available
            wall_observed = wall_observed and res.wall_ms is not None
            if res.runtime_available:
                total_runtime_ms += res.runtime_ms
            if res.memory_available:
                peak_mem_mb = max(peak_mem_mb, res.memory_mb)
            if res.wall_ms is not None:
                total_wall_ms += res.wall_ms
            chunk_rows.append({
                "chunk": ci, "cases": len(sub), "timeout_s": share,
                "status": res.status,
                "runtime_ms": res.runtime_ms if res.runtime_available else None,
                "memory_mb": res.memory_mb if res.memory_available else None,
                "wall_ms": res.wall_ms, "failed_case": res.failed_case,
            })
            if res.status == "Accepted" and not res.runtime_available:
                out["state"] = "INCOMPLETE"
                out["_meta"]["timing_error"] = "Cannot enforce aggregate budget without observed runtime"
                break
            if res.status == "Accepted" and total_runtime_ms > run_timeout_s * 1000:
                res = ExecResult("Time Limit Exceeded", log="Aggregate execution budget exceeded")
                break
            if res.status == "Accepted":
                correct += len(sub)
                continue
            if res.total_correct is not None:
                correct += res.total_correct
            elif res.status == "Wrong Answer" and res.failed_case is not None:
                correct += _clamp_failed(res.failed_case, len(sub))
            break
        out["ac_status"] = res.status
        # 耗时**累加**（各块串行执行，总耗时就是它们之和）、内存取**峰值**
        out["runtime"] = f"{total_runtime_ms:.0f} ms" if runtime_observed else ""
        out["memory"] = f"{peak_mem_mb:.1f} MB" if memory_observed else ""
        out["_meta"]["timing"] = {
            "runtime_ms": total_runtime_ms if runtime_observed else None,
            "memory_mb": peak_mem_mb if memory_observed else None,
            "wall_ms": total_wall_ms if wall_observed else None,
            "source": next(iter(timing_sources)) if runtime_observed and len(timing_sources) == 1 else "unavailable",
            "scope": "sum of submission and output-driver execution; excludes compilation, host checking and ASan",
            "budget_s": run_timeout_s,
        }
        out["total_testcases"] = len(cases)
        out["total_correct"] = correct
        out["_meta"]["error"] = res.log[:500]
        out["_meta"]["chunks"] = len(groups)
        out["_meta"]["chunk_detail"] = chunk_rows
        out["_meta"]["chunk_state_reset"] = True
        if len(supervisor_protocols) == 1:
            out['_meta']['execution_supervisor'] = next(iter(supervisor_protocols))

        if out["state"] == "SUCCESS" and out["_meta"]["asan_required"] and out["ac_status"] == "Accepted":
            out["_meta"]["asan_status"] = "pending"
            for idxs in groups:
                sub = [cases[i] for i in idxs]
                d = render_output_driver(lang, sig, entry, sub, user_code)
                if not _confirm_asan(out, lang, d, len(sub), backend, run_timeout_s, qid=qid, cases=sub, case_offset=idxs[0]):
                    break
        return out

    res = run_submission(lang, drv, limit=len(cases), backend=backend,
                         run_timeout_s=run_timeout_s, output_verifier=OutputVerifier(qid, cases, signature=sig))
    out["ac_status"] = res.status
    out['_meta']['execution_supervisor'] = res.supervisor_protocol
    out["runtime"] = f"{res.runtime_ms:.0f} ms" if res.runtime_available else ""
    out["memory"] = f"{res.memory_mb:.1f} MB" if res.memory_available else ""
    out["_meta"]["timing"] = {
        "runtime_ms": res.runtime_ms if res.runtime_available else None,
        "memory_mb": res.memory_mb if res.memory_available else None,
        "wall_ms": res.wall_ms,
        "source": res.timing_source if res.runtime_available else "unavailable",
        "scope": "submission and output-driver execution; excludes compilation, host checking and ASan",
    }
    if res.status == "Accepted":
        out["total_testcases"] = len(cases)
        out["total_correct"] = len(cases)
    elif res.status == "Wrong Answer" and res.failed_case is not None:
        out["total_testcases"] = len(cases)
        out["total_correct"] = _clamp_failed(res.failed_case, len(cases))
    else:
        out["total_testcases"] = len(cases)
        out["total_correct"] = 0
    if res.total_correct is not None:
        out["total_correct"] = res.total_correct
    out["_meta"]["error"] = res.log[:500]

    if out["state"] == "SUCCESS" and out["_meta"]["asan_required"] and out["ac_status"] == "Accepted":
        out["_meta"]["asan_status"] = "pending"
        _confirm_asan(out, lang, drv, len(cases), backend, run_timeout_s, qid=qid, cases=cases)
    return out


def result_path(base: Path, meta: dict, task: str) -> Path:
    # result filenames use the language keys (cpp/csharp/python3/...), matching
    # CodeTest6's LANGDICT convention consumed by downstream filename regexes.
    if task == "trans":
        name = f"{meta['qid']}_{meta['src']}_{meta['tgt']}_{meta['cand']}.json"
    else:
        name = f"{meta['qid']}_{meta['lang']}_{meta['cand']}.json"
    return base / str(meta["qid"]) / name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-submit_gen", default="")
    ap.add_argument("-submit_trans", default="")
    ap.add_argument("-id_list", default="")
    ap.add_argument("--max_cases", type=int, default=30)
    ap.add_argument("--max_workers", type=int, default=4)
    ap.add_argument("--backend", default="docker", choices=["host", "docker"])
    # 默认 5s：LeetCode 每题约 2-10s。原先的 20s 对 TLE 保真度太宽松——实测同一批
    # 21 个 false_ac 槽位，20s 只修好 1 个、5s 修好 8 个；而 100 题 × 8 语言
    # 参考解在 5s 下仍全部通过（800/800）。
    ap.add_argument("--run_timeout_s", type=int, default=5)
    ap.add_argument("--no_asan", action="store_true",
                    help="关闭 C/C++ 的 AddressSanitizer 确认 pass（见 ASAN_CONFIRM）")
    ap.add_argument("--out_dir", default="",
                    help="override the result root (e.g. Submit_Result/Submit_Results_<run>_local)")
    ap.add_argument("--code_root", default="",
                    help="override the code root (absolute or relative to cwd)")
    args = ap.parse_args()

    if args.submit_gen:
        task, name = "gen", args.submit_gen
        code_root = Path("Submit_Gen") / name / "codes"
        result_root = Path("Submit_Result") / f"Submit_Results_{name}"
    elif args.submit_trans:
        task, name = "trans", args.submit_trans
        code_root = Path("Submit_Trans") / name / "codes"
        result_root = Path("Submit_Result") / f"Submit_Results_Trans_{name}"
    else:
        ap.error("one of -submit_gen / -submit_trans is required")
    if args.code_root:
        code_root = Path(args.code_root)
    if args.out_dir:
        result_root = Path(args.out_dir)

    if not code_root.is_dir():
        sys.exit(f"code root not found: {code_root}")

    id_list = [int(x) for x in args.id_list.split(",") if x.strip()]
    code_files = sorted(code_root.glob("*.txt"))
    tasks = []
    for cf in code_files:
        meta = parse_code_filename(cf.name)
        if not meta:
            print(f"skip unparseable filename: {cf.name}")
            continue
        if id_list and meta["qid"] not in id_list:
            continue
        rp = result_path(result_root, meta, task)
        if rp.exists():
            continue  # resume by existence
        tasks.append((cf, rp))

    print(f"judge v{JUDGE_VERSION} | task={task} run={name} backend={args.backend} "
          f"image={DOCKER_IMAGE} | {len(tasks)} pending of {len(code_files)} code files")

    n_done = 0
    n_oom = 0
    global ASAN_CONFIRM
    if getattr(args, "no_asan", False):
        ASAN_CONFIRM = False

    n_unsupported = 0

    def work(t):
        cf, rp = t
        out = judge_one(cf, task, args.max_cases, args.backend, args.run_timeout_s)
        meta = out.pop("_meta")
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return out["ac_status"], meta

    if args.max_workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as ex:
            for status, meta in ex.map(work, tasks):
                n_done += 1
                n_oom += meta.get("dropped_unrepresentable", 0)
                n_unsupported += 1 if meta.get("unsupported") else 0
                print(f"[{n_done}/{len(tasks)}] {meta['qid']} "
                      f"{KEY_TO_LABEL[meta['lang']]:11s} {status}")
    else:
        for t in tasks:
            status, meta = work(t)
            n_done += 1
            n_oom += meta.get("dropped_unrepresentable", 0)
            n_unsupported += 1 if meta.get("unsupported") else 0
            print(f"[{n_done}/{len(tasks)}] {meta['qid']} "
                  f"{KEY_TO_LABEL[meta['lang']]:11s} {status}")
    if n_oom:
        print(f"warning: dropped {n_oom} corpus case(s) no target language can "
              f"represent; rebuild the corpus with the fixed pipeline")
    if n_unsupported:
        print(f"warning: {n_unsupported} file(s) belong to problems the harness "
              f"cannot judge; their ac_status is 'Compile Error' but state is "
              f"'UNSUPPORTED' -- do not read them as model failures")

    # judge metadata (ignored by all downstream consumers)
    meta_path = result_root / "judge_meta.json"
    corpus_hash = _corpus_hash()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({
        "judge_version": JUDGE_VERSION,
        "docker_image": DOCKER_IMAGE,
        "task": task,
        "run_name": name,
        "max_cases": args.max_cases,
        "backend": args.backend,
        "corpus_sha256": corpus_hash,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "judged_files": n_done,
        "dropped_unrepresentable_cases": n_oom,
        "unsupported_problem_files": n_unsupported,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"done: {n_done} results under {result_root}")


def _corpus_hash() -> str:
    h = hashlib.sha256()
    files = sorted(TESTCASES_DIR.rglob("cases.json"))
    for p in files:
        h.update(str(p.relative_to(TESTCASES_DIR)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16] if files else "empty"


if __name__ == "__main__":
    main()
