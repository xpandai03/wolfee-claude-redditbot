"""Claude API wrappers: tier classification + comment drafting.

Prompt templates live in prompts/*.md and are formatted with values from
config.py at call time. The system block is cached (ephemeral) so consecutive
calls in the same 5-minute window pay for it once.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from anthropic import Anthropic

import config
from reddit_client import RedditPost


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text()


def _fill(template: str, **vars: str) -> str:
    """Plain {KEY} substitution that doesn't choke on JSON examples in the prompt."""
    out = template
    for k, v in vars.items():
        out = out.replace("{" + k + "}", v)
    return out


def _render_classify_system() -> str:
    return _fill(
        _load_prompt("classify.md"),
        WOLFEE_USE_CASES=config.WOLFEE_USE_CASES,
        TIER_DEFINITIONS=config.TIER_DEFINITIONS,
        BURNED_SUBS_LIST=", ".join(f"r/{s}" for s in sorted(config.BURNED_SUBS)),
    )


def _render_draft_system(tier: int) -> str:
    return _fill(
        _load_prompt(f"draft_tier{tier}.md"),
        WOLFEE_USE_CASES=config.WOLFEE_USE_CASES,
        WOLFEE_FEATURES=config.WOLFEE_FEATURES,
        BODY_RULES=config.BODY_RULES,
    )


def _post_to_user_message(post: RedditPost, keyword: str | None) -> str:
    selftext = post.selftext.strip()
    if len(selftext) > 4000:
        selftext = selftext[:4000] + "\n…[truncated]"

    parts = [
        f"Subreddit: r/{post.subreddit}",
        f"Author: u/{post.author}",
        f"Title: {post.title}",
        f"Score: {post.score} | Comments: {post.num_comments}",
    ]
    if keyword:
        parts.append(f"f5bot keyword that matched: {keyword!r}")
    parts.append("")
    parts.append("--- Post body ---")
    parts.append(selftext if selftext else "(no body — link post)")
    if post.top_comments:
        parts.append("")
        parts.append("--- Top comments (for context) ---")
        for c in post.top_comments:
            body = c.body.strip()
            if len(body) > 600:
                body = body[:600] + "…"
            parts.append(f"[{c.score}] u/{c.author}: {body}")
    return "\n".join(parts)


@dataclass
class ClassifyResult:
    tier: int
    reason: str


def classify_post(post: RedditPost, keyword: str | None = None) -> ClassifyResult:
    """Return Tier 1/2/3 + a one-sentence reason."""
    client = _get_client()
    system_text = _render_classify_system()
    user_text = _post_to_user_message(post, keyword)

    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=300,
        system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_text}],
    )
    raw = resp.content[0].text.strip()
    return _parse_classify(raw)


def _parse_classify(raw: str) -> ClassifyResult:
    # Strip optional code fences in case the model adds them
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        raise ValueError(f"classifier did not return JSON: {raw!r}")
    data = json.loads(m.group(0))
    tier = int(data.get("tier"))
    if tier not in (1, 2, 3):
        raise ValueError(f"tier out of range: {tier}")
    reason = str(data.get("reason", "")).strip()
    return ClassifyResult(tier=tier, reason=reason)


MAX_WORDS = 120


def draft_comment(post: RedditPost, tier: int, keyword: str | None = None) -> str:
    """Draft a comment for Tier 2 or Tier 3. Returns plain-prose comment body.

    If the first draft exceeds MAX_WORDS, send one follow-up turn asking the
    model to cut. Return whichever version is closer to (and ideally under)
    the cap.
    """
    if tier not in (2, 3):
        raise ValueError(f"draft_comment only supports tier 2 or 3; got {tier}")
    client = _get_client()
    system_text = _render_draft_system(tier)
    user_text = _post_to_user_message(post, keyword)

    messages: list[dict] = [{"role": "user", "content": user_text}]

    resp = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=600,
        system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    draft = _scrub_draft(resp.content[0].text)
    wc = len(draft.split())

    if wc <= MAX_WORDS:
        return draft

    # One retry: feed the over-long draft back and demand a shorter version.
    messages.append({"role": "assistant", "content": draft})
    messages.append(
        {
            "role": "user",
            "content": (
                f"That draft is {wc} words. The hard ceiling is {MAX_WORDS}. "
                f"Rewrite it so it is under {MAX_WORDS} words. Cut whole sentences "
                "if you have to; do not just shave adjectives. Keep the voice, "
                "specificity to the OP, and the ending question. Respond with "
                "ONLY the new comment body."
            ),
        }
    )
    resp2 = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=600,
        system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    )
    draft2 = _scrub_draft(resp2.content[0].text)
    # Prefer the shorter draft. If the retry somehow grew, keep the original.
    return draft2 if len(draft2.split()) < wc else draft


# Body-rule scrubber: catches the obvious banned punctuation in case the model slips.
# Banned phrases are caught by the prompt; we don't auto-strip those (rewording is a
# model job).  Em-dashes get swapped to commas; exclamation marks → period.
def _scrub_draft(text: str) -> str:
    out = text.strip()
    out = out.replace("—", ", ").replace(" - ", ", ")
    out = out.replace("!", ".")
    out = re.sub(r"#\w+", "", out)  # strip hashtags
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


if __name__ == "__main__":
    # Smoke test: fetch a hardcoded post and classify it.
    import sys
    from reddit_client import fetch_post

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.reddit.com/r/cscareerquestions/comments/1taf0gg/"
        "is_the_push_for_ai_burning_anyone_else_out/"
    )
    keyword = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Fetching: {url}")
    post = fetch_post(url, top_comments_n=5)
    print(f"  r/{post.subreddit} · {post.title!r}")
    print(f"Classifying via model={config.CLAUDE_MODEL}…")
    result = classify_post(post, keyword=keyword)
    print(f"  Tier {result.tier} — {result.reason}")
