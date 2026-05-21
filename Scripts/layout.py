from __future__ import annotations

from pathlib import Path


def first_existing(root: Path, *relative_paths: str) -> Path:
    for relative_path in relative_paths:
        path = root / relative_path
        if path.exists():
            return path
    return root / relative_paths[0]


def metadata_dir(root: Path) -> Path:
    return first_existing(root, "data/metadata", "Infor")


def descriptions_dir(root: Path) -> Path:
    return first_existing(root, "data/raw/descriptions", "Description")


def reference_solutions_dir(root: Path) -> Path:
    return first_existing(root, "data/raw/reference_solutions", "Answer")


def snippets_dir(root: Path) -> Path:
    return first_existing(root, "data/raw/snippets", "Snippets")


def generation_code_dir(root: Path) -> Path:
    return first_existing(root, "experiments/generation/code", "GenCode")


def generation_submit_dir(root: Path) -> Path:
    return first_existing(root, "experiments/generation/submissions", "Submit_Gen")


def translation_code_dir(root: Path) -> Path:
    return first_existing(root, "experiments/translation/code", "TransCode")


def translation_submit_dir(root: Path) -> Path:
    return first_existing(root, "experiments/translation/submissions", "Submit_Trans")


def derived_data_dir(root: Path) -> Path:
    return first_existing(root, "artifacts/derived_data", "paper/derived_data")


def figure_dir(root: Path) -> Path:
    return first_existing(root, "artifacts/figures", "paper/figures")


def table_dir(root: Path) -> Path:
    return first_existing(root, "artifacts/tables", "paper/tables")


def docs_dir(root: Path) -> Path:
    return first_existing(root, "docs", "paper")


def indexes_dir(root: Path) -> Path:
    return root / "data" / "indexes"
