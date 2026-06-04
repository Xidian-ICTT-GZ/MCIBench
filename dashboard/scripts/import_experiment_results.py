from __future__ import annotations

import csv
import json
import re
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = DASHBOARD_ROOT / "packages" / "server" / "data" / "mcibench.db"
DEPLOY_DB = DASHBOARD_ROOT / "volumes" / "backend-data" / "mcibench.db"

GEN_SUB_RE = re.compile(r"^(?P<qid>\d+)_(?P<lang>[a-zA-Z0-9#]+)_(?P<attempt>\d+)\.json$")
TRANS_SUB_RE = re.compile(r"^(?P<qid>\d+)_(?P<src>[a-zA-Z0-9#]+)_(?P<tgt>[a-zA-Z0-9#]+)_(?P<attempt>\d+)\.json$")
REFERENCE_RE = re.compile(r"^(?P<qid>\d+)_(?P<lang>.+)_ans(?P<attempt>\d+)\.txt$")
SLUG_RE = re.compile(r"\[(?P<slug>[^\]]+)\]")

LANG_SLUGS = {
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "java": "Java",
    "javascript": "JavaScript",
    "python3": "Python3",
    "rust": "Rust",
    "golang": "Golang",
}

CODE_ATTEMPTS_TO_IMPORT = {1, 2, 3, 4, 5}
SLUG_BY_LANG = {value: key for key, value in LANG_SLUGS.items()}
READ_WORKERS = 32
READ_TASK_BATCH = 20000

GEN_CODE_SQL = """
INSERT INTO gen_codes (qid, model_name, language, attempt_num, code, file_path)
VALUES (?, ?, ?, ?, ?, ?)
"""

TRANS_CODE_SQL = """
INSERT INTO translations (qid, model_name, src_lang, tgt_lang, attempt_num, code, file_path)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

SUBMISSION_SQL = """
INSERT INTO submissions
    (qid, model_name, language, src_lang, tgt_lang, attempt_num, submit_id, state, ac_status,
     total_testcases, total_correct, runtime, runtime_percentile, memory, memory_percentile, source_type, source_dir)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def lang_from_slug(slug: str) -> str:
    key = slug.lower()
    if key not in LANG_SLUGS:
        raise ValueError(f"unknown language slug: {slug}")
    return LANG_SLUGS[key]


def as_int(value) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def as_float(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def reset_db() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(DB_PATH) + suffix)
        if target.exists():
            target.unlink()
    print(f"reset db at {DB_PATH}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")
    return conn


