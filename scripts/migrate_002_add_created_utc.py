"""Migration 002 — add created_utc column to processed_emails.

No backfill. Existing 11 rows remain NULL (acceptable per spec — historical
posts won't have an age recorded). Idempotent.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "state" / "processed.db"


def main() -> int:
    if not DB.exists():
        print(f"migration 002: {DB} does not exist yet — nothing to migrate", file=sys.stderr)
        return 0
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(processed_emails)")}
        if "created_utc" not in cols:
            cur.execute("ALTER TABLE processed_emails ADD COLUMN created_utc REAL")
            print("migration 002: added created_utc column")
        else:
            print("migration 002: created_utc column already present")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
