"""Data issues recorded by the loader (the only place problems are kept)."""
from .common import ServiceError, need_text, one, rows, service

SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _entity_keys(con, entity_id):
    """Which (source_file, source_id) pairs and plain ids belong to this entity? Raises if unknown."""
    pairs, ids = set(), {entity_id}
    if one(con, "SELECT 1 x FROM candidates WHERE id = ?", entity_id) or one(con, "SELECT 1 x FROM persons WHERE id = ?", entity_id):
        cands = [r[0] for r in con.execute("SELECT id FROM candidates WHERE id = ? OR person_id = ?", (entity_id, entity_id))]
        for cid in cands:
            ids.add(cid)
            pairs.add(("candidates.json", cid))
            for (a,) in con.execute("SELECT id FROM applications WHERE candidate_id = ?", (cid,)).fetchall():
                ids.add(a)
                pairs.add(("applications.json", a))
                pairs |= {("stage_events.csv", str(e)) for (e,) in con.execute("SELECT id FROM stage_events WHERE application_id = ?", (a,))}
                pairs |= {("scorecards.json", s) for (s,) in con.execute("SELECT id FROM scorecards WHERE application_id = ?", (a,))}
            pairs |= {("emails", f) for (f,) in con.execute("SELECT file FROM emails WHERE candidate_id = ?", (cid,))}
            pairs |= {("activity.json", str(n)) for (n,) in con.execute("SELECT id FROM activity_notes WHERE candidate_id = ?", (cid,))}
            pairs |= {("cvs", f) for (f,) in con.execute("SELECT filename FROM cvs WHERE candidate_id = ? OR source_candidate_id = ?", (cid, cid))}
    elif one(con, "SELECT 1 x FROM applications WHERE id = ?", entity_id):
        pairs.add(("applications.json", entity_id))
        pairs |= {("stage_events.csv", str(e)) for (e,) in con.execute("SELECT id FROM stage_events WHERE application_id = ?", (entity_id,))}
        pairs |= {("scorecards.json", s) for (s,) in con.execute("SELECT id FROM scorecards WHERE application_id = ?", (entity_id,))}
    elif one(con, "SELECT 1 x FROM scorecards WHERE id = ?", entity_id):
        pairs.add(("scorecards.json", entity_id))
    elif one(con, "SELECT 1 x FROM jobs WHERE id = ?", entity_id):
        pairs.add(("jobs.json", entity_id))
        for (a,) in con.execute("SELECT id FROM applications WHERE job_id_effective = ?", (entity_id,)).fetchall():
            ids.add(a)
            pairs.add(("applications.json", a))
    elif one(con, "SELECT 1 x FROM emails WHERE file = ?", entity_id):
        pairs.add(("emails", entity_id))
    else:
        raise ServiceError("unknown_entity_id", f"No job, candidate, person, application, scorecard or email with id '{entity_id}'.",
                           hint="Use ids like 'j-backend', 'c-105', 'p-105', 'a-114', 's-131', or an email file name.")
    return pairs, ids


@service
def get_data_issues(con, entity_id=None):
    pairs = ids = None
    if entity_id is not None:
        pairs, ids = _entity_keys(con, need_text(entity_id, "entity_id"))
    out = []
    for r in rows(con, "SELECT * FROM data_issues"):
        if pairs is not None:
            related = set((r["related_source_id"] or "").split(","))
            if (r["source_file"], r["source_id"]) not in pairs and not (related & ids):
                continue
        out.append({"issue_id": r["id"], "problem_id": r["problem_id"], "issue_type": r["issue_type"],
                    "severity": r["severity"], "handling": r["handling"], "reason": r["reason"],
                    "value_source": r["value_source"], "value_used": r["value_used"],
                    "related_source_id": r["related_source_id"],
                    "source_file": r["source_file"], "source_id": r["source_id"]})
    out.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["problem_id"] or "~", x["issue_id"]))
    by_type = {}
    for i in out:
        by_type[i["issue_type"]] = by_type.get(i["issue_type"], 0) + 1
    return {"entity_id": entity_id, "count": len(out), "by_issue_type": by_type, "issues": out}, \
        ["handling: normalized = the loader fixed it and kept the source value; recorded = stored as is and flagged; "
         "left = deliberately not changed."]
