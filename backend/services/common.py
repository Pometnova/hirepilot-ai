"""Shared helpers for all services: read-only DB, result envelope, structured errors, small lookups.

Rules (CLAUDE.md): plain Python, no MCP code, no print() (stdout belongs to the MCP protocol),
no SQL built from user input (every query uses ? parameters), dates compared in Python.
"""
import functools
import logging
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime

from backend import config

log = logging.getLogger("hirepilot")
if not log.handlers:                                   # logs go to STDERR only, never stdout
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


class ServiceError(Exception):
    """A problem with the caller's input. Becomes {"ok": false, "error": {...}}, never a crash."""

    def __init__(self, code, message, valid_values=None, hint=None):
        super().__init__(message)
        self.code, self.message, self.valid_values, self.hint = code, message, valid_values, hint

    def as_dict(self):
        err = {"code": self.code, "message": self.message}
        if self.valid_values is not None:
            err["valid_values"] = self.valid_values
        if self.hint:
            err["hint"] = self.hint
        return {"ok": False, "error": err}


def ok(data, notes=None):
    return {"ok": True, "as_of": config.REFERENCE_DATE.isoformat(), "data": data, "notes": notes or []}


@contextmanager
def connect():
    """Read-only connection. A write attempt raises sqlite3.OperationalError."""
    con = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def service(fn):
    """Open the DB, call fn(con, ...) -> (data, notes), wrap as ok(...) or a structured error."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            with connect() as con:
                data, notes = fn(con, *args, **kwargs)
            return ok(data, notes)
        except ServiceError as e:
            return e.as_dict()
        except Exception as e:                          # never leak a stack trace or a record
            log.error("internal error in %s: %s", fn.__name__, type(e).__name__)
            return {"ok": False, "error": {"code": "internal_error",
                                           "message": "Unexpected error. Details are in the server log."}}
    return wrapper


def rows(con, sql, *params):
    return [dict(r) for r in con.execute(sql, params)]


def one(con, sql, *params):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def need_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ServiceError("invalid_input", f"'{name}' must be a non-empty string.")
    return value.strip()


def require_job(con, job_id):
    job_id = need_text(job_id, "job_id")
    job = one(con, "SELECT * FROM jobs WHERE id = ?", job_id)
    if not job:
        raise ServiceError("unknown_job_id", f"No job with id '{job_id}'.",
                           valid_values=[r["id"] for r in rows(con, "SELECT id FROM jobs ORDER BY id")])
    return job


def require_candidate(con, candidate_id):
    candidate_id = need_text(candidate_id, "candidate_id")
    cand = one(con, "SELECT * FROM candidates WHERE id = ?", candidate_id)
    if not cand:
        raise ServiceError("unknown_candidate_id", f"No candidate with id '{candidate_id}'.",
                           hint="Candidate ids look like 'c-101'. Use list_candidates_for_job to find them.")
    return cand


def job_stages(con, job_id):
    """[(position, stage)] in order."""
    return [(r["position"], r["stage"]) for r in
            con.execute("SELECT position, stage FROM job_stages WHERE job_id = ? ORDER BY position", (job_id,))]


def effective_stage(app):
    """Stage from the sorted events if the application has events, else the source stage."""
    return app["current_stage_from_events"] or app["current_stage_source"]


def stage_conflict(app):
    a, b = app["current_stage_source"], app["current_stage_from_events"]
    return bool(a and b and a != b)


def to_date(value):
    return date.fromisoformat(value) if value else None


def to_dt(value):
    return datetime.fromisoformat(value) if value else None


def issue_flags(con, pairs, ids, files=None):
    """data_issues rows that match (source_file, source_id) pairs or related ids. Compact form."""
    out = []
    for r in rows(con, "SELECT * FROM data_issues ORDER BY id"):
        related = set((r["related_source_id"] or "").split(","))
        if (r["source_file"], r["source_id"]) in pairs or (related & ids):
            if files is None or r["source_file"] in files:
                out.append({"problem_id": r["problem_id"], "issue_type": r["issue_type"],
                            "severity": r["severity"], "reason": r["reason"], "handling": r["handling"],
                            "source_file": r["source_file"], "source_id": r["source_id"]})
    return out
