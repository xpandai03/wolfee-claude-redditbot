"""Two-mode helper for seeding existing processed_emails rows to Railway.

Usage (operator-driven, two-step):

  1. On your local Mac (default STATE_DIR -> repo state/processed.db):
       .venv/bin/python scripts/seed_db_from_local.py --export > /tmp/seed.sql

  2. On Railway, with the volume mounted at /data:
       cat /tmp/seed.sql | railway run python scripts/seed_db_from_local.py --import

The --import mode reads SQL from stdin and applies it against config.DB_PATH
(which on Railway is /data/processed.db when STATE_DIR=/data is set).

Idempotency: --export emits INSERT OR IGNORE statements, so re-running the
import against a DB that has already received some of those rows (or that
has newer rows produced by Railway cron ticks between export and import)
will not clobber anything. PRIMARY KEY = email_id is the dedup point.

Schema: --import will create the table via the same SCHEMA the runtime uses,
so it's safe to import into a fresh /data/processed.db that has never been
init'd.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import db as wolfee_db  # noqa: E402


COLUMNS = (
    "email_id",
    "processed_at",
    "post_url",
    "post_id",
    "created_utc",
    "keyword",
    "tier",
    "action",
    "note",
)


def _quote_sql(v) -> str:
    """Render one value for SQL literal embedding. Handles None / int / float / str."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def export(out=sys.stdout) -> int:
    if not config.DB_PATH.exists():
        print(f"ERROR: source DB not found at {config.DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM processed_emails ORDER BY processed_at"
        ).fetchall()
    finally:
        conn.close()

    print("BEGIN;", file=out)
    for r in rows:
        values = ", ".join(_quote_sql(r[c]) for c in COLUMNS)
        print(
            f"INSERT OR IGNORE INTO processed_emails ({', '.join(COLUMNS)}) "
            f"VALUES ({values});",
            file=out,
        )
    print("COMMIT;", file=out)
    print(f"-- exported {len(rows)} row(s) from {config.DB_PATH}", file=sys.stderr)
    return 0


def import_from_stdin() -> int:
    sql = sys.stdin.read()
    if not sql.strip():
        print("ERROR: stdin was empty; nothing to import", file=sys.stderr)
        return 1
    wolfee_db.init_db()  # ensures table + indexes exist with current schema
    conn = sqlite3.connect(config.DB_PATH)
    try:
        before = conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()[0]
        conn.executescript(sql)
        after = conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    print(
        f"imported into {config.DB_PATH}: {before} -> {after} rows (delta {after - before})",
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--export", action="store_true", help="dump local DB rows as SQL to stdout")
    g.add_argument("--import", dest="do_import", action="store_true", help="read SQL from stdin and apply to config.DB_PATH")
    args = p.parse_args()
    if args.export:
        return export()
    return import_from_stdin()


if __name__ == "__main__":
    sys.exit(main())
