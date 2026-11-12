"""Step 2-6: counts, link integrity, duplicates, status/stage conflicts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections as C
from common import *

jobs = {j["id"]: j for j in load_json("jobs")}
cands = load_json("candidates")
apps = load_json("applications")
cards = load_json("scorecards")
acts = load_json("activity")
ev = load_events()
cid = {c["id"]: c for c in cands}
aid = {a["id"]: a for a in apps}

print("## COUNTS")
print(dict(jobs=len(jobs), candidates=len(cands), applications=len(apps),
           stage_events=len(ev), scorecards=len(cards), activity=len(acts)))
print("unique ids:", len(cid) == len(cands), len(aid) == len(apps),
      "scorecard ids unique:", len({s['id'] for s in cards}) == len(cards))

print("\n## LINKS")
print("apps -> missing candidate:", [a["id"] for a in apps if a["candidate_id"] not in cid])
print("apps -> missing job:", [a["id"] for a in apps if a["job_id"] not in jobs])
print("job_title != jobs.json title (app, job_id, title in app):",
      [(a["id"], a["job_id"], a["job_title"]) for a in apps
       if a["job_id"] in jobs and a["job_title"] != jobs[a["job_id"]]["title"]])
print("events -> missing app:", sorted({r.application_id for r in ev.itertuples() if r.application_id not in aid}))
print("scorecards -> missing app:", [s["id"] for s in cards if s["application_id"] not in aid])
print("activity -> missing candidate:", [(i, x["candidate_id"]) for i, x in enumerate(acts) if x["candidate_id"] not in cid])
print("candidates with no application:", [c["id"] for c in cands if c["id"] not in {a["candidate_id"] for a in apps}])
napps = C.Counter(a["candidate_id"] for a in apps)
print("candidates with >1 application:", {k: v for k, v in napps.items() if v > 1})
print("same candidate + same job twice:", [k for k, v in C.Counter((a["candidate_id"], a["job_id"]) for a in apps).items() if v > 1])
ev_apps = set(ev.application_id)
print("apps with no stage events:", [(a["id"], a["status"], a["current_stage"]) for a in apps if a["id"] not in ev_apps])
print("candidate ids by prefix:", C.Counter(c["id"][:3] for c in cands))

print("\n## DUPLICATE CANDIDATES (same person, two IDs?)")
for label, key in [("name", lambda c: [norm_name(c["name"])]),
                   ("phone", lambda c: [norm_phone(p) for p in c["phones"]]),
                   ("email(+tag stripped)", lambda c: [norm_email(e) for e in c["emails"]]),
                   ("cv filename", lambda c: [a["filename"] for a in c["attachments"]])]:
    g = C.defaultdict(set)
    for c in cands:
        for k in key(c):
            g[k].add(c["id"])
    print(f"shared {label}:", {k: sorted(v) for k, v in g.items() if len(v) > 1})
for x, y in [("c-105", "c-121"), ("c-110", "c-210")]:
    a, b = cid[x], cid[y]
    print(x, y, "-> phones", a["phones"], b["phones"], "| loc", a["location"], "/", b["location"],
          "| apps", [(q["id"], q["job_id"], q["status"]) for q in apps if q["candidate_id"] in (x, y)])
first = C.defaultdict(list)
for c in cands:
    first[c["name"].split()[0].lower()].append(c["id"] + ":" + c["name"])
print("same first name (near-name watch list):", {k: v for k, v in first.items() if len(v) > 1})

print("\n## STATUS / STAGE CONSISTENCY (applications.json)")
print("status:", dict(C.Counter(a["status"] for a in apps)))
print("current_stage not in the job's stage list:",
      [(a["id"], a["job_id"], a["current_stage"]) for a in apps if a["current_stage"] not in jobs[a["job_id"]]["stages"]])
print("rejected without rejected_at:", [a["id"] for a in apps if a["status"] == "rejected" and not a["rejected_at"]])
print("rejected without reason:", [a["id"] for a in apps if a["status"] == "rejected" and not a["rejection_reason"]])
print("rejected_at set on non-rejected:", [(a["id"], a["status"]) for a in apps if a["status"] != "rejected" and a["rejected_at"]])
print("reason set on non-rejected:", [(a["id"], a["status"]) for a in apps if a["status"] != "rejected" and a["rejection_reason"]])
print("withdrawn count / withdrawn reasons:", [(a["id"], a["rejected_at"], a["rejection_reason"]) for a in apps if a["status"] == "withdrawn"])
print("offer_deadline rows:", [(a["id"], a["status"], a["current_stage"], a["offer_deadline"]) for a in apps if a["offer_deadline"]])
print("at Offer stage:", [(a["id"], a["status"], a["offer_deadline"]) for a in apps if a["current_stage"] == "Offer"])
print("hired:", [(a["id"], a["current_stage"]) for a in apps if a["status"] == "hired"])
print("applied_at before candidate.created_at:",
      [(a["id"], a["applied_at"][:10], cid[a["candidate_id"]]["created_at"]) for a in apps
       if a["applied_at"][:10] < cid[a["candidate_id"]]["created_at"]])
print("applied_at before job opened_at:",
      [(a["id"], a["applied_at"][:10], jobs[a["job_id"]]["opened_at"]) for a in apps
       if a["applied_at"][:10] < jobs[a["job_id"]]["opened_at"]])

print("\n## STAGE EVENTS vs applications.json")
ev["dt"] = ev.changed_at.map(parse_dt)
print("event stage names not in ANY job:",
      dict(C.Counter(s for s in list(ev.from_stage) + list(ev.to_stage) if not any(s in j["stages"] for j in jobs.values()))))
print("event rows with empty changed_at (csv line):", list(ev[ev.changed_at == ""].row))
print("exact duplicate event rows:", ev[ev.duplicated(["application_id", "from_stage", "to_stage", "changed_at"], keep=False)][["row", "application_id"]].values.tolist())
conf = []; chain_gap = []; wrong_stage_name = []; order_issue = []
for a in apps:
    e = ev[ev.application_id == a["id"]].copy()
    if e.empty:
        continue
    e = e.sort_values(["dt", "row"], na_position="last")
    last = e.iloc[-1].to_stage
    if last != a["current_stage"]:
        conf.append((a["id"], a["status"], "app=" + a["current_stage"], "last_event=" + last))
    # chain: each from_stage should equal previous to_stage
    prev = None
    for r in e.itertuples():
        if prev is not None and r.from_stage != prev:
            chain_gap.append((a["id"], f"line {r.row}", f"expected from={prev}", f"got from={r.from_stage}"))
        prev = r.to_stage
    for r in e.itertuples():
        for s in (r.from_stage, r.to_stage):
            if s not in jobs[a["job_id"]]["stages"]:
                wrong_stage_name.append((a["id"], f"line {r.row}", s))
print("CONFLICT current_stage != last event:", conf)
print("chain gaps (from_stage != previous to_stage):", chain_gap)
print("event stage not in that job's stage list:", wrong_stage_name)
print("apps whose first event from_stage != first job stage:",
      [(a["id"]) for a in apps if not ev[ev.application_id == a["id"]].empty
       and ev[ev.application_id == a["id"]].sort_values(["dt", "row"]).iloc[0].from_stage != jobs[a["job_id"]]["stages"][0]])
print("apps not at first stage but no events:", [a["id"] for a in apps if a["id"] not in ev_apps and a["current_stage"] != jobs[a["job_id"]]["stages"][0]])
print("changed_by:", dict(C.Counter(ev.changed_by)))
print("events after rejected_at:",
      [(a["id"], r.row) for a in apps if a["rejected_at"] for r in ev[ev.application_id == a["id"]].itertuples()
       if r.dt and r.dt > parse_dt(a["rejected_at"])])
print("event before applied_at:",
      [(a["id"], r.row) for a in apps for r in ev[ev.application_id == a["id"]].itertuples()
       if r.dt and r.dt < parse_dt(a["applied_at"])])
