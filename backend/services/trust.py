"""Rules for the Overview that are not MCP tools: status conflicts, why candidates leave, data coverage, the data-quality
groups and the "needs your decision" alerts. FREE: no model call. Read-only (the same DB as every service).

Definitions (also in README):
  status conflict   = an application has an offer_deadline but its status is rejected or withdrawn. The data cannot say whether
                      the offer was declined or the status is wrong. Nothing is corrected; it is flagged.
  exit              = an application with status rejected or withdrawn (hired and active are not exits). Status comes from
                      applications.json. Emails are never used to decide that somebody withdrew.
  exit "unknown"    = status rejected, but the data has no rejection reason or the application is a status conflict.
  coverage          = CVs: people (not records) with a linked CV / all people. Recruiter emails: people with at least one
                      linked email / all people. Scorecards: submitted / all scorecards (scheduled interviews).
"""
from backend import config

from . import issues, ranking, score_conflict
from .common import connect, rows

CLOSED = ("rejected", "withdrawn")
TOP_N = 3


# ---------------------------------------------------------------- status conflicts
def status_conflicts():
    """Applications with an offer deadline and a closed status (rejected or withdrawn). Newest deadline first."""
    with connect() as con:
        out = []
        for r in rows(con, "SELECT a.id, a.status, a.offer_deadline, a.rejected_at, a.rejection_reason, a.job_id_effective AS job, "
                           "c.name, j.title FROM applications a JOIN candidates c ON c.id = a.candidate_id "
                           "JOIN jobs j ON j.id = a.job_id_effective "
                           f"WHERE a.offer_deadline IS NOT NULL AND a.status IN ({','.join('?' * len(CLOSED))}) "
                           "ORDER BY a.offer_deadline DESC, a.id", *CLOSED):
            out.append({"application_id": r["id"], "candidate": r["name"], "job_id": r["job"], "role": r["title"], "status": r["status"],
                        "offer_deadline": r["offer_deadline"], "rejected_at": (r["rejected_at"] or "")[:10] or None,
                        "has_reason": bool(r["rejection_reason"]), "source": f"applications.json:{r['id']}"})
    for o in out:
        o["text"] = f"Verify status: {o['candidate']} — offer deadline {_day(o['offer_deadline'])}, but marked {o['status']}"
        o["explanation"] = (f"{o['candidate']} is marked {o['status']}"
                            + (f" on {_day(o['rejected_at'])}" if o["rejected_at"] else "")
                            + f", but the data has an offer deadline of {_day(o['offer_deadline'])}"
                            + ("" if o["has_reason"] else " and no reason for the rejection")
                            + ". The data cannot say whether the candidate declined or the status is wrong. "
                              "Nothing was changed: please check with the recruiter.")
    return out


def conflict_ids():
    return {c["application_id"] for c in status_conflicts()}


def _day(iso):
    from datetime import date
    d = date.fromisoformat(iso[:10])
    return f"{d:%b} {d.day}"


# ---------------------------------------------------------------- why candidates leave
def exit_reasons(job_id=None):
    """Rejected / withdrew / unknown for one role (or all roles). Counted from application status only."""
    conflicts = conflict_ids()
    with connect() as con:
        sql = "SELECT id, status, rejection_reason FROM applications WHERE status IN ('rejected','withdrawn')"
        args = ()
        if job_id:
            sql, args = sql + " AND job_id_effective = ?", (job_id,)
        found = rows(con, sql, *args)
    rejected = withdrew = unknown = 0
    for a in found:
        if a["status"] == "withdrawn":
            withdrew += 1
        elif not a["rejection_reason"] or a["id"] in conflicts:
            unknown += 1
        else:
            rejected += 1
    total = rejected + withdrew + unknown
    note = None
    if total == 0:
        note = "Nobody has left this role yet, so there is nothing to show."
    elif unknown * 2 > total:
        note = "Most exits have no usable reason in the data, so a chart would mislead."
    return {"job_id": job_id, "total": total, "rejected": rejected, "withdrew": withdrew, "unknown": unknown, "note": note}


