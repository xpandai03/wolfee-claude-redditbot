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
MAX_POST_AGE_HOURS = 36.0


def _subreddit_from_url(url: str) -> str | None:
    m = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/", url, re.I)
    return m.group(1) if m else None


def _post_id_from_url(url: str) -> str | None:
    m = re.search(r"/comments/([A-Za-z0-9]+)", url, re.I)
    return m.group(1) if m else None


def _process_email(
    email: gmail_client.F5BotEmail,
) -> tuple[str, str, int | None, str | None, float | None]:
    """Return (action, summary_line, tier, post_id, created_utc).

    Caller handles db.record + errors.
    """
    if not email.matches:
        return "skipped_no_url", f"  · no reddit URL found in {email.subject!r}", None, None, None

    # Process the first URL in the email. f5bot emails almost always contain one.
    match = email.matches[0]
    post_id = _post_id_from_url(match.url)

    # URL-based dedup: skip before any Reddit fetch or LLM call.
    if post_id and db.is_post_processed(post_id):
        return (
            "skipped_duplicate_post",
            f"  · duplicate post {post_id} — {match.url}",
            None,
            post_id,
            None,
        )

    sub = _subreddit_from_url(match.url)
    if sub and sub.lower() in config.BURNED_SUBS:
        return "skipped_burned_sub", f"  · burned sub r/{sub} — {match.url}", None, post_id, None

    # Allowlist gate — must run before any Reddit fetch / LLM call.
    if sub and sub.lower() not in config.ALLOWED_SUBS:
        return (
            "skipped_not_allowed_sub",
            f"  · r/{sub} not in allowlist — {match.url}",
            None,
            post_id,
            None,
        )

    # Reddit fetch
    try:
        post = reddit_client.fetch_post(match.url, top_comments_n=5)
    except reddit_client.FetchSkip as e:
        time.sleep(REDDIT_POLITE_SLEEP_S)
        return "skipped_fetch_failed", f"  · {e.reason} — {match.url}", None, post_id, None
    time.sleep(REDDIT_POLITE_SLEEP_S)

    # Defensive: subreddit-from-URL can disagree with reality (cross-posts, etc).
    if post.subreddit.lower() in config.BURNED_SUBS:
        return (
            "skipped_burned_sub",
            f"  · burned sub r/{post.subreddit} (post-fetch)",
            None,
            post_id,
            post.created_utc,
        )
    if post.subreddit.lower() not in config.ALLOWED_SUBS:
        return (
            "skipped_not_allowed_sub",
            f"  · r/{post.subreddit} not in allowlist (post-fetch)",
            None,
            post_id,
            post.created_utc,
        )

    # Age filter — fall through (don't drop) if timestamp missing or unparseable.
    if post.created_utc is None:
        print(f"  · warning: created_utc missing for {match.url}; processing anyway")
    else:
        age_hours = (datetime.now(timezone.utc).timestamp() - post.created_utc) / 3600.0
        if age_hours > MAX_POST_AGE_HOURS:
            return (
                "skipped_too_old",
                f"  · {age_hours:.1f}h old (>{MAX_POST_AGE_HOURS:.0f}h cap) — r/{post.subreddit}",
                None,
                post_id,
                post.created_utc,
            )

    # Classify
    result = claude_client.classify_post(post, keyword=match.keyword)
    if result.tier == 1:
        return "skipped_tier1", f"  · Tier 1 — {result.reason}", 1, post_id, post.created_utc

    # Draft + deliver
    draft_result = claude_client.draft_comment(post, tier=result.tier, keyword=match.keyword)
    if draft_result.skip_reason:
        action = f"skipped_{draft_result.skip_reason}"
        return (
            action,
            f"  · Tier {result.tier} {draft_result.skip_reason} — r/{post.subreddit} · {post.title[:60]}",
            result.tier,
            post_id,
            post.created_utc,
        )
    draft = draft_result.draft
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
        post_id,
        post.created_utc,
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
        traceback.print_exc(file=sys.stderr)
        telegram_client.send_error_alert("gmail auth", e)
        return 2

    try:
        processed_ids = db.get_processed_ids()
    except Exception as e:
        print(f"FATAL: db read failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        telegram_client.send_error_alert("db read", e)
        return 3
    limit_str = f", limit={args.limit}" if args.limit else ""
    print(f"[{run_started}] starting run. {len(processed_ids)} email(s) in processed log{limit_str}.")

    new_this_run = 0
    email_iter = gmail_client.iter_unprocessed_emails(service, processed_ids)
    while True:
        try:
            email = next(email_iter)
        except StopIteration:
            break
        except Exception as e:
            # Iterator itself failed (label lookup, Gmail listing, network).
            print(f"FATAL: gmail listing failed mid-stream: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            telegram_client.send_error_alert("gmail listing", e)
            return 4
        if args.limit is not None and new_this_run >= args.limit:
            print(f"  (--limit {args.limit} reached; stopping)")
            break
        new_this_run += 1
        url = email.matches[0].url if email.matches else None
        keyword = email.matches[0].keyword if email.matches else None
        post_id = _post_id_from_url(url) if url else None
        try:
            action, line, tier, post_id_out, created_utc = _process_email(email)
            db.record(
                email.message_id,
                action,
                post_url=url,
                post_id=post_id_out or post_id,
                created_utc=created_utc,
                keyword=keyword,
                tier=tier,
            )
            print(f"[{email.message_id}] {action}")
            print(line)
        except Exception as exc:
            tb = traceback.format_exc(limit=2)
            print(f"[{email.message_id}] error: {exc}\n{tb}", file=sys.stderr)
            db.record(
                email.message_id,
                "error",
                post_url=url,
                post_id=post_id,
                keyword=keyword,
                note=f"{type(exc).__name__}: {exc}",
            )
            telegram_client.send_error_alert(
                f"email {email.message_id}", exc
            )

    if new_this_run == 0:
        print("  (no new emails in the label)")

    # End-of-run summary line, scoped to this run
    counts = db.counts_since(run_started)
    tiers = db.tier_counts_since(run_started)
    skipped_total = sum(
        counts[a] for a in (
            'skipped_tier1',
            'skipped_burned_sub',
            'skipped_fetch_failed',
            'skipped_no_url',
            'skipped_duplicate_post',
            'skipped_not_allowed_sub',
            'skipped_too_old',
            'skipped_tier2_no_fit',
            'skipped_tier2_missing_brand',
            'skipped_tier3_no_fit',
            'skipped_tier3_missing_brand',
        )
    )
    print(
        f"Processed {new_this_run} email(s): "
        f"{counts['drafted']} drafted "
        f"(Tier 2: {tiers.get(2, 0)}, Tier 3: {tiers.get(3, 0)}), "
        f"{skipped_total} skipped "
        f"(Tier 1: {counts['skipped_tier1']}, "
        f"burned: {counts['skipped_burned_sub']}, "
        f"not allowed: {counts['skipped_not_allowed_sub']}, "
        f"too old: {counts['skipped_too_old']}, "
        f"duplicate: {counts['skipped_duplicate_post']}, "
        f"fetch failed: {counts['skipped_fetch_failed']}, "
        f"no url: {counts['skipped_no_url']}, "
        f"t2 no_fit: {counts['skipped_tier2_no_fit']}, "
        f"t2 missing_brand: {counts['skipped_tier2_missing_brand']}, "
        f"t3 no_fit: {counts['skipped_tier3_no_fit']}, "
        f"t3 missing_brand: {counts['skipped_tier3_missing_brand']}), "
        f"errors: {counts['error']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
