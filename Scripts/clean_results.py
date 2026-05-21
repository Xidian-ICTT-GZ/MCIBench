import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from layout import generation_code_dir, generation_submit_dir, metadata_dir, translation_code_dir, translation_submit_dir


LANG_TO_SLUG = {
    "C": "c",
    "C++": "cpp",
    "C#": "csharp",
    "Java": "java",
    "JavaScript": "javascript",
    "Python3": "python3",
    "Golang": "golang",
    "Rust": "rust",
}

SLUG_TO_LANG = {value: key for key, value in LANG_TO_SLUG.items()}

STATUS_GROUP = {
    "Accepted": "Accepted",
    "Wrong Answer": "WrongAnswer",
    "Compile Error": "CompileError",
    "Runtime Error": "RuntimeError",
    "Time Limit Exceeded": "TimeLimitExceeded",
    "Memory Limit Exceeded": "MemoryLimitExceeded",
    "Output Limit Exceeded": "OutputLimitExceeded",
}

EXCLUDED_MODEL_PATTERNS: tuple[str, ...] = ()

GEN_CODE_RE = re.compile(r"^(?:error_)?(?P<qid>\d+)_(?P<language>.+)_ans(?P<ans_id>[1-5])\.txt$")
TRANS_CODE_RE = re.compile(
    r"^(?:error_)?(?P<qid>\d+)_(?P<source>.+)_(?P<target>.+)_ans(?P<ans_id>[1-5])\.txt$"
)


def read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def read_language_pairs(path: Path) -> list[tuple[str, str]]:
    pairs = []
    for line in read_lines(path):
        source, target = line.split()
        if source not in LANG_TO_SLUG:
            raise ValueError(f"Unknown source language in pair file: {source}")
        if target not in LANG_TO_SLUG:
            raise ValueError(f"Unknown target language in pair file: {target}")
        pairs.append((source, target))
    return pairs


def read_question_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    metadata = {}
    for row in rows:
        qid = str(row["qid"])
        metadata[qid] = {
            "difficulty": row["difficulty"],
            "tags": "|".join(row.get("tags", [])),
        }
    return metadata


def load_submit_json(path: Path | None) -> dict[str, object]:
    if path is None:
        return {
            "submit_id": "",
            "state": "",
            "ac_status": "Wrong Answer",
            "total_testcases": "",
            "total_correct": "",
            "runtime": "",
            "runtime_percentile": "",
            "memory": "",
            "memory_percentile": "",
        }
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if "ac_status" not in data:
        ac_status = "Wrong Answer"
    else:
        ac_status = data["ac_status"]
        if ac_status == "Internal Error":
            ac_status = "Wrong Answer"
    if ac_status not in STATUS_GROUP:
        raise ValueError(f"Unknown ac_status in {path}: {ac_status}")
    return {
        "submit_id": data.get("submit_id", ""),
        "state": data.get("state", ""),
        "ac_status": ac_status,
        "total_testcases": data.get("total_testcases", ""),
        "total_correct": data.get("total_correct", ""),
        "runtime": data.get("runtime", ""),
        "runtime_percentile": data.get("runtime_percentile", ""),
        "memory": data.get("memory", ""),
        "memory_percentile": data.get("memory_percentile", ""),
    }


def result_model_name(model_dir_name: str) -> str:
    prefix = "Submit_Results_"
    if not model_dir_name.startswith(prefix):
        raise ValueError(f"Unexpected submit model directory: {model_dir_name}")
    return model_dir_name[len(prefix) :]


def build_submit_index(submit_dir: Path) -> dict[tuple[str, str], Path]:
    index = {}
    for model_dir in submit_dir.iterdir():
        if not model_dir.is_dir():
            continue
        model = result_model_name(model_dir.name)
        for json_path in model_dir.glob("*/*.json"):
            key = (model, json_path.stem)
            if key in index:
                raise ValueError(f"Duplicate submit result key: {key}")
            index[key] = json_path
    return index


def require_metadata(metadata: dict[str, dict[str, str]], qid: str) -> dict[str, str]:
    if qid not in metadata:
        raise KeyError(f"Missing question metadata for qid={qid}")
    return metadata[qid]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean_generation(root: Path, metadata: dict[str, dict[str, str]], qids: list[str], languages: list[str]) -> list[dict[str, object]]:
    code_dir = generation_code_dir(root)
    model_dirs = sorted(
        [
            path
            for path in code_dir.iterdir()
            if path.is_dir() and not is_excluded_model(path.name)
        ],
        key=lambda item: item.name,
    )
    worker_args = [(str(root), str(model_dir), metadata, qids, languages) for model_dir in model_dirs]
    rows = []
    with ProcessPoolExecutor(max_workers=min(8, len(worker_args))) as pool:
        for model_rows in pool.map(clean_generation_model, worker_args):
            rows.extend(model_rows)
    return rows


