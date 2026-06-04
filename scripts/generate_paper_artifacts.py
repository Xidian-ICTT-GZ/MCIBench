from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch
from matplotlib.ticker import PercentFormatter

from layout import derived_data_dir, figure_dir, table_dir


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = derived_data_dir(ROOT)
FIG_DIR = figure_dir(ROOT)
TABLE_DIR = table_dir(ROOT)

LANGUAGE_ORDER = ["C", "C++", "C#", "Java", "JavaScript", "Python3", "Golang", "Rust"]
STATUS_ORDER = [
    "WrongAnswer",
    "CompileError",
    "RuntimeError",
    "TimeLimitExceeded",
    "MemoryLimitExceeded",
    "OutputLimitExceeded",
]
PASS_COLS = [f"pass_at_{k}" for k in range(1, 6)]
EXCLUDED_MODEL_PATTERNS: tuple[str, ...] = ()

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["DejaVu Serif"],
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name)


def drop_excluded_models(df: pd.DataFrame) -> pd.DataFrame:
    if "model" not in df.columns:
        return df
    model_text = df["model"].astype(str).str.lower()
    excluded = model_text.apply(lambda value: any(pattern in value for pattern in EXCLUDED_MODEL_PATTERNS))
    return df.loc[~excluded].copy()


def require_columns(df: pd.DataFrame, name: str, columns: list[str]) -> None:
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")


def ensure_dirs() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)


def save_figure(fig: plt.Figure, stem: str) -> None:
    fig.savefig(FIG_DIR / f"{stem}.png")
    plt.close(fig)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def int_fmt(x: int | float) -> str:
    return f"{int(x):,}"


def float_fmt(x: int | float, digits: int = 1) -> str:
    return f"{float(x):.{digits}f}"


def write_table(df: pd.DataFrame, stem: str, caption: str, label: str) -> None:
    df.to_csv(TABLE_DIR / f"{stem}.csv", index=False, encoding="utf-8")


def model_order_from_passk(passk: pd.DataFrame) -> list[str]:
    return (
        passk.groupby("model")["pass_at_5"]
        .mean()
        .sort_values(ascending=False)
        .index.tolist()
    )


def draw_bar(
    series: pd.Series,
    ylabel: str,
    stem: str,
    color: str = "#4C78A8",
    figsize: tuple[float, float] = (7.2, 3.4),
) -> None:
    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(len(series))
    bars = ax.bar(x, series.to_numpy(), color=color, width=0.72)
    ax.set_ylabel(ylabel)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks(x, series.index, rotation=35, ha="right")
    ax.set_ylim(0, max(series.max() * 1.18, 0.05))
    for bar, value in zip(bars, series.to_numpy()):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.01,
            pct(value),
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    save_figure(fig, stem)


def draw_heatmap(
    matrix: pd.DataFrame,
    stem: str,
    cbar_label: str,
    figsize: tuple[float, float] = (7.6, 4.2),
    annotate: bool = True,
) -> None:
    fig, ax = plt.subplots(figsize=figsize)
    values = matrix.to_numpy(dtype=float)
    image = ax.imshow(values, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(np.arange(matrix.shape[1]), matrix.columns, rotation=35, ha="right")
    ax.set_yticks(np.arange(matrix.shape[0]), matrix.index)
    if annotate:
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                color = "white" if values[i, j] < 0.45 else "black"
                ax.text(j, i, f"{values[i, j] * 100:.0f}", ha="center", va="center", color=color, fontsize=7)
    cbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.02)
    cbar.ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    cbar.set_label(cbar_label)
    save_figure(fig, stem)


