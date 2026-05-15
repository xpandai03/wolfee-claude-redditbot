"""Local SQLite log so we never re-draft the same f5bot email.

Single table: processed_emails. We treat the Gmail message id as the key.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Literal

import config


ActionLiteral = Literal[
    "drafted",
    "skipped_tier1",
    "skipped_burned_sub",
    "skipped_fetch_failed",
    "skipped_no_url",
    "skipped_duplicate_post",
    "skipped_not_allowed_sub",
    "skipped_too_old",
    "skipped_tier2_no_fit",
    "skipped_tier2_missing_brand",
    "skipped_tier3_no_fit",
    "skipped_tier3_missing_brand",
    "error",
]

ALL_ACTIONS: tuple[ActionLiteral, ...] = (
    "drafted",
    "skipped_tier1",
    "skipped_burned_sub",
    "skipped_fetch_failed",
    "skipped_no_url",
    "skipped_duplicate_post",
    "skipped_not_allowed_sub",
    "skipped_too_old",
    "skipped_tier2_no_fit",
    "skipped_tier2_missing_brand",
    "skipped_tier3_no_fit",
    "skipped_tier3_missing_brand",
    "error",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_emails (
    email_id      TEXT PRIMARY KEY,
    processed_at  TEXT NOT NULL,
    post_url      TEXT,
    post_id       TEXT,
    created_utc   REAL,
    tier          INTEGER,
    action        TEXT NOT NULL,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_emails(processed_at);
CREATE INDEX IF NOT EXISTS idx_post_id ON processed_emails(post_id);
"""


@contextmanager
def _conn():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def is_processed(email_id: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM processed_emails WHERE email_id = ? LIMIT 1", (email_id,)
        ).fetchone()
        return row is not None


def get_processed_ids() -> set[str]:
    with _conn() as c:
        return {
            r["email_id"]
            for r in c.execute("SELECT email_id FROM processed_emails")
        }


def record(
    email_id: str,
    action: ActionLiteral,
    post_url: str | None = None,
    post_id: str | None = None,
    created_utc: float | None = None,
    tier: int | None = None,
    note: str | None = None,
) -> None:
    if action not in ALL_ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {ALL_ACTIONS}")
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO processed_emails "
            "(email_id, processed_at, post_url, post_id, created_utc, tier, action, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                email_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                post_url,
                post_id,
                created_utc,
                tier,
                action,
                note,
            ),
        )


def is_post_processed(post_id: str) -> bool:
    """True if any prior email already produced a row for this Reddit post id."""
    if not post_id:
        return False
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM processed_emails WHERE post_id = ? LIMIT 1", (post_id,)
        ).fetchone()
        return row is not None


def counts_since(since_iso: str) -> dict[str, int]:
    """Action -> count for rows processed at or after `since_iso`."""
    with _conn() as c:
        rows = c.execute(
            "SELECT action, COUNT(*) AS n FROM processed_emails "
            "WHERE processed_at >= ? GROUP BY action",
            (since_iso,),
        ).fetchall()
    out = {a: 0 for a in ALL_ACTIONS}
    for r in rows:
        out[r["action"]] = r["n"]
    return out


def tier_counts_since(since_iso: str) -> dict[int, int]:
    """Tier (2 or 3) -> count for drafted rows since."""
    with _conn() as c:
        rows = c.execute(
            "SELECT tier, COUNT(*) AS n FROM processed_emails "
            "WHERE processed_at >= ? AND action = 'drafted' "
            "GROUP BY tier",
            (since_iso,),
        ).fetchall()
    return {int(r["tier"]): r["n"] for r in rows if r["tier"] is not None}


if __name__ == "__main__":
    # Smoke test: init, insert 3 rows of different shapes, verify lookups + counts.
    init_db()
    record("test-msg-1", "drafted", "https://reddit.com/r/x/comments/aaa/", tier=3)
    record("test-msg-2", "skipped_tier1", "https://reddit.com/r/y/comments/bbb/", tier=1)
    record("test-msg-3", "skipped_burned_sub", "https://reddit.com/r/saas/comments/ccc/",
           note="r/saas is on the blocklist")
    record("test-msg-1", "drafted", "https://reddit.com/r/x/comments/aaa/", tier=3)  # idempotent

    assert is_processed("test-msg-1")
    assert not is_processed("does-not-exist")

    ids = get_processed_ids()
    print(f"processed_ids ({len(ids)}): {sorted(ids)}")

    today = datetime.now(timezone.utc).date().isoformat()
    print(f"counts today:        {counts_since(today)}")
    print(f"tier counts today:   {tier_counts_since(today)}")

    # cleanup test rows so we don't poison the real run
    with _conn() as c:
        c.execute("DELETE FROM processed_emails WHERE email_id LIKE 'test-msg-%'")
    print("cleaned up test rows")
