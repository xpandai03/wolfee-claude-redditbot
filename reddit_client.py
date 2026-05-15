"""Read-only Reddit post fetcher via the public .json endpoint.

No OAuth — we just need to read public posts the way f5bot already does.
Polite 2-second sleep between requests is the caller's responsibility (run.py).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

import requests

import config


class FetchSkip(Exception):
    """Recoverable — log and move on to the next email."""

    def __init__(self, reason: str, url: str, status: int | None = None):
        super().__init__(f"{reason} ({url})")
        self.reason = reason
        self.url = url
        self.status = status


@dataclass
class RedditComment:
    author: str
    body: str
    score: int


@dataclass
class RedditPost:
    url: str               # canonical permalink the post lives at
    subreddit: str         # without r/ prefix
    title: str
    author: str
    selftext: str          # empty string for link posts
    score: int
    num_comments: int
    is_self: bool
    over_18: bool
    permalink: str         # absolute https URL
    created_utc: float | None = None  # unix epoch seconds; None if missing/unparseable
    top_comments: list[RedditComment] = field(default_factory=list)


def _normalize_url(raw: str) -> str:
    """Drop query/fragment, force https + www.reddit.com, append /.json."""
    p = urlparse(raw)
    if not p.netloc:
        raise FetchSkip("malformed URL", raw)
    netloc = "www.reddit.com" if "reddit.com" in p.netloc else p.netloc
    path = p.path or "/"
    if path.endswith("/.json") or path.endswith(".json"):
        json_path = path
    else:
        json_path = path.rstrip("/") + "/.json"
    return urlunparse(("https", netloc, json_path, "", "raw_json=1", ""))


def fetch_post(raw_url: str, top_comments_n: int = 5, timeout: float = 15.0) -> RedditPost:
    """Fetch one post + a slice of top-sorted comments.

    Raises FetchSkip on 404/403/429/deleted/banned — caller should log + continue.
    """
    json_url = _normalize_url(raw_url)
    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    try:
        resp = requests.get(json_url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise FetchSkip(f"network error: {e}", raw_url) from e

    if resp.status_code == 404:
        raise FetchSkip("404 (deleted or never existed)", raw_url, 404)
    if resp.status_code == 403:
        raise FetchSkip("403 (private, quarantined, or banned)", raw_url, 403)
    if resp.status_code == 429:
        raise FetchSkip("429 (rate limited)", raw_url, 429)
    if resp.status_code >= 500:
        raise FetchSkip(f"server error {resp.status_code}", raw_url, resp.status_code)
    if resp.status_code != 200:
        raise FetchSkip(f"unexpected status {resp.status_code}", raw_url, resp.status_code)

    try:
        data = resp.json()
    except ValueError as e:
        raise FetchSkip(f"non-JSON response: {e}", raw_url) from e

    if not isinstance(data, list) or len(data) < 1:
        raise FetchSkip("unexpected JSON shape (not a listing pair)", raw_url)

    post_listing = data[0].get("data", {}).get("children") or []
    if not post_listing:
        raise FetchSkip("no post in listing", raw_url)
    pd = post_listing[0].get("data", {})

    author = pd.get("author") or "[unknown]"
    selftext = pd.get("selftext") or ""
    title = pd.get("title") or ""

    # Deleted/removed signals
    if author == "[deleted]" or selftext == "[deleted]" or selftext == "[removed]":
        raise FetchSkip("post was deleted or removed", raw_url)
    if pd.get("removed_by_category"):
        raise FetchSkip(f"removed_by_category={pd['removed_by_category']}", raw_url)

    permalink_path = pd.get("permalink") or ""
    permalink = f"https://www.reddit.com{permalink_path}" if permalink_path else raw_url

    created_utc_raw = pd.get("created_utc")
    try:
        created_utc = float(created_utc_raw) if created_utc_raw is not None else None
    except (TypeError, ValueError):
        created_utc = None

    post = RedditPost(
        url=raw_url,
        subreddit=pd.get("subreddit", ""),
        title=title,
        author=author,
        selftext=selftext,
        score=int(pd.get("score") or 0),
        num_comments=int(pd.get("num_comments") or 0),
        is_self=bool(pd.get("is_self")),
        over_18=bool(pd.get("over_18")),
        permalink=permalink,
        created_utc=created_utc,
    )

    # Comments: second listing (may be missing if requested without comments path).
    if len(data) >= 2:
        comment_children = data[1].get("data", {}).get("children") or []
        for child in comment_children:
            if child.get("kind") != "t1":
                continue
            cd = child.get("data", {})
            body = cd.get("body") or ""
            author_c = cd.get("author") or "[unknown]"
            if author_c == "[deleted]" or body in ("[deleted]", "[removed]"):
                continue
            post.top_comments.append(
                RedditComment(
                    author=author_c,
                    body=body,
                    score=int(cd.get("score") or 0),
                )
            )
            if len(post.top_comments) >= top_comments_n:
                break

    return post


if __name__ == "__main__":
    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.reddit.com/r/announcements/comments/3g1jl8/"
        "reddit_in_2015_so_far_and_looking_ahead/"
    )
    print(f"Fetching: {test_url}")
    try:
        post = fetch_post(test_url, top_comments_n=3)
    except FetchSkip as e:
        print(f"SKIP — {e.reason}")
        sys.exit(2)
    print(f"  r/{post.subreddit} · u/{post.author} · score {post.score} · comments {post.num_comments}")
    print(f"  title: {post.title}")
    if post.selftext:
        body_preview = post.selftext[:300].replace("\n", " ")
        print(f"  body : {body_preview}{'…' if len(post.selftext) > 300 else ''}")
    else:
        print("  body : (link post, no selftext)")
    print(f"  top {len(post.top_comments)} comment(s):")
    for c in post.top_comments:
        snip = c.body[:140].replace("\n", " ")
        print(f"    • u/{c.author} ({c.score}): {snip}{'…' if len(c.body) > 140 else ''}")
    time.sleep(0.1)
