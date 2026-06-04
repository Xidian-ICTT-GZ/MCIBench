from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GENCODE_ROOT = SCRIPT_DIR / "GenCode"
DEFAULT_SUBMIT_ROOT = SCRIPT_DIR / "Submit_Results"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "pass_at_1_ac_models.txt"
DEFAULT_WARNING_OUTPUT_PATH = SCRIPT_DIR / "pass_at_1_ac_models.warnings.txt"

GENCODE_MODEL_NAME_MAP = {
    "gpt_4o": "gpt-4o",
}

GENCODE_LANG_TO_CANONICAL = {
    "C": "c",
    "C++": "cpp",
    "C#": "csharp",
    "Java": "java",
    "JavaScript": "javascript",
    "Python3": "python3",
    "Golang": "golang",
    "Rust": "rust",
}

CANONICAL_TO_DISPLAY_LANG = {
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "java": "Java",
    "javascript": "JavaScript",
    "python3": "Python3",
    "golang": "Golang",
    "rust": "Rust",
}

LANGUAGE_ORDER = {
    "c": 0,
    "cpp": 1,
    "csharp": 2,
    "java": 3,
    "javascript": 4,
    "python3": 5,
    "golang": 6,
    "rust": 7,
}

GENCODE_FILE_PATTERN = re.compile(r"^(?P<qid>\d+)_(?P<lang>.+)_ans(?P<idx>[1-9]\d*)\.txt$")
SUBMIT_FILE_PATTERN = re.compile(
    r"^(?P<qid>\d+)_(?P<lang>c|cpp|csharp|java|javascript|python3|golang|rust)_(?P<idx>[1-9]\d*)(?:_.+)?\.json$"
)


def normalize_gencode_model_name(name: str) -> str:
    return GENCODE_MODEL_NAME_MAP.get(name, name)


def resolve_submit_model_dir(submit_root: Path, gencode_model_name: str) -> Path | None:
    preferred_dir = submit_root / f"Submit_Results_{gencode_model_name}"
    if preferred_dir.is_dir():
        return preferred_dir

    fallback_name = gencode_model_name.replace("-", "_")
    fallback_dir = submit_root / f"Submit_Results_{fallback_name}"
    if fallback_dir.is_dir():
        return fallback_dir

    return None


def parse_gencode_file_name(file_name: str) -> tuple[str, str, int]:
    match = GENCODE_FILE_PATTERN.fullmatch(file_name)
    if match is None:
        raise ValueError(f"Invalid GenCode file name: {file_name}")

    qid = match.group("qid")
    raw_lang = match.group("lang")
    idx = int(match.group("idx"))

    if raw_lang not in GENCODE_LANG_TO_CANONICAL:
        raise ValueError(f"Unsupported GenCode language: {raw_lang}")

    return qid, GENCODE_LANG_TO_CANONICAL[raw_lang], idx


def parse_submit_file_name(file_name: str) -> tuple[str, str, int]:
    match = SUBMIT_FILE_PATTERN.fullmatch(file_name)
    if match is None:
        raise ValueError(f"Invalid submit result file name: {file_name}")
    return match.group("qid"), match.group("lang"), int(match.group("idx"))


def status_priority(status: str) -> int:
    if status == "Accepted":
        return 3
    if status in {"Compile Error", "Runtime Error", "Wrong Answer", "Time Limit Exceeded", "Memory Limit Exceeded"}:
        return 2
    if status in {"SUCCESS", "PENDING", "UNKNOWN"}:
        return 1
    return 2


def load_submit_statuses(submit_model_dir: Path) -> tuple[dict[tuple[str, str, int], str], list[str]]:
    statuses: dict[tuple[str, str, int], str] = {}
    warnings: list[str] = []

    for question_dir in sorted(path for path in submit_model_dir.iterdir() if path.is_dir()):
        for json_path in sorted(path for path in question_dir.iterdir() if path.is_file()):
            qid, language, idx = parse_submit_file_name(json_path.name)
            key = (qid, language, idx)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            ac_status = payload.get("ac_status")
            if isinstance(ac_status, str):
                new_status = ac_status
            else:
                state = payload.get("state")
                if isinstance(state, str):
                    new_status = state
                    warnings.append(f"Missing ac_status, fallback to state={state}: {json_path}")
                else:
                    new_status = "UNKNOWN"
                    warnings.append(f"Missing ac_status/state: {json_path}")

            if key in statuses:
                old_status = statuses[key]
                if status_priority(new_status) > status_priority(old_status):
                    statuses[key] = new_status
                warnings.append(
                    f"Duplicate submit result merged: {json_path} | kept_status={statuses[key]}"
                )
                continue

            statuses[key] = new_status

    return statuses, warnings


