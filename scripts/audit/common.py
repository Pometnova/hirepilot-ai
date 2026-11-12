"""Shared helpers for the Phase 1 audit scripts. READ-ONLY on data/raw/.

Run scripts with:  .venv/bin/python -I scripts/audit/<script>.py
(-I stops Python from importing files from the current folder, so we add
this folder to sys.path explicitly in each script.)
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
REFERENCE_DATE = datetime(2026, 10, 15)  # export date. Never use today's date.
STAFF_DOMAIN = "quillfeather.example.com"
# Q3 thresholds are assumptions, not data. They live ONLY in backend/config.py; we import them here.
sys.path.insert(0, str(ROOT))
from backend.config import SCORECARD_OVERDUE_DAYS, EMAIL_UNANSWERED_DAYS  # noqa: E402

def load_json(name):
    with open(RAW / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def load_events():
    import pandas as pd
    df = pd.read_csv(RAW / "stage_events.csv", dtype=str, keep_default_na=False)
    df["row"] = df.index + 2  # CSV line number (line 1 = header)
    return df


def parse_dt(s, dayfirst=None):
    """Parse the date formats seen in the export. Returns naive datetime or None.

    Formats seen: ISO 'YYYY-MM-DD[ T]HH:MM[:SS]' and slash dates.
    Slash-date rule (INFERRED, checked on all 8 cases in 02_dates.py):
      24-hour 'HH:MM'  -> DD/MM/YYYY
      12-hour 'H:MM AM/PM' -> MM/DD/YYYY
    Pass dayfirst=True/False to force one reading (used only for comparison).
    """
    if dayfirst is None:
        dayfirst = not re.search(r"[AP]M$", str(s).strip())
    if s is None or str(s).strip() == "":
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    order = ("%d/%m/%Y", "%m/%d/%Y") if dayfirst else ("%m/%d/%Y", "%d/%m/%Y")
    for d in order:
        for t in ("%I:%M %p", "%H:%M"):
            try:
                return datetime.strptime(s, f"{d} {t}")
            except ValueError:
                pass
    return None


def norm_name(s):
    return re.sub(r"[^a-z]", "", s.lower())


def norm_phone(s):
    return re.sub(r"\D", "", s)


def norm_email(s):
    """Lowercase and strip '+tag' from the local part."""
    s = s.strip().lower()
    local, _, dom = s.partition("@")
    return local.split("+")[0] + "@" + dom
