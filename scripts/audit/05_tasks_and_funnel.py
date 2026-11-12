"""Step 11: where can Q3 'tasks' come from, and what does the data say for Q2.

There is NO tasks file. Candidate task sources (all relative to REFERENCE_DATE 2026-10-15):

 A. offer_deadline (applications.json)  explicit date          -> strongest evidence
 B. unsubmitted scorecards              explicit interview_at, no due date -> threshold inferred
 C. unanswered inbound emails           explicit timestamps, no due date   -> threshold inferred
 D. follow-ups in activity.json         free text, no structure            -> LLM reading only
 E. stalled applications                derived from stage_events          -> threshold inferred

Thresholds for B and C are NOT in the data. The author decided them (see common.py):
scorecard overdue after 2 days, email unanswered after 3 days. The observed lags are still
printed so the choice can be reviewed. E (stalled) has no threshold; it only lists dwell time.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections as C, email, email.policy, os, statistics as st
from email.utils import getaddresses, parsedate_to_datetime
from common import *

REF = REFERENCE_DATE
apps = {a["id"]: a for a in load_json("applications")}
cards = load_json("scorecards"); jobs = {j["id"]: j for j in load_json("jobs")}
ev = load_events()
ev["dt"] = ev.changed_at.map(parse_dt)
ALIAS = {"Phone Screen": "Recruiter Call"}  # inferred: only used in the CSM job's events
norm_stage = lambda s: ALIAS.get(s, s)
days = lambda a, b: (a - b).total_seconds() / 86400


print("## A. OFFER DEADLINES")
for a in apps.values():
    if a["offer_deadline"]:
        d = (parse_dt(a["offer_deadline"]) - REF).days
        rule = ("CLOSED (hired)" if a["status"] == "hired" else
                "OVERDUE %dd" % -d if d < 0 and a["status"] == "active" else
                "PENDING, due in %dd" % d if d >= 0 and a["status"] == "active" else
                "CONFLICT: status=%s but has a deadline (%+dd)" % (a["status"], d))
        print(f"  {a['id']} {a['candidate_id']} status={a['status']} stage={a['current_stage']} deadline={a['offer_deadline']} -> {rule}")
print("  apps at Offer stage without a deadline:", [a["id"] for a in apps.values() if a["current_stage"] == "Offer" and not a["offer_deadline"]])

print("\n## B. SCORECARDS: submit lag (hours from interview_at to submitted_at)")
lags = sorted((parse_dt(s["submitted_at"]) - parse_dt(s["interview_at"])).total_seconds() / 3600 for s in cards if s["submitted_at"])
q = lambda p: lags[min(len(lags) - 1, int(p * len(lags)))]
print(f"  n={len(lags)} min={lags[0]:.1f}h median={st.median(lags):.1f}h p90={q(.9):.1f}h p95={q(.95):.1f}h max={lags[-1]:.1f}h")
print("  submitted > 24h after interview:", sum(l > 24 for l in lags), "| > 48h:", sum(l > 48 for l in lags))
print("  UNSUBMITTED (no text, no submitted_at):")
for s in cards:
    if not s["submitted_at"]:
        age = days(REF, parse_dt(s["interview_at"]))
        flag = (f"OVERDUE (> {SCORECARD_OVERDUE_DAYS} days)" if age > SCORECARD_OVERDUE_DAYS
                else f"pending (<= {SCORECARD_OVERDUE_DAYS} days)")
        a = apps[s["application_id"]]
        print(f"   {s['id']} {s['application_id']} {a['candidate_id']} {s['interview']} held {s['interview_at'][:16]} age={age:.1f}d by {s['interviewer']} -> {flag}")
print("  interviews already held but app is rejected/withdrawn and card unsubmitted:",
      [s["id"] for s in cards if not s["submitted_at"] and apps[s["application_id"]]["status"] != "active"])

print("\n## C. EMAILS: staff reply latency and unanswered inbound")
rows = []
for f in sorted(os.listdir(RAW / "emails")):
    m = email.message_from_binary_file(open(RAW / "emails" / f, "rb"), policy=email.policy.default)
    frm = getaddresses([str(m["From"])])[0][1].lower()
    rows.append(dict(f=f, mid=str(m["Message-ID"]).strip("<>").split("@")[0], irt=str(m["In-Reply-To"] or "").strip("<>").split("@")[0],
                     out=frm.endswith("@" + STAFF_DOMAIN), dt=parsedate_to_datetime(str(m["Date"])).replace(tzinfo=None),
                     subj=str(m["Subject"]), party=frm))
by = {r["mid"]: r for r in rows}
lat = []
replied = set()
for r in rows:
    if r["out"] and r["irt"] in by and not by[r["irt"]]["out"]:
        lat.append(days(r["dt"], by[r["irt"]]["dt"]) * 24); replied.add(r["irt"])
lat.sort()
print(f"  staff reply latency to inbound (h): n={len(lat)} median={st.median(lat):.1f} p90={lat[int(.9*len(lat))]:.1f} max={lat[-1]:.1f}")
un = [r for r in rows if not r["out"] and r["mid"] not in replied]
print("  inbound emails with no direct staff reply:", len(un))
for r in sorted(un, key=lambda r: r["dt"]):
    later_out = [x for x in rows if x["out"] and x["dt"] > r["dt"] and x["subj"].replace("Re: ", "") == r["subj"].replace("Re: ", "")]
    age = days(REF, r["dt"])
    state = ("probably answered (later staff message, same subject)" if later_out else
             f"UNANSWERED (> {EMAIL_UNANSWERED_DAYS} days)" if age > EMAIL_UNANSWERED_DAYS else
             f"pending (<= {EMAIL_UNANSWERED_DAYS} days)")
    print(f"   {r['f']} {r['party']} {r['dt']:%Y-%m-%d} age={age:.1f}d -> {state}")

print("\n## D. ACTIVITY NOTES (free text; no due date field)")
acts = load_json("activity")
print("  notes:", len(acts), "| with a date-like phrase (e.g. 'Oct 12', '10/13', 'Tuesday', 'July 1'):",
      sum(bool(__import__('re').search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d|\d{1,2}/\d{1,2}|monday|tuesday|wednesday|thursday|friday", x["body"])) for x in acts))
print("  note dates after reference date:", [x for x in acts if x["created_at"] > "2026-10-15"])

print("\n## E. STAGE DWELL (days) using sorted events, stages normalized (Phone Screen -> Recruiter Call)")
def history(a):
    e = ev[ev.application_id == a["id"]].dropna(subset=["dt"]).sort_values("dt")
    return e
dwell = C.defaultdict(list); cur = []
for a in apps.values():
    e = history(a)
    t0 = parse_dt(a["applied_at"]); stage = jobs[a["job_id"]]["stages"][0]
    for r in e.itertuples():
        if r.dt < t0: continue  # a-116 line 2 is dated before applied_at: skipped here, flagged elsewhere
        dwell[norm_stage(r.from_stage)].append(days(r.dt, t0)); t0 = r.dt; stage = norm_stage(r.to_stage)
    if a["status"] == "active":
        cur.append((days(REF, t0), a["id"], a["candidate_id"], a["job_id"], norm_stage(a["current_stage"]), stage))
for s, v in dwell.items():
    print(f"  left {s:18} n={len(v):2} median={st.median(v):5.1f}d max={max(v):5.1f}d")
print("  ACTIVE apps, days since last recorded change (top 10):")
for d, aid_, c, j, s, last in sorted(cur, reverse=True)[:10]:
    print(f"   {aid_} {c} {j} app_stage={s} last_event_stage={last} {d:.0f}d")

print("\n## Q2 EVIDENCE: where do applications end? (status x current_stage, per job; Phone Screen normalized)")
for j in jobs:
    t = C.Counter((a["status"], norm_stage(a["current_stage"])) for a in apps.values() if a["job_id"] == j)
    print(" ", j, "opened", jobs[j]["opened_at"], "open for", (REF - parse_dt(jobs[j]["opened_at"])).days, "days")
    for stage in jobs[j]["stages"]:
        print(f"    {stage:20}", {k[0]: v for k, v in t.items() if k[1] == stage})
print("  a-113 (job_id=j-designer but backend title/stages) counted above under j-designer.")
print("  withdrawals mentioning the wait/feedback delay:", [a["id"] for a in apps.values() if a["status"] == "withdrawn" and __import__('re').search(r"(?i)wait|frustrat", a["rejection_reason"] or "")])
print("  Senior Backend Engineer: open", (REF - parse_dt(jobs["j-backend"]["opened_at"])).days, "days =", round((REF - parse_dt(jobs["j-backend"]["opened_at"])).days / 30.44, 1), "months")