def prepare_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            tid TEXT,
            title TEXT,
            slug TEXT,
            url TEXT,
            description TEXT,
            difficulty TEXT,
            is_benchmark INTEGER NOT NULL DEFAULT 0,
            is_generation_benchmark INTEGER NOT NULL DEFAULT 0,
            is_translation_benchmark INTEGER NOT NULL DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS snippets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            language TEXT NOT NULL,
            code TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS "references" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            language TEXT NOT NULL,
            attempt_num INTEGER NOT NULL,
            code TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gen_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            language TEXT NOT NULL,
            attempt_num INTEGER NOT NULL,
            code TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            src_lang TEXT NOT NULL,
            tgt_lang TEXT NOT NULL,
            attempt_num INTEGER NOT NULL,
            code TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            language TEXT NOT NULL,
            src_lang TEXT NOT NULL DEFAULT '',
            tgt_lang TEXT NOT NULL DEFAULT '',
            attempt_num INTEGER NOT NULL,
            submit_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            ac_status TEXT NOT NULL,
            total_testcases INTEGER NOT NULL,
            total_correct INTEGER NOT NULL,
            runtime TEXT NOT NULL,
            runtime_percentile REAL NOT NULL,
            memory TEXT NOT NULL,
            memory_percentile REAL NOT NULL,
            source_type TEXT NOT NULL,
            source_dir TEXT NOT NULL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS generation_pass_ks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            qid INTEGER NOT NULL,
            language TEXT NOT NULL,
            n_candidates INTEGER NOT NULL,
            pass_at_1 REAL NOT NULL,
            pass_at_2 REAL NOT NULL,
            pass_at_3 REAL NOT NULL,
            pass_at_4 REAL NOT NULL,
            pass_at_5 REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS translation_pass_ks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            qid INTEGER NOT NULL,
            src_lang TEXT NOT NULL,
            tgt_lang TEXT NOT NULL,
            n_candidates INTEGER NOT NULL,
            pass_at_1 REAL NOT NULL,
            pass_at_2 REAL NOT NULL,
            pass_at_3 REAL NOT NULL,
            pass_at_4 REAL NOT NULL,
            pass_at_5 REAL NOT NULL
        );

        DROP INDEX IF EXISTS idx_gen_unique;
        DROP INDEX IF EXISTS idx_gen_qid_model_lang;
        DROP INDEX IF EXISTS idx_trans_unique;
        DROP INDEX IF EXISTS idx_trans_qid_model;
        DROP INDEX IF EXISTS idx_sub_unique;
        DROP INDEX IF EXISTS idx_sub_qid_model_lang;
        DROP INDEX IF EXISTS idx_sub_task_model;
        DROP INDEX IF EXISTS idx_sub_src_tgt;
        DROP INDEX IF EXISTS idx_gen_passk_unique;
        DROP INDEX IF EXISTS idx_gen_passk_model;
        DROP INDEX IF EXISTS idx_gen_passk_lang;
        DROP INDEX IF EXISTS idx_trans_passk_unique;
        DROP INDEX IF EXISTS idx_trans_passk_model;
        DROP INDEX IF EXISTS idx_trans_passk_pair;
        DROP INDEX IF EXISTS idx_problem_qid;
        DROP INDEX IF EXISTS idx_problem_slug;
        DROP INDEX IF EXISTS idx_problem_generation;
        DROP INDEX IF EXISTS idx_problem_translation;
        DROP INDEX IF EXISTS idx_snippet_qid_lang;
        DROP INDEX IF EXISTS idx_ref_qid_lang;

        DELETE FROM problems;
        DELETE FROM snippets;
        DELETE FROM "references";
        DELETE FROM gen_codes;
        DELETE FROM translations;
        DELETE FROM submissions;
        DELETE FROM generation_pass_ks;
        DELETE FROM translation_pass_ks;
        DELETE FROM sqlite_sequence WHERE name IN ('problems', 'snippets', 'references', 'gen_codes', 'translations', 'submissions', 'generation_pass_ks', 'translation_pass_ks');
        """
    )
    conn.commit()


def recreate_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE UNIQUE INDEX idx_gen_unique ON gen_codes(qid, model_name, language, attempt_num);
        CREATE INDEX idx_gen_qid_model_lang ON gen_codes(qid, model_name, language);

        CREATE UNIQUE INDEX idx_trans_unique ON translations(qid, model_name, src_lang, tgt_lang, attempt_num);
        CREATE INDEX idx_trans_qid_model ON translations(qid, model_name);

        CREATE UNIQUE INDEX idx_sub_unique ON submissions(qid, model_name, language, src_lang, tgt_lang, attempt_num, source_type);
        CREATE INDEX idx_sub_qid_model_lang ON submissions(qid, model_name, language);
        CREATE INDEX idx_sub_task_model ON submissions(source_type, model_name);
        CREATE INDEX idx_sub_src_tgt ON submissions(src_lang, tgt_lang);

        CREATE UNIQUE INDEX idx_gen_passk_unique ON generation_pass_ks(model_name, qid, language);
        CREATE INDEX idx_gen_passk_model ON generation_pass_ks(model_name);
        CREATE INDEX idx_gen_passk_lang ON generation_pass_ks(language);

        CREATE UNIQUE INDEX idx_trans_passk_unique ON translation_pass_ks(model_name, qid, src_lang, tgt_lang);
        CREATE INDEX idx_trans_passk_model ON translation_pass_ks(model_name);
        CREATE INDEX idx_trans_passk_pair ON translation_pass_ks(src_lang, tgt_lang);

        CREATE UNIQUE INDEX idx_problem_qid ON problems(qid);
        CREATE INDEX idx_problem_slug ON problems(slug);
        CREATE INDEX idx_problem_generation ON problems(is_generation_benchmark);
        CREATE INDEX idx_problem_translation ON problems(is_translation_benchmark);
        CREATE UNIQUE INDEX idx_snippet_qid_lang ON snippets(qid, language);
        CREATE INDEX idx_ref_qid_lang ON "references"(qid, language);
        """
    )
    conn.commit()


