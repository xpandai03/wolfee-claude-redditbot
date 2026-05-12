"""One full pass: read labeled f5bot emails → for each new one, classify the
linked Reddit post → draft a comment if Tier 2/3 → send to Telegram → log.

Safe to re-run: emails already in the processed log are skipped silently.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import traceback
from datetime import datetime, timezone

import claude_client
import config
import db
import gmail_client
import reddit_client
import telegram_client


REDDIT_POLITE_SLEEP_S = 2.0


def _subreddit_from_url(url: str) -> str | None:
    m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/", url, re.I)
    return m.group(1) if m else None


def _process_email(email: gmail_client.F5BotEmail) -> tuple[str, str, int | None]:
    """Return (action, summary_line, tier). Caller handles db.record + errors."""
    if not email.matches:
        return "skipped_no_url", f"  · no reddit URL found in {email.subject!r}", None

    # Process the first URL in the email. f5bot emails almost always contain one.
    match = email.matches[0]

    sub = _subreddit_from_url(match.url)
    if sub and sub.lower() in config.BURNED_SUBS:
        return "skipped_burned_sub", f"  · burned sub r/{sub} — {match.url}", None

    # Reddit fetch
    try:
        post = reddit_client.fetch_post(match.url, top_comments_n=5)
    except reddit_client.FetchSkip as e:
        time.sleep(REDDIT_POLITE_SLEEP_S)
        return "skipped_fetch_failed", f"  · {e.reason} — {match.url}", None
    time.sleep(REDDIT_POLITE_SLEEP_S)

    # Defensive: subreddit-from-URL can disagree with reality (cross-posts, etc).
    if post.subreddit.lower() in config.BURNED_SUBS:
        return "skipped_burned_sub", f"  · burned sub r/{post.subreddit} (post-fetch)", None

    # Classify
    result = claude_client.classify_post(post, keyword=match.keyword)
    if result.tier == 1:
        return "skipped_tier1", f"  · Tier 1 — {result.reason}", 1

    # Draft + deliver
    draft = claude_client.draft_comment(post, tier=result.tier, keyword=match.keyword)
    delivery = telegram_client.DraftDelivery(
        tier=result.tier,
        subreddit=post.subreddit,
        title=post.title,
        author=post.author,
        post_url=match.url,
        permalink=post.permalink,
        score=post.score,
        num_comments=post.num_comments,
        keyword=match.keyword,
        classify_reason=result.reason,
        draft=draft,
    )
    telegram_client.send_message(telegram_client.render_draft_message(delivery))
    wc = len(draft.split())
    return (
        "drafted",
        f"  · Tier {result.tier} draft sent ({wc} words) — r/{post.subreddit} · {post.title[:60]}",
        result.tier,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one pass over labeled f5bot emails.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of emails to process this run (default: no limit).",
    )
    args = parser.parse_args()

    db.init_db()
    run_started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        service = gmail_client.get_service()
    except Exception as e:
        print(f"FATAL: gmail auth failed: {e}", file=sys.stderr)
        return 2

    processed_ids = db.get_processed_ids()
    limit_str = f", limit={args.limit}" if args.limit else ""
    print(f"[{run_started}] starting run. {len(processed_ids)} email(s) in processed log{limit_str}.")

    new_this_run = 0
    for email in gmail_client.iter_unprocessed_emails(service, processed_ids):
        if args.limit is not None and new_this_run >= args.limit:
            print(f"  (--limit {args.limit} reached; stopping)")
            break
        new_this_run += 1
        url = email.matches[0].url if email.matches else None
        try:
            action, line, tier = _process_email(email)
            db.record(email.message_id, action, post_url=url, tier=tier)
            print(f"[{email.message_id}] {action}")
            print(line)
        except Exception as exc:
            tb = traceback.format_exc(limit=2)
            print(f"[{email.message_id}] error: {exc}\n{tb}", file=sys.stderr)
            db.record(
                email.message_id,
                "error",
                post_url=url,
                note=f"{type(exc).__name__}: {exc}",
            )

    if new_this_run == 0:
        print("  (no new emails in the label)")

    # End-of-run summary line, scoped to this run
    counts = db.counts_since(run_started)
    tiers = db.tier_counts_since(run_started)
    print(
        f"Processed {new_this_run} email(s): "
        f"{counts['drafted']} drafted "
        f"(Tier 2: {tiers.get(2, 0)}, Tier 3: {tiers.get(3, 0)}), "
        f"{counts['skipped_tier1'] + counts['skipped_burned_sub'] + counts['skipped_fetch_failed'] + counts['skipped_no_url']} skipped "
        f"(Tier 1: {counts['skipped_tier1']}, "
        f"burned: {counts['skipped_burned_sub']}, "
        f"fetch failed: {counts['skipped_fetch_failed']}, "
        f"no url: {counts['skipped_no_url']}), "
        f"errors: {counts['error']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
