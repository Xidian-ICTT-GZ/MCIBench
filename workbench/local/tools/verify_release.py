"""Behavioral regression plus exact artifact checks. Run from repository root."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from local.harness.evidence import valid_measurement, load_evidence


def golden_errors(rows: list[dict], expected: set[tuple], fingerprint: str, protocol: int) -> list[str]:
    errors = []
    pairs = [(r.get("qid"), r.get("lang")) for r in rows]
    if len(pairs) != len(set(pairs)) or set(pairs) != expected:
        errors.append("reference coverage is not exactly the planned matrix")
    for row in rows:
        slot = f"{row.get('qid')}/{row.get('lang')}"
        if row.get("fingerprint") != fingerprint or row.get("protocol") != protocol:
            errors.append(f"{slot}: stale reference identity/protocol")
        if row.get("status_full") != "Accepted":
            errors.append(f"{slot}: reference not Accepted")
        if not valid_measurement(row.get("runtime_ms")):
            errors.append(f"{slot}: observed timing missing")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="Only the isolated behavior regressions")
    ap.add_argument("--artifacts-only", action="store_true")
    ap.add_argument("--base-url", default="http://127.0.0.1:8090", help="Served dashboard checked by full release verification")
    args = ap.parse_args()
    errors = []
    if not args.artifacts_only:
        suites = ["test_identity_production", "test_import_identity", "test_rebuild_expected",
                  "test_publication", "test_publication_lock", "test_checked_publication", "test_asan_admission", "test_chunk_budget",
                  "test_release_evidence", "test_image_resolution", "test_status_table", "test_dashboard_reconciliation",
                  "test_unverified_recovery", "test_output_protocol", "test_output_integration", "test_process_capture",
                  "test_supervisor_report", "test_output_collection", "test_wide_evidence",
                  "test_gap_workflow", "test_routed_constraints", "test_routed_cleanup"]
        command = [sys.executable, "-B", "-X", "utf8", "-m", "unittest", "-q",
                   *["local.tests." + name for name in suites]]
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            errors.append("isolated behavior tests failed")
    if not args.offline:
        from local.common import LANGS, load_ft_test_qids
        from local.gen_testcases.validate import fingerprint, REFERENCE_PROTOCOL
        from local.dashboard.scripts import judge_all_models as batch
        from local.dashboard.scripts.import_local_results import inspect_result
        qids = load_ft_test_qids()
        path = ROOT / "local/results/golden_check.json"
        try:
            rows = [load_evidence(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            errors.extend(golden_errors(rows, {(q, lang) for q in qids for lang in LANGS},
                                        fingerprint(qids), REFERENCE_PROTOCOL))
        except Exception as exc:
            errors.append("reference artifacts unavailable: " + str(exc))
        from local.common import LABEL_TO_KEY
        con = batch.open_db()
        try:
            planned = set(con.execute(
                "SELECT qid,model_name,language,attempt_num FROM gen_codes WHERE attempt_num=1 "
                "AND code IS NOT NULL AND code<>'' AND qid IN (" + ",".join("?" for _ in qids) + ")", qids))
        finally:
            con.close()
        checked = 0
        for qid, model, label, cand in sorted(planned):
            lang = LABEL_TO_KEY.get(label)
            if lang not in LANGS:
                continue
            checked += 1
            path = batch.OUT_ROOT / model / "results" / str(qid) / f"{qid}_{lang}_{cand}.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                status, reason = inspect_result(payload, model=model, qid=qid, lang=lang, cand=cand)
                if status != "current":
                    errors.append(f"{model}/{qid}/{lang}: {status}: {reason}")
            except Exception as exc:
                errors.append(f"{model}/{qid}/{lang}: {exc}")
        if checked == 0:
            errors.append("no planned model slots")
        print(f"Checked {checked} planned model slots")
        from local.tools.verify_dashboard import audit_database
        try:
            db_errors, snapshot = audit_database(base_url=None if args.artifacts_only else args.base_url)
            errors.extend(db_errors)
            print(f"Database coverage: {snapshot['coverage']}")
        except Exception as exc:
            errors.append("database/service verification unavailable: " + str(exc))
    # ------------------------------------------------------------------
    # 宿主解释器诊断（2026-10-12 复核补充）
    #
    # 结果身份里含 `config.host_python`（`platform.python_version()`）——
    # 判据本身是对的：宿主 Python 负责输出校验与答案比对，版本变了判定可能变。
    # 但**没有文档说明**，于是用另一个解释器验收时，几千个槽位会被判 stale，
    # 看起来像"结果全废了"。实测：用 msys64 的 3.14.5 跑，4000 个槽位报
    # `stale: config.host_python`；换成产出结果时用的 3.12.14 就 0 失败。
    #
    # 这里不改变判定（stale 仍然是 stale），只是把原因**单独说清楚**，
    # 并给出该用哪个解释器。
    # ------------------------------------------------------------------
    hp = [e for e in errors if "host_python" in e]
    if hp:
        try:
            import json as _json
            import platform as _plat
            from local.common import LABEL_TO_KEY, LANGS as _L, load_ft_test_qids as _q
            from local.dashboard.scripts import judge_all_models as _b
            want = None
            for _qid in _q():
                for _lang in _L:
                    _p = (_b.OUT_ROOT / "gpt-4o" / "results" / str(_qid)
                          / f"{_qid}_{_lang}_1.json")
                    if _p.exists():
                        _d = _json.loads(_p.read_text(encoding="utf-8"))
                        want = ((_d.get("_identity") or {}).get("config")
                                or {}).get("host_python")
                        break
                if want:
                    break
            print()
            print("=" * 70)
            print("宿主解释器不匹配 —— 这不是结果过期，是验收用错了 Python")
            print("=" * 70)
            print(f"  结果是用 host_python = {want} 产出的")
            print(f"  本次验收用的是       = {_plat.python_version()}"
                  f"   ({sys.executable})")
            print(f"  受影响槽位           = {len(hp)}")
            print("  结果身份绑定宿主解释器版本（它负责输出校验与答案比对），"
                  "所以必须用同一个解释器验收。")
            print("  修复：改用产出这批结果时的解释器重跑本命令。")
            print("=" * 70)
        except Exception:  # noqa: BLE001
            pass
    for error in errors[:30]:
        print("FAIL:", error)
    print(f"verification failures: {len(errors)}")
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
