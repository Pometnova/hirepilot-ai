"""Pending and overdue tasks. The loader stores tasks with a due date and NO overdue flag;
the state is decided here, in Python, against REFERENCE_DATE.

  overdue              open and due_date <  REFERENCE_DATE
  due_today            open and due_date == REFERENCE_DATE   (not overdue)
  pending              open and due_date >  REFERENCE_DATE
  pending_no_due_date  open and no due date in the data      (never overdue)
"""
from backend import config
from .common import ServiceError, need_text, require_job, rows, service, to_date

STATES = ["overdue", "due_today", "pending", "all"]
_RULE = {  # task_type -> (due_rule, text)
    "offer_deadline": ("data", "explicit date in applications.json (offer_deadline)"),
    "scorecard_pending": ("assumption", None),
    "email_unanswered": ("assumption", None),
    "application_unreviewed": ("none", "the data has no due date for a new application"),
}


def task_state(due, ref=None):
    ref = ref or config.REFERENCE_DATE
    if due is None:
        return "pending_no_due_date"
    return "overdue" if due < ref else "due_today" if due == ref else "pending"


def _rule(task_type):
    rule, text = _RULE[task_type]
    if task_type == "scorecard_pending":
        text = f"interview date + {config.SCORECARD_OVERDUE_DAYS} days (config.SCORECARD_OVERDUE_DAYS, our assumption, not data)"
    elif task_type == "email_unanswered":
        text = f"date received + {config.EMAIL_UNANSWERED_DAYS} days (config.EMAIL_UNANSWERED_DAYS, our assumption, not data)"
    return rule, text


def collect_tasks(con, job_id=None, include_closed=False):
    """All tasks (open, plus closed if asked) as dicts with state and due rule. No state filter."""
    app_job = {r["id"]: r["job_id_effective"] for r in rows(con, "SELECT id, job_id_effective FROM applications")}
    cand_jobs = {}
    for r in rows(con, "SELECT candidate_id, job_id_effective FROM applications"):
        cand_jobs.setdefault(r["candidate_id"], set()).add(r["job_id_effective"])
    names = {r["id"]: r["name"] for r in rows(con, "SELECT id, name FROM candidates")}
    by_person = {}                                    # person -> all candidate records (duplicates, audit P01)
    for r in rows(con, "SELECT id, person_id FROM candidates ORDER BY id"):
        by_person.setdefault(r["person_id"], []).append(r["id"])

    out = []
    for t in rows(con, "SELECT * FROM tasks ORDER BY id"):
        job_ids = {app_job[t["application_id"]]} if t["application_id"] else cand_jobs.get(t["candidate_id"], set())
        if job_id and job_id not in job_ids:
            continue
        due = to_date(t["due_date"])
        is_open = t["status"] == "open"
        if not is_open and not include_closed:
            continue
        item = {"task_id": t["id"], "task_type": t["task_type"], "status": t["status"],
                "application_id": t["application_id"], "candidate_id": t["candidate_id"],
                "person_id": t["person_id"], "candidate_name": names.get(t["candidate_id"]),
                "job_ids": sorted(job_ids), "due_date": t["due_date"], "due_basis": t["due_basis"]}
        item["due_rule"], item["due_rule_detail"] = _rule(t["task_type"])
        others = [c for c in by_person.get(t["person_id"], []) if c != t["candidate_id"]]
        if others:                                   # only when it is true; no field for ordinary candidates
            item["other_records"] = others
            item["other_records_note"] = (f"{names.get(t['candidate_id'])} is stored as {len(others) + 1} candidate records "
                                          f"(this one and {', '.join(others)}); it is the same person (audit P01). Application, "
                                          "candidate and scorecard ids are numbered separately, so different numbers are normal.")
        if is_open:
            item["state"] = task_state(due)
            if due and due < config.REFERENCE_DATE:
                item["days_overdue"] = (config.REFERENCE_DATE - due).days
            elif due:
                item["days_until_due"] = (due - config.REFERENCE_DATE).days
        else:
            item["state"] = "closed"
            item.update(closed_at=t["closed_at"], closed_by=t["closed_by"], close_method=t["close_method"],
                        close_confidence=t["close_confidence"])
        item.update(source_file=t["source_file"], source_id=t["source_id"])
        out.append(item)
    return out


@service
def list_tasks(con, state="all", job_id=None, include_closed=False):
    state = need_text(state, "state").lower()
    if state not in STATES:
        raise ServiceError("invalid_state", f"Unknown state '{state}'.", valid_values=STATES)
    if job_id is not None:
        job_id = require_job(con, job_id)["id"]
    if not isinstance(include_closed, bool):
        raise ServiceError("invalid_input", "'include_closed' must be true or false.")

    out = collect_tasks(con, job_id, include_closed)
    counts = {k: sum(i["state"] == k for i in out) for k in ("overdue", "due_today", "pending", "pending_no_due_date")}
    if state != "all":
        keep = {"overdue": {"overdue"}, "due_today": {"due_today"}, "pending": {"pending", "pending_no_due_date"}}[state]
        out = [i for i in out if i["state"] in keep]
    rank = {"overdue": 0, "due_today": 1, "pending": 2, "pending_no_due_date": 3, "closed": 4}
    out.sort(key=lambda i: (rank[i["state"]], i["due_date"] or "9999", i["task_id"]))
    notes = [f"States are decided against REFERENCE_DATE {config.REFERENCE_DATE} (not today). Overdue means due_date is "
             "before that day; a task due on that day is 'due_today'. 'pending' also includes tasks with no due date "
             "(state 'pending_no_due_date'), which are never overdue.",
             "due_rule says where the due date comes from: 'data' (explicit in the source), 'assumption' (our rule, "
             "not in the data) or 'none'."]
    if job_id:
        notes.append("Email tasks have no application; they match a job through the candidate's applications.")
    for i in out:
        i.pop("person_id", None)                     # internal id: not shown (prompt rule 10)
    return {"state_filter": state, "job_id": job_id, "count": len(out),
            "counts_before_state_filter": counts, "tasks": out}, notes