# ---------------------------------------------------------------- data coverage
def _plural(n, one, many):
    return one if n == 1 else many


def coverage():
    """Three rings: CVs, recruiter emails, submitted scorecards. Each: {label, have, of, missing, pct, available, definition,
    sentence, missing_text}. The sentence is plain English; missing_text is the part to show in coral ("" when nothing is missing)."""
    out = []
    for label, query, definition in COVERAGE_QUERIES:
        try:
            with connect() as con:
                have, of = [con.execute(q).fetchone()[0] for q in query]
            if not of:
                raise ValueError("empty denominator")
            missing = of - have
            out.append({"label": label, "have": have, "of": of, "missing": missing, "pct": have / of, "available": True,
                        "definition": definition, **_sentence(label, have, of, missing)})
        except Exception:                                           # never show a made-up number
            out.append({"label": label, "have": None, "of": None, "missing": None, "pct": None, "available": False,
                        "definition": definition, "sentence": "Not available", "missing_text": ""})
    return out


def _sentence(label, have, of, missing):
    if label == "CVs":
        base = f"All {of} candidates have a CV" if not missing else f"{have} of {of} candidates have a CV"
        tail = f" — {missing} missing"
    elif label == "Recruiter emails":
        base = f"All {of} candidates have recruiter emails" if not missing else f"{have} of {of} candidates have recruiter emails"
        tail = f" — {missing} missing"
    else:
        base = f"All {of} interviews have feedback" if not missing else f"{have} of {of} interviews have feedback"
        tail = f" — {missing} not submitted yet"
    return {"sentence": base, "missing_text": tail if missing else ""}


COVERAGE_QUERIES = [
    ("CVs", ("SELECT COUNT(DISTINCT person_id) FROM cvs WHERE link_status IN ('linked','corrected') AND person_id IS NOT NULL",
             "SELECT COUNT(DISTINCT person_id) FROM candidates"),
     "People with a CV linked to them, out of all people (a duplicate record counts once)."),
    ("Recruiter emails", ("SELECT COUNT(DISTINCT person_id) FROM emails WHERE link_status = 'linked' AND person_id IS NOT NULL",
                          "SELECT COUNT(DISTINCT person_id) FROM candidates"),
     "People with at least one email linked to them, out of all people."),
    ("Submitted scorecards", ("SELECT COUNT(*) FROM scorecards WHERE feedback_status = 'submitted'",
                              "SELECT COUNT(*) FROM scorecards"),
     "Scorecards with feedback submitted, out of all scorecards (scheduled interviews)."),
]


# ---------------------------------------------------------------- data quality in plain English
# issue type -> (group, singular line, plural line). Groups: fixed = the loader corrected or merged it, human = a person has to
# decide, left = kept as it is on purpose. A type that is not listed here goes to "human" (safe default); a test checks the list.
GROUPS = {"fixed": "Fixed Automatically", "human": "Needs Your Review", "left": "Left Unchanged"}
GROUP_NOTE = {"fixed": "Issues corrected during processing.", "human": "Issues requiring a decision.", "left": "Documented without modification."}
ATTENTION_FIRST = {"rejected_with_offer_deadline": "Rejected application has an offer deadline",
                   "scorecard_mentions_other_application": "Interview feedback may refer to another application",
                   "stage_conflict": "Hiring stage conflicts with history"}