def clean_translation(root: Path, metadata: dict[str, dict[str, str]], target_qids: list[str], language_pairs: list[tuple[str, str]]) -> list[dict[str, object]]:
    code_dir = translation_code_dir(root)
    model_dirs = sorted(
        [
            path
            for path in code_dir.iterdir()
            if path.is_dir() and not is_excluded_model(path.name)
        ],
        key=lambda item: item.name,
    )
    worker_args = [(str(root), str(model_dir), metadata, target_qids, language_pairs) for model_dir in model_dirs]
    rows = []
    with ProcessPoolExecutor(max_workers=min(6, len(worker_args))) as pool:
        for model_rows in pool.map(clean_translation_model, worker_args):
            rows.extend(model_rows)
    return rows


def is_excluded_model(model: str) -> bool:
    model_lower = model.lower()
    return any(pattern in model_lower for pattern in EXCLUDED_MODEL_PATTERNS)


def clean_generation_model(args: tuple[str, str, dict[str, dict[str, str]], list[str], list[str]]) -> list[dict[str, object]]:
    root = Path(args[0])
    model_dir = Path(args[1])
    metadata = args[2]
    qids = args[3]
    languages = args[4]
    model = model_dir.name
    rows = []
    for qid in qids:
        meta = require_metadata(metadata, qid)
        for language in languages:
            if language not in LANG_TO_SLUG:
                raise ValueError(f"Unknown language: {language}")
            slug = LANG_TO_SLUG[language]
            for ans_id in range(1, 6):
                normal_code_path = model_dir / qid / f"{qid}_{language}_ans{ans_id}.txt"
                error_code_path = model_dir / qid / f"error_{qid}_{language}_ans{ans_id}.txt"
                if normal_code_path.exists():
                    code_path = normal_code_path
                elif error_code_path.exists():
                    code_path = error_code_path
                else:
                    code_path = None
                submit_stem = f"{qid}_{slug}_{ans_id}"
                expected_submit_path = generation_submit_dir(root) / f"Submit_Results_{model}" / qid / f"{submit_stem}.json"
                submit_path = expected_submit_path if expected_submit_path.exists() else None
                submit = load_submit_json(submit_path)
                ac_status = submit["ac_status"]
                rows.append(
                    {
                        "task": "generation",
                        "model": model,
                        "qid": qid,
                        "language": language,
                        "language_slug": slug,
                        "ans_id": ans_id,
                        "code_path": "" if code_path is None else str(code_path),
                        "submit_path": "" if submit_path is None else str(submit_path),
                        "submit_id": submit["submit_id"],
                        "state": submit["state"],
                        "ac_status": ac_status,
                        "status_group": STATUS_GROUP[ac_status],
                        "is_accepted": 1 if ac_status == "Accepted" else 0,
                        "total_testcases": submit["total_testcases"],
                        "total_correct": submit["total_correct"],
                        "runtime": submit["runtime"],
                        "runtime_percentile": submit["runtime_percentile"],
                        "memory": submit["memory"],
                        "memory_percentile": submit["memory_percentile"],
                        "difficulty": meta["difficulty"],
                        "tags": meta["tags"],
                    }
                )
    return rows


def clean_translation_model(args: tuple[str, str, dict[str, dict[str, str]], list[str], list[tuple[str, str]]]) -> list[dict[str, object]]:
    root = Path(args[0])
    model_dir = Path(args[1])
    metadata = args[2]
    target_qids = args[3]
    language_pairs = args[4]
    model = model_dir.name
    rows = []
    for qid in target_qids:
        meta = require_metadata(metadata, qid)
        for source, target in language_pairs:
            source_slug = LANG_TO_SLUG[source]
            target_slug = LANG_TO_SLUG[target]
            for ans_id in range(1, 6):
                normal_code_path = model_dir / qid / f"{qid}_{source}_{target}_ans{ans_id}.txt"
                error_code_path = model_dir / qid / f"error_{qid}_{source}_{target}_ans{ans_id}.txt"
                if normal_code_path.exists():
                    code_path = normal_code_path
                elif error_code_path.exists():
                    code_path = error_code_path
                else:
                    code_path = None
                submit_stem = f"{qid}_{source_slug}_{target_slug}_{ans_id}"
                expected_submit_path = translation_submit_dir(root) / f"Submit_Results_{model}" / qid / f"{submit_stem}.json"
                submit_path = expected_submit_path if expected_submit_path.exists() else None
                submit = load_submit_json(submit_path)
                ac_status = submit["ac_status"]
                rows.append(
                    {
                        "task": "translation",
                        "model": model,
                        "qid": qid,
                        "source_lang": source,
                        "target_lang": target,
                        "source_slug": source_slug,
                        "target_slug": target_slug,
                        "language_pair": f"{source}->{target}",
                        "ans_id": ans_id,
                        "code_path": "" if code_path is None else str(code_path),
                        "submit_path": "" if submit_path is None else str(submit_path),
                        "submit_id": submit["submit_id"],
                        "state": submit["state"],
                        "ac_status": ac_status,
                        "status_group": STATUS_GROUP[ac_status],
                        "is_accepted": 1 if ac_status == "Accepted" else 0,
                        "total_testcases": submit["total_testcases"],
                        "total_correct": submit["total_correct"],
                        "runtime": submit["runtime"],
                        "runtime_percentile": submit["runtime_percentile"],
                        "memory": submit["memory"],
                        "memory_percentile": submit["memory_percentile"],
                        "difficulty": meta["difficulty"],
                        "tags": meta["tags"],
                    }
                )
    return rows