def draw_workflow() -> None:
    fig, ax = plt.subplots(figsize=(8.8, 3.6))
    ax.axis("off")
    boxes = {
        "desc": (0.06, 0.72, "Description\nSnippets"),
        "gen": (0.25, 0.72, "LLM code\ngeneration"),
        "submit_gen": (0.45, 0.72, "LeetCode\nsubmission"),
        "json_gen": (0.66, 0.72, "Submit_Gen\nJSON"),
        "ref": (0.06, 0.25, "Reference code\nSnippets"),
        "trans": (0.25, 0.25, "LLM code\ntranslation"),
        "submit_trans": (0.45, 0.25, "LeetCode\nsubmission"),
        "json_trans": (0.66, 0.25, "Submit_Trans\nJSON"),
        "clean": (0.84, 0.50, "CSV cleaning\nand grouping"),
    }
    for x, y, text in boxes.values():
        ax.text(
            x,
            y,
            text,
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.35", "fc": "#F7F7F7", "ec": "#555555", "lw": 1.0},
        )
    arrows = [
        ("desc", "gen"),
        ("gen", "submit_gen"),
        ("submit_gen", "json_gen"),
        ("ref", "trans"),
        ("trans", "submit_trans"),
        ("submit_trans", "json_trans"),
        ("json_gen", "clean"),
        ("json_trans", "clean"),
    ]
    for start, end in arrows:
        sx, sy, _ = boxes[start]
        ex, ey, _ = boxes[end]
        ax.add_patch(
            FancyArrowPatch(
                (sx + 0.06, sy),
                (ex - 0.06, ey),
                arrowstyle="-|>",
                mutation_scale=10,
                color="#444444",
                linewidth=1,
            )
        )
    ax.text(
        0.84,
        0.18,
        "Tables and figures",
        ha="center",
        va="center",
        bbox={"boxstyle": "round,pad=0.32", "fc": "#E9F2FB", "ec": "#4C78A8", "lw": 1.0},
    )
    ax.add_patch(
        FancyArrowPatch((0.84, 0.40), (0.84, 0.27), arrowstyle="-|>", mutation_scale=10, color="#444444", linewidth=1)
    )
    save_figure(fig, "fig1_workflow")


def parse_runtime_ms(value: object) -> float:
    text = str(value).strip()
    if not text.endswith(" ms"):
        raise ValueError(f"Unexpected runtime format: {value}")
    return float(text.removesuffix(" ms").strip())


def parse_memory_mb(value: object) -> float:
    text = str(value).strip()
    if not text.endswith(" MB"):
        raise ValueError(f"Unexpected memory format: {value}")
    return float(text.removesuffix(" MB").strip())


def first_ac_efficiency_data(gen_results: pd.DataFrame) -> pd.DataFrame:
    required = ["model", "qid", "language", "ans_id", "is_accepted", "runtime", "memory"]
    require_columns(gen_results, "generation_results", required)
    accepted = gen_results[gen_results["is_accepted"] == 1].copy()
    if accepted.empty:
        raise ValueError("generation_results has no accepted rows for efficiency analysis")
    accepted["ans_id"] = pd.to_numeric(accepted["ans_id"])
    accepted["runtime_ms"] = accepted["runtime"].map(parse_runtime_ms)
    accepted["memory_mb"] = accepted["memory"].map(parse_memory_mb)
    first = (
        accepted.sort_values(["model", "qid", "language", "ans_id"])
        .drop_duplicates(["model", "qid", "language"], keep="first")
        .copy()
    )
    first["runtime_ms_plus1"] = first["runtime_ms"] + 1.0
    medians = (
        first.groupby(["qid", "language"])
        .agg(
            median_runtime_ms_plus1=("runtime_ms_plus1", "median"),
            median_memory_mb=("memory_mb", "median"),
            comparable_models=("model", "nunique"),
        )
        .reset_index()
    )
    first = first.merge(medians, on=["qid", "language"], how="left", validate="many_to_one")
    first = first[first["comparable_models"] >= 2].copy()
    if first.empty:
        raise ValueError("No comparable first-AC problem-language groups found")
    first["norm_runtime"] = np.log(first["runtime_ms_plus1"] / first["median_runtime_ms_plus1"])
    first["norm_memory"] = np.log(first["memory_mb"] / first["median_memory_mb"])
    first["is_pareto"] = False
    pareto_flags: list[pd.Series] = []
    for _, group in first.groupby(["qid", "language"], sort=False):
        runtime = group["runtime_ms"].to_numpy()
        memory = group["memory_mb"].to_numpy()
        flags = []
        for i in range(len(group)):
            dominates = (runtime <= runtime[i]) & (memory <= memory[i]) & (
                (runtime < runtime[i]) | (memory < memory[i])
            )
            flags.append(not bool(dominates.any()))
        pareto_flags.append(pd.Series(flags, index=group.index))
    first.loc[pd.concat(pareto_flags).index, "is_pareto"] = pd.concat(pareto_flags).sort_index()
    return first

