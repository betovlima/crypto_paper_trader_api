from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DATABASE_NAMES = ("crypto_paper_trader_api.db", "ai_pattern_trader.db")


def integrity_status(database_path: Path) -> tuple[bool, str]:
    if not database_path.exists():
        return True, "database does not exist yet"
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        return False, str(exc)
    messages = [str(row[0]) for row in rows]
    return messages == ["ok"], "; ".join(messages)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Back up SQLite files and isolate stale WAL/SHM sidecars without deleting them. "
            "Use only while the API is stopped."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move WAL/SHM files after creating a backup.",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = data_dir / f"sqlite_backup_{timestamp}"

    existing = []
    for name in DATABASE_NAMES:
        database = data_dir / name
        existing.extend(
            path
            for path in (
                database,
                Path(f"{database}-wal"),
                Path(f"{database}-shm"),
            )
            if path.exists()
        )

    if not existing:
        print(f"No SQLite files found in {data_dir}")
        return 0

    print("Files found:")
    for path in existing:
        print(f"- {path}")

    if not args.apply:
        print("\nDry run only. Stop the API and run again with --apply to back up the files")
        print("and isolate only the -wal and -shm sidecars.")
        return 0

    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    print(f"\nBackup created: {backup_dir}")

    for name in DATABASE_NAMES:
        database = data_dir / name
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            if not sidecar.exists():
                continue
            isolated = data_dir / f"{sidecar.name}.stale.{timestamp}"
            sidecar.rename(isolated)
            print(f"Isolated: {sidecar.name} -> {isolated.name}")

    print("\nIntegrity after isolating sidecars:")
    exit_code = 0
    for name in DATABASE_NAMES:
        database = data_dir / name
        healthy, detail = integrity_status(database)
        print(f"- {database.name}: {'OK' if healthy else 'CORRUPTED'} ({detail})")
        if not healthy:
            exit_code = 2

    if exit_code:
        print("\nThe main database is still corrupted. Do not delete the backup.")
        print("Restore a known-good database or perform a controlled SQLite recovery.")
    else:
        print("\nThe main databases are readable. Start the API and confirm the experiment state.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
