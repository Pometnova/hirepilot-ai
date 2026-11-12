"""Expected facts for the eval set, computed ONLY from data/raw/ (json, csv, eml).

It does NOT read data/hirepilot.db and does NOT import backend.services. That is the point: it is a second,
independent calculation, so a bug in the services cannot hide itself. It only reads constants from backend.config
(reference date, weights, the 2/3-day rules, staff domain).

    .venv/bin/python evals/build_expected.py --handcheck     # facts + raw file/record ids for the 5 hand-checked questions
    .venv/bin/python evals/build_expected.py --all           # every fact, as JSON
"""
import csv
import email
import email.policy
import json
import re
import sys
from datetime import date, datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import config  # noqa: E402  (constants only)

RAW = Path(config.RAW_DIR)
REF = config.REFERENCE_DATE
ALIAS = {"Phone Screen": "Recruiter Call"}          # audit: same stage, two names
JOB_OVERRIDE = {"a-113": "j-backend"}               # audit P06 (author decision): a-113 is a backend application
SCORE = re.compile(r"([A-Za-z][A-Za-z ]*?):\s*(\d+(?:\.\d+)?)/(\d+)")


def _load():
    jobs = {j["id"]: j for j in json.loads((RAW / "jobs.json").read_text())}
    apps = json.loads((RAW / "applications.json").read_text())
    cands = {c["id"]: c for c in json.loads((RAW / "candidates.json").read_text())}
    cards = json.loads((RAW / "scorecards.json").read_text())
    events = {}
    for r in csv.DictReader((RAW / "stage_events.csv").open()):
        events.setdefault(r["application_id"], []).append((ALIAS.get(r["from_stage"], r["from_stage"]),
                                                           ALIAS.get(r["to_stage"], r["to_stage"])))
    for a in apps:
        a["job"] = JOB_OVERRIDE.get(a["id"], a["job_id"])
    return jobs, apps, cands, cards, events


def _chain(pairs):
    """Walk the from->to chain from its start to its end. Straight line only (checked by a test)."""
    step = dict(pairs)
    cur = (set(step) - set(step.values())).pop()
    path = [cur]
    while cur in step:
        cur = step[cur]
        path.append(cur)
    return path


def funnel(job_id, jobs, apps, events):
    """Each application counts once per stage on its path; its stage = the end of its event chain."""
    stages = jobs[job_id]["stages"]
    rows = {s: {"entered": 0, "moved_on": 0, "rejected": 0, "withdrew": 0, "hired": 0, "still_there": 0,
                "entered_ids": [], "rejected_ids": []} for s in stages}
    for a in (x for x in apps if x["job"] == job_id):
        end = _chain(events[a["id"]])[-1] if a["id"] in events else a["current_stage"]
        path = {stages[0], end} | {s for p in events.get(a["id"], []) for s in p}
        for s in path:
            if stages.index(s) <= stages.index(end):
                rows[s]["entered"] += 1
                rows[s]["entered_ids"].append(a["id"])
                if s != end:
                    rows[s]["moved_on"] += 1
        key = {"rejected": "rejected", "withdrawn": "withdrew", "hired": "hired", "active": "still_there"}[a["status"]]
        rows[end][key] += 1
        if a["status"] == "rejected":
            rows[end]["rejected_ids"].append(a["id"])
    for r in rows.values():
        r["entered_ids"].sort()
    return rows


def ranking(job_id, jobs, apps, cands, cards, events):
    stages = jobs[job_id]["stages"]
    ranked, not_scored = [], []
    for a in (x for x in apps if x["job"] == job_id and x["status"] == "active"):
        path = _chain(events[a["id"]]) if a["id"] in events else [a["current_stage"]]
        end = path[-1]
        per_interview, used = {}, []
        for c in cards:
            if c["application_id"] != a["id"] or not (c.get("text") or "").strip() or not c.get("submitted_at"):
                continue
            sc = {m[0].strip().lower(): float(m[1]) / int(m[2]) for m in SCORE.findall(c["text"])}
            if not sc:
                continue
            value = sc["overall"] if "overall" in sc else sum(sc.values()) / len(sc)
            per_interview.setdefault(c["interview"], []).append(value)
            used.append({"scorecard": c["id"], "interview": c["interview"],
                         "scores_in_text": ", ".join(f"{m[0].strip()} {m[1]}/{m[2]}" for m in SCORE.findall(c["text"])),
                         "card_score": round(value, 4)})
        progress = stages.index(end) / (len(stages) - 1)
        item = {"application": a["id"], "candidate": a["candidate_id"], "name": cands[a["candidate_id"]]["name"],
                "stage": end, "stage_path": path, "progress": round(progress, 4), "cards": used}
        if per_interview:
            fb = sum(sum(v) / len(v) for v in per_interview.values()) / len(per_interview)
            item["feedback"] = round(fb, 4)
            item["score"] = round(100 * (config.RANK_WEIGHT_FEEDBACK * fb + config.RANK_WEIGHT_PROGRESS * progress), 2)
            ranked.append(item)
        else:
            not_scored.append(item)
    ranked.sort(key=lambda r: (-r["score"], r["application"]))
    return {"ranked": ranked, "not_scored": not_scored}


