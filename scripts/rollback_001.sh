#!/usr/bin/env bash
# Rollback migration 001 — drop post_id column + index.
# Requires SQLite >= 3.35 for DROP COLUMN. Verified on macOS system sqlite3.
set -euo pipefail
DB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/state/processed.db"
sqlite3 "$DB" <<'SQL'
DROP INDEX IF EXISTS idx_post_id;
ALTER TABLE processed_emails DROP COLUMN post_id;
SQL
echo "rollback 001: dropped post_id column and idx_post_id"
