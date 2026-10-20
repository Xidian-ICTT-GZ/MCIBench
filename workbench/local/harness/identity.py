# -*- coding: utf-8 -*-
"""Versioned identities shared by production judging, reuse and import.

Missing evidence never compares equal, including missing nested values.
All per-problem templates are bound because representability uses all languages.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

IDENTITY_SCHEMA = 2

REPO_ROOT = Path(__file__).resolve().parents[2]

# 判题器身份的**根**：从这里出发走导入闭包。
_JUDGE_ENTRY = "local/judge.py"

class ImageUnavailable(RuntimeError):
    """拿不到镜像 digest —— A-119：必须显式失败，不能静默降级成另一个指纹。"""


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@lru_cache(maxsize=256)
def _imports(source: str, package: str) -> tuple[str, ...]:
    import ast
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts)-node.level+1] + ([base] if base else []))
            modules.add(base)
            modules.update(base + "." + a.name for a in node.names if a.name != "*")
    return tuple(sorted(m for m in modules if m == "local" or m.startswith("local.")))


def judge_source_closure() -> tuple[tuple[str, str], ...]:
    """Read source afresh; cache only AST parsing so edits remain observable."""
    seen, todo = {}, [_JUDGE_ENTRY]
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        seen[rel] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        package = rel.rsplit("/", 1)[0].replace("/", ".")
        for mod in _imports(source, package):
            parts = mod.split(".")
            for i in range(1, len(parts) + 1):
                init = "/".join(parts[:i]) + "/__init__.py"
                if (REPO_ROOT / init).is_file():
                    todo.append(init)
            path = mod.replace(".", "/") + ".py"
            if (REPO_ROOT / path).is_file():
                todo.append(path)
    return tuple(sorted(seen.items()))


@lru_cache(maxsize=8)
def _resolve_image(image: str) -> str:
    """镜像 digest —— 进程内缓存一次；**持续**拿不到才显式失败（A-119）。

    ## 为什么要重试

    实测：`docker image inspect` 会**瞬时**失败（daemon 短暂无响应），
    报 `No such image: local-judge:1`，而镜像其实**在**（`docker images` 能看到）。
      - 一失败就放弃 → `validate` 会在机器只是"忙一下"时整体失败 ✗
      - 静默降级成一个别的值 → 指纹**抖动** ✗（实测同一工作树在同一机器上
        20 分钟内出现两个不同的"当前指纹"：`93d99a8a3afd48c4` 与
        `5fbb3683a17e2e58`，差别就是镜像那一项）
    所以：**重试 3 次、间隔递增；仍然拿不到才失败**。
    """
    import time as _t
    last = ""
    for i in range(3):
        r = subprocess.run(
            ["docker", "image", "inspect", image,
             "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip()
        if r.returncode == 0 and re.fullmatch(r"sha256:[0-9a-f]{64}", out):
            return out
        # Docker Desktop can list a tag while inspect(tag) fails. Resolve via
        # inventory, then independently inspect the immutable ID and verify its
        # RepoTags; never substitute an unavailable marker or an arbitrary ID.
        listed = subprocess.run(
            ["docker", "image", "ls", "--no-trunc", "--filter", f"reference={image}",
             "--format", "{{.ID}}"], capture_output=True, text=True, timeout=20)
        ids = set(listed.stdout.split()) if listed.returncode == 0 else set()
        if len(ids) == 1:
            candidate = ids.pop()
            if re.fullmatch(r"sha256:[0-9a-f]{64}", candidate):
                inspected = subprocess.run(["docker", "image", "inspect", candidate],
                                           capture_output=True, text=True, timeout=20)
                try:
                    record = json.loads(inspected.stdout)[0]
                    if (inspected.returncode == 0 and record["Id"] == candidate
                            and image in (record.get("RepoTags") or [])):
                        return candidate
                except (ValueError, IndexError, KeyError, TypeError):
                    pass
        last = f"rc={r.returncode} stderr={(r.stderr or '').strip()[:120]}"
        if i < 2:
            _t.sleep(2.0 * (i + 1))
    raise ImageUnavailable(
        f"重试 3 次仍拿不到 local-judge:1 的镜像 digest: {last}")


def image_digest() -> str:
    from local.harness.runner import DOCKER_IMAGE
    try:
        return _resolve_image(DOCKER_IMAGE)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ImageUnavailable(str(e)) from e


def image_digest_or_tag() -> str:
    """给"允许镜像不可用"的调用方（例如离线跑只读自检）用。

    返回 `digest` 或 `"unavailable:<原因摘要>"` —— **两种含义不共用一个字符串**
    （A-119 的核心要求）。
    """
    try:
        return image_digest()
    except Exception as e:  # noqa: BLE001
        return f"unavailable:{type(e).__name__}"


def corpus_content_sha(qid: int, testcases_dir: Path | None = None) -> str | None:
    """**per-qid** 语料内容哈希（原始字节，天然覆盖顺序）。A-108。

    语料不存在时返回 `None` —— 调用方必须把 `None` 判为**过期**（A-110）。
    """
    from local.common import TESTCASES_DIR
    d = testcases_dir or TESTCASES_DIR
    p = d / str(qid) / "cases.json"
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def template_sha(qid: int, lang: str) -> dict[str, str | None]:
    """**模板对**（A-102 第②点）：(python3 模板, 目标语言模板)。

    只绑"该语言的模板"会漏掉**签名**变化 —— 而签名来自 python3 模板。
    """
    from local.common import load_snippet, LANGS
    lang = language_key(lang)
    out: dict[str, str | None] = {}
    for tag, l in (("signature", "python3"), ("target", lang)):
        try:
            txt = load_snippet(qid, l)
        except Exception:  # noqa: BLE001
            txt = None
        out[tag] = (hashlib.sha256(txt.encode("utf-8")).hexdigest()
                    if isinstance(txt, str) and txt else None)
    # Representability checks call build_entries() for every language.
    out["all"] = {}
    for key in LANGS:
        try:
            text = load_snippet(qid, key)
            out["all"][key] = code_sha(text) if isinstance(text, str) and text else None
        except (OSError, ValueError, KeyError):
            out["all"][key] = None
    return out


def language_key(lang: str) -> str:
    from local.common import KEY_TO_LABEL, LABEL_TO_KEY
    key = LABEL_TO_KEY.get(lang, lang)
    if key not in KEY_TO_LABEL:
        raise IdentityUnavailable(f"Unknown language: {lang!r}")
    return key


class IdentityUnavailable(ValueError):
    pass


def code_sha(text: str) -> str:
    return hashlib.sha256(normalize_code(text).encode("utf-8")).hexdigest()


def normalize_code(text: str) -> str:
    """A-111：库文本规范化 —— 换行统一为 `\\n`，去掉尾部空白差异。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def submission_sha_from_db(db: Path, qid: int, model: str, lang: str,
                           attempt: int = 1) -> dict:
    """从主库 `gen_codes` 取**规范化文本**的提交代码身份（A-111）。

    返回 `{sha, gen_codes_id, attempt_num, found}`；查不到时 `found=False`
    —— 调用方应把它当**无法证明**处理，而不是"没变"。
    """
    from local.common import KEY_TO_LABEL
    lang = KEY_TO_LABEL[language_key(lang)]
    if not db.exists():
        return {"sha": None, "gen_codes_id": None, "attempt_num": attempt,
                "found": False}
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT id, code FROM gen_codes WHERE qid=? AND model_name=? "
            "AND language=? AND attempt_num=? ORDER BY id DESC LIMIT 1",
            (qid, model, lang, attempt)).fetchone()
    except sqlite3.Error:
        return {"sha": None, "gen_codes_id": None, "attempt_num": attempt,
                "found": False}
    finally:
        con.close()
    if not row or not isinstance(row[1], str) or not row[1].strip():
        return {"sha": None, "gen_codes_id": None, "attempt_num": attempt,
                "found": False}
    gid, code = row
    sha = hashlib.sha256(normalize_code(code or "").encode("utf-8")).hexdigest()
    return {"sha": sha, "gen_codes_id": gid, "attempt_num": attempt,
            "found": True}


