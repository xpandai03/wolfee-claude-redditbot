"""Static config for the Wolfee Reddit comment seeder.

Edit the lists/strings here as Wolfee evolves. Secrets stay in .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- paths ---
ROOT = Path(__file__).parent
STATE_DIR = ROOT / "state"
DB_PATH = STATE_DIR / "processed.db"
PROMPTS_DIR = ROOT / "prompts"
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"

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
BURNED_SUBS = {"saas", "sales"}

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
""".strip()

WOLFEE_FEATURES = """
Wolfee has three product moments. Be accurate; never claim features that aren't shipped.

1. Practice (Simulate) — AI-powered conversation simulator for interview, sales, and
   negotiation practice. Avatars push back. Post-session scoring.

2. Perform (Wolfee Copilot) — live Mac desktop copilot that listens to real calls and
   surfaces suggestions. Hidden from screen share on Zoom / Meet / Teams in most setups.

3. Review (Record + Analyze) — meeting bot that joins Zoom / Meet / Teams, transcribes,
   generates notes and action items.

Pricing: Free tier (1 simulation + 3 meetings/mo, 10-min copilot session cap).
Paid: Starter $19/mo, Pro $39/mo.
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
