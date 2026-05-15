# Wolfee Reddit Seeder — Railway Deployment Runbook

Deploy the Wolfee Reddit comment seeder to Railway as a cron-scheduled
service backed by a persistent volume. Estimated wall time: 30–45 min
including the first cron tick observation.

The local macOS cron path (`cron.sh` + `install_cron.sh`) is left in place
as a fallback. Use it if Railway has an incident; nothing about this
migration removed the local-cron option.

---

## Prerequisites

Before you start, confirm:

- [ ] The repo is pushed to `https://github.com/xpandai03/wolfee-claude-redditbot.git` and the local `main` branch is in sync (it currently is — verified at the start of this work).
- [ ] You have a Railway account (sign up at https://railway.com if not).
- [ ] You have these secrets at hand (do **not** paste them into this document or any commit — they go into Railway dashboard env vars only):
    - `ANTHROPIC_API_KEY` (from your Anthropic console)
    - `TELEGRAM_BOT_TOKEN` (from BotFather)
    - `TELEGRAM_CHAT_ID` (numeric chat id from your bot)
    - The **contents** of your local `credentials.json` (the OAuth client JSON)
    - The **contents** of your local `token.json` (the cached refresh token)
- [ ] Railway CLI installed locally (only needed for steps 3 & 7 — `npm i -g @railway/cli` or `brew install railway`).

---

## Step 1 — Push the latest changes to GitHub

This branch has 7 new Railway-prep commits (`32f87f2` through `0202be2`) plus the original 11 patches. Push them so Railway can pull from GitHub:

```bash
cd /Users/raunekpratap/Desktop/wolfee-reddit-seeding
git status              # working tree should be clean
git log --oneline origin/main..HEAD   # should list 7 commits
git push origin main
```

After this, `git log --oneline origin/main..HEAD` should be empty.

---

## Step 2 — Create the Railway project and connect to GitHub

1. Go to https://railway.com/new.
2. Select **"Deploy from GitHub repo"**.
3. Pick `xpandai03/wolfee-claude-redditbot`.
4. Railway will detect the Python service via `requirements.txt` and start a build. **Cancel this initial deploy** (top-right "..." → Stop) — we need to set env vars and attach the volume before the first real run.

(Naming the project `wolfee-reddit-seeder` is conventional; whatever you pick is fine — Railway uses it for the dashboard URL only.)

---

## Step 3 — Attach the persistent volume

The pipeline persists `processed.db`, `api_usage.jsonl`, and `token.json` across deploys via a Railway volume.

1. In the project canvas, **right-click the service** (or press `⌘K`) → **"New Volume"** → attach to this service.
2. Set the **mount path to `/data`**. (Railway docs recommend `/app/data` for relative-path apps, but our config is fully path-driven via env vars, so `/data` keeps the env values clean.)
3. Confirm the volume shows up under the service's "Variables" / "Volumes" section.

---

## Step 4 — Set environment variables (Railway dashboard → service → Variables)

Set these one at a time. Names only below — paste the actual values from your local secrets store. **Never** paste secrets into this file, into git, or into chat.

### Required

| Variable | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | (your sk-ant- key) | from Anthropic console |
| `TELEGRAM_BOT_TOKEN` | (BotFather token) | |
| `TELEGRAM_CHAT_ID` | (numeric chat id) | |
| `GMAIL_LABEL` | `f5bot-wolfee` | literal value |
| `GMAIL_CREDENTIALS_JSON` | (full contents of your local `credentials.json`) | paste the raw JSON, including the outer `{...}` |
| `GMAIL_TOKEN_JSON` | (full contents of your local `token.json`) | paste the raw JSON. Refresh rotations after this point persist to `/data/token.json` on the volume, so this env var is only needed for the initial seed (you can remove it from Railway 24 h after first successful cron tick — see step 9). |
| `STATE_DIR` | `/data` | pins SQLite onto the volume |
| `LOGS_DIR` | `/data/logs` | pins api_usage.jsonl onto the volume |
| `TOKEN_PATH` | `/data/token.json` | refresh-rotated token lives here |

### Optional (only set if you want to override a default)

| Variable | Default if unset | Override when |
|---|---|---|
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | you want max quality on Opus 4.7 (~5× cost) |
| `CREDENTIALS_PATH` | repo-root/credentials.json | unusual — leave unset |
| `REDDIT_USER_AGENT` | `wolfee-comment-seeder/0.1 by raunstrong` | personalize the UA if you want |

---

## Step 5 — Bootstrap `token.json` onto the volume

On first deploy the volume is empty. The `GMAIL_TOKEN_JSON` env var feeds the OAuth token to `_seed_token_from_env()` in `gmail_client.py`, which writes it to `/data/token.json`. From there, refresh rotations write back to the same path.

You can verify this works in one of two ways:

**Option A — let the first cron tick seed it (zero-action).** When the */30 cron fires, `run.py` calls `gmail_client.get_service()`, which seeds the token from env on its way to first use. Nothing to do.

**Option B — seed explicitly, before any cron tick, via `railway run`:**

```bash
cd /Users/raunekpratap/Desktop/wolfee-reddit-seeding
railway login           # opens browser, one-time
railway link            # pick the project + service you created
railway run python scripts/seed_token_from_env.py
```

Expected output:

```
seeded /data/token.json (<N> bytes)
```

(Exit code 0.) If you see `ERROR: GMAIL_TOKEN_JSON env var is not set`, you missed step 4 — go back and add it.

---

## Step 6 — Seed the existing 14 DB rows to the volume (optional but recommended)

Skipping this is fine; the cron will start with an empty processed-emails table and the first 14 historical posts could legitimately re-surface if f5bot sends another keyword email for the same post. The seed preserves your dedup history.

```bash
# On your local Mac, dump the current local DB to SQL:
.venv/bin/python scripts/seed_db_from_local.py --export > /tmp/wolfee_seed.sql

# Pipe through railway run to apply against /data/processed.db on the volume:
cat /tmp/wolfee_seed.sql | railway run python scripts/seed_db_from_local.py --import

# Clean up the local dump file (contains post URLs, not sensitive but tidy)
rm /tmp/wolfee_seed.sql
```

Expected output from the import step:

```
imported into /data/processed.db: 0 -> 14 rows (delta 14)
```

If a cron tick already happened between volume creation and seed, the delta may be less than 14 (some rows were already present) or it may be 14 + whatever Railway processed. `INSERT OR IGNORE` ensures no clobbering either way.

Verify:

```bash
railway run sqlite3 /data/processed.db "SELECT action, COUNT(*) FROM processed_emails GROUP BY action;"
```

You should see at minimum `drafted|2`, `skipped_tier1|9`, `skipped_not_allowed_sub|3` (plus anything cron has added).

---

## Step 7 — Deploy

Trigger a deploy by either:

- **Auto-deploy on push:** any subsequent `git push origin main` triggers a Railway build.
- **Manual deploy:** in the Railway dashboard, click "Deploy" on the service, or `railway up` from the local repo root.

Watch the build logs in the Railway dashboard:

- Build phase: Nixpacks detects Python via `requirements.txt`, installs deps. Should take ~60–90 s.
- Deploy phase: Railway registers the cron schedule. **The service does not run on deploy** — it waits for the next `*/30` boundary.

If the Nixpacks build fails, fall back to RAILPACK by editing `railway.toml`:

```toml
[build]
builder = "RAILPACK"
```

…and re-push. (No other config changes needed.)

---

## Step 8 — Verify the first cron tick

The cron fires at `:00` and `:30` of every UTC hour. Wait for the next boundary (≤ 30 min from deploy), then watch the Railway log stream for the service.

Expected log output on a clean run (no new f5bot emails):

```
[<utc-iso-timestamp>] starting run. <N> email(s) in processed log.
  (no new emails in the label)
Processed 0 email(s): 0 drafted (Tier 2: 0, Tier 3: 0), 0 skipped (...), errors: 0
```

Expected on a run with new emails:

```
[<utc-iso-timestamp>] starting run. <N> email(s) in processed log.
[<gmail-id>] skipped_not_allowed_sub
  · r/<sub> not in allowlist — <url>
[<gmail-id>] drafted
  · Tier 3 draft sent (104 words) — r/<sub> · <title>
Processed 2 email(s): 1 drafted (Tier 2: 0, Tier 3: 1), 1 skipped (...), errors: 0
```

A successful Tier 2 or Tier 3 draft results in a Telegram message to your configured chat. **That is the canary** — when you see a Telegram notification, the full pipeline (Gmail → Reddit → Claude → Telegram) is live on Railway.

If anything fails inside the run, you'll see a `⚠ Wolfee Reddit bot error: ...` Telegram alert from the `send_error_alert` path. **That's also healthy signal** — it means error wiring works.

---

## Step 9 — Optional cleanup after 24 h of stable operation

Once you've seen at least one successful refresh rotation (which happens automatically the first time `creds.expired` is true — usually within ~1 h of first run, since cached access tokens are short-lived), the in-place `/data/token.json` is the source of truth and `GMAIL_TOKEN_JSON` is no longer required.

You can either:

- **Leave it set** as a re-seed lifeline (if the volume is ever wiped, the env var rebuilds the token).
- **Remove it from Railway dashboard variables** for minimum attack surface. After removal, you cannot re-seed without re-running the local OAuth dance and updating the env var again.

Recommendation: **leave it set**. It costs nothing.

---

## Verifying it's all wired correctly — quick checklist

| Check | How |
|---|---|
| Service exists and is cron-scheduled | Railway dashboard → service → Settings → "Cron Schedule" should show `*/30 * * * *` |
| Volume mounted at `/data` | Railway dashboard → service → Volumes → mount path `/data` |
| Required env vars all set | Variables tab shows 9 required vars (4 + Gmail + 4 path) |
| Token seeded onto volume | `railway run ls -la /data/` shows `token.json` |
| DB seeded onto volume | `railway run sqlite3 /data/processed.db "SELECT COUNT(*) FROM processed_emails;"` returns ≥ 14 |
| First cron tick succeeded | Service "Deployments" tab → most recent invocation shows exit 0 |
| Telegram error alerts working | Trigger by removing GMAIL_TOKEN_JSON temporarily and waiting for next tick. You should get a `⚠ Wolfee Reddit bot error` Telegram message. Restore the env var afterward. |

---

## Rollback procedures

### Roll back a single deploy

Railway dashboard → service → Deployments → click prior successful deploy → **"Redeploy"**. Takes ~30 s.

### Pause the cron entirely

Railway dashboard → service → Settings → clear the **"Cron Schedule"** field. The service stops firing immediately. To resume, re-enter `*/30 * * * *`.

### Full migration rollback — go back to local Mac cron

1. Pause the Railway cron (above).
2. On your Mac: `./install_cron.sh` — installs the local crontab entry, idempotent.
3. Verify: `crontab -l` shows the wolfee entry; `tail -f logs/cron.log` shows the next tick within 30 min.

Nothing in Railway needs to be destroyed for fallback — both pipelines can coexist briefly without harm (they'd both hit the same Gmail label, but the dedup table keeps either side from re-processing what the other already did, as long as you sync the DB).

### Roll back a specific patch commit

Per-commit rollback paths are documented in the prior session's summary. The Railway-prep commits (P2.1 through P2.7) are independent — `git revert <hash>` and push to undo any one of them. They do not depend on each other.

---

## Known risks / things to watch

1. **OAuth `invalid_grant` after ~7 days.** Your Google Cloud OAuth client is in "Testing" mode with you as a test user. Google may force re-consent periodically. If `cron.log` (Railway logs) starts showing `invalid_grant` errors from `creds.refresh()`, the fix is to either (a) publish the consent screen in Google Cloud Console, or (b) re-do the local OAuth dance to get a fresh `token.json`, then update `GMAIL_TOKEN_JSON` env var and delete `/data/token.json` so it re-seeds.

2. **Volume costs.** Railway volumes are charged by allocated GB-month. Default 1 GB is well over our needs (the DB is 20 KB). Set the volume size to the smallest available option (typically 1 GB).

3. **Cron drift.** Railway cron fires "around" the schedule, not at the exact second. `*/30` means "twice per hour, within a few seconds of `:00` and `:30`." Not a problem for our use case.

4. **Concurrent runs.** If a cron tick happens to start while the previous one is still running (e.g. a slow Claude API call), Railway *may* spawn a second instance. SQLite tolerates this fine for reads, but two simultaneous writes against the same row will serialize via SQLite's lock. Worst case is a brief stall, not corruption. If you start seeing locked-DB errors in the logs, we can add a lockfile guard then.

5. **Telegram rate limiting.** Telegram caps outbound messages around 30/sec per bot. We send 1 message per drafted comment + 1 per error. We'll never hit this.

---

## What's *not* in this runbook

- f5bot keyword changes — managed in your f5bot.com dashboard, not in this repo.
- Anthropic billing — managed in Anthropic console.
- Google Cloud OAuth scopes — already configured; touch only if you change Gmail label or need extra scopes.
- Prompt edits — `prompts/classify.md` and `prompts/draft_tier{2,3}.md` are editable in-place; commit + push triggers redeploy.

---

## After deploy: next-day checklist

24 h after the first successful cron tick:

- [ ] Railway logs show ≥ 48 invocations (24h × 2/hr), most with exit 0.
- [ ] Telegram chat received at least one draft notification (assuming f5bot fired ≥ once on an allowed subreddit).
- [ ] `railway run sqlite3 /data/processed.db "SELECT COUNT(*) FROM processed_emails;"` shows growth.
- [ ] `railway run tail -1 /data/logs/api_usage.jsonl` shows a JSON record with `"model": "claude-sonnet-4-6"`.
- [ ] No persistent error alerts in Telegram.

If any of those are off, paste the relevant log slice into a new Claude Code session for diagnosis.
