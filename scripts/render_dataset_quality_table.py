from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

from layout import derived_data_dir, figure_dir, table_dir


LANGUAGE_DISPLAY_ORDER = ["C++", "Python3", "Java", "JavaScript", "C", "C#", "Golang", "Rust"]
LANGUAGE_LABELS = {"Golang": "Go"}
REFERENCE_STAGE = "reference"
ENHANCED_STAGE = "reference_plus_generation_and_translation_accepted"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_int(value: int | str) -> str:
    return f"{int(value):,}"


def fmt_pct(value: float | str) -> str:
    return f"{float(value) * 100:.1f}%"


def require_lookup(rows: list[dict[str, str]], key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    lookup: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in lookup:
            raise ValueError(f"Duplicate row key: {key}")
        lookup[key] = row
    return lookup


def build_rows(root: Path) -> list[dict[str, object]]:
    derived_dir = derived_data_dir(root)
    language_rows = read_csv(derived_dir / "dataset_quality_by_language.csv")
    distribution_rows = read_csv(derived_dir / "dataset_quality_by_problem_language_count.csv")
    language_lookup = require_lookup(language_rows, ("stage", "language"))
    distribution_lookup = require_lookup(distribution_rows, ("stage", "covered_languages"))

    rows: list[dict[str, object]] = []
    for index, language in enumerate(LANGUAGE_DISPLAY_ORDER, start=1):
        reference_language = language_lookup[(REFERENCE_STAGE, language)]
        enhanced_language = language_lookup[(ENHANCED_STAGE, language)]
        reference_distribution = distribution_lookup[(REFERENCE_STAGE, str(index))]
        enhanced_distribution = distribution_lookup[(ENHANCED_STAGE, str(index))]
        rows.append(
            {
                "language": LANGUAGE_LABELS.get(language, language),
                "reference_language_problems": int(reference_language["problems"]),
                "reference_language_coverage": fmt_pct(reference_language["coverage"]),
                "enhanced_language_problems": int(enhanced_language["problems"]),
                "enhanced_language_coverage": fmt_pct(enhanced_language["coverage"]),
                "covered_languages": index,
                "reference_problem_count": int(reference_distribution["problems"]),
                "enhanced_problem_count": int(enhanced_distribution["problems"]),
            }
        )
    return rows


def draw_table(path: Path, rows: list[dict[str, object]]) -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif"],
            "font.size": 12,
            "figure.dpi": 150,
            "savefig.dpi": 300,
        }
    )

    fig, ax = plt.subplots(figsize=(14.2, 5.0))
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.add_patch(plt.Rectangle((0.018, 0.935), 0.017, 0.035, color="#F4C20D", transform=ax.transAxes, clip_on=False))
    ax.text(0.052, 0.952, "Table 3", ha="left", va="center", fontsize=15, fontweight="bold")
    ax.text(
        0.165,
        0.952,
        "Coverage comparison before and after augmenting MciBench.",
        ha="left",
        va="center",
        fontsize=15,
    )

    left, right = 0.018, 0.982
    y_top = 0.895
    y_group = 0.856
    y_header = 0.79
    y_rule = 0.742
    y_bottom = 0.07
    col_x = [0.035, 0.245, 0.355, 0.500, 0.612, 0.715, 0.850, 0.965]

    ax.hlines([y_top, y_group - 0.035, y_rule, y_bottom], left, right, colors="black", linewidths=[0.9, 0.8, 0.75, 0.9])
    ax.vlines(0.66, y_bottom, y_top, colors="#666666", linewidth=0.5)

    ax.text(0.325, y_group, "Per-language coverage", ha="center", va="center", fontsize=15, fontweight="bold")
    ax.text(0.835, y_group, "Per-problem language coverage", ha="center", va="center", fontsize=15, fontweight="bold")

    headers = [
        "Language",
        "Ref. #Problems",
        "Ref. Coverage",
        "Aug. #Problems",
        "Aug. Coverage",
        "#Lang.",
        "Ref. #Prob.",
        "Aug. #Prob.",
    ]
    aligns = ["left", "right", "right", "right", "right", "right", "right", "right"]
    for x, header, align in zip(col_x, headers, aligns):
        ax.text(x, y_header, header, ha=align, va="center", fontsize=10, fontweight="bold")

    row_gap = (y_rule - y_bottom) / 8
    for i, row in enumerate(rows):
        y = y_rule - row_gap * (i + 0.5)
        values = [
            row["language"],
            fmt_int(row["reference_language_problems"]),
            row["reference_language_coverage"],
            fmt_int(row["enhanced_language_problems"]),
            row["enhanced_language_coverage"],
            str(row["covered_languages"]),
            fmt_int(row["reference_problem_count"]),
            fmt_int(row["enhanced_problem_count"]),
        ]
        for x, value, align in zip(col_x, values, aligns):
            ax.text(x, y, str(value), ha=align, va="center", fontsize=13)

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Table-2-style dataset quality comparison table.")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path, help="MCIBench repository root")
    args = parser.parse_args()

    root = args.root.resolve()
    rows = build_rows(root)
    tables = table_dir(root)
    figures = figure_dir(root)

    fieldnames = [
        "language",
        "reference_language_problems",
        "reference_language_coverage",
        "enhanced_language_problems",
        "enhanced_language_coverage",
        "covered_languages",
        "reference_problem_count",
        "enhanced_problem_count",
    ]
    write_csv(tables / "table_dataset_quality_comparison.csv", fieldnames, rows)
    draw_table(figures / "table_dataset_quality_comparison.png", rows)
    print(f"Wrote {tables / 'table_dataset_quality_comparison.csv'}")
    print(f"Wrote {figures / 'table_dataset_quality_comparison.png'}")


if __name__ == "__main__":
    main()
