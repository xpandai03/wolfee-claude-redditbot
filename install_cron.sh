#!/usr/bin/env bash
# Idempotent crontab installer for the Wolfee Reddit comment seeder.
#
# Adds a */30 minute cron entry if (and only if) one is not already present.
# Pass --dry-run to print the line that would be added without modifying
# anything. Re-running this script after install is a no-op.
#
# This script is NOT auto-installed. Run it manually after reviewing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_WRAPPER="$SCRIPT_DIR/cron.sh"
LOG_PATH="$SCRIPT_DIR/logs/cron.log"

# Marker grep'd on existing crontab to detect prior installs.
MARKER="$CRON_WRAPPER"
LINE="*/30 * * * * cd \"$SCRIPT_DIR\" && \"$CRON_WRAPPER\" >> \"$LOG_PATH\" 2>&1"

if [[ ! -x "$CRON_WRAPPER" ]]; then
    echo "ERROR: $CRON_WRAPPER is missing or not executable." >&2
    exit 1
fi

# Read current crontab into a tempfile. `crontab -l` exits non-zero when
# there is no crontab yet; treat that as empty.
CURRENT="$(crontab -l 2>/dev/null || true)"

if printf '%s\n' "$CURRENT" | grep -Fq "$MARKER"; then
    echo "Cron entry already present. No change made."
    printf '%s\n' "$CURRENT" | grep -F "$MARKER"
    exit 0
fi

if [[ "${1:-}" == "--dry-run" ]]; then
    echo "Would append the following line to your crontab:"
    echo "    $LINE"
    echo
    echo "(Current crontab will not be modified.)"
    exit 0
fi

# Append the new line preserving existing entries.
{
    printf '%s' "$CURRENT"
    # Ensure trailing newline between existing content and the new line.
    if [[ -n "$CURRENT" && "${CURRENT: -1}" != $'\n' ]]; then
        printf '\n'
    fi
    printf '%s\n' "$LINE"
} | crontab -

echo "Installed cron entry:"
echo "    $LINE"
echo
echo "Inspect with: crontab -l"
echo "Tail logs:    tail -f $LOG_PATH"