def corpus_admission(qid: int, testcases_dir: Path | None = None) -> str:
    from local.common import TESTCASES_DIR
    directory = (testcases_dir or TESTCASES_DIR) / str(qid)
    if (directory / ".publishing").exists() or (directory.parent / ".publishing").exists():
        return "publishing"
    path = directory / "meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        history = meta.get("publications") or []
        actual = corpus_content_sha(qid, testcases_dir)
        if actual is None:
            return "unverifiable"
        if history:
            latest = history[-1]
            if latest.get("new_sha256") != actual:
                return "unverifiable"
            return latest["status"]
        # Historical admission is limited to an explicit frozen byte manifest.
        # A new or edited corpus must not become "legacy" by omitting metadata.
        manifest = json.loads((directory.parent / "_legacy_admission.json").read_text(encoding="utf-8"))
        return "legacy" if manifest.get("corpus_sha256", {}).get(str(qid)) == actual else "unverifiable"
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return "unverifiable"


def judge_identity(*, qid: int, model: str = "", lang: str = "",
                   submission: dict | None = None,
                   config: dict | None = None,
                   testcases_dir: Path | None = None,
                   require_image: bool = True, attempt: int = 1,
                   task: str = "gen") -> dict:
    """**判题身份** —— 结果可复用的唯一依据。

    任一项为 `None`/缺失 ⇒ 调用方必须判**过期**（A-110）。
    """
    from local.judge import ASAN_CONFIRM  # noqa: PLC0415

    from local.harness import runner
    from local.harness.output_protocol import PROTOCOL
    from local.harness.process_capture import STDOUT_LIMIT, STDERR_LIMIT
    from local.harness.supervised_runner import SUPERVISOR_PROTOCOL
    lang = language_key(lang)
    ident: dict = {
        "schema": IDENTITY_SCHEMA,
        "slot": {"qid": qid, "model": model, "lang": lang, "attempt": attempt, "task": task},
        # ① 判题器（闭包式，A-101）
        "judge_closure": dict(judge_source_closure()),
        # ② 语料内容（per-qid，A-108）
        "corpus_sha256": corpus_content_sha(qid, testcases_dir),
        "corpus_admission": corpus_admission(qid, testcases_dir),
        # ③ 模板对（A-102）
        "template": template_sha(qid, lang) if lang else None,
        # ④ 镜像（A-119：不可用时要么抛错，要么写 "unavailable:..."）
        "image": (image_digest() if require_image else image_digest_or_tag()),
        # ⑤ 生效配置（A-109：含 ASAN_CONFIRM）
        "config": {
            "asan_confirm": bool(ASAN_CONFIRM),
            "backend": "docker", "memory_mb": runner.DOCKER_MEM_MB,
            "host_python": platform.python_version(),
            "cpus": 1, "pids_limit": 128,
            **(config or {}),
            "output_protocol": PROTOCOL,
            "stdout_limit_bytes": STDOUT_LIMIT, "stderr_limit_bytes": STDERR_LIMIT,
            "supervisor_protocol": SUPERVISOR_PROTOCOL, "execution_uid": 65534,
        },
        # ⑥ 提交代码（A-111：规范化库文本）
        "submission": submission,
    }
    return ident


