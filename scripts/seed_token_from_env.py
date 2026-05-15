"""One-shot helper: write GMAIL_TOKEN_JSON env var content to TOKEN_PATH.

Run once on Railway to bootstrap the OAuth token onto the mounted volume,
e.g.:

    railway run python scripts/seed_token_from_env.py

After this script runs, subsequent cron invocations of run.py read the
token from disk and refresh-rotate it in place, so the GMAIL_TOKEN_JSON
env var is only needed for the initial seed.

Exit codes:
    0  token already present on disk OR seeded successfully
    1  GMAIL_TOKEN_JSON env var is missing / unset
    2  GMAIL_TOKEN_JSON is set but contains invalid JSON

This script does not echo the token to stdout. The token never appears
in this file or in any commit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gmail_client  # noqa: E402 — wraps the env-var seed logic
import config  # noqa: E402


def main() -> int:
    if config.TOKEN_PATH.exists():
        print(f"token already present at {config.TOKEN_PATH}; no seed needed")
        return 0
    try:
        seeded = gmail_client._seed_token_from_env()
    except RuntimeError as e:
        # gmail_client raises a clean message when JSON is malformed; preserve it.
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not seeded:
        print(
            "ERROR: GMAIL_TOKEN_JSON env var is not set and token file is "
            f"absent at {config.TOKEN_PATH}. Set the env var (paste the "
            "contents of your local token.json into the Railway dashboard) "
            "and re-run this script.",
            file=sys.stderr,
        )
        return 1
    # Confirm without echoing contents.
    size = config.TOKEN_PATH.stat().st_size
    print(f"seeded {config.TOKEN_PATH} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
