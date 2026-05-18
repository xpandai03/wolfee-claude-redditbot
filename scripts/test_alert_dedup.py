"""Manual test for send_error_alert dedup logic.

Run with:    .venv/bin/python scripts/test_alert_dedup.py

Asserts:
  1. First alert with a given (class, normalized-message) fires + writes a record.
  2. A second alert with the same key (different email id baked into the message)
     is suppressed and the file stays at 1 record.
  3. A third alert with a different exception class fires + writes a 2nd record.
  4. After the TTL window has elapsed (simulated by rewriting timestamps), the
     same key fires again and a 3rd record is written.

Does not hit the real Telegram API — send_message is monkeypatched.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    test_dir = Path("/tmp/wolfee_dedup_test")
    test_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LOGS_DIR"] = str(test_dir)
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "x")

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    import config  # noqa: F401  (forces LOGS_DIR resolution from env)
    import telegram_client

    dedup_file = telegram_client.ALERT_DEDUP_PATH
    if dedup_file.exists():
        dedup_file.unlink()

    sent: list[str] = []

    def fake_send(text, parse_mode="HTML", disable_preview=True):
        sent.append(text)
        return {"ok": True}

    telegram_client.send_message = fake_send

    def line_count(p: Path) -> int:
        if not p.exists():
            return 0
        with p.open() as f:
            return sum(1 for line in f if line.strip())

    telegram_client.send_error_alert(
        "test",
        ValueError("billing too low for email 19e3ad9ecb82ef0a, request 11223344556677"),
    )
    assert len(sent) == 1, f"test 1: expected 1 send, got {len(sent)}"
    assert line_count(dedup_file) == 1, "test 1: expected 1 dedup record"
    print("test 1 ok — first alert sent, dedup record written")

    telegram_client.send_error_alert(
        "test",
        ValueError("billing too low for email 19e3ad9ecb82ef0b, request 99887766554433"),
    )
    assert len(sent) == 1, f"test 2: expected still 1 send, got {len(sent)}"
    assert line_count(dedup_file) == 1, "test 2: dedup file should not have grown"
    print("test 2 ok — same normalized key suppressed (varying email id stripped)")

    telegram_client.send_error_alert("test", RuntimeError("billing too low"))
    assert len(sent) == 2, f"test 3: expected 2 sends, got {len(sent)}"
    assert line_count(dedup_file) == 2, "test 3: expected 2 dedup records"
    print("test 3 ok — different exception class fires its own alert")

    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=4000)).isoformat(timespec="seconds")
    records = []
    with dedup_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec["ts_iso"] = old_ts
            records.append(rec)
    with dedup_file.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    telegram_client.send_error_alert(
        "test",
        ValueError("billing too low for email 19e3ad9ecb82ef0c, request 12345678901234"),
    )
    assert len(sent) == 3, f"test 4: expected 3 sends after TTL expiry, got {len(sent)}"
    print("test 4 ok — same key fires again once TTL has elapsed")

    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
