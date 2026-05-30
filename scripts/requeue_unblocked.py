"""One-time re-queue of posts the old allowlist wrongly skipped (Phase 2).

Before Phase 2 (2026-05-29) every F5Bot post in a sub outside the ~48-sub
ALLOWED_SUBS frozenset was recorded as `skipped_not_allowed_sub` and thereby
marked processed. Removing the allowlist only helps *future* posts — the
already-skipped backlog stays deduped (by email id AND post id) and never gets
a second look. This script deletes those backlog rows so the next cron tick
re-fetches the still-in-label emails and runs them through the new
denylist -> classifier path.

Scope: only rows with action='skipped_not_allowed_sub' whose processed_at is
within the last N hours (default 48). The window keeps re-fetched posts near the
36h MAX_POST_AGE_HOURS cap so they're actually draftable, and bounds the
one-tick burst of Reddit fetches. processed_at is used as the freshness proxy
because the pre-fetch allowlist skip stored created_utc=None.

SAFE BY DEFAULT: with no flags this only prints what it *would* delete (a dry
SELECT). Pass --execute to actually delete. Run this AFTER the Phase 2 code is
deployed, otherwise re-fetched posts hit the old allowlist again and re-skip.

Usage:
    python scripts/requeue_unblocked.py                  # dry run (count + sample)
    python scripts/requeue_unblocked.py --hours 48       # dry run, custom window
    python scripts/requeue_unblocked.py --execute        # actually delete
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone

import config

TARGET_ACTION = "skipped_not_allowed_sub"


def _cutoff_iso(hours: int) -> str:
    """ISO-8601 UTC timestamp `hours` ago, matching db.record's format so a
    lexicographic string compare on processed_at is correct."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=48,
                        help="Re-queue skips newer than this many hours (default: 48).")
    parser.add_argument("--execute", action="store_true",
                        help="Actually DELETE the rows. Omit for a dry run.")
    args = parser.parse_args()

    cutoff = _cutoff_iso(args.hours)
    where = "action = ? AND processed_at >= ?"
    params = (TARGET_ACTION, cutoff)

    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT email_id, processed_at, post_url FROM processed_emails "
            f"WHERE {where} ORDER BY processed_at",
            params,
        ).fetchall()

        n = len(rows)
        print(f"DB: {config.DB_PATH}")
        print(f"Window: last {args.hours}h (processed_at >= {cutoff})")
        print(f"Matching '{TARGET_ACTION}' rows: {n}")
        for r in rows[:30]:
            print(f"  {r['processed_at']}  {r['email_id']}  {r['post_url']}")
        if n > 30:
            print(f"  ... and {n - 30} more")

        if not args.execute:
            print("\nDRY RUN — no rows deleted. Re-run with --execute to delete the above.")
            return 0

        if n == 0:
            print("\nNothing to delete.")
            return 0

        deleted = con.execute(
            f"DELETE FROM processed_emails WHERE {where}", params
        ).rowcount
        con.commit()
        print(f"\nDELETED {deleted} row(s). The next cron tick will re-fetch these "
              f"emails and run them through the denylist -> classifier path.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
