"""Readable labels for source references like "scorecards.json:s-104". FREE: a read-only DB lookup, no model call.

source_labels(refs) -> {"count": N, "groups": [{"candidate": name or "Other", "items": [{"ref", "label"}]}]}
The model's answer only carries raw refs; the label ("Scorecard s-104 · Technical Screen · Jonah Whitfield") is looked up here,
so it can not be invented. A ref that is not found keeps its raw text as the label, in the group "Other".
"""
from .common import connect, one

OTHER = "Other"


def _day(iso):
    from datetime import datetime
    try:
        d = datetime.fromisoformat(iso[:19])
        return f"{d:%b} {d.day}"
    except (TypeError, ValueError):
        return ""


def _app(con, app_id):
    return one(con, "SELECT a.id, a.status, j.title, c.name FROM applications a JOIN candidates c ON c.id = a.candidate_id "
                    "JOIN jobs j ON j.id = a.job_id_effective WHERE a.id = ?", app_id)


def _lookup(con, ref):
    """(candidate name or None, label) for one ref."""
    file, _, key = ref.partition(":")
    if file == "scorecards.json":
        r = one(con, "SELECT s.interview, a.id AS aid FROM scorecards s JOIN applications a ON a.id = s.application_id WHERE s.id = ?", key)
        a = _app(con, r["aid"]) if r else None
        if r:
            return a["name"], f"Scorecard {key} · {r['interview']} · {a['name']}"
    elif file == "applications.json":
        a = _app(con, key)
        if a:
            return a["name"], f"Application {key} · {a['title']} · {a['name']}"
    elif file == "candidates.json":
        r = one(con, "SELECT name FROM candidates WHERE id = ?", key)
        if r:
            return r["name"], f"Candidate record {key} · {r['name']}"
    elif file == "emails":
        r = one(con, "SELECT e.sent_at, e.direction, e.counterparty_name, c.name FROM emails e "
                     "LEFT JOIN candidates c ON c.id = e.candidate_id WHERE e.file = ?", key)
        if r:
            who = r["name"] or r["counterparty_name"] or "unknown sender"
            return r["name"], f"Email {'from' if r['direction'] == 'inbound' else 'to'} {who} · {_day(r['sent_at'])}"
    elif file == "stage_events.csv":
        r = one(con, "SELECT e.from_stage, e.to_stage, e.application_id FROM stage_events e WHERE e.id = ?", key)
        a = _app(con, r["application_id"]) if r else None
        if r and a:
            return a["name"], f"Stage change (line {key}) · {r['from_stage'] or 'start'} → {r['to_stage']} · {a['name']}"
    elif file == "activity.json":
        r = one(con, "SELECT n.author, c.name FROM activity_notes n JOIN candidates c ON c.id = n.candidate_id WHERE n.id = ?", key)
        if r:
            return r["name"], f"Recruiter note by {r['author']} · {r['name']}"
    elif file == "jobs.json":
        r = one(con, "SELECT title FROM jobs WHERE id = ?", key)
        if r:
            return None, f"Role {key} · {r['title']}"
    elif file == "cvs":
        r = one(con, "SELECT p.display_name AS name FROM cvs v LEFT JOIN persons p ON p.id = v.person_id WHERE v.filename = ?", key)
        if r:
            return r["name"], f"CV file · {r['name'] or 'unlinked'}"
    return None, ref


def source_labels(refs):
    refs = list(dict.fromkeys(refs or []))
    groups = {}
    with connect() as con:
        for ref in refs:
            name, label = _lookup(con, ref)
            groups.setdefault(name or OTHER, []).append({"ref": ref, "label": label})
    ordered = sorted(groups, key=lambda n: (n == OTHER, n))
    return {"count": len(refs), "groups": [{"candidate": n, "items": groups[n]} for n in ordered]}


def candidate_names():
    """All candidate names (longest first), to make names stand out in the answer text. Display only."""
    with connect() as con:
        names = {r[0] for r in con.execute("SELECT name FROM candidates")}
    return sorted(names, key=lambda n: (-len(n), n))
