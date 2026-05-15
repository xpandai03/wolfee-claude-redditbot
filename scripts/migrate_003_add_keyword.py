"""Migration 003 — add keyword column to processed_emails.

No backfill — the f5bot keyword for existing rows is not recoverable without
re-reading Gmail messages. Idempotent.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "state" / "processed.db"


def main() -> int:
    if not DB.exists():
        print(f"migration 003: {DB} does not exist yet — nothing to migrate", file=sys.stderr)
        return 0
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(processed_emails)")}
        if "keyword" not in cols:
            cur.execute("ALTER TABLE processed_emails ADD COLUMN keyword TEXT")
            print("migration 003: added keyword column")
        else:
            print("migration 003: keyword column already present")
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
