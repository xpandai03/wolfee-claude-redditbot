"""Migration 001 — add post_id column + index to processed_emails, backfill from post_url.

Idempotent: safe to re-run. Detects existing column and skips ALTER.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# Make the project root importable so STATE_DIR / DB_PATH respect env vars
# the same way the runtime does (so this script works on Railway with
# STATE_DIR=/data the same way it works on the Mac with the default path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

DB = config.DB_PATH

POST_ID_RE = re.compile(r"/comments/([A-Za-z0-9]+)", re.IGNORECASE)


def main() -> int:
    if not DB.exists():
        print(f"migration 001: {DB} does not exist yet — nothing to migrate", file=sys.stderr)
        return 0
    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()
        cols = {row[1] for row in cur.execute("PRAGMA table_info(processed_emails)")}
        if "post_id" not in cols:
            cur.execute("ALTER TABLE processed_emails ADD COLUMN post_id TEXT")
            print("migration 001: added post_id column")
        else:
            print("migration 001: post_id column already present")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_post_id ON processed_emails(post_id)")

        rows = cur.execute(
            "SELECT email_id, post_url FROM processed_emails "
            "WHERE post_id IS NULL AND post_url IS NOT NULL"
        ).fetchall()
        backfilled = 0
        for email_id, url in rows:
            m = POST_ID_RE.search(url or "")
            if m:
                cur.execute(
                    "UPDATE processed_emails SET post_id = ? WHERE email_id = ?",
                    (m.group(1), email_id),
                )
                backfilled += 1
        conn.commit()
        print(f"migration 001: backfilled {backfilled} row(s)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
