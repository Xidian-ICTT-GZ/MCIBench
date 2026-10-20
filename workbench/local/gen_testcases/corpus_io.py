# -*- coding: utf-8 -*-
r"""语料写盘的共享工具：**唯一备份** + **原子写** + **meta 同步**。

审查代理 B 的 B-012 要求「语料发布采用可回滚的暂存与原子替换，保存变更原因和原数据」。
这个模块把三件事收成一处，避免每个工具各写一份（B2-002 就是因为我用正则给
`clean_oob.py` 注入了 helper、而 `guarantees.py` 只拿到了调用、没有定义）。

用法：
    from local.gen_testcases.corpus_io import unique_backup, atomic_save, sync_meta
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def unique_backup(path: Path, suffix: str) -> Path:
    """备份**只增不覆盖**，返回实际路径。

    原先是 `if not bak.exists(): copy2(...)` 或直接 `save_json(bak, ...)`，
    第二次运行时把**上一次的回滚点**覆盖掉，于是"删除前状态"只剩最近一次。
    现在加序号：`x.json.bak_pre_oob`、`x.json.bak_pre_oob.1`、…

    顺带把 mtime 设成"现在"（B2-007）：`shutil.copy2` 会继承源文件的旧 mtime，
    按 mtime 巡检新建的备份会**找不到它**（实测：10/9 建的备份显示 10/1）。
    """
    import os
    # B3-005：后缀一律按**字符串拼接**处理。
    # 此前写成 `path.with_suffix(suffix) if not suffix.startswith(".")`，实测：
    #   `.json.bak_constraints` -> `cases.json.json.bak_constraints`（.json 双写）
    #   非点号后缀（`json.bak`） -> ValueError: Invalid suffix
    #   空后缀                  -> `cases`（把扩展名也吃掉）
    # 现在只接受以 "." 开头的后缀，其余直接报错（宁可大声失败）。
    if not suffix.startswith("."):
        raise ValueError(f"备份后缀必须以点号开头，收到 {suffix!r}")
    bak = Path(str(path) + suffix)
    if bak.exists():
        i = 1
        while (alt := Path(f"{path}{suffix}.{i}")).exists():
            i += 1
        bak = alt
    shutil.copy2(path, bak)
    try:
        os.utime(bak, None)          # B2-007：不要继承源文件 mtime
    except OSError:
        pass
    return bak


def atomic_save(path: Path, data, indent: int = 1) -> None:
    """原子写：临时文件 + `os.replace`，中断不会留下半截语料。"""
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent),
                   encoding="utf-8", newline="\n")
    tmp.replace(path)


def sync_meta(cases_path: Path, n_cases: int) -> bool:
    """把 `meta.json` 的 `n_cases` 同步成实际条数（B2-006）。

    此前 `scan_corpus`/`clean_oob`/`guarantees` 改了 `cases.json` 却不动 meta，
    实测 **47 题**的 `n_cases` 与实际不符（本批次又新造 2 条）。
    """
    mp = cases_path.parent / "meta.json"
    if not mp.exists():
        return False
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return False
        meta["n_cases"] = n_cases
        atomic_save(mp, meta)
        return True
    except Exception:  # noqa: BLE001
        return False


def publish_cases(path: Path, cases: list, meta: dict, expected_old: bytes | None) -> None:
    """Single-question and batch publication share the same exclusive root lock."""
    publish_batch(path.parent.parent, [(path, cases, meta, expected_old)])


def prepare_checked_metadata(path: Path, cases: list, expected_old: bytes | None,
                             reason: str, *, allow_unparsed: bool = False,
                             reference_evidence: dict | None = None) -> dict:
    """Run the same admission checks for expansion, cleanup and rebuild writers."""
    import hashlib
    from datetime import datetime
    from local.gen_testcases.constraints import check, unparsed
    from local.gen_testcases.validate import validate_expected
    from local.gen_testcases.apply_found import verify_candidate

    qid = int(path.parent.name)
    unknown = unparsed(qid)
    if unknown and not allow_unparsed:
        raise ValueError(f"q{qid}: unparsed constraints block publication")
    if not cases:
        raise ValueError(f"q{qid}: empty corpus cannot be published")
    for i, case in enumerate(cases):
        violations = check(qid, case)
        if violations:
            raise ValueError(f"q{qid} case {i}: {violations}")
    before = path.read_bytes() if path.exists() else None
    if before != expected_old:
        raise ValueError(f"Corpus changed since planning: {path}")
    evidence = reference_evidence or validate_expected(qid, cases, "docker")
    baseline = json.loads(expected_old) if expected_old is not None else []
    verification = verify_candidate(qid, cases, "docker", baseline_corpus=baseline)
    if (verification.get("skipped") or verification.get("planned", 0) <= 0
            or verification.get("executed") != verification.get("planned")
            or any(verification.get(key, 0) for key in ("missing", "judge_error", "broken", "regressed"))):
        raise ValueError(f"q{qid}: model admission failed: {verification}")
    mp = path.with_name("meta.json")
    meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    if not isinstance(meta, dict):
        raise ValueError(f"Invalid metadata: {mp}")
    meta["n_cases"] = len(cases)
    meta["expected_validation"] = evidence
    meta.setdefault("publications", []).append({
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "status": "unverified" if unknown else "verified",
        "reasons": ["unparsed constraints explicitly allowed"] if unknown else [],
        "operation": reason,
        "old_sha256": hashlib.sha256(expected_old).hexdigest() if expected_old is not None else None,
        "new_sha256": hashlib.sha256(json.dumps(cases, ensure_ascii=False, indent=1).encode("utf-8")).hexdigest(),
        "verification": verification,
    })
    return meta


def publish_checked_cases(path: Path, cases: list, expected_old: bytes | None,
                          reason: str, *, allow_unparsed: bool = False) -> None:
    meta = prepare_checked_metadata(path, cases, expected_old, reason,
                                    allow_unparsed=allow_unparsed)
    publish_cases(path, cases, meta, expected_old)


def publish_batch(root: Path, updates: list[tuple[Path, list, dict, bytes | None]]) -> None:
    """Publish under one exclusive writer/admission lock, retaining crash evidence.

    A rollback never overwrites bytes other than this transaction's output.
    Unsupported writers that ignore the lock cause a recovery-required failure.
    """
    import uuid
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".publishing"
    transaction = uuid.uuid4().hex
    recovery = root / ".publication_history" / transaction
    # Acquire before reading preimages. A second publisher must fail without writes.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"transaction": transaction, "recovery": str(recovery),
                                 "state": "publishing"}, ensure_ascii=False))
    before = {}
    after = {}
    attempted = []
    release_lock = False
    try:
        normalized = []
        for path, cases, meta, expected in updates:
            path = path.resolve()
            if path.parent.parent != root or path.name != "cases.json":
                raise ValueError(f"Not a corpus path under {root}: {path}")
            if path in before:
                raise ValueError(f"Duplicate publication target: {path}")
            if (path.parent / ".publishing").exists():
                raise ValueError(f"Unfinished question publication: {path.parent}")
            old = path.read_bytes() if path.exists() else None
            if old != expected:
                raise ValueError(f"Corpus changed since validation: {path}")
            mp = path.with_name("meta.json")
            before[path] = old
            before[mp] = mp.read_bytes() if mp.exists() else None
            normalized.extend(((path, cases), (mp, meta)))
        recovery.mkdir(parents=True)
        manifest = []
        for target, original in before.items():
            relative = target.relative_to(root)
            manifest.append({"path": relative.as_posix(), "existed": original is not None})
            if original is not None:
                dest = recovery / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(original)
                unique_backup(target, ".bak_publication")
        atomic_save(recovery / "manifest.json", manifest)
        for target, data in normalized:
            target.parent.mkdir(parents=True, exist_ok=True)
            after[target] = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
            attempted.append(target)
            atomic_save(target, data)
        release_lock = True
    except Exception:
        # Keep the lock if rollback itself fails or detects a foreign write.
        for target in reversed(attempted):
            current = target.read_bytes() if target.exists() else None
            original = before[target]
            if current == original:
                continue
            if current != after[target]:
                raise RuntimeError(f"Foreign write detected; manual recovery required: {target}")
            if original is None:
                target.unlink(missing_ok=True)
            else:
                temp = Path(str(target) + ".rollback")
                temp.write_bytes(original)
                temp.replace(target)
        release_lock = True
        raise
    finally:
        if release_lock:
            lock.unlink()
