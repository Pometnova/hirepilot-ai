"""Deterministic candidate ranking for one job. Python does the maths; the LLM explains.

card score        = the 'overall' score / its scale; if the card has no 'overall', the mean of its other scores
interview score   = mean of the card scores of the same interview (several interviewers count once)
feedback          = mean of the interview scores                              (0..1)
progress          = (stage position - 1) / (number of stages - 1)             (0..1)
score             = 100 * (RANK_WEIGHT_FEEDBACK * feedback + RANK_WEIGHT_PROGRESS * progress)

A candidate with no submitted, scorable feedback is NOT scored (no feedback yet is not negative).
They go in a separate 'not_scored' list. The job has no role requirements, so fit to the role is not measured.
"""
from statistics import mean

from backend import config
from .tasks import collect_tasks
from .common import (ServiceError, effective_stage, issue_flags, job_stages, require_job, rows, service,
                     stage_conflict)

THIN_EVIDENCE_MAX_CARDS = 1
FLAG_FILES = {"applications.json", "candidates.json", "scorecards.json"}


def _card_score(scores):
    by_label = {s["label"]: s["normalized"] for s in scores}
    if "overall" in by_label:
        return by_label["overall"], "overall"
    return (mean(by_label.values()), "mean of other scores") if by_label else (None, None)