def passk_from_rows(rows: list[dict[str, object]], group_cols: list[str]) -> list[dict[str, object]]:
    grouped = defaultdict(list)
    for row in rows:
        key = tuple(str(row[col]) for col in group_cols)
        grouped[key].append(row)

    output = []
    for key, items in sorted(grouped.items()):
        by_ans = {int(item["ans_id"]): int(item["is_accepted"]) for item in items}
        row = {col: value for col, value in zip(group_cols, key)}
        row["n_candidates"] = len(items)
        for k in range(1, 6):
            row[f"pass_at_{k}"] = 1 if any(by_ans.get(i, 0) == 1 for i in range(1, k + 1)) else 0
        output.append(row)
    return output


def summarize_generation_language(passk_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = defaultdict(list)
    for row in passk_rows:
        grouped[row["language"]].append(row)
    return summarize_passk_groups(grouped, ["language"])


def summarize_translation_pair(passk_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped = defaultdict(list)
    for row in passk_rows:
        grouped[(row["source_lang"], row["target_lang"])].append(row)
    return summarize_passk_groups(grouped, ["source_lang", "target_lang"])


def summarize_passk_groups(grouped: dict[object, list[dict[str, object]]], names: list[str]) -> list[dict[str, object]]:
    rows = []
    for key, items in sorted(grouped.items()):
        if not isinstance(key, tuple):
            key = (key,)
        row = {name: value for name, value in zip(names, key)}
        row["n_tasks"] = len(items)
        for k in range(1, 6):
            row[f"pass_at_{k}"] = sum(int(item[f"pass_at_{k}"]) for item in items) / len(items)
        row["pass_at_5_gain"] = row["pass_at_5"] - row["pass_at_1"]
        rows.append(row)
    return rows


def summarize_difficulty(passk_rows: list[dict[str, object]], result_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    difficulty_by_task = {}
    for row in result_rows:
        key = (str(row["model"]), str(row["qid"]), str(row.get("language", row.get("source_lang", ""))), str(row.get("target_lang", "")))
        difficulty_by_task[key] = str(row["difficulty"])

    grouped = defaultdict(list)
    for row in passk_rows:
        key = tuple(str(row[col]) for col in row.keys() if col in {"model", "qid", "language", "source_lang", "target_lang"})
        if len(key) == 3:
            lookup = (row["model"], row["qid"], row["language"], "")
        else:
            lookup = (row["model"], row["qid"], row["source_lang"], row["target_lang"])
        grouped[difficulty_by_task[lookup]].append(row)
    return summarize_passk_groups(grouped, ["difficulty"])


def summarize_tags(passk_rows: list[dict[str, object]], result_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    tags_by_lookup = {}
    for row in result_rows:
        key = (str(row["model"]), str(row["qid"]), str(row.get("language", row.get("source_lang", ""))), str(row.get("target_lang", "")))
        tags_by_lookup[key] = str(row["tags"]).split("|") if row["tags"] else []

    grouped = defaultdict(list)
    for row in passk_rows:
        if "language" in row:
            lookup = (row["model"], row["qid"], row["language"], "")
        else:
            lookup = (row["model"], row["qid"], row["source_lang"], row["target_lang"])
        for tag in tags_by_lookup[lookup]:
            grouped[tag].append(row)
    return summarize_passk_groups(grouped, ["tag"])


def failure_summary(rows: list[dict[str, object]], task: str) -> list[dict[str, object]]:
    grouped = Counter((str(row["model"]), str(row["status_group"])) for row in rows)
    totals = Counter(str(row["model"]) for row in rows)
    output = []
    for (model, status_group), count in sorted(grouped.items()):
        output.append(
            {
                "task": task,
                "model": model,
                "status_group": status_group,
                "count": count,
                "rate": count / totals[model],
            }
        )
    return output


def coverage_report(generation_rows: list[dict[str, object]], translation_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for task, task_rows in [("generation", generation_rows), ("translation", translation_rows)]:
        grouped = defaultdict(list)
        for row in task_rows:
            grouped[str(row["model"])].append(row)
        for model, model_rows in sorted(grouped.items()):
            rows.append(
                {
                    "task": task,
                    "model": model,
                    "expected_rows": len(model_rows),
                    "accepted_rows": sum(1 for row in model_rows if row["status_group"] == "Accepted"),
                    "wrong_answer_rows": sum(1 for row in model_rows if row["status_group"] == "WrongAnswer"),
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--output", default="artifacts/derived_data", help="CSV output directory")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    metadata_root = metadata_dir(root)
    metadata = read_question_metadata(metadata_root / "question_tags.json")
    generation_qids = read_lines(metadata_root / "GenCode_ids.txt")
    generation_languages = read_lines(metadata_root / "language.txt")
    translation_target_qids = read_lines(metadata_root / "TransCode_targ_ids.txt")
    translation_language_pairs = read_language_pairs(metadata_root / "language_pairs.txt")

    generation_rows = clean_generation(root, metadata, generation_qids, generation_languages)
    generation_passk = passk_from_rows(generation_rows, ["model", "qid", "language"])
    translation_rows = clean_translation(root, metadata, translation_target_qids, translation_language_pairs)
    translation_passk = passk_from_rows(translation_rows, ["model", "qid", "source_lang", "target_lang"])

    write_csv(
        output / "generation_results.csv",
        [
            "task",
            "model",
            "qid",
            "language",
            "language_slug",
            "ans_id",
            "code_path",
            "submit_path",
            "submit_id",
            "state",
            "ac_status",
            "status_group",
            "is_accepted",
            "total_testcases",
            "total_correct",
            "runtime",
            "runtime_percentile",
            "memory",
            "memory_percentile",
            "difficulty",
            "tags",
        ],
        generation_rows,
    )
    write_csv(
        output / "translation_results.csv",
        [
            "task",
            "model",
            "qid",
            "source_lang",
            "target_lang",
            "source_slug",
            "target_slug",
            "language_pair",
            "ans_id",
            "code_path",
            "submit_path",
            "submit_id",
            "state",
            "ac_status",
            "status_group",
            "is_accepted",
            "total_testcases",
            "total_correct",
            "runtime",
            "runtime_percentile",
            "memory",
            "memory_percentile",
            "difficulty",
            "tags",
        ],
        translation_rows,
    )
    write_csv(
        output / "generation_passk.csv",
        ["model", "qid", "language", "n_candidates", "pass_at_1", "pass_at_2", "pass_at_3", "pass_at_4", "pass_at_5"],
        generation_passk,
    )
    write_csv(
        output / "translation_passk.csv",
        [
            "model",
            "qid",
            "source_lang",
            "target_lang",
            "n_candidates",
            "pass_at_1",
            "pass_at_2",
            "pass_at_3",
            "pass_at_4",
            "pass_at_5",
        ],
        translation_passk,
    )
    write_csv(
        output / "language_summary.csv",
        ["language", "n_tasks", "pass_at_1", "pass_at_2", "pass_at_3", "pass_at_4", "pass_at_5", "pass_at_5_gain"],
        summarize_generation_language(generation_passk),
    )
    write_csv(
        output / "pair_summary.csv",
        [
            "source_lang",
            "target_lang",
            "n_tasks",
            "pass_at_1",
            "pass_at_2",
            "pass_at_3",
            "pass_at_4",
            "pass_at_5",
            "pass_at_5_gain",
        ],
        summarize_translation_pair(translation_passk),
    )
    write_csv(
        output / "difficulty_summary.csv",
        ["difficulty", "n_tasks", "pass_at_1", "pass_at_2", "pass_at_3", "pass_at_4", "pass_at_5", "pass_at_5_gain"],
        summarize_difficulty(generation_passk, generation_rows),
    )
    write_csv(
        output / "tag_summary.csv",
        ["tag", "n_tasks", "pass_at_1", "pass_at_2", "pass_at_3", "pass_at_4", "pass_at_5", "pass_at_5_gain"],
        summarize_tags(generation_passk, generation_rows),
    )
    write_csv(
        output / "failure_summary.csv",
        ["task", "model", "status_group", "count", "rate"],
        failure_summary(generation_rows, "generation") + failure_summary(translation_rows, "translation"),
    )
    write_csv(
        output / "coverage_report.csv",
        ["task", "model", "expected_rows", "accepted_rows", "wrong_answer_rows"],
        coverage_report(generation_rows, translation_rows),
    )

    print(f"Wrote CSV files to {output}")
    print(f"generation rows: {len(generation_rows)}")
    print(f"translation rows: {len(translation_rows)}")


if __name__ == "__main__":
    main()