ATTENTION_OTHER = "Other records requiring verification"
ISSUE_TEXT = {
    "slash_date_inferred": ("fixed", "{n} date was written with slashes and was read with a fixed rule",
                            "{n} dates were written with slashes and were read with a fixed rule"),
    "stage_alias_applied": ("fixed", "{n} stage name was renamed to the role's standard stage",
                            "{n} stage names were renamed to the role's standard stage (for example Phone Screen → Recruiter Call)"),
    "cv_attached_to_wrong_candidate": ("fixed", "{n} CV was attached to the wrong candidate — moved to the right one",
                                       "{n} CVs were attached to the wrong candidate — moved to the right one"),
    "duplicate_person": ("fixed", "{n} person had two candidate records — merged into one person",
                         "{n} people had two candidate records — merged into one person"),
    "job_id_title_mismatch": ("fixed", "{n} application had a role ID that did not match its role — fixed from its stages and scorecards",
                              "{n} applications had a role ID that did not match their role — fixed from their stages and scorecards"),
    "stage_resolved_by_chain": ("fixed", "{n} application had stage dates that disagreed — the stage chain was used",
                                "{n} applications had stage dates that disagreed — the stage chain was used"),
    "email_on_merged_person": ("fixed", "{n} email was linked to a duplicate candidate record — merged",
                               "{n} emails were linked to a duplicate candidate record — merged"),
    "note_on_merged_person": ("fixed", "{n} recruiter note was on a duplicate candidate record — merged",
                              "{n} recruiter notes were on a duplicate candidate record — merged"),
    "rejected_with_offer_deadline": ("human", "{n} application is marked rejected but has an offer deadline — please check",
                                     "{n} applications are marked rejected but have an offer deadline — please check"),
    "stage_conflict": ("human", "{n} application has a stage that disagrees with its stage history — please check",
                       "{n} applications have a stage that disagrees with their stage history — please check"),
    "suspect_date": ("human", "{n} stage change is dated before the application — probably a typo",
                     "{n} stage changes are dated before the application — probably typos"),
    "missing_date": ("human", "{n} stage change has no date", "{n} stage changes have no date"),
    "scorecard_names_other_person": ("human", "{n} scorecard starts with another person's name — typo or misfiled?",
                                     "{n} scorecards start with another person's name — typo or misfiled?"),
    "scorecard_mentions_other_application": ("human", "{n} scorecard talks about another application of the same person",
                                             "{n} scorecards talk about another application of the same person"),
    "cv_shared_by_duplicate_records": ("human", "{n} CV is shared by two records of one person — linked to the person",
                                       "{n} CVs are shared by two records of one person — linked to the person"),
    "no_stage_events": ("left", "{n} application has no stage history — its path is not guessed",
                        "{n} applications have no stage history — their path is not guessed"),
    "task_no_due_date": ("left", "{n} task has no due date — none was made up", "{n} tasks have no due date — none was made up"),
    "same_name_different_people": ("left", "{n} pair of candidates share a name but are different people — kept apart",
                                   "{n} pairs of candidates share a name but are different people — kept apart"),
    "score_without_scale": ("left", "{n} score has no scale (like “3” instead of “3/5”) — not used",
                            "{n} scores have no scale (like “3” instead of “3/5”) — not used"),
    "no_email_in_record": ("left", "{n} candidate has no email address in the record",
                           "{n} candidates have no email address in the record"),
    "reply_to_missing_message": ("left", "{n} email replies to a message that is not in the mailbox",
                                 "{n} emails reply to messages that are not in the mailbox"),
}
# short title of each issue type, for the tables of the Data Quality card (the long sentence is in ISSUE_TEXT)
ISSUE_TITLE = {
    "slash_date_inferred": "Date written with slashes", "stage_alias_applied": "Stage renamed to the standard stage",
    "cv_attached_to_wrong_candidate": "CV attached to the wrong candidate", "duplicate_person": "Duplicate candidate record",
    "job_id_title_mismatch": "Role ID does not match the role", "stage_resolved_by_chain": "Stage dates disagree",
    "email_on_merged_person": "Email on a duplicate candidate record", "note_on_merged_person": "Note on a duplicate candidate record",
    "rejected_with_offer_deadline": "Rejected application has an offer deadline", "stage_conflict": "Hiring stage conflicts with history",
    "suspect_date": "Stage change dated before the application", "missing_date": "Missing stage-change date",
    "scorecard_names_other_person": "Scorecard contains another person's name",
    "scorecard_mentions_other_application": "Interview feedback may refer to another application",
    "cv_shared_by_duplicate_records": "CV shared by two records of one person", "no_stage_events": "No stage history",
    "task_no_due_date": "Task without a due date", "same_name_different_people": "Same name, different people",
    "score_without_scale": "Score without a scale", "no_email_in_record": "No email in the record",
    "reply_to_missing_message": "Reply to a missing message",
}
RESOLUTION = {"fixed": "Fixed Automatically", "human": "Needs Review", "left": "Left Unchanged"}
INCOMPLETE_FEEDBACK = "no_feedback_yet"        # an unsubmitted scorecard is missing feedback, not a data error (not counted)


