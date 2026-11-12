"""Project settings. The only place for REFERENCE_DATE, paths and thresholds."""
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")                # secrets live only in .env (git-ignored). Never print them.
RAW_DIR = ROOT / "data" / "raw"          # READ ONLY. Never write here.
DB_PATH = ROOT / "data" / "hirepilot.db"
SCHEMA_PATH = ROOT / "backend" / "db" / "schema.sql"

# Export date. Used for "overdue", "pending" and "open for N months".
# Never use today's date.
#
# Overdue rule (used by backend/services/ from Phase 3 on):
#   overdue   = due_date <  REFERENCE_DATE
#   due today = due_date == REFERENCE_DATE   (NOT overdue)
# Dates are compared in Python (date objects), never as text in SQL.
REFERENCE_DATE = date(2026, 10, 15)

# All times in the export are New York local time.
TIMEZONE = "America/New_York"

# Email sender on this domain = company staff.
STAFF_DOMAIN = "quillfeather.example.com"

# Task thresholds. ASSUMPTIONS chosen by the author, NOT data (docs/DATA_AUDIT.md section 8).
# This is the only place they are defined; everything else imports them.
SCORECARD_OVERDUE_DAYS = 2   # scorecard due = interview date + 2 days
EMAIL_UNANSWERED_DAYS = 3    # inbound email due = date received + 3 days
STALLED_DAYS = 14            # an active application is 'stalled' after MORE than this many days in its current stage

# Ranking weights (backend/services/ranking.py). ASSUMPTIONS, not data (docs/DATA_AUDIT.md section 8).
# score = 100 * (RANK_WEIGHT_FEEDBACK * feedback + RANK_WEIGHT_PROGRESS * progress). Must add up to 1.
RANK_WEIGHT_FEEDBACK = 0.70
RANK_WEIGHT_PROGRESS = 0.30

# ---- Agent (Phase 4) ----
# Model: default here, optional override with ANTHROPIC_MODEL in .env.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5-5"
AGENT_MAX_TOOL_ROUNDS = 10         # max model calls per question (the last one may not ask for tools)
AGENT_MAX_TOKENS = 16000           # per model call. Thinking tokens count against it, so do not set it low.
AGENT_EFFORT = "medium"            # output_config.effort: low | medium | high | xhigh | max
AGENT_REQUEST_TIMEOUT_S = 120      # per model call
AGENT_TOOL_TIMEOUT_S = 30          # per MCP call_tool
AGENT_MAX_TOOL_RESULT_CHARS = 40000   # longer tool results are cut, with a marker the model can see
API_MAX_RETRIES = 2                # SDK retries (429, 5xx, connection errors)
# Estimate only, USD per million tokens for claude-sonnet-5-5 (cached 2026-10; check the pricing page).
PRICE_PER_MTOK = {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50}

# ---- Web app (Phase 5) ----
UI_MAX_HISTORY_TURNS = 6           # earlier question/answer pairs sent to the agent for follow-ups
