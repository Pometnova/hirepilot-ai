"""Rebuild data/hirepilot.db from data/raw/.

Run from the project root:   .venv/bin/python scripts/build_db.py
Deletes the old database first, so running it twice gives the same result.
Prints row counts per table only (no candidate records).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # needed because we run with -I or from anywhere

from backend import config                      # noqa: E402
from backend.ingest.build import build_database  # noqa: E402


def main():
    counts = build_database(config.DB_PATH)
    print(f"Built {config.DB_PATH.relative_to(config.ROOT)} (REFERENCE_DATE {config.REFERENCE_DATE})")
    width = max(len(t) for t in counts)
    for table, n in counts.items():
        print(f"  {table:<{width}}  {n:>5}")


if __name__ == "__main__":
    main()