def quality_groups():
    """{group: {"title", "total", "lines": [{type, n, text, sources[]}]}} for the three columns, biggest line first."""
    result = issues.get_data_issues()
    if not result.get("ok"):
        raise RuntimeError("data issues not available")
    by_type = {}
    for i in result["data"]["issues"]:
        if i["issue_type"] != INCOMPLETE_FEEDBACK:
            by_type.setdefault(i["issue_type"], []).append(f"{i['source_file']}:{i['source_id']}")
    out = {g: {"title": t, "note": GROUP_NOTE[g], "total": 0, "lines": []} for g, t in GROUPS.items()}
    for kind, sources in by_type.items():
        group, one, many = ISSUE_TEXT.get(kind, ("human", f"{{n}} problem of type {kind.replace('_', ' ')}", f"{{n}} problems of type {kind.replace('_', ' ')}"))
        n = len(sources)
        out[group]["lines"].append({"type": kind, "n": n, "text": (one if n == 1 else many).format(n=n), "sources": sources})
        out[group]["total"] += n
    for g in out.values():
        g["lines"].sort(key=lambda x: (-x["n"], x["type"]))
    return out


def quality_records():
    """One row per data issue (the existing audit records, nothing added): title, resolution group, severity, source, the audit's own
    reason, and the candidate the source belongs to when the existing source labels can tell (never guessed)."""
    from . import sources as source_lookup
    result = issues.get_data_issues()["data"]["issues"]
    records = [i for i in result if i["issue_type"] != INCOMPLETE_FEEDBACK]
    refs = [f"{i['source_file']}:{i['source_id']}" for i in records]
    label = {it["ref"]: it["label"] for g in source_lookup.source_labels(refs)["groups"] for it in g["items"]}
    rows_ = []
    for i, ref in zip(records, refs):
        kind = i["issue_type"]
        group = ISSUE_TEXT.get(kind, ("human",))[0]
        rows_.append({"problem": i["problem_id"], "type": kind, "issue": ISSUE_TITLE.get(kind, kind.replace("_", " ").capitalize()),
                      "group": group, "resolution": RESOLUTION[group], "severity": i["severity"], "handling": i["handling"],
                      "source": ref, "record": label.get(ref, ref), "content": i["reason"]})
    return rows_


def quality_summary():
    """Everything the Data Quality card shows: total, high severity, the three groups, and the "Issues Requiring Attention" rows
    (the three named issue types, then the rest of the "needs review" group added together)."""
    groups = quality_groups()
    result = issues.get_data_issues()["data"]["issues"]
    records = [i for i in result if i["issue_type"] != INCOMPLETE_FEEDBACK]
    human = {l["type"]: l["n"] for l in groups["human"]["lines"]}
    rows_ = [{"issue": ATTENTION_FIRST[t], "count": human[t], "type": t} for t in ATTENTION_FIRST if t in human]
    rest = sum(n for t, n in human.items() if t not in ATTENTION_FIRST)
    if rest:
        rows_.append({"issue": ATTENTION_OTHER, "count": rest, "type": "other"})
    return {"total": len(records), "high": sum(i["severity"] == "High" for i in records), "groups": groups, "attention": rows_,
            "to_review": groups["human"]["total"], "records": quality_records()}


