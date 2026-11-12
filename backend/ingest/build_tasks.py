"""Build the tasks table from the sources defined in docs/DATA_AUDIT.md section 3.3.

The loader stores EVERY item, open and closed. It does not filter by REFERENCE_DATE and it does not
compute "overdue" (backend/services/ does that: overdue = due_date < REFERENCE_DATE).

  A offer_deadline          one task per application with an offer_deadline
  B scorecard_pending       one task per scorecard
  C email_unanswered        one task per inbound email
  H application_unreviewed  one task per ACTIVE application with no stage events (open only;
                            audit class H names only the pending ones, so no closed rows)

Closing rules
  status_field   the application / scorecard status says so                (confidence high)
  same_thread    a LATER staff message on the SAME thread to the SAME person closes an inbound email
                 (high if it replies directly to it, medium if it is later in the thread).
                 Same subject alone is NOT enough: the task stays open and a data_issues row is written.
"""
import re
import sqlite3
from datetime import timedelta

from backend import config
from .dates import date_of, parse_iso
from .normalize import insert


def _row(task_type, source_file, source_id, due_basis, status, application_id=None, candidate_id=None,
         person_id=None, due_date=None, closed_at=None, closed_by=None, close_method=None, close_confidence=None):
    return dict(id=f"{task_type}:{source_id}", task_type=task_type, application_id=application_id,
                candidate_id=candidate_id, person_id=person_id, due_date=due_date, due_basis=due_basis,
                status=status, closed_at=closed_at, closed_by=closed_by, close_method=close_method,
                close_confidence=close_confidence, source_file=source_file, source_id=source_id)


def _offer_tasks(con):
    out = []
    q = """SELECT a.id, a.status, a.offer_deadline, a.rejected_at, a.candidate_id, c.person_id
           FROM applications a JOIN candidates c ON c.id = a.candidate_id
           WHERE a.offer_deadline IS NOT NULL ORDER BY a.id"""
    for r in con.execute(q):
        kw = dict(application_id=r["id"], candidate_id=r["candidate_id"], person_id=r["person_id"],
                  due_date=r["offer_deadline"])
        basis = "applications.offer_deadline"
        by = f"applications.json#{r['id']}"
        if r["status"] == "active":
            out.append(_row("offer_deadline", "applications.json", r["id"], basis, "open", **kw))
        elif r["status"] == "hired":     # closed_at is not in the data
            out.append(_row("offer_deadline", "applications.json", r["id"], basis, "done",
                            closed_by=by, close_method="status_field", close_confidence="high", **kw))
        else:                            # rejected / withdrawn
            out.append(_row("offer_deadline", "applications.json", r["id"], basis, "closed",
                            closed_at=r["rejected_at"], closed_by=by, close_method="status_field",
                            close_confidence="high", **kw))
    return out


def _scorecard_tasks(con):
    out = []
    q = """SELECT s.id, s.application_id, s.interview_at, s.submitted_at, s.feedback_status,
                  a.status AS app_status, a.rejected_at, a.candidate_id, c.person_id
           FROM scorecards s JOIN applications a ON a.id = s.application_id
           JOIN candidates c ON c.id = a.candidate_id ORDER BY s.id"""
    for r in con.execute(q):
        due = (date_of(r["interview_at"]) + timedelta(days=config.SCORECARD_OVERDUE_DAYS)).isoformat()
        basis = f"interview_at + {config.SCORECARD_OVERDUE_DAYS} days (config.SCORECARD_OVERDUE_DAYS)"
        kw = dict(application_id=r["application_id"], candidate_id=r["candidate_id"],
                  person_id=r["person_id"], due_date=due)
        if r["feedback_status"] == "submitted":
            out.append(_row("scorecard_pending", "scorecards.json", r["id"], basis, "done",
                            closed_at=r["submitted_at"], closed_by=f"scorecards.json#{r['id']}",
                            close_method="status_field", close_confidence="high", **kw))
        elif r["app_status"] == "active":
            out.append(_row("scorecard_pending", "scorecards.json", r["id"], basis, "open", **kw))
        else:   # nobody is waiting for this feedback any more
            out.append(_row("scorecard_pending", "scorecards.json", r["id"], basis, "closed",
                            closed_at=r["rejected_at"], closed_by=f"applications.json#{r['application_id']}",
                            close_method="status_field", close_confidence="high", **kw))
    return out


