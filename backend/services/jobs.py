"""Jobs and the applications for a job."""
from backend import config
from .common import (ServiceError, effective_stage, job_stages, need_text, require_job, rows, service,
                     stage_conflict, to_date)

APP_STATUSES = ["active", "rejected", "withdrawn", "hired"]


@service
def list_jobs(con):
    counts = {}
    for r in rows(con, "SELECT job_id_effective AS j, status, COUNT(*) n FROM applications GROUP BY 1, 2"):
        counts.setdefault(r["j"], {})[r["status"]] = r["n"]
    out = []
    for j in rows(con, "SELECT * FROM jobs ORDER BY opened_at, id"):
        opened = to_date(j["opened_at"])
        days = (config.REFERENCE_DATE - opened).days if opened else None
        out.append({"job_id": j["id"], "title": j["title"], "department": j["department"], "status": j["status"],
                    "opened_at": j["opened_at"], "days_open": days,
                    "months_open": round(days / 30.44, 1) if days is not None else None,
                    "applications_by_status": counts.get(j["id"], {}),
                    "source_file": j["source_file"], "source_id": j["source_id"]})
    return out, [f"days_open and months_open are counted to {config.REFERENCE_DATE} (the export date), not today. "
                 "months_open = days_open / 30.44."]


@service
def get_job(con, job_id):
    job = require_job(con, job_id)
    stages = rows(con, "SELECT position, stage, source_file, source_id FROM job_stages WHERE job_id = ? "
                       "ORDER BY position", job["id"])
    names = {s["stage"] for s in stages}
    aliases = rows(con, "SELECT alias, stage, source_file, source_id FROM stage_aliases")
    data = {"job_id": job["id"], "title": job["title"], "department": job["department"], "status": job["status"],
            "opened_at": job["opened_at"], "requirements": None, "stages": stages,
            "stage_aliases": [a for a in aliases if a["stage"] in names],
            "source_file": job["source_file"], "source_id": job["source_id"]}
    return data, ["The source data has no role requirements (audit P02), so 'requirements' is null. "
                  "Do not invent any. Rankings use interview feedback and stage progress only."]


@service
def list_candidates_for_job(con, job_id, status=None):
    job = require_job(con, job_id)
    if status is not None:
        status = need_text(status, "status").lower()
        if status not in APP_STATUSES:
            raise ServiceError("invalid_status", f"Unknown status '{status}'.", valid_values=APP_STATUSES)
    sql = ("SELECT a.*, c.name FROM applications a JOIN candidates c ON c.id = a.candidate_id "
           "WHERE a.job_id_effective = ?" + (" AND a.status = ?" if status else "") + " ORDER BY a.id")
    apps = rows(con, sql, job["id"], *([status] if status else []))
    order = {s: p for p, s in job_stages(con, job["id"])}
    out, notes = [], []
    for a in apps:
        conflict = stage_conflict(a)
        item = {"application_id": a["id"], "candidate_id": a["candidate_id"], "name": a["name"],
                "status": a["status"], "current_stage": effective_stage(a), "stage_position": order.get(effective_stage(a)),
                "applied_at": a["applied_at"], "rejected_at": a["rejected_at"],
                "rejection_reason": a["rejection_reason"], "stage_conflict": conflict,
                "source_file": a["source_file"], "source_id": a["source_id"]}
        if conflict:
            item["stage_in_applications_json"] = a["current_stage_source"]
            notes.append(f"{a['id']}: applications.json says '{a['current_stage_source']}', the stage "
                         f"events (end of the stage chain) say '{a['current_stage_from_events']}'. The events value is shown.")
        if a["job_id_source"] != a["job_id_effective"]:
            item["job_id_in_source"] = a["job_id_source"]
            notes.append(f"{a['id']}: source job_id is '{a['job_id_source']}' but the job title and stages match "
                         f"'{a['job_id_effective']}' (audit P06). Listed under {a['job_id_effective']}.")
        out.append(item)
    # applications of this job whose source job id points elsewhere are already in `apps` (effective id)
    return {"job_id": job["id"], "title": job["title"], "status_filter": status, "count": len(out),
            "applications": out}, notes