# ---------------------------------------------------------------- "Needs your decision"
def _passed_offer_top_ranked():
    """Active applications that are in the top 3 of their role and whose offer deadline is before the reference date."""
    ref = config.REFERENCE_DATE.isoformat()
    with connect() as con:
        jobs_ = rows(con, "SELECT id, title FROM jobs ORDER BY id")
        late = {r["id"]: r["offer_deadline"] for r in rows(con, "SELECT id, offer_deadline FROM applications "
                                                                 "WHERE status = 'active' AND offer_deadline IS NOT NULL AND offer_deadline < ?", ref)}
    out = []
    for j in jobs_:
        res = ranking.rank_candidates_for_job(j["id"], top_n=TOP_N)
        for r in (res["data"]["ranked"] if res.get("ok") else []):
            if r["application_id"] in late:
                out.append({"application_id": r["application_id"], "candidate": r["name"], "role": j["title"], "job_id": j["id"],
                            "rank": r["rank"], "offer_deadline": late[r["application_id"]]})
    return out


def risk_flags(application_ids):
    """application_id -> rule-based flags that need the DB: offer deadline overdue (active) or status conflict. Open tasks, thin
    evidence and stage conflict come from the ranking tool result itself (web/chat.py). Never built from AI text."""
    ids = list(application_ids)
    if not ids:
        return {}
    ref = config.REFERENCE_DATE
    flags = {i: [] for i in ids}
    with connect() as con:
        for a in rows(con, f"SELECT id, status, offer_deadline FROM applications WHERE id IN ({','.join('?' * len(ids))})", *ids):
            if a["status"] == "active" and a["offer_deadline"] and a["offer_deadline"] < ref.isoformat():
                flags[a["id"]].append("Offer deadline overdue")
            elif a["status"] in CLOSED and a["offer_deadline"]:
                flags[a["id"]].append("Status conflict")
    for app_id in score_conflict.conflict_application_ids() & set(ids):          # review flag only: the ranking score is not touched
        flags[app_id].append(score_conflict.FLAG)
    return {i: _dedupe(f) for i, f in flags.items()}


def _dedupe(items):
    seen = []
    for x in items:
        if x not in seen:
            seen.append(x)
    return seen


def needs_decision(stalled_rows):
    """Up to three alerts, most important first. Rules: (1) a status conflict, (2) a top-3 candidate whose offer deadline has
    passed while the application is still active, (3) the longest-stalled active candidate. Each alert carries a prepared
    question for the AI panel; nothing is sent until the user clicks."""
    alerts = []
    for c in status_conflicts()[:1]:
        alerts.append({"kind": "status_conflict", "title": f"Status conflict: {c['candidate']}",
                       "text": c["explanation"], "source": c["source"], "job_id": c["job_id"],
                       "question": f"{c['candidate']} ({c['application_id']}) is marked {c['status']} but has an offer deadline of "
                                   f"{c['offer_deadline']}. What does the data say, and what should I verify?"})
    for c in _passed_offer_top_ranked()[:1]:
        alerts.append({"kind": "offer_passed", "title": f"Offer deadline passed: {c['candidate']}",
                       "text": f"{c['candidate']} is ranked #{c['rank']} for {c['role']}. The offer deadline was {_day(c['offer_deadline'])} "
                               f"and the application is still active.", "source": f"applications.json:{c['application_id']}",
                       "job_id": c["job_id"],
                       "question": f"{c['candidate']} ({c['application_id']}) is ranked #{c['rank']} for {c['role']} and their offer "
                                   f"deadline was {c['offer_deadline']}, but the application is still active. What is the status?"})
    for c in score_conflict.score_text_conflicts()[:1]:
        alerts.append({"kind": "score_text", "title": f"Score/text conflict: {c['candidate']}", "text": c["text"],
                       "source": c["source"], "job_id": c["job_id"],
                       "question": f"{c['candidate']}'s scorecard {c['scorecard_id']} ({c['interview']}) scores {c['score_text']} but the text says "
                                   f"'{c['quote']}'. What does the scorecard say in full, and what should I confirm with {c['interviewer']}?"})
    if stalled_rows:
        s = stalled_rows[0]
        alerts.append({"kind": "stalled", "title": f"Longest stalled: {s['candidate']}",
                       "text": f"{s['candidate']} has been in {s['stage']} for {s['days_in_stage']} days ({s['role']}).",
                       "source": s["source"].split(";")[0], "job_id": s["job_id"],
                       "question": f"{s['candidate']} has been in {s['stage']} for {s['days_in_stage']} days for {s['role']}. "
                                   "What is the status, and what is blocking them?"})
    return alerts[:4]


