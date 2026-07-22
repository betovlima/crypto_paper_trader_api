from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def check_database(path: Path) -> int:
    if not path.exists():
        print(f"MISSING: {path}")
        return 0

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as exc:
        print(f"CORRUPTED: {path}")
        print(f"SQLite error: {exc}")
        return 2

    messages = [str(row[0]) for row in rows]
    if messages == ["ok"]:
        print(f"OK: {path}")
        return 0

    print(f"CORRUPTED: {path}")
    for message in messages:
        print(f"- {message}")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Crypto Paper Trader SQLite databases without modifying them."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing the SQLite databases (default: ./data).",
    )
    args = parser.parse_args()

    statuses = [
        check_database(args.data_dir / "crypto_paper_trader_api.db"),
        check_database(args.data_dir / "ai_pattern_trader.db"),
    ]
    return max(statuses)


if __name__ == "__main__":
    raise SystemExit(main())
