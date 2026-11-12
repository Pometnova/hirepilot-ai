"""Cross-check: do emails contradict applications.json status? Also: is stage_events.csv in date order?

Simple keyword rules (limited: it can miss contradictions phrased differently).
 - staff 'not moving forward' style email, application still 'active'
 - candidate 'withdraw / accepted another offer' email, application not 'withdrawn'
 - rejection email date differs from rejected_at by more than 3 days
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import email, email.policy, os, re
from email.utils import getaddresses, parsedate_to_datetime
from common import *

apps = load_json("applications"); cn = {c["id"]: c for c in load_json("candidates")}
byc = {}
for a in apps:
    byc.setdefault(a["candidate_id"], []).append(a)
em2c = {norm_email(e): c["id"] for c in cn.values() for e in c["emails"]}
em2c.update({"sana.qureshi@example.org": "c-309", "hcastellano.home@example.net": "c-306"})  # found by 04_emails.py (cv_email / exact_name)
rej = re.compile(r"(?i)won't be moving forward|will not be moving forward|not (be )?(moving|proceeding)|decided to (move forward with|go with) other")
wd = re.compile(r"(?i)withdraw|accepted (an|another) offer|no longer (interested|available)")
hits = 0
for f in sorted(os.listdir(RAW / "emails")):
    m = email.message_from_binary_file(open(RAW / "emails" / f, "rb"), policy=email.policy.default)
    frm = getaddresses([str(m["From"])])[0][1].lower(); out = frm.endswith(STAFF_DOMAIN)
    to = [x[1] for x in getaddresses([str(m["To"])]) if x[1]]
    c = em2c.get(norm_email(to[0] if out else frm))
    if not c:
        continue
    b = " ".join(m.get_body().get_content().split())
    d = parsedate_to_datetime(str(m["Date"])).replace(tzinfo=None)
    for a in byc[c]:
        if out and rej.search(b) and a["status"] == "active":
            print("staff rejection-like email, app active:", f, a["id"]); hits += 1
        if not out and wd.search(b) and a["status"] != "withdrawn":
            print("candidate withdraw-like email, status", a["status"], ":", f, a["id"]); hits += 1
        if out and rej.search(b) and a["status"] == "rejected" and a["rejected_at"] and abs((d - parse_dt(a["rejected_at"])).days) > 3:
            print("rejection email vs rejected_at differ >3 days:", f, a["id"]); hits += 1
print("contradictions found:", hits)

ev = load_events()
ev["dt"] = ev.changed_at.map(parse_dt)
ok = ev.dt.dropna().is_monotonic_increasing
print("stage_events.csv rows in date order:", ok, "| rows in application_id order:", ev.application_id.is_monotonic_increasing)
