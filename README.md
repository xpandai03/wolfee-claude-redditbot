# Wolfee Reddit Comment Seeder

A leaner replacement for the n8n + Adaptive AI workflow that drafts Reddit
comments from f5bot alerts. Single-purpose Python pipeline using Claude (your
own Anthropic API key), Gmail, and Telegram. **No auto-posting** — drafts are
delivered to Telegram for you to copy/paste into Reddit manually.

## Pipeline

```
Gmail (label: f5bot-wolfee)
   ├── parse f5bot redirect, normalize comment URLs to post URLs
   ↓
Reddit (public .json endpoint, 2s politeness sleep)
   ├── burned-sub blocklist short-circuit
   ↓
Claude classify → Tier 1 / 2 / 3
   ├── Tier 1 → log skip, no draft, no Telegram
   ↓
Claude draft (Tier 2 = soft mention, Tier 3 = named + wolfee.io)
   ├── 120-word ceiling with one-shot retry if over
   ├── scrubber strips em-dashes, "!", hashtags
   ↓
Telegram (HTML, draft in <pre> for long-press copy)
   ↓
SQLite log (state/processed.db, idempotent per Gmail message id)
```

## One-time setup

### 1. Project + Python

```bash
cd /path/to/wolfee-reddit-seeding
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Gmail OAuth (Desktop client)

1. https://console.cloud.google.com/ → create or pick a project.
2. **APIs & Services → Library** → enable **Gmail API**.
3. **OAuth consent screen** → External, Testing → add your Google account as
   a test user → add scope `.../auth/gmail.readonly`.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**.
5. Download the JSON → save as `./credentials.json` in this project root.

### 3. Gmail label + filter

1. Gmail → Settings → Labels → create label `f5bot-wolfee`.
2. Settings → Filters → create a filter on `from:noreply@f5bot.com` (or your
   f5bot sender) → Apply the label `f5bot-wolfee` → check **Also apply to
   matching conversations** to backfill.

### 4. Telegram bot

1. In Telegram, talk to **@BotFather** → `/newbot` → pick a name + username
   ending in `bot` → copy the token.
2. Open your new bot, hit **Start**, send any message (this registers the
   chat). Without this, getUpdates returns nothing.
3. After messaging the bot, fetch your chat id:
   ```bash
   .venv/bin/python -c "import requests, config; \
     print(requests.get(f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates').json())"
   ```
   Look for `chat.id` in the response.

### 5. .env

Copy `.env.example` → `.env` and fill in:

| var | value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` (default; swap to `claude-opus-4-7` if you want max quality at ~5x cost) |
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `TELEGRAM_CHAT_ID` | numeric chat id (private chats are positive; groups start with `-100`) |
| `GMAIL_LABEL` | `f5bot-wolfee` |
| `REDDIT_USER_AGENT` | already set; keep `wolfee-comment-seeder/0.1 by <your-handle>` |

### 6. First Gmail consent

```bash
.venv/bin/python gmail_client.py
```

This opens a browser the first time. After granting access, `token.json` is
cached locally (gitignored) and future runs are non-interactive.

## Running

```bash
# Process every unread / unlogged email in the label
.venv/bin/python run.py

# First pass on a large backlog — cap at 10 to sanity-check the drafts
.venv/bin/python run.py --limit 10
```

Re-running is safe: anything already in `state/processed.db` is skipped.

## Cron

`cron.sh` is a self-locating wrapper that runs inside the project's venv and
appends timestamped output to `logs/cron.log`.

Edit your user crontab (`crontab -e`) and add:

```cron
*/30 * * * * /Users/raunekpratap/Desktop/wolfee-reddit-seeding/cron.sh
```

Every 30 min. Adjust the cadence to your f5bot frequency. To pass through CLI
args: `cron.sh --limit 5`.

Inspect activity:

```bash
tail -f logs/cron.log
```

## File layout

```
.
├── run.py              entrypoint — one full pass
├── cron.sh             cron wrapper (self-locating, logs)
├── gmail_client.py     OAuth + label + f5bot body/URL parsing
├── reddit_client.py    public .json fetch with FetchSkip handling
├── claude_client.py    classify + draft with 120-word retry
├── telegram_client.py  HTML send with <pre> draft block
├── db.py               sqlite processed log
├── config.py           constants: burned subs, tier defs, Wolfee positioning
├── prompts/
│   ├── classify.md
│   ├── draft_tier2.md
│   └── draft_tier3.md
├── .env.example
├── .gitignore          excludes .env, credentials.json, token.json, state/, logs/
└── requirements.txt
```

## Editing brand / behavior

- **Add a burned subreddit**: edit `BURNED_SUBS` in `config.py`.
- **Update Wolfee positioning / features**: edit `WOLFEE_USE_CASES` and
  `WOLFEE_FEATURES` in `config.py`. Both the classifier and drafter pick this
  up automatically.
- **Tier thresholds**: edit `prompts/classify.md` (decision rules section).
- **Body rules** (length, banned phrases, etc.): edit `BODY_RULES` in
  `config.py`.

## Cost ballpark

Per email: 1 classify call (~500-2000 input tokens, ~100 output) plus, if
Tier 2/3, 1 draft call (~500-2000 input, ~200-300 output). The system prompt
is cached (`cache_control: ephemeral`) so consecutive calls within ~5 minutes
pay for it once.

## Troubleshooting

- `Gmail label 'f5bot-wolfee' not found` — create the label in Gmail; the API
  is case-insensitive.
- `0 updates` from Telegram getUpdates — you haven't sent the bot a message
  yet. Hit **Start** in the chat with your bot.
- `403 (private, quarantined, or banned)` from a Reddit post — expected for
  some subs. The pipeline logs `skipped_fetch_failed` and continues.
- A draft exceeds 120 words — the retry mechanism should catch this; if it
  consistently fails, tighten the rule wording in `prompts/draft_tier{2,3}.md`.
