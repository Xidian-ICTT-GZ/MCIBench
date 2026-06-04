from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


REFERENCE_RE = re.compile(r"^(?P<qid>\d+)_(?P<lang>.+)_ans(?P<attempt>\d+)\.txt$")


def require_path(path: Path, kind: str) -> Path:
    resolved = path.resolve()
    if kind == "dir" and resolved.is_dir():
        return resolved
    if kind == "file" and resolved.is_file():
        return resolved
    raise FileNotFoundError(f"required {kind} missing: {resolved}")


def copy_tree(src: Path, dst: Path) -> None:
    require_path(src, "dir")
    shutil.copytree(src, dst)


def copy_file(src: Path, dst: Path) -> None:
    require_path(src, "file")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def materialize_references(src_dir: Path, out_file: Path) -> int:
    require_path(src_dir, "dir")
    result: dict[str, dict[str, dict[str, str]]] = {}
    total = 0

    for qid_dir in sorted(src_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else p.name):
        if not qid_dir.is_dir():
            continue
        for file_path in sorted(qid_dir.iterdir()):
            if not file_path.is_file():
                continue
            match = REFERENCE_RE.match(file_path.name)
            if match is None:
                raise ValueError(f"unexpected reference filename: {file_path}")

            qid = match.group("qid")
            lang = match.group("lang")
            attempt = match.group("attempt")
            que_key = f"Que{qid}"
            ans_key = f"Ans{attempt}"
            result.setdefault(que_key, {}).setdefault(lang, {})[ans_key] = file_path.read_text(encoding="utf-8")
            total += 1

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return total


def reset_destination(dest: Path, expected_root: Path) -> None:
    resolved_dest = dest.resolve()
    resolved_root = expected_root.resolve()
    if resolved_dest != resolved_root / "rawdata":
        raise ValueError(f"destination must be repository rawdata: {resolved_root / 'rawdata'}")
    if resolved_dest.exists():
        shutil.rmtree(resolved_dest)
    resolved_dest.mkdir(parents=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize canonical MCIBench data into this app's rawdata layout.")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    source = require_path(Path(args.source), "dir")
    repo = require_path(Path(args.repo), "dir")
    dest = repo / "rawdata"

    metadata = require_path(source / "metadata", "dir")
    descriptions = require_path(source / "metadata" / "problems" / "descriptions", "dir")
    snippets = require_path(source / "metadata" / "templates" / "snippets", "dir")
    references = require_path(source / "solutions" / "reference", "dir")

    reset_destination(dest, repo)

    copy_tree(descriptions, dest / "description" / "merged")
    copy_tree(snippets, dest / "Snippets")
    copy_tree(metadata / "indexes", dest / "indexes")
    copy_tree(metadata, dest / "metadata")

    copy_file(metadata / "Qid_mapping.json", dest / "Que" / "Qid_mapping.json")
    copy_file(metadata / "question_urls.json", dest / "Que" / "question_urls.json")
    copy_file(metadata / "GenCode_ids.txt", dest / "final_que_ids.txt")
    copy_file(metadata / "TransCode_ids.txt", dest / "TransCode_ids.txt")
    copy_file(metadata / "language_pairs.txt", dest / "language_pairs.txt")

    reference_count = materialize_references(references, dest / "Que" / "all_code_result.json")

    (dest / "GenCode").mkdir()
    (dest / "Submit_Results").mkdir()
    (dest / "TransCode").mkdir()

    description_count = sum(1 for p in (dest / "description" / "merged").iterdir() if p.is_dir())
    snippet_count = sum(1 for p in (dest / "Snippets").iterdir() if p.is_dir())
    valid_count = len((dest / "final_que_ids.txt").read_text(encoding="utf-8").splitlines())
    print(f"materialized rawdata at {dest}")
    print(f"descriptions={description_count} snippets={snippet_count} references={reference_count} valid_ids={valid_count}")


if __name__ == "__main__":
    main()