@service
def rank_candidates_for_job(con, job_id, top_n=3, include_statuses=None):
    job = require_job(con, job_id)
    include = include_statuses if include_statuses is not None else ["active"]
    valid = ["active", "rejected", "withdrawn", "hired"]
    if not isinstance(include, list) or not include or any(s not in valid for s in include):
        raise ServiceError("invalid_status", "include_statuses must be a non-empty list of statuses.", valid_values=valid)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 50:
        raise ServiceError("invalid_input", "top_n must be a whole number from 1 to 50.")
    w_fb, w_pr = config.RANK_WEIGHT_FEEDBACK, config.RANK_WEIGHT_PROGRESS

    stages = job_stages(con, job["id"])
    pos = {s: p for p, s in stages}
    n = len(stages)
    ph = ",".join("?" * len(include))
    apps = rows(con, f"SELECT a.*, c.name FROM applications a JOIN candidates c ON c.id = a.candidate_id "
                     f"WHERE a.job_id_effective = ? AND a.status IN ({ph}) ORDER BY a.id", job["id"], *include)
    cards = {}
    for c in rows(con, "SELECT * FROM scorecards ORDER BY id"):
        cards.setdefault(c["application_id"], []).append(c)
    scores = {}
    for s in rows(con, "SELECT * FROM scorecard_scores ORDER BY id"):
        scores.setdefault(s["scorecard_id"], []).append(s)

    persons = {r["id"]: r["person_id"] for r in rows(con, "SELECT id, person_id FROM candidates")}
    open_tasks = collect_tasks(con, include_closed=False)       # same rules and states as list_tasks

    def tasks_for(a):
        """Tasks of this application; email tasks (no application) by candidate, or by person (duplicate record)."""
        mine = []
        for t in open_tasks:
            if t["application_id"]:
                hit = t["application_id"] == a["id"]
            else:
                hit = t["candidate_id"] == a["candidate_id"] or t["person_id"] == persons[a["candidate_id"]]
            if hit:
                keep = ("task_id", "task_type", "state", "candidate_name", "due_date", "days_overdue", "days_until_due",
                        "due_rule", "due_rule_detail", "other_records", "other_records_note", "source_file", "source_id")
                item = {k: t[k] for k in keep if k in t}
                if t["candidate_id"] != a["candidate_id"]:
                    item["linked_via"] = f"same person as {t['candidate_id']} (duplicate record, audit P01)"
                mine.append(item)
        return mine

    ranked, not_scored = [], []
    for a in apps:
        stage = effective_stage(a)
        progress = (pos[stage] - 1) / (n - 1) if stage in pos and n > 1 else 0.0
        mine = cards.get(a["id"], [])
        pending = [c["id"] for c in mine if c["feedback_status"] == "no_feedback_yet"]
        evidence, interviews = [], {}
        for c in (c for c in mine if c["feedback_status"] == "submitted"):
            value, basis = _card_score(scores.get(c["id"], []))
            ev = {"scorecard_id": c["id"], "interview": c["interview"], "interviewer": c["interviewer"],
                  "submitted_at": c["submitted_at"], "card_score": round(value, 3) if value is not None else None,
                  "card_score_basis": basis, "scores": [f"{s['label']}: {s['value']:g}/{s['scale']}" for s in scores.get(c["id"], [])],
                  "text_excerpt": (c["text"] or "")[:240], "source_file": c["source_file"], "source_id": c["source_id"]}
            evidence.append(ev)
            if value is not None:
                interviews.setdefault(c["interview_key"], []).append(value)
        pairs = {("applications.json", a["id"]), ("candidates.json", a["candidate_id"])} | \
                {("scorecards.json", c["id"]) for c in mine}
        base = {"application_id": a["id"], "candidate_id": a["candidate_id"], "name": a["name"], "status": a["status"],
                "current_stage": stage, "stage_position": pos.get(stage), "stage_conflict": stage_conflict(a),
                "pending_scorecards": pending, "open_tasks": tasks_for(a), "evidence": evidence,
                "flags": issue_flags(con, pairs, {a["id"], a["candidate_id"]}, FLAG_FILES),
                "source_file": a["source_file"], "source_id": a["source_id"]}
        if stage_conflict(a):
            base["stage_in_applications_json"] = a["current_stage_source"]
        if interviews:
            feedback = mean(mean(v) for v in interviews.values())
            ranked.append({**base, "score": round(100 * (w_fb * feedback + w_pr * progress), 2),
                           "components": {
                               "feedback": {"value": round(feedback, 3), "weight": w_fb, "points": round(100 * w_fb * feedback, 2),
                                            "interviews_scored": len(interviews)},
                               "progress": {"value": round(progress, 3), "weight": w_pr, "points": round(100 * w_pr * progress, 2),
                                            "stage": stage, "position": pos.get(stage), "of": n}},
                           "evidence_level": "thin" if len(evidence) <= THIN_EVIDENCE_MAX_CARDS else "ok",
                           "_f": feedback, "_p": progress})
        else:
            reason = ("no submitted scorecard yet" if not evidence else "submitted scorecards have no numeric score")
            not_scored.append({**base, "score": None, "reason": f"{reason}; this is not negative feedback",
                               "progress": {"value": round(progress, 3), "stage": stage}, "_p": progress})

    ranked.sort(key=lambda r: (-r["score"], -r["_f"], -r["_p"], r["candidate_id"], r["application_id"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    not_scored.sort(key=lambda r: (-r["_p"], r["application_id"]))
    for r in ranked + not_scored:
        r.pop("_f", None), r.pop("_p", None)

    data = {"job_id": job["id"], "title": job["title"], "include_statuses": include,
            "formula": {"score": "100 * (feedback_weight * feedback + progress_weight * progress)",
                        "feedback_weight": w_fb, "progress_weight": w_pr,
                        "feedback": "mean over interviews of the card scores (overall/scale, or mean of other scores)",
                        "progress": "(stage position - 1) / (stages - 1)"},
            "ranked_total": len(ranked), "ranked": ranked[:top_n],
            "not_scored_total": len(not_scored), "not_scored": not_scored}
    notes = ["The job has no role requirements in the data (jobs.json), so this ranking uses interview feedback and stage "
             "progress only. It does NOT measure fit to the role.",
             "'ranked' = has submitted, scorable feedback. 'not_scored' = no feedback yet; this is not negative feedback "
             "and not a lower rank. The two lists must not be merged into one order.",
             "evidence_level 'thin' = one scorecard only. Weights are assumptions (DATA_AUDIT section 8).",
             "open_tasks lists each candidate's open tasks (same rules and states as list_tasks). They do not change the score."]
    if len(ranked) > top_n:
        notes.append(f"Showing the top {top_n} of {len(ranked)} ranked candidates.")
    return data, notes