def flush(conn: sqlite3.Connection, sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn.executemany(sql, rows)
    conn.commit()
    count = len(rows)
    rows.clear()
    return count


def read_lines(path: Path) -> set[str]:
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def problem_text_and_slug(qid: str) -> tuple[str, str, str]:
    desc_dir = SOURCE / "metadata" / "problems" / "descriptions" / qid
    if not desc_dir.is_dir():
        raise FileNotFoundError(desc_dir)

    candidates = sorted(desc_dir.glob("*English*.txt")) or sorted(desc_dir.glob("*.txt"))
    if not candidates:
        raise FileNotFoundError(f"no txt description for qid={qid}: {desc_dir}")
    desc_path = candidates[0]
    match = SLUG_RE.search(desc_path.name)
    if match is None:
        raise ValueError(f"description filename missing slug: {desc_path}")
    title = desc_path.name.split("[", 1)[0].replace("(English)", "").strip()
    return title, match.group("slug"), desc_path.read_text(encoding="utf-8")


def import_problem_metadata(conn: sqlite3.Connection) -> None:
    metadata_dir = SOURCE / "metadata"
    question_tags = {str(item["qid"]): item for item in load_json(metadata_dir / "question_tags.json")}
    urls = load_json(metadata_dir / "question_urls.json")
    qid_mapping = load_json(metadata_dir / "Qid_mapping.json")
    generation_qids = read_lines(metadata_dir / "GenCode_ids.txt")
    translation_qids = read_lines(metadata_dir / "TransCode_targ_ids.txt")
    now = datetime.now(timezone.utc).isoformat()

    problem_rows: list[tuple] = []
    for qid in sorted(question_tags, key=lambda value: int(value)):
        title, slug, description = problem_text_and_slug(qid)
        item = question_tags[qid]
        is_generation = qid in generation_qids
        is_translation = qid in translation_qids
        problem_rows.append(
            (
                int(qid),
                str(qid_mapping.get(qid, "")),
                title,
                slug,
                urls.get(qid, ""),
                description,
                item["difficulty"],
                int(is_generation or is_translation),
                int(is_generation),
                int(is_translation),
                now,
                now,
            )
        )

    flush(
        conn,
        """
        INSERT INTO problems
            (qid, tid, title, slug, url, description, difficulty, is_benchmark,
             is_generation_benchmark, is_translation_benchmark, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        problem_rows,
    )

    snippet_rows: list[tuple] = []
    snippets_root = SOURCE / "metadata" / "templates" / "snippets"
    for qid_dir in sorted(snippets_root.iterdir(), key=lambda path: int(path.name) if path.name.isdigit() else path.name):
        if not qid_dir.is_dir():
            continue
        qid = int(qid_dir.name)
        for snippet_path in sorted(qid_dir.glob("*.json")):
            code = load_json(snippet_path)
            if not isinstance(code, str):
                raise TypeError(f"snippet must be a JSON string: {snippet_path}")
            snippet_rows.append((qid, snippet_path.stem, code))
            if len(snippet_rows) >= 20000:
                flush(conn, "INSERT INTO snippets (qid, language, code) VALUES (?, ?, ?)", snippet_rows)
    flush(conn, "INSERT INTO snippets (qid, language, code) VALUES (?, ?, ?)", snippet_rows)

    reference_rows: list[tuple] = []
    references_root = SOURCE / "solutions" / "reference"
    for qid_dir in sorted(references_root.iterdir(), key=lambda path: int(path.name) if path.name.isdigit() else path.name):
        if not qid_dir.is_dir():
            continue
        for reference_path in sorted(qid_dir.glob("*.txt")):
            match = REFERENCE_RE.match(reference_path.name)
            if match is None:
                raise ValueError(f"unexpected reference filename: {reference_path}")
            reference_rows.append(
                (
                    int(match.group("qid")),
                    match.group("lang"),
                    int(match.group("attempt")),
                    reference_path.read_text(encoding="utf-8"),
                )
            )
            if len(reference_rows) >= 20000:
                flush(conn, 'INSERT INTO "references" (qid, language, attempt_num, code) VALUES (?, ?, ?, ?)', reference_rows)
    flush(conn, 'INSERT INTO "references" (qid, language, attempt_num, code) VALUES (?, ?, ?, ?)', reference_rows)
    print("imported problems, snippets, references")


def import_passk(conn: sqlite3.Connection) -> None:
    gen_rows: list[tuple] = []
    with (SOURCE / "docs" / "derived_data" / "generation_passk.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gen_rows.append(
                (
                    row["model"],
                    int(row["qid"]),
                    row["language"],
                    int(row["n_candidates"]),
                    float(row["pass_at_1"]),
                    float(row["pass_at_2"]),
                    float(row["pass_at_3"]),
                    float(row["pass_at_4"]),
                    float(row["pass_at_5"]),
                )
            )
    flush(
        conn,
        """
        INSERT INTO generation_pass_ks
            (model_name, qid, language, n_candidates, pass_at_1, pass_at_2, pass_at_3, pass_at_4, pass_at_5)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        gen_rows,
    )

    trans_rows: list[tuple] = []
    with (SOURCE / "docs" / "derived_data" / "translation_passk.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            trans_rows.append(
                (
                    row["model"],
                    int(row["qid"]),
                    row["source_lang"],
                    row["target_lang"],
                    int(row["n_candidates"]),
                    float(row["pass_at_1"]),
                    float(row["pass_at_2"]),
                    float(row["pass_at_3"]),
                    float(row["pass_at_4"]),
                    float(row["pass_at_5"]),
                )
            )
    flush(
        conn,
        """
        INSERT INTO translation_pass_ks
            (model_name, qid, src_lang, tgt_lang, n_candidates, pass_at_1, pass_at_2, pass_at_3, pass_at_4, pass_at_5)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        trans_rows,
    )
    print("imported passk")


def read_submission(file_path: Path) -> dict:
    return json.loads(file_path.read_text(encoding="utf-8"))


def process_task_batch(tasks: list[tuple], fn) -> tuple[list[tuple], list[tuple], dict[str, int], int]:
    code_rows: list[tuple] = []
    sub_rows: list[tuple] = []
    per_model: dict[str, int] = {}
    missing = 0

    with ThreadPoolExecutor(max_workers=READ_WORKERS) as executor:
        for result in executor.map(fn, tasks):
            if result is None:
                missing += 1
                continue
            model, code_row, sub_row = result
            code_rows.append(code_row)
            sub_rows.append(sub_row)
            per_model[model] = per_model.get(model, 0) + 1

    return code_rows, sub_rows, per_model, missing


def merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def read_generation_task(task: tuple) -> tuple[str, tuple, tuple] | None:
    model, qid, language, slug, attempt, sub_root, code_root = task
    model_dir = f"Submit_Results_{model}"
    submission_path = sub_root / model_dir / str(qid) / f"{qid}_{slug}_{attempt}.json"
    code_path = code_root / model / str(qid) / f"{qid}_{language}_ans{attempt}.txt"
    if not submission_path.exists() or not code_path.exists():
        return None
    item = read_submission(submission_path)
    code_row = (
        qid,
        model,
        language,
        attempt,
        code_path.read_text(encoding="utf-8"),
        code_path.relative_to(SOURCE).as_posix(),
    )
    sub_row = (
        qid,
        model,
        language,
        "",
        "",
        attempt,
        as_int(item.get("submit_id")),
        item.get("state") or "",
        item.get("ac_status") or "",
        as_int(item.get("total_testcases")),
        as_int(item.get("total_correct")),
        item.get("runtime") or "",
        as_float(item.get("runtime_percentile")),
        item.get("memory") or "",
        as_float(item.get("memory_percentile")),
        "generation",
        model_dir,
    )
    return model, code_row, sub_row


def import_generation(conn: sqlite3.Connection) -> None:
    sub_root = SOURCE / "generation" / "submissions"
    code_root = SOURCE / "generation" / "code"
    total_codes = 0
    total_subs = 0
    per_model: dict[str, int] = {}
    missing = 0
    tasks: list[tuple] = []

    def process_pending() -> None:
        nonlocal total_codes, total_subs, missing
        code_rows, sub_rows, batch_counts, batch_missing = process_task_batch(tasks, read_generation_task)
        total_codes += flush(conn, GEN_CODE_SQL, code_rows)
        total_subs += flush(conn, SUBMISSION_SQL, sub_rows)
        merge_counts(per_model, batch_counts)
        missing += batch_missing
        tasks.clear()

    with (SOURCE / "docs" / "derived_data" / "generation_passk.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            model = row["model"]
            qid = int(row["qid"])
            language = row["language"]
            slug = SLUG_BY_LANG[language]
            for attempt in sorted(CODE_ATTEMPTS_TO_IMPORT):
                tasks.append((model, qid, language, slug, attempt, sub_root, code_root))
                if len(tasks) >= READ_TASK_BATCH:
                    process_pending()

    if tasks:
        process_pending()
    for model, count in sorted(per_model.items()):
        print(f"generation {model}: codes={count} submissions={count}")

    print(f"generation total: codes={total_codes} submissions={total_subs} missing_pairs={missing}")


def read_translation_task(task: tuple) -> tuple[str, tuple, tuple] | None:
    model, qid, src, tgt, src_slug, tgt_slug, attempt, sub_root, code_root = task
    model_dir = f"Submit_Results_{model}"
    submission_path = sub_root / model_dir / str(qid) / f"{qid}_{src_slug}_{tgt_slug}_{attempt}.json"
    code_path = code_root / model / str(qid) / f"{qid}_{src}_{tgt}_ans{attempt}.txt"
    if not submission_path.exists() or not code_path.exists():
        return None
    item = read_submission(submission_path)
    code_row = (
        qid,
        model,
        src,
        tgt,
        attempt,
        code_path.read_text(encoding="utf-8"),
        code_path.relative_to(SOURCE).as_posix(),
    )
    sub_row = (
        qid,
        model,
        tgt,
        src,
        tgt,
        attempt,
        as_int(item.get("submit_id")),
        item.get("state") or "",
        item.get("ac_status") or "",
        as_int(item.get("total_testcases")),
        as_int(item.get("total_correct")),
        item.get("runtime") or "",
        as_float(item.get("runtime_percentile")),
        item.get("memory") or "",
        as_float(item.get("memory_percentile")),
        "translation",
        model_dir,
    )
    return model, code_row, sub_row


def import_translation(conn: sqlite3.Connection) -> None:
    sub_root = SOURCE / "translation" / "submissions"
    code_root = SOURCE / "translation" / "code"
    total_codes = 0
    total_subs = 0
    per_model: dict[str, int] = {}
    missing = 0
    tasks: list[tuple] = []

    def process_pending() -> None:
        nonlocal total_codes, total_subs, missing
        code_rows, sub_rows, batch_counts, batch_missing = process_task_batch(tasks, read_translation_task)
        total_codes += flush(conn, TRANS_CODE_SQL, code_rows)
        total_subs += flush(conn, SUBMISSION_SQL, sub_rows)
        merge_counts(per_model, batch_counts)
        missing += batch_missing
        tasks.clear()

    with (SOURCE / "docs" / "derived_data" / "translation_passk.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            model = row["model"]
            qid = int(row["qid"])
            src = row["source_lang"]
            tgt = row["target_lang"]
            src_slug = SLUG_BY_LANG[src]
            tgt_slug = SLUG_BY_LANG[tgt]
            for attempt in sorted(CODE_ATTEMPTS_TO_IMPORT):
                tasks.append((model, qid, src, tgt, src_slug, tgt_slug, attempt, sub_root, code_root))
                if len(tasks) >= READ_TASK_BATCH:
                    process_pending()

    if tasks:
        process_pending()
    for model, count in sorted(per_model.items()):
        print(f"translation {model}: codes={count} submissions={count}")

    print(f"translation total: codes={total_codes} submissions={total_subs} missing_pairs={missing}")


def verify(conn: sqlite3.Connection) -> None:
    expected = {
        "problems": 2944,
        "generation_pass_ks": 119120,
        "translation_pass_ks": 28000,
    }
    for table, minimum in expected.items():
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count < minimum:
            raise RuntimeError(f"{table} count {count} < {minimum}")
        print(f"{table}: {count}")

    for table in ("gen_codes", "translations", "submissions"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count == 0:
            raise RuntimeError(f"{table} is empty")
        print(f"{table}: {count}")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity_check failed: {integrity}")
    print("integrity_check: ok")


def publish_db() -> None:
    if DB_PATH.resolve() == DEPLOY_DB.resolve():
        return
    for suffix in ("-wal", "-shm"):
        target = Path(str(DEPLOY_DB) + suffix)
        if target.exists():
            target.unlink()
    shutil.copy2(DB_PATH, DEPLOY_DB)
    print(f"published db to {DEPLOY_DB}")


def main() -> None:
    reset_db()
    conn = connect()
    try:
        prepare_schema(conn)
        import_problem_metadata(conn)
        import_passk(conn)
        import_generation(conn)
        import_translation(conn)
        recreate_indexes(conn)
        conn.execute("ANALYZE")
        conn.commit()
        verify(conn)
    finally:
        conn.close()
    publish_db()


if __name__ == "__main__":
    main()