def generation_efficiency_summary(gen_results: pd.DataFrame, first: pd.DataFrame | None = None) -> pd.DataFrame:
    required = ["model", "is_accepted"]
    require_columns(gen_results, "generation_results", required)
    if first is None:
        first = first_ac_efficiency_data(gen_results)
    counts = gen_results.groupby("model").agg(total_attempts=("is_accepted", "size"), accepted_count=("is_accepted", "sum"))
    summary = (
        first.groupby("model")
        .agg(
            comparable_first_ac_count=("is_accepted", "size"),
            median_runtime_ms=("runtime_ms", "median"),
            median_memory_mb=("memory_mb", "median"),
            mean_norm_runtime=("norm_runtime", "mean"),
            mean_norm_memory=("norm_memory", "mean"),
            pareto_rate=("is_pareto", "mean"),
        )
    )
    summary = counts.join(summary, how="left").reset_index()
    summary["AC_rate"] = summary["accepted_count"] / summary["total_attempts"]
    summary["runtime_efficiency"] = -summary["mean_norm_runtime"]
    summary["memory_efficiency"] = -summary["mean_norm_memory"]
    return summary


def bootstrap_ci(values: pd.Series, rng: np.random.Generator, n_boot: int = 500, stat: str = "median") -> tuple[float, float]:
    data = values.to_numpy(dtype=float)
    if len(data) < 2:
        raise ValueError("Bootstrap CI requires at least two values")
    samples = rng.choice(data, size=(n_boot, len(data)), replace=True)
    if stat == "median":
        stats = np.median(samples, axis=1)
    elif stat == "mean":
        stats = np.mean(samples, axis=1)
    else:
        raise ValueError(f"Unknown bootstrap stat: {stat}")
    low, high = np.percentile(stats, [2.5, 97.5])
    return float(low), float(high)


def model_family(model: str) -> str:
    text = model.lower()
    if "qwen" in text:
        return "Qwen"
    if "gpt" in text:
        return "GPT"
    if "claude" in text:
        return "Claude"
    if "deepseek" in text:
        return "DeepSeek"
    if "glm" in text:
        return "GLM"
    return "Other"


