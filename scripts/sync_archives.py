from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ARCHIVES = {
    "generation_submissions": (ROOT / "generation" / "submissions.tgz", ROOT / "generation"),
    "translation_submissions": (ROOT / "translation" / "submissions.tgz", ROOT / "translation"),
    "generation_results": (ROOT / "generation" / "records" / "generation_results.csv.tgz", ROOT / "generation" / "records"),
    "translation_results": (ROOT / "translation" / "records" / "translation_results.csv.tgz", ROOT / "translation" / "records"),
}


def ensure_within_root(path: Path) -> Path:
    resolved = path.resolve()
    root = ROOT.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"path escapes repository root: {resolved}")
    return resolved


def reset_directory(path: Path) -> None:
    target = ensure_within_root(path)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)


def extract_archive(archive: Path, destination: Path, reset_dirs: bool) -> None:
    archive = ensure_within_root(archive)
    destination = ensure_within_root(destination)
    if not archive.is_file():
        raise FileNotFoundError(f"archive missing: {archive}")
    destination.mkdir(parents=True, exist_ok=True)

    if reset_dirs:
        if archive.name == "submissions.tgz":
            reset_directory(destination / "submissions")
        elif archive.name.endswith(".csv.tgz"):
            csv_path = destination / archive.name.removesuffix(".tgz")
            if csv_path.exists():
                csv_path.unlink()

    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(destination)
    print(f"extracted {archive.relative_to(ROOT)} -> {destination.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MCIBench local data archives.")
    parser.add_argument(
        "names",
        nargs="*",
        choices=sorted(ARCHIVES),
        help="Archives to extract. Defaults to every available archive.",
    )
    parser.add_argument("--keep-existing", action="store_true", help="Keep existing expanded directories/files.")
    args = parser.parse_args()

    names = args.names or sorted(ARCHIVES)
    for name in names:
        archive, destination = ARCHIVES[name]
        extract_archive(archive, destination, reset_dirs=not args.keep_existing)


if __name__ == "__main__":
    main()
