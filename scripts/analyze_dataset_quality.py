from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from layout import derived_data_dir, metadata_dir, reference_solutions_dir


LANGUAGE_ORDER = ["C", "C++", "C#", "Java", "JavaScript", "Python3", "Golang", "Rust"]
ANSWER_RE = re.compile(r"^(?P<qid>\d+)_(?P<language>.+)_ans(?P<ans_id>\d+)\.txt$")


def read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        raise ValueError(f"Invalid denominator: {denominator}")
    return f"{numerator / denominator:.6f}"


def ordered_join(values: set[str]) -> str:
    return "|".join([language for language in LANGUAGE_ORDER if language in values])


def validate_qids(qids: list[str]) -> None:
    duplicated = [qid for qid, count in Counter(qids).items() if count > 1]
    if duplicated:
        raise ValueError(f"Duplicate qids: {duplicated[:10]}")


def scan_reference_solutions(root: Path, qids: list[str], min_file_bytes: int) -> dict[str, set[str]]:
    qid_set = set(qids)
    coverage: dict[str, set[str]] = {qid: set() for qid in qids}
    answer_dir = reference_solutions_dir(root)
    if not answer_dir.is_dir():
        raise FileNotFoundError(answer_dir)

    for qid_dir in answer_dir.iterdir():
        if not qid_dir.is_dir() or qid_dir.name not in qid_set:
            continue
        for path in qid_dir.glob("*.txt"):
            match = ANSWER_RE.match(path.name)
            if match is None:
                continue
            qid = match.group("qid")
            language = match.group("language")
            if qid != qid_dir.name:
                raise ValueError(f"Answer file qid mismatch: {path}")
            if language not in LANGUAGE_ORDER:
                raise ValueError(f"Unknown answer language in {path}: {language}")
            if path.stat().st_size >= min_file_bytes:
                coverage[qid].add(language)
    return coverage


