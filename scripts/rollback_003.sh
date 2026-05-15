#!/usr/bin/env bash
# Rollback migration 003 — drop keyword column.
# Requires SQLite >= 3.35 for DROP COLUMN.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${STATE_DIR:-$REPO_ROOT/state}/processed.db"
sqlite3 "$DB" "ALTER TABLE processed_emails DROP COLUMN keyword;"
echo "rollback 003: dropped keyword column (db=$DB)"
