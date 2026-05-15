#!/usr/bin/env bash
# Rollback migration 002 — drop created_utc column.
# Requires SQLite >= 3.35 for DROP COLUMN.
set -euo pipefail
DB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/state/processed.db"
sqlite3 "$DB" "ALTER TABLE processed_emails DROP COLUMN created_utc;"
echo "rollback 002: dropped created_utc column"