def tasks(apps, cands, cards, events):
    """Open tasks with owner, due date, state and the raw record each fact comes from."""
    app_by = {a["id"]: a for a in apps}
    out = []

    def add(task_id, owner, due, source, how):
        state = ("pending (no due date in the data)" if due is None else "overdue" if due < REF
                 else "due_today" if due == REF else "pending")
        out.append({"task_id": task_id, "owner": owner, "due": due.isoformat() if due else None,
                    "state": state, "source": source, "how": how})

    for a in apps:
        if a.get("offer_deadline") and a["status"] == "active":
            add(f"offer_deadline:{a['id']}", cands[a["candidate_id"]]["name"], date.fromisoformat(a["offer_deadline"]),
                f"applications.json {a['id']}", f"offer_deadline {a['offer_deadline']} (explicit date), status active")
    for c in cards:
        if not (c.get("text") or "").strip() and app_by[c["application_id"]]["status"] == "active":
            at = datetime.fromisoformat(c["interview_at"]).date()
            due = at + timedelta(days=config.SCORECARD_OVERDUE_DAYS)
            add(f"scorecard_pending:{c['id']}", cands[app_by[c["application_id"]]["candidate_id"]]["name"], due,
                f"scorecards.json {c['id']} (application {c['application_id']})",
                f"empty text, interview_at {c['interview_at']} + {config.SCORECARD_OVERDUE_DAYS} days (our assumption)")
    for a in apps:
        first_stage = json.loads((RAW / "jobs.json").read_text())
        first_stage = {j["id"]: j["stages"][0] for j in first_stage}[a["job"]]
        if a["status"] == "active" and a["id"] not in events and a["current_stage"] == first_stage:
            add(f"application_unreviewed:{a['id']}", cands[a["candidate_id"]]["name"], None,
                f"applications.json {a['id']}",
                f"active, still at '{first_stage}', no rows in stage_events.csv, no due date in the data")
    # unanswered candidate emails: no later staff email in the same thread to that sender
    by_email = {e.lower(): c["name"] for c in cands.values() for e in c["emails"]}
    mails = []
    for p in sorted((RAW / "emails").glob("*.eml")):
        m = email.message_from_binary_file(p.open("rb"), policy=email.policy.default)
        frm = getaddresses([str(m["From"])])[0][1].lower()
        to = [x[1].lower() for x in getaddresses([str(m["To"]), str(m["Cc"] or "")]) if x[1]]
        mails.append({"file": p.name, "mid": str(m["Message-ID"]).strip("<>"), "name": getaddresses([str(m["From"])])[0][0],
                      "irt": str(m["In-Reply-To"]).strip("<>") if m["In-Reply-To"] else None,
                      "dt": parsedate_to_datetime(str(m["Date"])), "date_header": str(m["Date"]),
                      "staff": frm.endswith("@" + config.STAFF_DOMAIN), "from": frm, "to": to})
    by_id = {m["mid"]: m for m in mails}

    def root(m):
        seen = set()
        while m["irt"] in by_id and m["mid"] not in seen:
            seen.add(m["mid"])
            m = by_id[m["irt"]]
        return m["mid"]

    for m in mails:
        if m["staff"]:
            continue
        if not [s for s in mails if s["staff"] and s["dt"] > m["dt"] and root(s) == root(m) and m["from"] in s["to"]]:
            owner, link = by_email.get(m["from"]), "sender address is in candidates.json"
            if owner is None:        # candidate has no email on file: use the display name if exactly one candidate has it
                same = [c["name"] for c in cands.values() if c["name"] == m["name"]]
                owner, link = (same[0], "sender address not in candidates.json; linked by display name (unique)") \
                    if len(same) == 1 else (m["from"], "sender not linked to a candidate")
            add(f"email_unanswered:{m['file']}", owner,
                m["dt"].date() + timedelta(days=config.EMAIL_UNANSWERED_DAYS), f"emails/{m['file']}",
                f"Date header '{m['date_header']}' + {config.EMAIL_UNANSWERED_DAYS} days (our assumption); "
                f"no later staff reply in the thread; owner: {link}")
    order = {"overdue": 0, "due_today": 1, "pending": 2}
    out.sort(key=lambda t: (order.get(t["state"], 3), t["due"] or "9999", t["task_id"]))
    return out


def people_named(name, apps, cands, jobs):
    """Every candidate record with this name, with its applications (for 'tell me about X' questions)."""
    out = []
    for c in cands.values():
        if c["name"] == name:
            out.append({"candidate": c["id"], "emails": c["emails"], "phones": c["phones"], "location": c["location"],
                        "applications": [{"application": a["id"], "job": jobs[a["job"]]["title"], "status": a["status"],
                                          "stage": a["current_stage"], "rejected_at": a["rejected_at"],
                                          "rejection_reason": a["rejection_reason"], "offer_deadline": a["offer_deadline"]}
                                         for a in apps if a["candidate_id"] == c["id"]]})
    return out


