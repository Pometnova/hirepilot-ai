"""Numbers and tables for the web app (Overview, Candidates, Tasks). FREE: no model call. It combines the existing services
(list_jobs, get_funnel, list_tasks, list_candidates_for_job, get_data_issues) and adds a few read-only queries for things no
service returns yet (offer deadlines, no stage history, days in the current stage). The web app contains no logic or SQL.

dashboard() -> {as_of, kpis, roles[], funnels{job_id: {...}}, tasks{counts, overdue[], priority[], by_kpi{...}}, activity[], stalled{...},
  issues{...}, conflicts[], exits{job_id: {...}}, coverage[], quality{fixed, human, left}, decisions[], quality_summary{...},
  candidates[]}   (conflicts .. quality_summary come from trust.py)
Raises AnalyticsError (with a safe message) when a service returns an error.

Definitions (also in README):
  drop-off into stage B (previous stage A) = (rejected + withdrew at A) / reached A. Applications still waiting at A are NOT lost.
  stalled = active application with MORE than config.STALLED_DAYS days in its current stage as of config.REFERENCE_DATE.
  record issue = a data_issues row that is an actual conflict or cleaning decision. An unsubmitted scorecard (no_feedback_yet)
  is incomplete feedback, not a data error, so it is counted separately.
"""
from backend import config

from . import funnel, issues, jobs, tasks, trust
from .common import connect, effective_stage, job_stages, rows, to_dt

TASK_STATES = ("overdue", "due_today", "pending", "pending_no_due_date")
STATUSES = ("active", "hired", "rejected", "withdrawn")
INCOMPLETE_FEEDBACK_TYPES = ("no_feedback_yet",)
DEADLINE_SOURCE = {"data": "From the data", "assumption": "Assumed", "none": "No due date"}


class AnalyticsError(Exception):
    pass


def _data(result, what):
    if not result.get("ok"):
        raise AnalyticsError(f"Could not load {what}: {result.get('error', {}).get('code', 'unknown error')}.")
    return result["data"]


def fmt_date(d):
    return f"{d:%b} {d.day}, {d.year}"


# ---------------------------------------------------------------- funnel for one role
def no_history_counts():
    """job_id -> number of applications that have no stage events (their path is unknown beyond the first stage)."""
    with connect() as con:
        return {r["j"]: r["n"] for r in rows(con, "SELECT job_id_effective AS j, COUNT(*) AS n FROM applications "
                                                   "WHERE current_stage_from_events IS NULL GROUP BY 1")}


def _stage_row(s):
    return {"stage": s["stage"], "position": s["position"], "entered": s["entered"], "reached": s["entered"], "moved_on": s["moved_on"],
            "rejected": s["rejected"], "withdrew": s["withdrew"], "hired": s["hired"],
            "still_in_stage": s["still_in_stage"], "still_in_progress": s["still_in_stage"], "lost": s["rejected"] + s["withdrew"],
            "conversion_rate": s["conversion_rate"], "median_days_in_stage": s["median_days_in_stage"],
            "median_days_n": s["median_days_n"]}


def role_funnel(job_id, title, days_open=None, opened_at=None, no_history=0):
    f = _data(funnel.get_funnel(job_id), f"the funnel for {job_id}")
    stages = [_stage_row(s) for s in f["stages"]]
    for i, s in enumerate(stages):
        if i == 0:
            s.update(dropoff_pct=None, dropoff_from=None, dropoff_lost=None, dropoff_base=None)
            continue
        prev = stages[i - 1]
        base = prev["reached"]
        s.update(dropoff_from=prev["stage"], dropoff_lost=prev["lost"], dropoff_base=base,
                 dropoff_pct=(prev["lost"] / base) if base else None)
    candidates = [s for s in stages if s["dropoff_pct"]]                       # only transitions where somebody was lost
    top = max(candidates, key=lambda s: (s["dropoff_pct"], -s["position"]), default=None)         # ties: the earlier transition
    prev_of = {s["stage"]: stages[i - 1] for i, s in enumerate(stages) if i}
    largest = None
    if top:
        p = prev_of[top["stage"]]
        largest = {"from_stage": p["stage"], "to_stage": top["stage"], "pct": top["dropoff_pct"], "lost": p["lost"],
                   "base": p["reached"], "rejected": p["rejected"], "withdrew": p["withdrew"]}
    timed = [s for s in stages if s["median_days_in_stage"] is not None]
    slow = max(timed, key=lambda s: (s["median_days_in_stage"], -s["position"]), default=None)
    worst = max(stages, key=lambda s: (s["lost"], -s["position"]), default=None)               # most people lost AT a stage
    out = {"job_id": job_id, "title": title, "opened_at": opened_at or f["opened_at"], "days_open": days_open,
           "applications": f["applications"], "stages": stages, "largest_dropoff": largest, "no_history": no_history,
           "slowest_stage": ({"stage": slow["stage"], "median_days": slow["median_days_in_stage"]} if slow else None),
           "biggest_loss": ({"stage": worst["stage"], "lost": worst["lost"], "entered": worst["entered"]}
                            if worst and worst["lost"] else None)}
    out["summary"] = funnel_summary(out)
    return out


