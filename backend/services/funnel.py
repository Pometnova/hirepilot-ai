"""Hiring funnel for one job: where are candidates lost?

Per stage (stage names after alias mapping, e.g. Phone Screen -> Recruiter Call):
  Each application has ONE path: the first stage, every stage with an event into or out of it, and the
  stage it ends in (current stage from the sorted events). Stages AFTER the end stage are dropped, so an
  application is never counted beyond where its sorted events say it is.
  entered        applications whose path contains the stage
  moved_on       entered, and the stage is not the end stage
  rejected / withdrew / hired / still_in_stage
                 final status of the applications whose end stage is this stage
So for every stage: entered = moved_on + rejected + withdrew + hired + still_in_stage (tested).
The stage of an application is the end of its stage chain (from -> to), not the last event by date (audit P05).
Conflicts and chain-resolved applications are counted at that stage and listed in notes.
"""
from statistics import median

from .common import effective_stage, job_stages, require_job, rows, service, stage_conflict, to_dt


def _rate(a, b):
    return round(a / b, 3) if b else None


@service
def get_funnel(con, job_id):
    job = require_job(con, job_id)
    jid = job["id"]
    stages = [s for _, s in job_stages(con, jid)]
    first = stages[0]
    apps = rows(con, "SELECT * FROM applications WHERE job_id_effective = ? ORDER BY id", jid)
    ids = [a["id"] for a in apps]
    ph = ",".join("?" * len(ids)) or "NULL"
    events = rows(con, f"SELECT * FROM stage_events WHERE application_id IN ({ph}) ORDER BY id", *ids)

    pos = {st: i for i, st in enumerate(stages)}
    entered = {s: set() for s in stages}
    moved = {s: set() for s in stages}
    final = {s: {"rejected": [], "withdrawn": [], "hired": [], "active": []} for s in stages}
    by_app = {}
    for e in events:
        by_app.setdefault(e["application_id"], []).append(e)
    notes, dropped = [], {}                            # dropped: app -> stages its events reach beyond its end stage
    for a in apps:
        eff = effective_stage(a)
        if eff not in pos:
            notes.append(f"{a['id']}: stage '{eff}' is not in the stage list of {jid}; not counted in any stage.")
            continue
        path = {first, eff}
        for e in by_app.get(a["id"], []):
            for st in (e["from_stage"], e["to_stage"]):
                if st in pos:
                    path.add(st)
                elif st:
                    notes.append(f"Event line {e['id']}: stage '{st}' is not in the stage list of {jid}.")
        beyond = sorted((st for st in path if pos[st] > pos[eff]), key=pos.get)
        if beyond:
            dropped[a["id"]] = beyond
        for st in path:
            if pos[st] <= pos[eff]:
                entered[st].add(a["id"])
                if st != eff:
                    moved[st].add(a["id"])
        final[eff][a["status"]].append(a)

    # days in a stage = time from entering it to leaving it (completed stays only)
    t_in, t_out = {}, {}
    for a in apps:
        t_in[(a["id"], first)] = a["applied_at"]
    for e in events:
        if e["changed_at"]:
            k_in, k_out = (e["application_id"], e["to_stage"]), (e["application_id"], e["from_stage"])
            t_in[k_in] = min(t_in.get(k_in) or e["changed_at"], e["changed_at"]) if k_in[1] != first else t_in.get(k_in)
            t_out[k_out] = min(t_out.get(k_out) or e["changed_at"], e["changed_at"])
    dwell, skipped = {s: [] for s in stages}, {s: 0 for s in stages}
    for (app, stage), out_at in t_out.items():
        if stage not in dwell or app not in moved[stage]:
            continue
        start = t_in.get((app, stage))
        days = (to_dt(out_at) - to_dt(start)).total_seconds() / 86400 if start else None
        if days is None or days < 0:
            skipped[stage] += 1
        else:
            dwell[stage].append(days)
    for e in events:                                   # left-stage events without a date: count them as skipped
        if not e["changed_at"] and e["from_stage"] in skipped and e["application_id"] in moved[e["from_stage"]]:
            skipped[e["from_stage"]] += 1

    out = []
    for pos, s in enumerate(stages, 1):
        f = final[s]
        n_in, n_moved = len(entered[s]), len(moved[s])
        resolved = n_moved + len(f["rejected"]) + len(f["withdrawn"]) + len(f["hired"])
        reasons = {}
        for a in f["rejected"]:
            r = a["rejection_reason"] or "not recorded"
            reasons[r] = reasons.get(r, 0) + 1
        out.append({"position": pos, "stage": s, "entered": n_in, "moved_on": n_moved,
                    "rejected": len(f["rejected"]), "withdrew": len(f["withdrawn"]), "hired": len(f["hired"]),
                    "still_in_stage": len(f["active"]),
                    "is_final_stage": pos == len(stages),
                    "conversion_rate": None if pos == len(stages) else _rate(n_moved, n_in),
                    "resolved_conversion_rate": None if pos == len(stages) else _rate(n_moved, resolved),
                    "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
                    "median_days_in_stage": round(median(dwell[s]), 1) if dwell[s] else None,
                    "median_days_n": len(dwell[s]), "dwell_excluded_missing_or_negative_dates": skipped[s],
                    "rejected_application_ids": [a["id"] for a in f["rejected"]],
                    "source_file": "stage_events.csv + applications.json", "source_id": jid})

    for a in apps:
        if stage_conflict(a):
            eff = effective_stage(a)
            msg = (f"{a['id']}: applications.json says '{a['current_stage_source']}', the stage events (end of the "
                   f"stage chain) say '{a['current_stage_from_events']}'. Counted at '{eff}'. Both values are stored (audit P05).")
            if a["id"] in dropped:
                msg += (f" Its events also reach {', '.join(repr(x) for x in dropped[a['id']])}, which is after that stage; "
                        "the event dates and the source disagree (see audit P07), so that stage is NOT counted for it.")
            notes.append(msg)
        if a["job_id_source"] != a["job_id_effective"]:
            notes.append(f"{a['id']}: source job_id is '{a['job_id_source']}', counted in {jid} (audit P06).")
    for r in rows(con, "SELECT source_id, value_source, value_used FROM data_issues WHERE issue_type = 'stage_resolved_by_chain'"):
        if r["source_id"] in ids:
            notes.append(f"{r['source_id']}: the event dates put it at '{r['value_source']}', but the event chain ends at "
                         f"'{r['value_used']}' (one event has a date before the application, audit P07). Counted at "
                         f"'{r['value_used']}', which also matches applications.json (audit P05, data_issues stage_resolved_by_chain).")
    no_ev = [a["id"] for a in apps if a["current_stage_from_events"] is None]
    if no_ev:
        notes.append(f"{len(no_ev)} application(s) have no stage events ({', '.join(no_ev)}); they are counted in the "
                     "first stage and the stage given in applications.json.")
    n_alias = sum(1 for e in events if e["from_stage_raw"] != e["from_stage"] or e["to_stage_raw"] != e["to_stage"])
    if n_alias:
        notes.append(f"{n_alias} event(s) used an old stage name ('Phone Screen'); counted as 'Recruiter Call'.")
    notes.append("median_days_in_stage uses completed stays only (entered and left). Samples are small; see median_days_n.")
    notes.append("conversion_rate = moved_on / entered. resolved_conversion_rate = moved_on / (moved_on + rejected + "
                 "withdrew + hired), which ignores applications still waiting.")
    totals = {}
    for a in apps:
        totals[a["status"]] = totals.get(a["status"], 0) + 1
    return {"job_id": jid, "title": job["title"], "opened_at": job["opened_at"], "applications": len(apps),
            "applications_by_status": totals, "stages": out}, notes