def generate_figures(data: dict[str, pd.DataFrame]) -> None:
    gen_results = data["generation_results"]
    gen_passk = data["generation_passk"]
    trans_passk = data["translation_passk"]
    failure = data["failure_summary"]
    language = data["language_summary"]
    pair = data["pair_summary"]
    difficulty = data["difficulty_summary"]
    tag = data["tag_summary"]

    gen_order = model_order_from_passk(gen_passk)
    trans_order = model_order_from_passk(trans_passk)

    draw_workflow()

    rq1 = gen_passk.groupby("model")["pass_at_5"].mean().reindex(gen_order)
    draw_bar(rq1, "Mean pass@5", "fig_rq1_1_generation_model_pass5")

    failure_plot = (
        failure[(failure["task"] == "generation") & (failure["status_group"].isin(STATUS_ORDER))]
        .pivot_table(index="model", columns="status_group", values="rate", aggfunc="sum")
        .reindex(gen_order)
        .fillna(0)
    )
    failure_plot = failure_plot[[c for c in STATUS_ORDER if c in failure_plot.columns]]
    fig, ax = plt.subplots(figsize=(7.4, 3.5))
    bottom = np.zeros(len(failure_plot))
    colors = ["#E45756", "#F58518", "#72B7B2", "#B279A2", "#54A24B", "#EECA3B"]
    for i, status in enumerate(failure_plot.columns):
        vals = failure_plot[status].to_numpy()
        ax.bar(np.arange(len(vals)), vals, bottom=bottom, label=status, color=colors[i % len(colors)], width=0.72)
        bottom += vals
    ax.set_ylabel("Candidate rate")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks(np.arange(len(failure_plot)), failure_plot.index, rotation=35, ha="right")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0.0, 1.16))
    save_figure(fig, "fig_rq1_2_generation_failure_stack")

    first_eff = data["generation_first_ac_efficiency"]
    efficiency = generation_efficiency_summary(gen_results, first_eff).set_index("model")
    rng = np.random.default_rng(20260512)
    ci_rows = []
    for model, group in first_eff.groupby("model"):
        runtime_low, runtime_high = bootstrap_ci(group["norm_runtime"], rng, stat="mean")
        memory_low, memory_high = bootstrap_ci(group["norm_memory"], rng, stat="mean")
        ci_rows.append(
            {
                "model": model,
                "runtime_eff_low": -runtime_high,
                "runtime_eff_high": -runtime_low,
                "memory_eff_low": -memory_high,
                "memory_eff_high": -memory_low,
            }
        )
    ci = pd.DataFrame(ci_rows).set_index("model")
    plot = efficiency.join(ci).dropna().reset_index()
    colors = {"Qwen": "#59A14F", "GPT": "#4C78A8", "Claude": "#B279A2", "DeepSeek": "#F58518", "GLM": "#7F7F7F"}
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    for family, group in plot.groupby(plot["model"].map(model_family)):
        ax.scatter(
            group["runtime_efficiency"],
            group["memory_efficiency"],
            s=80 + 520 * group["AC_rate"],
            color=colors.get(family, "#BAB0AC"),
            alpha=0.82,
            edgecolor="white",
            linewidth=0.8,
            label=family,
        )
        xerr = np.vstack(
            [
                group["runtime_efficiency"] - group["runtime_eff_low"],
                group["runtime_eff_high"] - group["runtime_efficiency"],
            ]
        )
        yerr = np.vstack(
            [
                group["memory_efficiency"] - group["memory_eff_low"],
                group["memory_eff_high"] - group["memory_efficiency"],
            ]
        )
        ax.errorbar(
            group["runtime_efficiency"],
            group["memory_efficiency"],
            xerr=xerr,
            yerr=yerr,
            fmt="none",
            ecolor=colors.get(family, "#BAB0AC"),
            elinewidth=0.8,
            alpha=0.55,
            capsize=2,
        )
    for i, row in plot.sort_values("runtime_efficiency").reset_index(drop=True).iterrows():
        ax.annotate(
            row["model"],
            (row["runtime_efficiency"], row["memory_efficiency"]),
            xytext=(5, 5 if i % 2 == 0 else -10),
            textcoords="offset points",
            fontsize=7,
        )
    ax.axvline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.axhline(0, color="#555555", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Runtime efficiency")
    ax.set_ylabel("Memory efficiency")
    ax.grid(color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, title="Family", loc="upper left", bbox_to_anchor=(1.02, 1.0))
    save_figure(fig, "fig_rq1_3_generation_efficiency_map")

    rq2_matrix = (
        gen_passk.groupby(["model", "language"])["pass_at_5"]
        .mean()
        .unstack("language")
        .reindex(gen_order)
        .reindex(columns=LANGUAGE_ORDER)
    )
    draw_heatmap(rq2_matrix, "fig_rq2_1_generation_model_language_heatmap", "pass@5", figsize=(8.0, 4.5))

    lang_series = language.set_index("language").reindex(LANGUAGE_ORDER)["pass_at_5"].sort_values(ascending=False)
    draw_bar(lang_series, "Mean pass@5", "fig_rq2_2_generation_language_pass5", color="#59A14F", figsize=(5.4, 3.2))

    pair_matrix = pair.pivot(index="source_lang", columns="target_lang", values="pass_at_5").reindex(
        index=LANGUAGE_ORDER, columns=LANGUAGE_ORDER
    )
    draw_heatmap(pair_matrix, "fig_rq3_1_translation_pair_heatmap", "pass@5", figsize=(6.4, 5.4))

    rq3 = trans_passk.groupby("model")["pass_at_5"].mean().reindex(trans_order)
    draw_bar(rq3, "Mean pass@5", "fig_rq3_2_translation_model_pass5", color="#F58518")

    src_avg = pair.groupby("source_lang")["pass_at_5"].mean().reindex(LANGUAGE_ORDER)
    tgt_avg = pair.groupby("target_lang")["pass_at_5"].mean().reindex(LANGUAGE_ORDER)
    fig, ax = plt.subplots(figsize=(6.8, 3.3))
    x = np.arange(len(LANGUAGE_ORDER))
    width = 0.38
    ax.bar(x - width / 2, src_avg, width=width, label="As source", color="#4C78A8")
    ax.bar(x + width / 2, tgt_avg, width=width, label="As target", color="#F58518")
    ax.set_ylabel("Mean pass@5")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xticks(x, LANGUAGE_ORDER, rotation=30, ha="right")
    ax.set_ylim(0, max(src_avg.max(), tgt_avg.max()) * 1.15)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False)
    save_figure(fig, "fig_rq3_3_translation_source_target_avg")

    diff_order = ["Easy", "Medium", "Hard"]
    fig, ax = plt.subplots(figsize=(5.4, 3.3))
    k = np.arange(1, 6)
    for diff in diff_order:
        row = difficulty.set_index("difficulty").loc[diff, PASS_COLS]
        ax.plot(k, row.to_numpy(dtype=float), marker="o", linewidth=1.8, label=diff)
    ax.set_xlabel("k")
    ax.set_ylabel("pass@k")
    ax.set_xticks(k)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False)
    save_figure(fig, "fig_rq4_1_difficulty_passk_curve")

    tag_filtered = tag[tag["n_tasks"] >= 30].copy()
    top = tag_filtered.nlargest(8, "pass_at_5").assign(group="Top")
    bottom = tag_filtered.nsmallest(8, "pass_at_5").assign(group="Bottom")
    tag_plot = pd.concat([top, bottom], ignore_index=True).sort_values("pass_at_5")
    colors = tag_plot["group"].map({"Top": "#59A14F", "Bottom": "#E45756"}).to_list()
    fig, ax = plt.subplots(figsize=(6.0, 5.0))
    y = np.arange(len(tag_plot))
    ax.barh(y, tag_plot["pass_at_5"], color=colors)
    ax.set_yticks(y, tag_plot["tag"])
    ax.set_xlabel("pass@5")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(axis="x", color="#D9D9D9", linewidth=0.6)
    save_figure(fig, "fig_rq4_2_tag_top_bottom_pass5")

    for passk, order, stem in [
        (gen_passk, gen_order, "fig_rq4_3_generation_passk_gain_curve"),
        (trans_passk, trans_order, "fig_rq4_4_translation_passk_gain_curve"),
    ]:
        curve = passk.groupby("model")[PASS_COLS].mean().reindex(order)
        fig, ax = plt.subplots(figsize=(6.8, 3.6))
        for model, row in curve.iterrows():
            ax.plot(k, row.to_numpy(dtype=float), marker="o", linewidth=1.5, label=model)
        ax.set_xlabel("k")
        ax.set_ylabel("pass@k")
        ax.set_xticks(k)
        ax.yaxis.set_major_formatter(PercentFormatter(1.0))
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
        ax.legend(frameon=False, ncol=2, loc="upper left", bbox_to_anchor=(0.0, 1.28))
        save_figure(fig, stem)


