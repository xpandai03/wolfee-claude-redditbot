"""Gmail reader for f5bot emails.

OAuth2 Desktop-app flow on first run: opens a browser, you grant gmail.readonly,
the resulting refresh token is cached to token.json (gitignored).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

REDDIT_URL_RE = re.compile(
    r"https?://(?:www\.|old\.|new\.)?reddit\.com/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9_]+(?:/[^\s)>\]]*)?",
    re.IGNORECASE,
)


@dataclass
class F5BotMatch:
    """One Reddit URL pulled out of an f5bot email, plus the keyword that triggered it."""
    url: str
    keyword: str | None


@dataclass
class F5BotEmail:
    """A single Gmail message we treat as an f5bot alert."""
    message_id: str
    subject: str
    snippet: str
    body: str
    matches: list[F5BotMatch]


def get_service():
    """Return an authorized Gmail API service object. Triggers consent on first run."""
    creds: Credentials | None = None
    if config.TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(
            str(config.TOKEN_PATH), config.GMAIL_SCOPES
        )
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing {config.CREDENTIALS_PATH}. Download the OAuth client "
                    "JSON from Google Cloud and save it there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.CREDENTIALS_PATH), config.GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)
        config.TOKEN_PATH.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _find_label_id(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for lbl in labels:
        if lbl["name"].lower() == label_name.lower():
            return lbl["id"]
    raise LookupError(
        f"Gmail label {label_name!r} not found. Create it and route f5bot emails to it."
    )


def list_message_ids(service, label_name: str, max_results: int = 50) -> list[str]:
    """Return message IDs in the given label, newest first."""
    label_id = _find_label_id(service, label_name)
    ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label_id],
                maxResults=min(100, max_results - len(ids)),
                pageToken=page_token,
            )
            .execute()
        )
        for msg in resp.get("messages", []):
            ids.append(msg["id"])
            if len(ids) >= max_results:
                return ids
        page_token = resp.get("nextPageToken")
        if not page_token:
            return ids


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode(errors="replace")


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree, prefer text/plain, fall back to text/html stripped."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            text = _decode_part(data)
            if mime == "text/plain":
                plain.append(text)
            elif mime == "text/html":
                html.append(text)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain)
    if html:
        # crude tag strip; f5bot bodies are mostly text but be safe
        stripped = re.sub(r"<[^>]+>", " ", "\n".join(html))
        return re.sub(r"\s+\n", "\n", stripped)
    return ""


def _extract_keyword(subject: str, body: str) -> str | None:
    """f5bot subjects look like: 'F5Bot Alert: <keyword>' — best-effort parse."""
    m = re.search(r"f5bot\s*(?:alert|update|notification)?\s*[:\-]\s*(.+)", subject, re.I)
    if m:
        return m.group(1).strip()
    return None


def parse_email(service, message_id: str) -> F5BotEmail:
    """Fetch one message and pull out URLs + subject + body."""
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    subject = headers.get("subject", "")
    snippet = msg.get("snippet", "")
    body = _extract_body(msg["payload"])
    keyword = _extract_keyword(subject, body)

    seen: set[str] = set()
    matches: list[F5BotMatch] = []
    for url in REDDIT_URL_RE.findall(body + "\n" + snippet):
        normalized = url.rstrip(".,);]")
        if normalized in seen:
            continue
        seen.add(normalized)
        matches.append(F5BotMatch(url=normalized, keyword=keyword))

    return F5BotEmail(
        message_id=message_id,
        subject=subject,
        snippet=snippet,
        body=body,
        matches=matches,
    )


def iter_unprocessed_emails(
    service, already_processed_ids: Iterable[str], label_name: str | None = None
) -> Iterable[F5BotEmail]:
    """Yield F5BotEmail for each message in the label not already in the processed log."""
    label_name = label_name or config.GMAIL_LABEL
    seen = set(already_processed_ids)
    for mid in list_message_ids(service, label_name):
        if mid in seen:
            continue
        yield parse_email(service, mid)


if __name__ == "__main__":
    # Manual smoke test: list and pretty-print parsed emails from the label.
    svc = get_service()
    ids = list_message_ids(svc, config.GMAIL_LABEL, max_results=5)
    print(f"Found {len(ids)} message(s) in label {config.GMAIL_LABEL!r}")
    for mid in ids:
        e = parse_email(svc, mid)
        print("-" * 60)
        print(f"id:      {e.message_id}")
        print(f"subject: {e.subject}")
        print(f"keyword: {e.matches[0].keyword if e.matches else None}")
        print(f"urls:    {[m.url for m in e.matches]}")
