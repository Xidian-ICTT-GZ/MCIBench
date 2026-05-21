from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from layout import derived_data_dir, indexes_dir, metadata_dir


def read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_question_metadata(path: Path) -> dict[str, dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    return {str(row["qid"]): row for row in rows}


def load_urls(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as handle:
        rows = json.load(handle)
    urls: dict[str, str] = {}
    if isinstance(rows, dict):
        return {str(qid): str(url) for qid, url in rows.items()}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Unexpected URL row in {path}: {row!r}")
        qid = str(row.get("qid", ""))
        url = row.get("url") or row.get("question_url") or row.get("link") or ""
        if qid:
            urls[qid] = str(url)
    return urls


def metadata_row(qid: str, metadata: dict[str, dict[str, object]], urls: dict[str, str]) -> dict[str, object]:
    row = metadata.get(qid, {})
    tags = row.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "qid": qid,
        "difficulty": row.get("difficulty", ""),
        "tags": "|".join(str(tag) for tag in tags),
        "url": urls.get(qid, ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export human-readable MCIBench task and coverage index files.")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path, help="MCIBench repository root")
    args = parser.parse_args()

    root = args.root.resolve()
    metadata_root = metadata_dir(root)
    derived_root = derived_data_dir(root)
    output_root = indexes_dir(root)

    generation_qids = read_lines(metadata_root / "GenCode_ids.txt")
    translation_candidate_qids = read_lines(metadata_root / "TransCode_ids.txt")
    translation_task_qids = read_lines(metadata_root / "TransCode_targ_ids.txt")
    detail_rows = read_csv(derived_root / "dataset_quality_problem_detail.csv")
    question_metadata = load_question_metadata(metadata_root / "question_tags.json")
    urls = load_urls(metadata_root / "question_urls.json")

    complete_reference_qids = [row["qid"] for row in detail_rows if row["is_complete_reference"] == "1"]
    complete_augmented_qids = [row["qid"] for row in detail_rows if row["is_complete_after_all"] == "1"]
    incomplete_augmented_rows = [
        {
            "qid": row["qid"],
            "after_all_language_count": row["after_all_language_count"],
            "missing_languages_after_all": row["missing_languages_after_all"],
        }
        for row in detail_rows
        if row["is_complete_after_all"] != "1"
    ]

    write_lines(output_root / "generation_task_qids.txt", generation_qids)
    write_lines(output_root / "translation_candidate_qids.txt", translation_candidate_qids)
    write_lines(output_root / "translation_task_qids.txt", translation_task_qids)
    write_lines(output_root / "complete_reference_qids.txt", complete_reference_qids)
    write_lines(output_root / "complete_augmented_qids.txt", complete_augmented_qids)
    write_csv(
        output_root / "translation_task_qids.csv",
        ["qid", "difficulty", "tags", "url"],
        [metadata_row(qid, question_metadata, urls) for qid in translation_task_qids],
    )
    write_csv(
        output_root / "complete_reference_qids.csv",
        ["qid", "difficulty", "tags", "url"],
        [metadata_row(qid, question_metadata, urls) for qid in complete_reference_qids],
    )
    write_csv(
        output_root / "complete_augmented_qids.csv",
        ["qid", "difficulty", "tags", "url"],
        [metadata_row(qid, question_metadata, urls) for qid in complete_augmented_qids],
    )
    write_csv(
        output_root / "incomplete_augmented_qids.csv",
        ["qid", "after_all_language_count", "missing_languages_after_all"],
        incomplete_augmented_rows,
    )
    print(f"Wrote dataset indexes to {output_root}")
    print(f"generation qids: {len(generation_qids)}")
    print(f"translation task qids: {len(translation_task_qids)}")
    print(f"complete reference qids: {len(complete_reference_qids)}")
    print(f"complete augmented qids: {len(complete_augmented_qids)}")


if __name__ == "__main__":
    main()
