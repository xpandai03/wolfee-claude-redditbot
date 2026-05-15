#!/usr/bin/env bash
# Rollback migration 001 — drop post_id column + index.
# Requires SQLite >= 3.35 for DROP COLUMN. Verified on macOS system sqlite3.
#
# Resolves DB path the same way the runtime does (STATE_DIR env var with
# repo-root/state fallback), so this also works on Railway with STATE_DIR=/data.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${STATE_DIR:-$REPO_ROOT/state}/processed.db"
sqlite3 "$DB" <<'SQL'
DROP INDEX IF EXISTS idx_post_id;
ALTER TABLE processed_emails DROP COLUMN post_id;
SQL
echo "rollback 001: dropped post_id column and idx_post_id (db=$DB)"