def funnel_summary(f):
    """Plain sentences built from the numbers (no model call)."""
    parts = []
    if f["days_open"] is not None:
        parts.append(f"The role has been open for {f['days_open']} days as of {fmt_date(config.REFERENCE_DATE)}.")
    d = f["largest_dropoff"]
    if d:
        parts.append(f"The largest drop-off is {d['from_stage']} → {d['to_stage']}: {d['lost']} of {d['base']} candidates did not "
                     f"progress ({d['rejected']} rejected, {d['withdrew']} withdrew).")
    else:
        parts.append("No candidate has been rejected or has withdrawn at any stage.")
    if f["slowest_stage"]:
        parts.append(f"The slowest stage is {f['slowest_stage']['stage']} (median {f['slowest_stage']['median_days']:g} days).")
    if d:
        parts.append(f"Check {d['from_stage']} first.")
    return " ".join(parts)


# ---------------------------------------------------------------- tasks, KPIs
def task_row(t, titles):
    return {"task_id": t["task_id"], "candidate": t.get("candidate_name") or "(unknown)", "task": t["task_type"].replace("_", " "),
            "task_type": t["task_type"], "role": ", ".join(titles.get(j, j) for j in t["job_ids"]), "job_ids": t["job_ids"],
            "due_date": t["due_date"], "state": t["state"], "days_overdue": t.get("days_overdue"),
            "deadline_source": DEADLINE_SOURCE[t["due_rule"]], "deadline_rule": t["due_rule_detail"],
            "source": f"{t['source_file']}:{t['source_id']}"}


def offer_deadlines():
    """Every offer deadline in applications.json with the application status. upcoming = on or after the reference date."""
    with connect() as con:
        out = []
        for r in rows(con, "SELECT a.id, a.status, a.offer_deadline, a.job_id_effective AS job, c.name FROM applications a "
                           "JOIN candidates c ON c.id = a.candidate_id WHERE a.offer_deadline IS NOT NULL ORDER BY a.offer_deadline, a.id"):
            out.append({"application_id": r["id"], "candidate": r["name"], "job_id": r["job"], "status": r["status"],
                        "deadline": r["offer_deadline"], "upcoming": r["offer_deadline"] >= config.REFERENCE_DATE.isoformat(),
                        "source": f"applications.json:{r['id']}"})
        return out


def _by_state(task_list):
    return {k: sum(t["state"] == k for t in task_list) for k in TASK_STATES}


# ---------------------------------------------------------------- stalled candidates
def stalled_candidates(min_days=None):
    """Active applications with MORE than min_days days in their current stage as of the reference date.
    Entry into the current stage = the latest stage event into it; for an application with no events that is still in the
    first stage, its application date. Anything else is 'unknown' and is counted, not guessed."""
    min_days = config.STALLED_DAYS if min_days is None else min_days
    ref = config.REFERENCE_DATE
    with connect() as con:
        titles = {r["id"]: r["title"] for r in rows(con, "SELECT id, title FROM jobs")}
        first = {j: job_stages(con, j)[0][1] for j in titles}
        events = {}
        for e in rows(con, "SELECT * FROM stage_events ORDER BY id"):
            events.setdefault(e["application_id"], []).append(e)
        result, unknown = [], []
        for a in rows(con, "SELECT a.*, c.name FROM applications a JOIN candidates c ON c.id = a.candidate_id "
                           "WHERE a.status = 'active' ORDER BY a.id"):
            stage = effective_stage(a)
            into = [e for e in events.get(a["id"], []) if e["to_stage"] == stage and e["changed_at"]]
            entered, ref_src = None, None
            if into:
                last = max(into, key=lambda e: e["changed_at"])
                entered, ref_src = to_dt(last["changed_at"]), f"stage_events.csv:{last['source_id']}"
            elif stage == first.get(a["job_id_effective"]) and not events.get(a["id"]):
                entered, ref_src = to_dt(a["applied_at"]), "applications.json (applied_at)"
            if entered is None or entered.date() < to_dt(a["applied_at"]).date():
                unknown.append(a["id"])
                continue
            days = (ref - entered.date()).days
            if days > min_days:
                result.append({"application_id": a["id"], "candidate": a["name"], "role": titles.get(a["job_id_effective"]),
                               "job_id": a["job_id_effective"], "stage": stage, "entered_on": entered.date().isoformat(),
                               "days_in_stage": days, "source": f"applications.json:{a['id']}; {ref_src}"})
    result.sort(key=lambda r: (-r["days_in_stage"], r["application_id"]))
    return {"min_days": min_days, "rows": result, "unknown_stage_date": unknown}


