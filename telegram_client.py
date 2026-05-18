"""Telegram delivery for drafted Reddit comments.

Sends as HTML (more forgiving than MarkdownV2). The draft body goes in a <pre>
block so it's monospaced and a long-press selects the whole thing on mobile —
copy → paste into Reddit, done.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

import config


class TelegramError(RuntimeError):
    pass


TELEGRAM_API = "https://api.telegram.org"
# Telegram caps text at 4096 chars per message. Drafts are <120 words so a single
# message is fine; truncate defensively just in case.
MAX_LEN = 4000

# --- alert dedup ---------------------------------------------------------
# Suppress duplicate error alerts that hit the same exception class + similar
# message text within a 1h window. The bot wakes every 30 min, so a systemic
# outage (auth, billing, sustained 5xx) would otherwise generate 2+ alerts per
# hour as new emails arrive. Dedup lets the first alert through and silences
# the rest, so you still get a real ping and don't get spammed.
#
# Storage: append-only JSONL on the mounted volume so dedup state survives
# the cron container exiting between ticks.
ALERT_DEDUP_PATH = config.LOGS_DIR / "alert_dedup.jsonl"
ALERT_DEDUP_TTL_S = 3600
ALERT_DEDUP_MAX_BYTES = 1_000_000
ALERT_DEDUP_MAX_LINES = 10_000

# Per-email variability we strip from error messages so different emails
# hitting the same outage produce the same dedup key:
#   - 16-char lowercase hex   → Gmail message ids like 19e3ad9ecb82ef0a
#   - 6+ digit runs           → request ids, token counts
#   - "Error code: NNN" /
#     "status: NNN"           → so e.g. a 502 and a 503 from the same Anthropic
#                               outage collapse to one dedup class.
_NORMALIZE_HEX_RE = re.compile(r"\b[0-9a-f]{16}\b")
_NORMALIZE_NUM_RE = re.compile(r"\b\d{6,}\b")
_NORMALIZE_STATUS_RE = re.compile(r"\b(?:error\s*code|status)\s*[:=]?\s*\d{3}\b")


def _normalize_msg(msg: str) -> str:
    s = msg.lower().strip()
    s = _NORMALIZE_HEX_RE.sub("<id>", s)
    s = _NORMALIZE_STATUS_RE.sub("<status>", s)
    s = _NORMALIZE_NUM_RE.sub("<n>", s)
    s = re.sub(r"\s+", " ", s)
    return s[:80]


def _dedup_key(exc: BaseException) -> tuple[str, str]:
    return type(exc).__name__, _normalize_msg(str(exc))


def _key_hash(klass: str, excerpt: str) -> str:
    return hashlib.sha1(f"{klass}|{excerpt}".encode()).hexdigest()[:16]


def _is_recent_dup(klass: str, excerpt: str) -> bool:
    """True iff an identical (class, normalized-excerpt) record sits inside
    ALERT_DEDUP_TTL_S. Raises only on truly unexpected errors; caller wraps."""
    if not ALERT_DEDUP_PATH.exists():
        return False
    cutoff = time.time() - ALERT_DEDUP_TTL_S
    target = _key_hash(klass, excerpt)
    with ALERT_DEDUP_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("key_hash") != target:
                continue
            try:
                t = datetime.fromisoformat(rec.get("ts_iso", "")).timestamp()
            except Exception:
                continue
            if t >= cutoff:
                return True
    return False


def _record_alert(klass: str, excerpt: str) -> None:
    ALERT_DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "key_hash": _key_hash(klass, excerpt),
        "exception_class": klass,
        "message_excerpt": excerpt,
    }
    with ALERT_DEDUP_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    try:
        st = ALERT_DEDUP_PATH.stat()
        if st.st_size > ALERT_DEDUP_MAX_BYTES:
            _truncate_dedup_file()
            return
        with ALERT_DEDUP_PATH.open() as f:
            count = sum(1 for _ in f)
        if count > ALERT_DEDUP_MAX_LINES:
            _truncate_dedup_file()
    except Exception:
        pass


def _truncate_dedup_file() -> None:
    """Rewrite the dedup file keeping only records inside ALERT_DEDUP_TTL_S."""
    cutoff = time.time() - ALERT_DEDUP_TTL_S
    keep: list[str] = []
    with ALERT_DEDUP_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                t = datetime.fromisoformat(rec.get("ts_iso", "")).timestamp()
            except Exception:
                continue
            if t >= cutoff:
                keep.append(line)
    tmp = ALERT_DEDUP_PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        for ln in keep:
            f.write(ln + "\n")
    tmp.replace(ALERT_DEDUP_PATH)


def send_error_alert(prefix: str, exc: BaseException) -> None:
    """Best-effort short error notification. NEVER raises.

    Used by run.py to surface silent breaks (auth expiry, network, API errors)
    so you notice within hours, not days. If Telegram itself is the failure
    domain, this becomes a no-op and the error stays in logs/cron.log only.

    Dedup: see ALERT_DEDUP_* above. Failures in the dedup path fall through
    to the original send-anyway behavior so a corrupted state file can never
    suppress a real alert.
    """
    try:
        try:
            klass, excerpt = _dedup_key(exc)
            if _is_recent_dup(klass, excerpt):
                print(
                    f"[telegram_client] alert suppressed (dedup): "
                    f"class={klass} excerpt={excerpt!r}",
                    file=sys.stderr,
                )
                return
        except Exception:
            klass = type(exc).__name__
            excerpt = ""

        msg_body = f"{type(exc).__name__}: {exc}"[:200]
        text = html.escape(f"⚠ Wolfee Reddit bot error: {prefix}: {msg_body}")
        send_message(text, disable_preview=True)

        try:
            _record_alert(klass, excerpt)
        except Exception:
            pass
    except Exception:
        # Never let alert failure block the main pipeline or cascade.
        pass


def send_message(text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> dict:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise TelegramError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + "\n[…truncated]"
    url = f"{TELEGRAM_API}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    resp = requests.post(url, json=payload, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"Telegram API error: {data}")
    return data


@dataclass
class DraftDelivery:
    tier: int
    subreddit: str
    title: str
    author: str
    post_url: str
    permalink: str
    score: int
    num_comments: int
    keyword: str | None
    classify_reason: str
    draft: str


def render_draft_message(d: DraftDelivery) -> str:
    """One HTML message: header metadata + a <pre> block with the draft body."""
    # Telegram-HTML: only <b>, <i>, <u>, <s>, <a>, <code>, <pre> are supported.
    title = html.escape(d.title)
    sub = html.escape(d.subreddit)
    author = html.escape(d.author)
    keyword = html.escape(d.keyword) if d.keyword else "(none)"
    reason = html.escape(d.classify_reason)
    link = html.escape(d.permalink, quote=True)
    # Draft body: escape so <, >, & don't break parser.
    draft = html.escape(d.draft)

    return (
        f"<b>Tier {d.tier}</b> · r/{sub}\n"
        f"<a href=\"{link}\">{title}</a>\n"
        f"u/{author} · score {d.score} · {d.num_comments} comments\n"
        f"keyword: <i>{keyword}</i>\n"
        f"reason: {reason}\n"
        f"\n"
        f"<b>Draft</b> (long-press to copy):\n"
        f"<pre>{draft}</pre>"
    )


def render_skip_message(
    subreddit: str | None,
    title: str | None,
    permalink: str | None,
    keyword: str | None,
    action: str,
    note: str = "",
) -> str:
    """Optional terse skip notification — used by run.py for visibility."""
    sub = html.escape(subreddit) if subreddit else "?"
    title_h = html.escape(title) if title else "(unknown)"
    note_h = html.escape(note) if note else ""
    link_line = (
        f"<a href=\"{html.escape(permalink, quote=True)}\">{title_h}</a>\n"
        if permalink else f"{title_h}\n"
    )
    keyword_line = f"keyword: <i>{html.escape(keyword)}</i>\n" if keyword else ""
    note_line = f"\n{note_h}" if note_h else ""
    return (
        f"<b>Skipped</b> · {html.escape(action)} · r/{sub}\n"
        f"{link_line}{keyword_line}{note_line}"
    )


if __name__ == "__main__":
    # Smoke test: send a hardcoded sample draft.
    sample = DraftDelivery(
        tier=3,
        subreddit="FinalRoundAI",
        title="Best real-time interview assistant for video calls? My top pick after testing 5",
        author="testuser",
        post_url="https://www.reddit.com/r/FinalRoundAI/comments/1sdzpzm/best_realtime_interview_assistant_for_video_calls/",
        permalink="https://www.reddit.com/r/FinalRoundAI/comments/1sdzpzm/best_realtime_interview_assistant_for_video_calls/",
        score=42,
        num_comments=15,
        keyword="interview assistant",
        classify_reason="OP explicitly tested 5 tools and is asking for recommendations — exact Wolfee Copilot fit.",
        draft=(
            "Six weeks and $500 in subs is rough, sorry you had to learn it that way. "
            "Your behavioral blanking story is exactly why I started using something "
            "for live calls in the first place.\n\n"
            "For practice between rounds I've been using Wolfee (wolfee.io). It's "
            "mostly a simulator, so you run mock interviews against AI avatars that "
            "actually push back on weak STAR answers, then get scored after. Helped "
            "me stop freezing because I'd already heard the awkward follow-ups before.\n\n"
            "Honest caveat: the free tier is one sim a month so you'd need the $19 "
            "plan to drill seriously. Have you found anything good for the prep side, "
            "or are you mostly leaning on the live assist?"
        ),
    )
    msg = render_draft_message(sample)
    print("--- rendered HTML ---")
    print(msg)
    print("--- sending ---")
    result = send_message(msg)
    print(f"ok: message_id={result['result']['message_id']} chat={result['result']['chat']['id']}")
