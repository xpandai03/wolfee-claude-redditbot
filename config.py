"""Static config for the Wolfee Reddit comment seeder.

Edit the lists/strings here as Wolfee evolves. Secrets stay in .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- paths ---
# All four below are env-overridable so the same code runs unchanged on macOS
# (cron) and inside a Railway container (volume-backed /data). Defaults
# reproduce the original repo-root layout, so unset env vars on the Mac give
# the same behavior as before this refactor.
ROOT = Path(__file__).parent
STATE_DIR = Path(os.environ.get("STATE_DIR") or (ROOT / "state"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR") or (ROOT / "logs"))
DB_PATH = STATE_DIR / "processed.db"
PROMPTS_DIR = ROOT / "prompts"  # shipped in the image; never env-overridable
CREDENTIALS_PATH = Path(os.environ.get("CREDENTIALS_PATH") or (ROOT / "credentials.json"))
# token.json defaults to repo root on macOS for backwards compat. On Railway
# point TOKEN_PATH at the mounted volume (e.g. /data/token.json) so refresh
# rotations persist across container restarts.
TOKEN_PATH = Path(os.environ.get("TOKEN_PATH") or (ROOT / "token.json"))

# --- secrets / env-driven ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GMAIL_LABEL = os.environ.get("GMAIL_LABEL", "f5bot-wolfee")
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "wolfee-comment-seeder/0.1 by raunstrong"
)

# --- gmail scope ---
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# --- subs we never comment on (burned / off-brand) ---
# Match is case-insensitive against the sub name (without r/ prefix).
BURNED_SUBS: set[str] = set()

# --- allowlist: only these subs reach the classifier ---
# Burned subs always override the allowlist (hard block).
# Lowercase comparison; entries here must be lowercase.
ALLOWED_SUBS = frozenset({
    "jobsearchhacks",
    "interviewhacking",
    "recruitinghell",
    "techsales",
    "salesdevelopment",
    "cscareerquestions",
    "sdr",
    "salesoperations",
    "findapath",
    "layoffs",
    "jobs",
    "csmajors",
    "productmanagement",
    "consulting",
    "askhr",
    "interviews",
    "interviewhackers",
    "jobsearch",
    "careeradvice",
    "careeradvice_india",
    "productmanagement_in",
    "ainotetaker",
    "aitoolbench",
    "indiehackers",
    "entrepreneurridealong",
    "sideproject",
    "ycombinator",
    "microsaas",
    "growmybusiness",
    # expanded scope (2026-05): remote/async work, recording, broader business
    "remotework",
    "wfh",
    "productivity",
    "tools",
    "software",
    "freelance",
    "recruiting",
    "careerguidance",
    "saas",
    "startups",
    "entrepreneur",
    "smallbusiness",
    "sales",
    "marketing",
    "videoediting",
    "screenrecording",
    "telecommuting",
    "workonline",
})

# --- wolfee positioning ---
WOLFEE_USE_CASES = """
Wolfee's core use cases (for tier classification):
- interview prep / interview practice / AI interview tools
- live interview copilots
- sales call practice, objection handling, cold call practice
- recorded meeting analysis, conversation intelligence
- meeting transcription with action items
- context-switching across high-stakes calls
- screen recording with AI transcription and shareable links
- Loom alternative with automatic summaries
- async video messaging for teams
- recording and sharing product demos
""".strip()

WOLFEE_FEATURES = """
Wolfee is ONE tool that replaces a stack of four. Be accurate; never claim
features that aren't shipped. Core pitch: stop paying for 4 disconnected tools
that don't talk to each other — Wolfee handles everything before, during,
after, and between professional conversations.

Four capabilities (each replaces a standalone tool):

1. Screen + webcam recorder (Loom alternative, ~$15/mo standalone) — built-in
   screen and webcam recording with AI transcription, automatic summaries,
   and shareable links. Use cases: async video updates, product demos,
   walkthroughs instead of scheduling another meeting.

2. Meeting recorder (Fireflies / Otter alternative, ~$18/mo standalone) —
   joins Zoom / Meet / Teams, records and transcribes the call, extracts
   action items, syncs notes to your tools.

3. AI interview simulator (interview-prep tools, $20-40/mo standalone) —
   practices interviews, sales calls, and negotiations with you via video
   call. AI avatars push back in real time. Post-session scoring and
   feedback.

4. Invisible Copilot (no standalone equivalent) — live Mac desktop assistant
   that listens to real calls and surfaces AI suggestions only you can see.
   Hidden from screen share on Zoom / Meet / Teams in most setups.

Timeline framing (lean on this when the post is about workflow, not one tool):
- Before the call: practice with the AI simulator
- During the call: live coaching from the invisible Copilot
- After the call: auto-generated transcript, summary, action items
- Between calls: record and share async video updates

Pricing: $19/mo for the full stack vs $60-80/mo equivalent bought separately.
Free tier: 1 simulation + 3 meetings/mo, 10-min copilot session cap.
Site: https://wolfee.io
""".strip()

# --- tier definitions, shared by classifier + drafter ---
TIER_DEFINITIONS = """
Tier 1 — post is only tangentially related to Wolfee's use cases. Do NOT mention Wolfee.
        (We skip drafting entirely for Tier 1.)

Tier 2 — post is related and Wolfee is one of 2-3 reasonable options to bring up.
        Draft uses framing like "I've used Wolfee for this" without leading with the
        product. Soft mention, in service of a genuine answer.

Tier 3 — post is explicitly asking for tools / recommendations in Wolfee's exact use
        case. Draft names Wolfee directly, describes the relevant feature, and includes
        the wolfee.io link.
""".strip()

# --- body rules for drafts (Tier 2 + Tier 3) ---
BODY_RULES = """
Length: STRICT ceiling of 120 words. Aim for 80-110. Count your words before
   submitting. If you go over 120, cut sentences — do not just trim adjectives.
Voice: first-person experience framing. Talk like a human who has lived the problem.
Banned phrases / words: "game changer", "revolutionary", "excited to connect", "synergy",
   "leverage", "circle back".
Banned punctuation: em dashes (—), exclamation marks (!), hashtags (#).
End with: a genuine question OR a practical alternative.
Do NOT use markdown headings or bullet lists. Plain prose, 1-3 short paragraphs.
""".strip()
