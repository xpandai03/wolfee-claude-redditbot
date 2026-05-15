"""Telegram delivery for drafted Reddit comments.

Sends as HTML (more forgiving than MarkdownV2). The draft body goes in a <pre>
block so it's monospaced and a long-press selects the whole thing on mobile —
copy → paste into Reddit, done.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

import requests

import config


class TelegramError(RuntimeError):
    pass


TELEGRAM_API = "https://api.telegram.org"
# Telegram caps text at 4096 chars per message. Drafts are <120 words so a single
# message is fine; truncate defensively just in case.
MAX_LEN = 4000


def send_error_alert(prefix: str, exc: BaseException) -> None:
    """Best-effort short error notification. NEVER raises.

    Used by run.py to surface silent breaks (auth expiry, network, API errors)
    so you notice within hours, not days. If Telegram itself is the failure
    domain, this becomes a no-op and the error stays in logs/cron.log only.
    """
    try:
        msg_body = f"{type(exc).__name__}: {exc}"[:200]
        text = html.escape(f"⚠ Wolfee Reddit bot error: {prefix}: {msg_body}")
        send_message(text, disable_preview=True)
    except Exception:
        # Swallow — do not let alert failure block the main pipeline or
        # cause a recursive error storm.
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