def generate_tables(data: dict[str, pd.DataFrame]) -> None:
    gen_results = data["generation_results"]
    trans_results = data["translation_results"]
    gen_passk = data["generation_passk"]
    trans_passk = data["translation_passk"]
    failure = data["failure_summary"]
    language = data["language_summary"]
    pair = data["pair_summary"]
    difficulty = data["difficulty_summary"]
    tag = data["tag_summary"]

    gen_order = model_order_from_passk(gen_passk)
    trans_order = model_order_from_passk(trans_passk)

    gen_counts = gen_results.groupby("model").agg(candidates=("is_accepted", "size"), accepted=("is_accepted", "sum"))
    gen_pass = gen_passk.groupby("model")[["pass_at_1", "pass_at_5"]].mean()
    table = gen_counts.join(gen_pass).reindex(gen_order).reset_index()
    table["accepted_rate"] = table["accepted"] / table["candidates"]
    table = table[["model", "candidates", "accepted", "accepted_rate", "pass_at_1", "pass_at_5"]]
    out = table.copy()
    out["candidates"] = out["candidates"].map(int_fmt)
    out["accepted"] = out["accepted"].map(int_fmt)
    for col in ["accepted_rate", "pass_at_1", "pass_at_5"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq1_1_generation_overall", "Overall code generation results by model.", "tab:rq1_generation_overall")

    fail_rates = (
        failure[(failure["task"] == "generation") & (failure["status_group"].isin(STATUS_ORDER))]
        .pivot_table(index="model", columns="status_group", values="rate", aggfunc="sum")
        .reindex(gen_order)
        .fillna(0)
    )
    fail_rates = fail_rates[[c for c in STATUS_ORDER if c in fail_rates.columns]].reset_index()
    out = fail_rates.copy()
    for col in out.columns[1:]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq1_2_generation_failure_distribution", "Generation failure type distribution by model.", "tab:rq1_failure_distribution")

    efficiency = generation_efficiency_summary(gen_results, data["generation_first_ac_efficiency"]).sort_values("AC_rate", ascending=False)
    out = efficiency[
        [
            "model",
            "total_attempts",
            "accepted_count",
            "AC_rate",
            "median_runtime_ms",
            "median_memory_mb",
            "runtime_efficiency",
            "memory_efficiency",
            "pareto_rate",
        ]
    ].copy()
    out["total_attempts"] = out["total_attempts"].map(int_fmt)
    out["accepted_count"] = out["accepted_count"].map(int_fmt)
    out["AC_rate"] = out["AC_rate"].map(pct)
    out["pareto_rate"] = out["pareto_rate"].map(pct)
    for col in [
        "median_runtime_ms",
        "median_memory_mb",
        "runtime_efficiency",
        "memory_efficiency",
    ]:
        out[col] = out[col].map(lambda value: float_fmt(value, 3))
    write_table(out, "table_rq1_3_generation_efficiency", "Normalized first-AC code efficiency by model.", "tab:rq1_generation_efficiency")

    lang_table = language.sort_values("pass_at_5", ascending=False)[["language", "n_tasks", "pass_at_1", "pass_at_5", "pass_at_5_gain"]]
    out = lang_table.copy()
    out["n_tasks"] = out["n_tasks"].map(int_fmt)
    for col in ["pass_at_1", "pass_at_5", "pass_at_5_gain"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq2_1_language_ranking", "Average generation pass@1 and pass@5 by language.", "tab:rq2_language_ranking")

    matrix = (
        gen_passk.groupby(["model", "language"])["pass_at_5"]
        .mean()
        .unstack("language")
        .reindex(gen_order)
        .reindex(columns=LANGUAGE_ORDER)
        .reset_index()
    )
    out = matrix.copy()
    for col in LANGUAGE_ORDER:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq2_2_model_language_matrix", "Model by language generation pass@5 matrix.", "tab:rq2_model_language_matrix")

    trans_counts = trans_results.groupby("model").agg(candidates=("is_accepted", "size"), accepted=("is_accepted", "sum"))
    trans_pass = trans_passk.groupby("model")[["pass_at_1", "pass_at_5"]].mean()
    table = trans_counts.join(trans_pass).reindex(trans_order).reset_index()
    table["accepted_rate"] = table["accepted"] / table["candidates"]
    table = table[["model", "candidates", "accepted", "accepted_rate", "pass_at_1", "pass_at_5"]]
    out = table.copy()
    out["candidates"] = out["candidates"].map(int_fmt)
    out["accepted"] = out["accepted"].map(int_fmt)
    for col in ["accepted_rate", "pass_at_1", "pass_at_5"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq3_1_translation_overall", "Overall code translation results by model.", "tab:rq3_translation_overall")

    pair_matrix = pair.pivot(index="source_lang", columns="target_lang", values="pass_at_5").reindex(
        index=LANGUAGE_ORDER, columns=LANGUAGE_ORDER
    )
    out = pair_matrix.reset_index()
    for col in LANGUAGE_ORDER:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq3_2_pair_matrix", "Source by target language translation pass@5 matrix.", "tab:rq3_pair_matrix")

    pair_direct = pair[["source_lang", "target_lang", "pass_at_5"]].copy()
    pair_reverse = pair_direct.rename(
        columns={"source_lang": "target_lang", "target_lang": "source_lang", "pass_at_5": "reverse_pass_at_5"}
    )
    gaps = pair_direct.merge(pair_reverse, on=["source_lang", "target_lang"])
    gaps = gaps[gaps["source_lang"] < gaps["target_lang"]].copy()
    gaps["direction"] = gaps["source_lang"] + "->" + gaps["target_lang"]
    gaps["reverse_direction"] = gaps["target_lang"] + "->" + gaps["source_lang"]
    gaps["abs_gap"] = (gaps["pass_at_5"] - gaps["reverse_pass_at_5"]).abs()
    gaps = gaps.sort_values("abs_gap", ascending=False).head(10)
    out = gaps[["direction", "pass_at_5", "reverse_direction", "reverse_pass_at_5", "abs_gap"]].copy()
    for col in ["pass_at_5", "reverse_pass_at_5", "abs_gap"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq3_3_directional_gap", "Largest directional translation gaps by language pair.", "tab:rq3_directional_gap")

    diff = difficulty.set_index("difficulty").reindex(["Easy", "Medium", "Hard"]).reset_index()
    out = diff[["difficulty", "n_tasks", "pass_at_1", "pass_at_5", "pass_at_5_gain"]].copy()
    out["n_tasks"] = out["n_tasks"].map(int_fmt)
    for col in ["pass_at_1", "pass_at_5", "pass_at_5_gain"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq4_1_difficulty_pass", "Generation pass@1 and pass@5 by problem difficulty.", "tab:rq4_difficulty_pass")

    tag_top = tag[tag["n_tasks"] >= 30].sort_values("pass_at_5", ascending=False).head(20)
    out = tag_top[["tag", "n_tasks", "pass_at_1", "pass_at_5", "pass_at_5_gain"]].copy()
    out["n_tasks"] = out["n_tasks"].map(int_fmt)
    for col in ["pass_at_1", "pass_at_5", "pass_at_5_gain"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq4_2_top_tags", "Top algorithm tags by generation pass@5.", "tab:rq4_top_tags")

    gen_gain = gen_passk.groupby("model")[["pass_at_1", "pass_at_5"]].mean().reindex(gen_order).reset_index()
    gen_gain.insert(0, "task", "generation")
    trans_gain = trans_passk.groupby("model")[["pass_at_1", "pass_at_5"]].mean().reindex(trans_order).reset_index()
    trans_gain.insert(0, "task", "translation")
    gain = pd.concat([gen_gain, trans_gain], ignore_index=True)
    gain["pass_at_5_gain"] = gain["pass_at_5"] - gain["pass_at_1"]
    out = gain.copy()
    for col in ["pass_at_1", "pass_at_5", "pass_at_5_gain"]:
        out[col] = out[col].map(pct)
    write_table(out, "table_rq4_3_passk_gain", "Benefit of five samples over one sample.", "tab:rq4_passk_gain")


def main() -> None:
    ensure_dirs()
    data = {
        "generation_results": drop_excluded_models(read_csv("generation_results.csv")),
        "translation_results": drop_excluded_models(read_csv("translation_results.csv")),
        "generation_passk": drop_excluded_models(read_csv("generation_passk.csv")),
        "translation_passk": drop_excluded_models(read_csv("translation_passk.csv")),
        "language_summary": read_csv("language_summary.csv"),
        "pair_summary": read_csv("pair_summary.csv"),
        "difficulty_summary": read_csv("difficulty_summary.csv"),
        "tag_summary": read_csv("tag_summary.csv"),
        "failure_summary": drop_excluded_models(read_csv("failure_summary.csv")),
    }
    required = {
        "generation_results": ["model", "is_accepted"],
        "translation_results": ["model", "is_accepted"],
        "generation_passk": ["model", "language", *PASS_COLS],
        "translation_passk": ["model", "source_lang", "target_lang", *PASS_COLS],
        "language_summary": ["language", "n_tasks", *PASS_COLS, "pass_at_5_gain"],
        "pair_summary": ["source_lang", "target_lang", "n_tasks", *PASS_COLS, "pass_at_5_gain"],
        "difficulty_summary": ["difficulty", "n_tasks", *PASS_COLS, "pass_at_5_gain"],
        "tag_summary": ["tag", "n_tasks", *PASS_COLS, "pass_at_5_gain"],
        "failure_summary": ["task", "model", "status_group", "count", "rate"],
    }
    for name, columns in required.items():
        require_columns(data[name], name, columns)
    data["generation_first_ac_efficiency"] = first_ac_efficiency_data(data["generation_results"])

    generate_figures(data)
    generate_tables(data)
    print(f"Figures written to {FIG_DIR}")
    print(f"Tables written to {TABLE_DIR}")


if __name__ == "__main__":
    main()