def accepted_generation_languages(path: Path, qids: list[str]) -> dict[str, set[str]]:
    qid_set = set(qids)
    accepted: dict[str, set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"qid", "language", "is_accepted"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        for row in reader:
            if row["is_accepted"] != "1":
                continue
            qid = row["qid"]
            language = row["language"]
            if qid not in qid_set:
                continue
            if language not in LANGUAGE_ORDER:
                raise ValueError(f"Unknown generation language in {path}: {language}")
            accepted[qid].add(language)
    return accepted


def accepted_translation_languages(path: Path, qids: list[str]) -> dict[str, set[str]]:
    qid_set = set(qids)
    accepted: dict[str, set[str]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"qid", "target_lang", "is_accepted"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        for row in reader:
            if row["is_accepted"] != "1":
                continue
            qid = row["qid"]
            target = row["target_lang"]
            if qid not in qid_set:
                continue
            if target not in LANGUAGE_ORDER:
                raise ValueError(f"Unknown translation target language in {path}: {target}")
            accepted[qid].add(target)
    return accepted


def merge_coverages(*coverages: dict[str, set[str]]) -> dict[str, set[str]]:
    if not coverages:
        raise ValueError("At least one coverage map is required")
    qids = list(coverages[0])
    merged = {qid: set() for qid in qids}
    for coverage in coverages:
        if set(coverage) != set(qids):
            raise ValueError("Coverage maps use different qid sets")
        for qid, languages in coverage.items():
            merged[qid].update(languages)
    return merged


def normalize_sparse_coverage(qids: list[str], coverage: dict[str, set[str]]) -> dict[str, set[str]]:
    return {qid: set(coverage.get(qid, set())) for qid in qids}


def summary_row(stage: str, coverage: dict[str, set[str]], reference_complete: int) -> dict[str, object]:
    total_problems = len(coverage)
    total_slots = total_problems * len(LANGUAGE_ORDER)
    covered_slots = sum(len(languages) for languages in coverage.values())
    complete = sum(1 for languages in coverage.values() if len(languages) == len(LANGUAGE_ORDER))
    return {
        "stage": stage,
        "total_problems": total_problems,
        "complete_8_lang_problems": complete,
        "complete_rate": pct(complete, total_problems),
        "new_complete_vs_reference": complete - reference_complete,
        "language_slots_covered": covered_slots,
        "total_language_slots": total_slots,
        "language_slot_coverage": pct(covered_slots, total_slots),
    }


def language_rows(stage: str, coverage: dict[str, set[str]]) -> list[dict[str, object]]:
    total_problems = len(coverage)
    return [
        {
            "stage": stage,
            "language": language,
            "problems": sum(1 for languages in coverage.values() if language in languages),
            "coverage": pct(sum(1 for languages in coverage.values() if language in languages), total_problems),
        }
        for language in LANGUAGE_ORDER
    ]


def distribution_rows(stage: str, coverage: dict[str, set[str]]) -> list[dict[str, object]]:
    counts = Counter(len(languages) for languages in coverage.values())
    return [
        {
            "stage": stage,
            "covered_languages": covered_languages,
            "problems": counts.get(covered_languages, 0),
        }
        for covered_languages in range(1, len(LANGUAGE_ORDER) + 1)
    ]


def detail_rows(
    qids: list[str],
    reference: dict[str, set[str]],
    generation: dict[str, set[str]],
    translation: dict[str, set[str]],
    after_generation: dict[str, set[str]],
    after_all: dict[str, set[str]],
) -> list[dict[str, object]]:
    rows = []
    for qid in qids:
        generated_new = generation[qid] - reference[qid]
        translated_new = translation[qid] - after_generation[qid]
        missing_after_all = set(LANGUAGE_ORDER) - after_all[qid]
        rows.append(
            {
                "qid": qid,
                "reference_language_count": len(reference[qid]),
                "after_generation_language_count": len(after_generation[qid]),
                "after_all_language_count": len(after_all[qid]),
                "is_complete_reference": int(len(reference[qid]) == len(LANGUAGE_ORDER)),
                "is_complete_after_all": int(len(after_all[qid]) == len(LANGUAGE_ORDER)),
                "languages_reference": ordered_join(reference[qid]),
                "languages_after_generation": ordered_join(after_generation[qid]),
                "languages_after_all": ordered_join(after_all[qid]),
                "new_languages_from_generation": ordered_join(generated_new),
                "new_languages_from_translation": ordered_join(translated_new),
                "missing_languages_after_all": ordered_join(missing_after_all),
            }
        )
    return rows


def print_summary(rows: list[dict[str, object]]) -> None:
    print("MCIBench dataset quality coverage")
    for row in rows:
        print(
            "{stage}: complete={complete_8_lang_problems}/{total_problems} "
            "({complete_rate}), slots={language_slots_covered}/{total_language_slots} "
            "({language_slot_coverage}), new_complete_vs_reference={new_complete_vs_reference}".format(**row)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze MCIBench language-solution coverage before and after experiments.")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path, help="MCIBench repository root")
    parser.add_argument("--qids", default="", help="Question id list relative to root")
    parser.add_argument("--generation-results", default="", help="Generation CSV relative to root")
    parser.add_argument("--translation-results", default="", help="Translation CSV relative to root")
    parser.add_argument("--output-dir", default="", help="Output directory relative to root")
    parser.add_argument("--min-reference-bytes", default=1, type=int, help="Minimum reference solution file size")
    args = parser.parse_args()

    root = args.root.resolve()
    metadata_root = metadata_dir(root)
    derived_root = derived_data_dir(root)
    qid_path = root / args.qids if args.qids else metadata_root / "GenCode_ids.txt"
    generation_results_path = root / args.generation_results if args.generation_results else derived_root / "generation_results.csv"
    translation_results_path = root / args.translation_results if args.translation_results else derived_root / "translation_results.csv"
    qids = read_lines(qid_path)
    validate_qids(qids)

    reference = scan_reference_solutions(root, qids, args.min_reference_bytes)
    generation = normalize_sparse_coverage(qids, accepted_generation_languages(generation_results_path, qids))
    translation = normalize_sparse_coverage(qids, accepted_translation_languages(translation_results_path, qids))
    after_generation = merge_coverages(reference, generation)
    after_all = merge_coverages(after_generation, translation)

    stages = [
        ("reference", reference),
        ("reference_plus_generation_accepted", after_generation),
        ("reference_plus_generation_and_translation_accepted", after_all),
    ]
    reference_complete = sum(1 for languages in reference.values() if len(languages) == len(LANGUAGE_ORDER))
    summary_rows = [summary_row(stage, coverage, reference_complete) for stage, coverage in stages]
    by_language_rows = [row for stage, coverage in stages for row in language_rows(stage, coverage)]
    by_problem_count_rows = [row for stage, coverage in stages for row in distribution_rows(stage, coverage)]
    per_problem_rows = detail_rows(qids, reference, generation, translation, after_generation, after_all)

    output_dir = (root / args.output_dir).resolve() if args.output_dir else derived_root.resolve()
    write_csv(
        output_dir / "dataset_quality_summary.csv",
        [
            "stage",
            "total_problems",
            "complete_8_lang_problems",
            "complete_rate",
            "new_complete_vs_reference",
            "language_slots_covered",
            "total_language_slots",
            "language_slot_coverage",
        ],
        summary_rows,
    )
    write_csv(output_dir / "dataset_quality_by_language.csv", ["stage", "language", "problems", "coverage"], by_language_rows)
    write_csv(
        output_dir / "dataset_quality_by_problem_language_count.csv",
        ["stage", "covered_languages", "problems"],
        by_problem_count_rows,
    )
    write_csv(
        output_dir / "dataset_quality_problem_detail.csv",
        [
            "qid",
            "reference_language_count",
            "after_generation_language_count",
            "after_all_language_count",
            "is_complete_reference",
            "is_complete_after_all",
            "languages_reference",
            "languages_after_generation",
            "languages_after_all",
            "new_languages_from_generation",
            "new_languages_from_translation",
            "missing_languages_after_all",
        ],
        per_problem_rows,
    )
    print_summary(summary_rows)
    print(f"Wrote CSV reports to {output_dir}")


if __name__ == "__main__":
    main()
