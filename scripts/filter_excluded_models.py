from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from layout import derived_data_dir


PASS_COLS = [f"pass_at_{k}" for k in range(1, 6)]
EXCLUDED_MODEL_PATTERNS: tuple[str, ...] = ()


def is_excluded_series(series: pd.Series) -> pd.Series:
    model_text = series.astype(str).str.lower()
    return model_text.apply(lambda value: any(pattern in value for pattern in EXCLUDED_MODEL_PATTERNS))


def assert_no_excluded(df: pd.DataFrame, name: str) -> None:
    if "model" in df.columns and is_excluded_series(df["model"]).any():
        models = sorted(df.loc[is_excluded_series(df["model"]), "model"].astype(str).unique())
        raise ValueError(f"{name} still contains excluded models: {models}")


def summarize_passk_groups(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    grouped = df.groupby(group_cols, as_index=False)[PASS_COLS].mean()
    grouped.insert(len(group_cols), "n_tasks", df.groupby(group_cols).size().to_numpy())
    grouped["pass_at_5_gain"] = grouped["pass_at_5"] - grouped["pass_at_1"]
    return grouped


def failure_summary(rows: pd.DataFrame, task: str) -> pd.DataFrame:
    grouped = rows.groupby(["model", "status_group"]).size().reset_index(name="count")
    totals = rows.groupby("model").size().rename("total")
    output = grouped.merge(totals, on="model")
    output["rate"] = output["count"] / output["total"]
    output.insert(0, "task", task)
    return output[["task", "model", "status_group", "count", "rate"]].sort_values(["model", "status_group"])


def coverage_report(generation_rows: pd.DataFrame, translation_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for task, task_rows in [("generation", generation_rows), ("translation", translation_rows)]:
        for model, model_rows in task_rows.groupby("model"):
            status_counts = Counter(model_rows["status_group"])
            rows.append(
                {
                    "task": task,
                    "model": model,
                    "expected_rows": len(model_rows),
                    "accepted_rows": status_counts["Accepted"],
                    "wrong_answer_rows": status_counts["WrongAnswer"],
                }
            )
    return pd.DataFrame(rows).sort_values(["task", "model"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="", help="Derived CSV directory")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    data_dir = Path(args.data_dir).resolve() if args.data_dir else derived_data_dir(root).resolve()
    generation_results = pd.read_csv(data_dir / "generation_results.csv")
    translation_results = pd.read_csv(data_dir / "translation_results.csv")
    generation_passk = pd.read_csv(data_dir / "generation_passk.csv")
    translation_passk = pd.read_csv(data_dir / "translation_passk.csv")

    generation_results = generation_results.loc[~is_excluded_series(generation_results["model"])].copy()
    translation_results = translation_results.loc[~is_excluded_series(translation_results["model"])].copy()
    generation_passk = generation_passk.loc[~is_excluded_series(generation_passk["model"])].copy()
    translation_passk = translation_passk.loc[~is_excluded_series(translation_passk["model"])].copy()

    language_summary = summarize_passk_groups(generation_passk, ["language"])
    pair_summary = summarize_passk_groups(translation_passk, ["source_lang", "target_lang"])

    failure = pd.concat(
        [
            failure_summary(generation_results, "generation"),
            failure_summary(translation_results, "translation"),
        ],
        ignore_index=True,
    )
    coverage = coverage_report(generation_results, translation_results)

    outputs = {
        "generation_results.csv": generation_results,
        "translation_results.csv": translation_results,
        "generation_passk.csv": generation_passk,
        "translation_passk.csv": translation_passk,
        "language_summary.csv": language_summary,
        "pair_summary.csv": pair_summary,
        "failure_summary.csv": failure,
        "coverage_report.csv": coverage,
    }
    for name, df in outputs.items():
        assert_no_excluded(df, name)
        df.to_csv(data_dir / name, index=False)

    print(f"Filtered derived data written to {data_dir}")


if __name__ == "__main__":
    main()
