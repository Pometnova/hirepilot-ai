"""Build data/hirepilot.db from data/raw/. Deletes the old database first."""
import sqlite3
from pathlib import Path

from backend import config
from .build_tasks import build_tasks
from .issues import Issues
from .link_cvs import load_cvs
from .link_emails import load_emails
from .load_core import (load_activity, load_applications, load_candidates, load_jobs,
                        load_scorecards, load_stage_events)
from .normalize import insert, raw_checksum

TABLES = ["jobs", "job_stages", "stage_aliases", "persons", "candidates", "candidate_contacts",
          "applications", "stage_events", "scorecards", "scorecard_scores", "activity_notes",
          "cvs", "emails", "tasks", "data_issues", "build_meta"]


def table_counts(con):
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def build_database(db_path=config.DB_PATH):
    db_path = Path(db_path).resolve()
    if config.RAW_DIR.resolve() in db_path.parents:
        raise ValueError("The database must never be written inside data/raw/")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for p in (db_path, Path(str(db_path) + "-journal")):
        p.unlink(missing_ok=True)

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
        issues = Issues()

        jobs = load_jobs(con)
        link = load_candidates(con, issues)
        apps = load_applications(con, issues, jobs)
        load_stage_events(con, issues, apps)
        load_scorecards(con, issues, apps)
        load_activity(con, issues, link)
        load_cvs(con, issues)
        load_emails(con, issues)
        build_tasks(con, issues)
        issues.write(con)

        for k, v in (("reference_date", config.REFERENCE_DATE.isoformat()),
                     ("timezone", config.TIMEZONE),
                     ("raw_checksum", raw_checksum()),
                     ("scorecard_overdue_days", str(config.SCORECARD_OVERDUE_DAYS)),
                     ("email_unanswered_days", str(config.EMAIL_UNANSWERED_DAYS))):
            insert(con, "build_meta", dict(key=k, value=v))
        con.commit()

        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise RuntimeError(f"foreign key violations: {len(bad)}")
        counts = table_counts(con)
    except Exception:
        con.close()
        db_path.unlink(missing_ok=True)      # never leave a half-built database
        raise
    con.close()
    return counts