def _norm_subject(s):
    return re.sub(r"^(re:\s*)+", "", (s or "").strip(), flags=re.I).strip().lower()


def _email_tasks(con, issues):
    out = []
    emails = con.execute("""SELECT file, message_id, in_reply_to, thread_id, sent_at, direction, subject,
                                   candidate_id, person_id FROM emails ORDER BY file""").fetchall()
    staff = [e for e in emails if e["direction"] == "outbound" and e["person_id"]]
    for e in emails:
        if e["direction"] != "inbound":
            continue
        sent = parse_iso(e["sent_at"])
        later = [s for s in staff if e["person_id"] and s["person_id"] == e["person_id"]
                 and parse_iso(s["sent_at"]) > sent]
        same_thread = [s for s in later if s["thread_id"] == e["thread_id"]]
        due = (date_of(e["sent_at"]) + timedelta(days=config.EMAIL_UNANSWERED_DAYS)).isoformat()
        kw = dict(candidate_id=e["candidate_id"], person_id=e["person_id"], due_date=due)
        basis = f"email sent date + {config.EMAIL_UNANSWERED_DAYS} days (config.EMAIL_UNANSWERED_DAYS)"
        if same_thread:
            direct = [s for s in same_thread if s["in_reply_to"] == e["message_id"]]
            reply = min(direct or same_thread, key=lambda s: parse_iso(s["sent_at"]))
            out.append(_row("email_unanswered", "emails", e["file"], basis, "done",
                            closed_at=reply["sent_at"], closed_by=f"emails#{reply['file']}",
                            close_method="same_thread", close_confidence="high" if direct else "medium", **kw))
            continue
        out.append(_row("email_unanswered", "emails", e["file"], basis, "open", **kw))
        subject_only = [s for s in later if _norm_subject(s["subject"]) == _norm_subject(e["subject"])]
        if subject_only:
            issues.add("possible_answer_same_subject_only", "Medium", "emails", e["file"],
                       "A later staff message to the same person has the same subject, but it is not on this "
                       "thread. Same subject alone does not close a task, so the task stays open.",
                       "recorded", related_source_id=subject_only[0]["file"])
    return out


def _unreviewed_tasks(con, issues):
    out = []
    q = """SELECT a.id, a.candidate_id, c.person_id FROM applications a
           JOIN candidates c ON c.id = a.candidate_id
           WHERE a.status = 'active'
             AND NOT EXISTS (SELECT 1 FROM stage_events e WHERE e.application_id = a.id)
             AND a.current_stage_source = (SELECT stage FROM job_stages WHERE job_id = a.job_id_effective AND position = 1)
           ORDER BY a.id"""
    for r in con.execute(q):
        out.append(_row("application_unreviewed", "applications.json", r["id"],
                        "none: the data has no due date for a new application", "open",
                        application_id=r["id"], candidate_id=r["candidate_id"], person_id=r["person_id"]))
        issues.add("task_no_due_date", "Low", "applications.json", r["id"],
                   "Pending task (new application not yet reviewed) has no due date in the data. "
                   "It is listed as pending only and can never be called overdue.", "recorded")
    return out


def build_tasks(con, issues):
    con.row_factory = sqlite3.Row
    try:
        tasks = (_offer_tasks(con) + _scorecard_tasks(con) + _email_tasks(con, issues)
                 + _unreviewed_tasks(con, issues))
    finally:
        con.row_factory = None
    for t in tasks:
        insert(con, "tasks", t)
