from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path


DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = DASHBOARD_ROOT / "database"
TARGET_DIR = DASHBOARD_ROOT / "volumes" / "backend-data"
TARGET_DB = TARGET_DIR / "mcibench.db"
PACKAGE_DB = DASHBOARD_ROOT / "packages" / "server" / "data" / "mcibench.db"


def main() -> None:
    parts = sorted(DATABASE_DIR.glob("mcibench.db.tgz.part*"))
    if not parts:
        raise FileNotFoundError(f"database archive parts missing: {DATABASE_DIR}")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(TARGET_DB) + suffix)
        if target.exists():
            target.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "mcibench.db.tgz"
        with archive.open("wb") as output:
            for part in parts:
                with part.open("rb") as handle:
                    shutil.copyfileobj(handle, output)
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(TARGET_DIR)

    with sqlite3.connect(TARGET_DB) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity_check failed: {integrity}")
    PACKAGE_DB.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(PACKAGE_DB) + suffix)
        if target.exists():
            target.unlink()
    shutil.copy2(TARGET_DB, PACKAGE_DB)
    print(f"restored {TARGET_DB}")
    print(f"copied {PACKAGE_DB}")


if __name__ == "__main__":
    main()
