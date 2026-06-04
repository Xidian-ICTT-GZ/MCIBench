from __future__ import annotations

from pathlib import Path


def first_existing(root: Path, *relative_paths: str) -> Path:
    for relative_path in relative_paths:
        path = root / relative_path
        if path.exists():
            return path
    return root / relative_paths[0]


def metadata_dir(root: Path) -> Path:
    return first_existing(root, "metadata", "data/metadata", "Infor")


def descriptions_dir(root: Path) -> Path:
    return first_existing(root, "metadata/problems/descriptions", "data/raw/descriptions", "Description")


def reference_solutions_dir(root: Path) -> Path:
    return first_existing(root, "solutions/reference", "data/raw/reference_solutions", "Answer")


def snippets_dir(root: Path) -> Path:
    return first_existing(root, "metadata/templates/snippets", "data/raw/snippets", "Snippets")


def generation_code_dir(root: Path) -> Path:
    return first_existing(root, "generation/code", "experiments/generation/code", "GenCode")


def generation_submit_dir(root: Path) -> Path:
    return first_existing(root, "generation/submissions", "experiments/generation/submissions", "Submit_Gen")


def translation_code_dir(root: Path) -> Path:
    return first_existing(root, "translation/code", "experiments/translation/code", "TransCode")


def translation_submit_dir(root: Path) -> Path:
    return first_existing(root, "translation/submissions", "experiments/translation/submissions", "Submit_Trans")


def derived_data_dir(root: Path) -> Path:
    return first_existing(root, "docs/derived_data", "artifacts/derived_data", "paper/derived_data")


def figure_dir(root: Path) -> Path:
    return first_existing(root, "docs/figures", "artifacts/figures", "paper/figures")


def table_dir(root: Path) -> Path:
    return first_existing(root, "docs/tables", "artifacts/tables", "paper/tables")


def docs_dir(root: Path) -> Path:
    return first_existing(root, "docs", "paper")


def indexes_dir(root: Path) -> Path:
    return first_existing(root, "metadata/indexes", "data/indexes")