# ---------------------------------------------------------------- flags per application (Candidates page)
FLAG_CONFLICT, FLAG_OFFER, FLAG_STAGE, FLAG_STALLED = "Status conflict", "Offer deadline", "Stage conflict", "Longest stalled"
FLAG_SCORE_TEXT = score_conflict.FLAG


def application_flags(stalled_rows, stage_conflicts=()):
    """application_id -> [flag, ...] from rules only:
      Status conflict  = offer deadline on a rejected/withdrawn application
      Offer deadline   = still active, offer deadline before the reference date
      Stage conflict   = applications.json and the stage events disagree (given by the caller)
      Score/text conflict = a submitted scorecard with a high score but a "would not hire" verdict, or the reverse (score_conflict.py)
      Longest stalled  = the active application with the most days in its current stage"""
    flags = {}
    for c in status_conflicts():
        flags.setdefault(c["application_id"], []).append(FLAG_CONFLICT)
    ref = config.REFERENCE_DATE.isoformat()
    with connect() as con:
        for a in rows(con, "SELECT id FROM applications WHERE status = 'active' AND offer_deadline IS NOT NULL AND offer_deadline < ?", ref):
            flags.setdefault(a["id"], []).append(FLAG_OFFER)
    for app_id in stage_conflicts:
        flags.setdefault(app_id, []).append(FLAG_STAGE)
    for app_id in sorted(score_conflict.conflict_application_ids()):
        flags.setdefault(app_id, []).append(FLAG_SCORE_TEXT)
    if stalled_rows:
        flags.setdefault(stalled_rows[0]["application_id"], []).append(FLAG_STALLED)
    return flags


def last_updates():
    """application_id -> ISO date of the newest dated record of the application on or before the reference date: applied_at,
    stage events, submitted scorecards, rejected/withdrawn date, recruiter notes of the candidate. Emails are not used (their link to
    an application is not certain)."""
    end = config.REFERENCE_DATE.isoformat()
    best = {}

    def take(app_id, stamp):
        day = (stamp or "")[:10]
        if day and day <= end and day > best.get(app_id, ""):
            best[app_id] = day
    with connect() as con:
        apps = rows(con, "SELECT id, candidate_id, applied_at, rejected_at FROM applications")
        for a in apps:
            take(a["id"], a["applied_at"])
            take(a["id"], a["rejected_at"])
        for e in rows(con, "SELECT application_id, changed_at FROM stage_events"):
            take(e["application_id"], e["changed_at"])
        for c in rows(con, "SELECT application_id, submitted_at FROM scorecards WHERE feedback_status = 'submitted'"):
            take(c["application_id"], c["submitted_at"])
        notes = {}
        for n in rows(con, "SELECT candidate_id, created_at FROM activity_notes"):
            if (n["created_at"] or "")[:10] <= end:
                notes[n["candidate_id"]] = max(notes.get(n["candidate_id"], ""), n["created_at"][:10])
        for a in apps:
            if a["candidate_id"] in notes:
                take(a["id"], notes[a["candidate_id"]])
    return best