# ---------------------------------------------------------------- recent activity
ACTIVITY_LIMIT = 5


def recent_activity(limit=ACTIVITY_LIMIT):
    """The newest dated records on or before the reference date: recruiter notes, submitted scorecards, emails.
    Real dates from the files, no relative times. The text of a note or email is not copied: only who and what kind."""
    end = f"{config.REFERENCE_DATE.isoformat()}T23:59:59"
    with connect() as con:
        out = []
        for r in rows(con, "SELECT n.id, n.created_at AS at, n.author, c.name FROM activity_notes n "
                           "LEFT JOIN candidates c ON c.id = n.candidate_id"):
            out.append({"at": r["at"], "kind": "note", "text": f"Recruiter note on {r['name'] or 'a candidate'} by {r['author']}",
                        "source": f"activity.json:{r['id']}"})
        for r in rows(con, "SELECT s.id, s.submitted_at AS at, s.interview, c.name FROM scorecards s "
                           "JOIN applications a ON a.id = s.application_id JOIN candidates c ON c.id = a.candidate_id "
                           "WHERE s.feedback_status = 'submitted' AND s.submitted_at IS NOT NULL"):
            out.append({"at": r["at"], "kind": "scorecard", "text": f"Scorecard submitted for {r['name']} ({r['interview']})",
                        "source": f"scorecards.json:{r['id']}"})
        for r in rows(con, "SELECT e.file, e.sent_at AS at, e.direction, e.counterparty_name, c.name FROM emails e "
                           "LEFT JOIN candidates c ON c.id = e.candidate_id WHERE e.sent_at IS NOT NULL"):
            who = r["name"] or r["counterparty_name"] or "an unknown sender"
            out.append({"at": r["at"], "kind": "email",
                        "text": f"Email {'from' if r['direction'] == 'inbound' else 'sent to'} {who}", "source": f"emails:{r['file']}"})
    out = [o for o in out if to_dt(o["at"]).replace(tzinfo=None).isoformat() <= end]
    out.sort(key=lambda o: (to_dt(o["at"]), o["source"]), reverse=True)
    for o in out:
        d = to_dt(o["at"])
        o["date"] = f"{d:%b} {d.day}"
    return out[:limit]


# ---------------------------------------------------------------- tables for the Candidates and Tasks pages
def candidates_table(job_id=None):
    """One row per application, optionally for one role. Built on list_candidates_for_job."""
    job_list = _data(jobs.list_jobs(), "the roles")
    out = []
    conflicts = trust.conflict_ids()
    all_apps = [(j, a) for j in job_list for a in _data(jobs.list_candidates_for_job(j["job_id"]), f"the candidates of {j['job_id']}")["applications"]]
    flags = trust.application_flags(stalled_candidates()["rows"], [a["application_id"] for _, a in all_apps if a["stage_conflict"]])
    updates = trust.last_updates()                                      # flags and dates are always computed over ALL roles
    for j, a in all_apps:
        if job_id and j["job_id"] != job_id:
            continue
        out.append({"candidate": a["name"], "role": j["title"], "job_id": j["job_id"], "stage": a["current_stage"],
                    "status": a["status"], "applied": (a["applied_at"] or "")[:10],
                    "stage_conflict": bool(a["stage_conflict"]), "application_id": a["application_id"],
                    "flags": flags.get(a["application_id"], []), "last_update": updates.get(a["application_id"]),
                    "status_conflict": a["application_id"] in conflicts,
                    "source": f"{a['source_file']}:{a['source_id']}"})
    return out


def tasks_table(job_id=None):
    job_list = _data(jobs.list_jobs(), "the roles")
    titles = {j["job_id"]: j["title"] for j in job_list}
    t = _data(tasks.list_tasks("all", job_id=job_id), "the tasks")["tasks"]
    return [task_row(x, titles) for x in t]