def identity_sha(ident: dict) -> str:
    """身份摘要 —— 用于快速比较（人类可读的短串）。"""
    return hashlib.sha256(
        json.dumps(ident, sort_keys=True, ensure_ascii=False,
                   default=str).encode("utf-8")).hexdigest()


def identity_errors(ident: dict | None) -> list[str]:
    """Validate evidence independently of equality, including nested fields."""
    if not isinstance(ident, dict):
        return ["identity:missing"]
    bad = []
    def require(ok, field):
        if not ok:
            bad.append(field)
    def sha(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    def obj(key):
        val = ident.get(key)
        return val if isinstance(val, dict) else {}
    require(ident.get("schema") == IDENTITY_SCHEMA, "schema")
    slot = obj("slot")
    require(type(slot.get("qid")) is int and slot["qid"] > 0, "slot.qid")
    require(isinstance(slot.get("model"), str) and bool(slot["model"].strip()), "slot.model")
    from local.common import LANGS
    require(slot.get("lang") in LANGS, "slot.lang")
    require(type(slot.get("attempt")) is int and slot["attempt"] > 0, "slot.attempt")
    require(slot.get("task") == "gen", "slot.task")
    require(sha(ident.get("corpus_sha256")), "corpus_sha256")
    require(ident.get("corpus_admission") in ("legacy", "verified"), "corpus_admission")
    closure = obj("judge_closure")
    require(_JUDGE_ENTRY in closure and all(sha(v) for v in closure.values()), "judge_closure")
    template = obj("template")
    require(sha(template.get("signature")), "template.signature")
    require(sha(template.get("target")), "template.target")
    templates = template.get("all")
    require(isinstance(templates, dict) and set(templates) == set(LANGS)
            and all(sha(v) for v in templates.values()), "template.all")
    image = ident.get("image")
    require(isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image), "image")
    sub = obj("submission")
    require(sub.get("found") is True and sha(sub.get("sha")), "submission.sha")
    require(type(sub.get("gen_codes_id")) is int and sub["gen_codes_id"] > 0, "submission.gen_codes_id")
    require(sub.get("attempt_num") == slot.get("attempt") and slot.get("attempt") is not None,
            "submission.attempt_num")
    config = obj("config")
    require(type(config.get("asan_confirm")) is bool, "config.asan_confirm")
    require(config.get("backend") == "docker", "config.backend")
    from local.harness.output_protocol import PROTOCOL
    require(config.get("output_protocol") == PROTOCOL, "config.output_protocol")
    from local.harness.supervised_runner import SUPERVISOR_PROTOCOL
    require(config.get("supervisor_protocol") == SUPERVISOR_PROTOCOL, "config.supervisor_protocol")
    require(config.get("execution_uid") == 65534, "config.execution_uid")
    for field in ("max_cases", "run_timeout_s", "memory_mb", "cpus", "pids_limit"):
        v = config.get(field)
        require(type(v) in (int, float) and 0 < v < float("inf"), "config." + field)
    return bad


