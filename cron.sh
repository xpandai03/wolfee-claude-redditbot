#!/usr/bin/env bash
# Cron entrypoint for the Wolfee Reddit comment seeder.
# Resolves its own location so cron-from-anywhere works, runs the pipeline
# inside the project's venv, and appends timestamped output to logs/cron.log.

set -u  # don't set -e — we want the run line to record even if it returns non-zero

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p logs
LOG="$SCRIPT_DIR/logs/cron.log"

{
    echo
    echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/run.py" "$@"
    echo "exit=$?"
} >> "$LOG" 2>&1