# ---------------------------------------------------------------- everything the Overview needs
def dashboard():
    job_list = _data(jobs.list_jobs(), "the roles")
    titles = {j["job_id"]: j["title"] for j in job_list}
    no_hist = no_history_counts()
    roles, funnels = [], {}
    for j in job_list:
        by = {k: j["applications_by_status"].get(k, 0) for k in STATUSES}
        total = sum(by.values())
        roles.append({"job_id": j["job_id"], "title": j["title"], "department": j["department"], "status": j["status"],
                      "opened_at": j["opened_at"], "days_open": j["days_open"], "months_open": j["months_open"], "applications": total, **by,
                      "hire_rate": round(by["hired"] / total, 3) if total else None})
        funnels[j["job_id"]] = role_funnel(j["job_id"], j["title"], j["days_open"], j["opened_at"], no_hist.get(j["job_id"], 0))

    for r in roles:                                   # active candidates by current stage, for the small bar in Open Positions
        r["active_by_stage"] = [{"stage": x["stage"], "count": x["still_in_progress"]} for x in funnels[r["job_id"]]["stages"]]

    t = _data(tasks.list_tasks("all"), "the tasks")
    all_tasks = t["tasks"]
    counts = {k: t["counts_before_state_filter"].get(k, 0) for k in TASK_STATES}
    rows_all = [task_row(x, titles) for x in all_tasks]
    overdue = sorted((r for r in rows_all if r["state"] == "overdue"), key=lambda r: (-(r["days_overdue"] or 0), r["task_id"]))
    order = {k: i for i, k in enumerate(TASK_STATES)}                  # Priority Actions: overdue, due today, pending, no due date
    priority = sorted(rows_all, key=lambda r: (order[r["state"]], -(r["days_overdue"] or 0), r["due_date"] or "9999", r["task_id"]))
    scorecards = [x for x in all_tasks if x["task_type"] == "scorecard_pending"]
    emails = [x for x in all_tasks if x["task_type"] == "email_unanswered"]
    offers = offer_deadlines()
    upcoming = [o for o in offers if o["upcoming"]]
    live = [o for o in upcoming if o["status"] == "active"]
    conflicting = [o for o in upcoming if o["status"] != "active"]

    iss = _data(issues.get_data_issues(), "the data issues")
    record = [i for i in iss["issues"] if i["issue_type"] not in INCOMPLETE_FEEDBACK_TYPES]
    incomplete = [i for i in iss["issues"] if i["issue_type"] in INCOMPLETE_FEEDBACK_TYPES]
    by_sev, by_type = {}, {}
    for i in record:
        by_sev[i["severity"]] = by_sev.get(i["severity"], 0) + 1
        by_type[i["issue_type"]] = by_type.get(i["issue_type"], 0) + 1
    by_type = dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0])))

    totals = {k: sum(r[k] for r in roles) for k in STATUSES}
    applications = sum(totals.values())
    kpis = {"open_roles": sum(r["status"] == "open" for r in roles), "applications": applications, **totals,
            "hire_rate": round(totals["hired"] / applications, 3) if applications else None,
            "open_tasks": t["count"], "overdue_tasks": counts["overdue"], "due_today_tasks": counts["due_today"],
            "pending_scorecards": len(scorecards), "pending_scorecards_by_state": _by_state(scorecards),
            "unanswered_emails": len(emails), "unanswered_emails_by_state": _by_state(emails),
            "upcoming_offer_deadlines": len(live), "offer_deadlines_on_closed_applications": len(conflicting),
            "data_issues": len(record), "high_severity_issues": by_sev.get("High", 0), "incomplete_feedback": len(incomplete)}
    kpi_records = {
        "overdue_tasks": overdue,
        "pending_scorecards": [task_row(x, titles) for x in scorecards],
        "unanswered_emails": [task_row(x, titles) for x in emails],
        "upcoming_offer_deadlines": [{**o, "role": titles.get(o["job_id"], o["job_id"])} for o in upcoming]}
    stalled = stalled_candidates()
    return {"as_of": config.REFERENCE_DATE.isoformat(), "kpis": kpis, "roles": roles, "funnels": funnels,
            "tasks": {"counts": counts, "overdue": overdue, "priority": priority, "by_kpi": kpi_records},
            "activity": recent_activity(),
            "stalled": stalled,
            "conflicts": trust.status_conflicts(),
            "exits": {j["job_id"]: trust.exit_reasons(j["job_id"]) for j in job_list},
            "coverage": trust.coverage(),
            "quality": trust.quality_groups(),
            "decisions": trust.needs_decision(stalled["rows"]),
            "quality_summary": trust.quality_summary(),
            "candidates": candidates_table(),
            "issues": {"total": len(record), "by_severity": by_sev, "by_type": by_type, "incomplete_feedback": len(incomplete),
                       "all_rows": len(iss["issues"]),
                       "records": [{"problem": i["problem_id"], "type": i["issue_type"], "severity": i["severity"], "handling": i["handling"],
                                    "source": f"{i['source_file']}:{i['source_id']}", "reason": i["reason"]} for i in record]}}