def identity_mismatch(saved: dict | None, current: dict) -> list[str]:
    bad = identity_errors(saved) + identity_errors(current)
    if isinstance(saved, dict) and isinstance(current, dict):
        def compare(a, b, prefix=""):
            for key in a.keys() | b.keys():
                path = prefix + key
                if key not in a or key not in b:
                    bad.append(path)
                elif isinstance(a[key], dict) and isinstance(b[key], dict):
                    compare(a[key], b[key], path + ".")
                elif a[key] != b[key]:
                    bad.append(path)
        compare(saved, current)
    return sorted(set(bad))


def verification_identity(db: Path, *, qid: int, model: str, lang: str, attempt: int,
                          config: dict, task: str = "gen", code_path: Path | None = None) -> dict:
    """Identity for isolated repair checks, never admissible as published evidence.

    An existing unverified corpus must be inspectable to repair it. All other
    execution requirements remain mandatory, and active publication is blocked.
    """
    submission = submission_sha_from_db(db, qid, model, lang, attempt)
    ident = judge_identity(qid=qid, model=model, lang=lang, attempt=attempt, task=task,
                           submission=submission, config=config)
    errors = [e for e in identity_errors(ident) if e != "corpus_admission"]
    if ident.get("corpus_admission") == "publishing":
        errors.append("corpus_admission:publishing")
    if code_path is not None and code_sha(code_path.read_text(encoding="utf-8")) != submission["sha"]:
        errors.append("executed_code:database_mismatch")
    if errors:
        raise IdentityUnavailable(", ".join(errors))
    # Deliberately fails production identity_errors even for a verified corpus.
    ident["corpus_admission"] = "verification_only:" + ident["corpus_admission"]
    return ident


def slot_identity(db: Path, *, qid: int, model: str, lang: str, attempt: int,
                  config: dict, task: str = "gen", code_path: Path | None = None) -> dict:
    submission = submission_sha_from_db(db, qid, model, lang, attempt)
    ident = judge_identity(qid=qid, model=model, lang=lang, attempt=attempt, task=task,
                           submission=submission, config=config)
    errors = identity_errors(ident)
    if code_path is not None and code_sha(code_path.read_text(encoding="utf-8")) != submission["sha"]:
        errors.append("executed_code:database_mismatch")
    if errors:
        raise IdentityUnavailable(", ".join(errors))
    return ident


def result_errors(result: dict, expected_identity: dict | None = None) -> list[str]:
    """Only completed, well-formed verdicts may enter a current baseline."""
    errors = []
    if result.get("state") != "SUCCESS":
        errors.append("execution:incomplete")
    verdict = result.get("ac_status")
    if verdict not in {"Accepted", "Wrong Answer", "Compile Error", "Runtime Error",
                       "Time Limit Exceeded", "Memory Limit Exceeded", "Output Limit Exceeded"}:
        errors.append("execution:unknown_verdict")
    n, correct = result.get("total_testcases"), result.get("total_correct")
    if type(n) is not int or type(correct) is not int or not 0 <= correct <= n:
        errors.append("execution:invalid_counts")
    elif verdict == "Accepted" and (n == 0 or correct != n):
        errors.append("execution:incomplete_accepted")
    meta = result.get("_meta") or {}
    ident = expected_identity or result.get("_identity") or {}
    protocol = ident.get("config", {}).get("output_protocol")
    if protocol is not None and meta.get("output_protocol") != protocol:
        errors.append("execution:output_protocol_missing")
    supervisor = ident.get("config", {}).get("supervisor_protocol")
    if supervisor is not None and meta.get("execution_supervisor") != supervisor:
        errors.append("execution:supervisor_missing")
    required = (meta.get("asan_required") or
                (ident.get("config", {}).get("asan_confirm") and
                 ident.get("slot", {}).get("lang") in ("c", "cpp")))
    if verdict == "Accepted" and (meta.get("asan_error") or
                                    (required and meta.get("asan_status") != "passed")):
        errors.append("execution:asan_incomplete")
    return errors