def build():
    jobs, apps, cands, cards, events = _load()
    return {
        "reference_date": REF.isoformat(),
        "jobs": {j: {"title": v["title"], "stages": v["stages"]} for j, v in jobs.items()},
        "funnel": {j: funnel(j, jobs, apps, events) for j in jobs},
        "ranking": {j: ranking(j, jobs, apps, cands, cards, events) for j in jobs},
        "tasks": tasks(apps, cands, cards, events),
        "candidate_names": sorted({c["name"] for c in cands.values()}),
        "people": {n: people_named(n, apps, cands, jobs) for n in ("Jonah Whitfield", "Maya Chen", "Ravi Subramanian",
                                                                   "Rafael Mendoza")},
    }


def print_handcheck(x):
    """The facts behind the 5 hand-checked questions, each with the raw file and record id to open."""
    jobs, apps, cands, cards, events = _load()
    app_by = {a["id"]: a for a in apps}
    p = print
    p(f"HAND-CHECK FACTS (reference date {x['reference_date']}). Open the raw file named on each line and compare.\n")

    p("=== Q1  Top 3 for Senior Backend Engineer (ranking = 70% feedback + 30% progress)")
    r = x["ranking"]["j-backend"]
    for i, it in enumerate(r["ranked"][:5], 1):
        mark = "TOP 3" if i <= 3 else "(rank %d, not in top 3)" % i
        p(f"  #{i} {it['name']} -> score {it['score']}  {mark}")
        p(f"      application: applications.json {it['application']} (candidate {it['candidate']}, status active)")
        p(f"      stage: end of the chain in stage_events.csv rows for {it['application']}: {' > '.join(it['stage_path'])}"
          f"  => '{it['stage']}'  progress {it['progress']}")
        for c in it["cards"]:
            p(f"      scorecards.json {c['scorecard']}  [{c['interview']}]  text says: {c['scores_in_text']}  -> card score {c['card_score']}")
        p(f"      feedback = mean over interviews = {it['feedback']};  score = 100*(0.70*{it['feedback']} + 0.30*{it['progress']}) = {it['score']}")
    p("  Not scored (no submitted scorecard; NOT negative):")
    for it in r["not_scored"]:
        p(f"      {it['name']}: applications.json {it['application']}, stage {it['stage']}; no card with text in scorecards.json")

    p("\n=== Q2  Funnel for Senior Backend Engineer")
    p("  entered = applications whose path reaches the stage; path = first stage + stages in stage_events.csv + end stage")
    for stage, v in x["funnel"]["j-backend"].items():
        p(f"  {stage:<19} entered {v['entered']:>2}  moved_on {v['moved_on']:>2}  rejected {v['rejected']}  "
          f"withdrew {v['withdrew']}  hired {v['hired']}  still_there {v['still_there']}")
        p(f"      entered ids (applications.json): {', '.join(v['entered_ids'])}")
        if v["rejected_ids"]:
            p(f"      rejected here (applications.json status 'rejected'): {', '.join(v['rejected_ids'])}")
    a116 = _chain(events["a-116"])
    p(f"  Key number: Take-Home = 11 entered, 1 rejected. a-116: applications.json current_stage 'Take-Home', status rejected;"
      f"\n      stage_events.csv chain for a-116 = {' > '.join(a116)}")

    p("\n=== Q3  Pending or overdue tasks (11 open tasks)")
    for t in x["tasks"]:
        p(f"  {t['task_id']:<48} {t['owner']:<18} {str(t['due']):<10} {t['state']}")
        p(f"      source: {t['source']}; {t['how']}")
    counts = {}
    for t in x["tasks"]:
        k = t["state"].split(" ")[0]
        counts[k] = counts.get(k, 0) + 1
    p(f"  Counts: {counts}")

    p("\n=== Q8  Tasks due today (reference date 2026-10-15)")
    for t in x["tasks"]:
        if t["due"] == REF.isoformat():
            p(f"  {t['task_id']}  {t['owner']}  due {t['due']}\n      source: {t['source']}; {t['how']}")
    p(f"  Check that no other task has due date {REF}: " + str([t["task_id"] for t in x["tasks"] if t["due"] == REF.isoformat()]))

    p("\n=== Q9  Is application a-120 overdue?  Expected: NO. It has no due date, so it is pending (never overdue).")
    a = app_by["a-120"]
    p(f"  applications.json a-120: candidate {a['candidate_id']} ({cands[a['candidate_id']]['name']}), status {a['status']}, "
      f"current_stage '{a['current_stage']}', applied_at {a['applied_at']}, offer_deadline {a['offer_deadline']}")
    p(f"  stage_events.csv rows for a-120: {len(events.get('a-120', []))} (none = never reviewed)")
    p(f"  scorecards.json cards for a-120: {len([c for c in cards if c['application_id'] == 'a-120'])}")


if __name__ == "__main__":
    facts = build()
    if "--all" in sys.argv:
        print(json.dumps(facts, indent=1, default=str))
    else:
        print_handcheck(facts)