def discover_gencode_records(
    gencode_root: Path,
    selected_models: set[str],
) -> tuple[dict[str, dict[tuple[str, str], set[int]]], list[str]]:
    records: dict[str, dict[tuple[str, str], set[int]]] = {}
    warnings: list[str] = []

    for model_dir in sorted(path for path in gencode_root.iterdir() if path.is_dir()):
        model_name = normalize_gencode_model_name(model_dir.name)
        if selected_models and model_name not in selected_models:
            continue

        model_records: dict[tuple[str, str], set[int]] = defaultdict(set)
        for question_dir in sorted(path for path in model_dir.iterdir() if path.is_dir()):
            for code_path in sorted(path for path in question_dir.iterdir() if path.is_file()):
                if code_path.name.startswith("error_"):
                    warnings.append(f"Skipped error-prefixed GenCode file: {code_path}")
                    continue
                qid, language, idx = parse_gencode_file_name(code_path.name)
                if qid != question_dir.name:
                    raise ValueError(
                        f"Question id mismatch between GenCode directory and file: {question_dir} vs {code_path.name}"
                    )
                key = (qid, language)
                if idx in model_records[key]:
                    raise ValueError(f"Duplicate GenCode index for {model_name}: {code_path}")
                model_records[key].add(idx)

        if not model_records:
            warnings.append(f"GenCode model directory is empty: {model_dir.name}")
            continue

        records[model_name] = dict(model_records)

    return records, warnings


def evaluate_pass_at_1(
    gencode_records: dict[str, dict[tuple[str, str], set[int]]],
    submit_root: Path,
) -> tuple[dict[tuple[str, str], list[str]], list[str]]:
    accepted_models: dict[tuple[str, str], list[str]] = defaultdict(list)
    warnings: list[str] = []

    for model_name in sorted(gencode_records):
        submit_model_dir = resolve_submit_model_dir(submit_root, model_name)
        if submit_model_dir is None:
            warnings.append(f"Missing submit result directory for model: {model_name}")
            continue

        submit_statuses, submit_warnings = load_submit_statuses(submit_model_dir)
        warnings.extend(submit_warnings)
        for qid_language, indexes in sorted(gencode_records[model_name].items()):
            qid, language = qid_language
            matched_submit = False

            for idx in sorted(indexes):
                status = submit_statuses.get((qid, language, idx))
                if status is None:
                    warnings.append(
                        f"Missing submit result: model={model_name} question={qid} language={language} idx={idx}"
                    )
                    continue

                matched_submit = True
                if status == "Accepted":
                    accepted_models[qid_language].append(model_name)
                    break

            if not matched_submit:
                warnings.append(
                    f"No usable submit result matched any code file: model={model_name} question={qid} language={language}"
                )

    for qid_language in accepted_models:
        accepted_models[qid_language].sort()

    return dict(accepted_models), warnings


def build_all_qid_languages(
    gencode_records: dict[str, dict[tuple[str, str], set[int]]]
) -> list[tuple[str, str]]:
    all_pairs = {
        qid_language
        for model_records in gencode_records.values()
        for qid_language in model_records
    }
    return sorted(all_pairs, key=lambda item: (int(item[0]), LANGUAGE_ORDER[item[1]], item[1]))


def format_output(
    all_qid_languages: list[tuple[str, str]],
    accepted_models: dict[tuple[str, str], list[str]],
) -> str:
    lines = ["question_id\tlanguage\tac_models"]

    for qid, language in all_qid_languages:
        model_names = accepted_models.get((qid, language), [])
        model_text = ",".join(model_names) if model_names else "-"
        lines.append(f"{qid}\t{CANONICAL_TO_DISPLAY_LANG[language]}\t{model_text}")

    return "\n".join(lines) + "\n"


def format_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return "\n".join(warnings) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract pass@1 accepted models by question and language")
    parser.add_argument("--gencode-root", type=Path, default=DEFAULT_GENCODE_ROOT, help="GenCode root directory")
    parser.add_argument("--submit-root", type=Path, default=DEFAULT_SUBMIT_ROOT, help="Submit_Results root directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output txt path")
    parser.add_argument(
        "--warning-output",
        type=Path,
        default=DEFAULT_WARNING_OUTPUT_PATH,
        help="Optional warning output txt path",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Optional comma-separated model names, using GenCode directory names after normalization",
    )
    args = parser.parse_args()

    gencode_root = args.gencode_root.resolve()
    submit_root = args.submit_root.resolve()
    output_path = args.output.resolve()
    warning_output_path = args.warning_output.resolve()
    selected_models = {name.strip() for name in args.models.split(",") if name.strip()}

    if not gencode_root.is_dir():
        raise NotADirectoryError(f"GenCode root not found: {gencode_root}")
    if not submit_root.is_dir():
        raise NotADirectoryError(f"Submit_Results root not found: {submit_root}")

    gencode_records, discovery_warnings = discover_gencode_records(gencode_root, selected_models)
    if not gencode_records:
        raise ValueError("No GenCode records found")

    accepted_models, evaluation_warnings = evaluate_pass_at_1(gencode_records, submit_root)
    all_qid_languages = build_all_qid_languages(gencode_records)

    output_text = format_output(
        all_qid_languages=all_qid_languages,
        accepted_models=accepted_models,
    )
    warning_text = format_warnings(discovery_warnings + evaluation_warnings)
    output_path.write_text(output_text, encoding="utf-8")
    if warning_text:
        warning_output_path.write_text(warning_text, encoding="utf-8")

    print(f"Wrote {len(all_qid_languages)} records to {output_path}")
    if warning_text:
        print(f"Wrote warnings to {warning_output_path}")
    print(f"Accepted entries: {sum(1 for pair in all_qid_languages if pair in accepted_models)}")
    print(f"Warnings: {len(discovery_warnings) + len(evaluation_warnings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())