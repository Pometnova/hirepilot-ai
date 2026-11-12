"""Step 7: dates and time zones across all files."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections as C, os, re, email, email.policy
from email.utils import parsedate_to_datetime
from common import *

apps = load_json("applications"); cards = load_json("scorecards")
acts = load_json("activity"); cands = load_json("candidates"); jobs = load_json("jobs")
ev = load_events()
aid = {a["id"]: a for a in apps}
REF = REFERENCE_DATE

print("## FORMAT SHAPES (digits -> 9)")
shape = lambda s: re.sub(r"\d", "9", str(s))
for f, rows, k in [("jobs.opened_at", jobs, "opened_at"), ("candidates.created_at", cands, "created_at"),
                   ("applications.applied_at", apps, "applied_at"), ("applications.rejected_at", apps, "rejected_at"),
                   ("applications.offer_deadline", apps, "offer_deadline"), ("scorecards.interview_at", cards, "interview_at"),
                   ("scorecards.submitted_at", cards, "submitted_at"), ("activity.created_at", acts, "created_at")]:
    print(f, dict(C.Counter(shape(r[k]) for r in rows)))
print("stage_events.changed_at", dict(C.Counter(shape(x) for x in ev.changed_at)))
print("any timezone marker (Z/+hh:mm) in JSON/CSV dates:",
      any(re.search(r"(Z|[+-]\d\d:?\d\d)$", str(r[k])) for rows, k in [(apps, "applied_at"), (cards, "interview_at"), (acts, "created_at")] for r in rows) or
      any(re.search(r"(Z|[+-]\d\d:\d\d)$", x) for x in ev.changed_at))

print("\n## NON-ISO event dates (csv line, raw, DD/MM reading, MM/DD reading, neighbours in same app)")
ev["dt_dm"] = ev.changed_at.map(lambda s: parse_dt(s, True))
ev["dt_md"] = ev.changed_at.map(lambda s: parse_dt(s, False))
ev["dt_rule"] = ev.changed_at.map(parse_dt)  # AM/PM -> MM/DD, 24h -> DD/MM
iso = ev.changed_at.str.match(r"^\d{4}-")
verdict = {}
for r in ev[~iso & (ev.changed_at != "")].itertuples():
    same = ev[(ev.application_id == r.application_id) & (ev.row != r.row)]
    before = [x for x in same.dt_dm if x and x < r.dt_dm]; after = [x for x in same.dt_dm if x and x > r.dt_dm]
    ambiguous = int(r.changed_at.split("/")[0]) <= 12
    a = aid[r.application_id]; ap = parse_dt(a["applied_at"])
    def fits(d):
        # event must not be before applied_at or after the reference date; chain order via from/to stage
        return d is not None and d >= ap and d <= REF
    print(r.row, r.application_id, repr(r.changed_at), "DD/MM->", r.dt_dm, "| MM/DD->", r.dt_md,
          "| ambiguous" if ambiguous else "| unambiguous", "| DM fits", fits(r.dt_dm), "| MD fits", fits(r.dt_md))
print("missing changed_at:", [(r.row, r.application_id, r.from_stage, r.to_stage) for r in ev.itertuples() if r.changed_at == ""])

print("\n## ORDER CHECK using the AM/PM rule (events earlier than applied_at / after reference date)")
for r in ev.itertuples():
    a = aid[r.application_id]
    if r.dt_rule and r.dt_rule < parse_dt(a["applied_at"]):
        print("before applied_at:", r.row, r.application_id, r.changed_at, "applied", a["applied_at"])
    if r.dt_rule and r.dt_rule > REF:
        print("after reference date:", r.row, r.application_id, r.changed_at)

print("\n## DATES AFTER REFERENCE DATE", REF.date())
for name, rows, ks in [("applications", apps, ["applied_at", "rejected_at"]), ("scorecards", cards, ["interview_at", "submitted_at"]),
                       ("activity", acts, ["created_at"]), ("candidates", cands, ["created_at"])]:
    for r in rows:
        for k in ks:
            d = parse_dt(r.get(k))
            if d and d > REF:
                print(name, r.get("id", r.get("candidate_id")), k, r[k])
print("offer_deadlines vs reference date:", [(a["id"], a["offer_deadline"], (parse_dt(a["offer_deadline"]) - REF).days) for a in apps if a["offer_deadline"]])

print("\n## SCORECARD DATE LOGIC")
print("submitted_at before interview_at:", [(s["id"], s["interview_at"], s["submitted_at"]) for s in cards
      if s["submitted_at"] and parse_dt(s["submitted_at"]) < parse_dt(s["interview_at"])])
print("interview_at after reference date (future, not yet held):", [(s["id"], s["interview_at"]) for s in cards if parse_dt(s["interview_at"]) > REF])
print("rejected_at before applied_at:", [a["id"] for a in apps if a["rejected_at"] and parse_dt(a["rejected_at"]) < parse_dt(a["applied_at"])])

print("\n## EMAIL DATE HEADERS (UTC offsets)")
offs = C.Counter(); bad = []; out_of_range = []
D = RAW / "emails"
for f in sorted(os.listdir(D)):
    m = email.message_from_binary_file(open(D / f, "rb"), policy=email.policy.default)
    try:
        d = parsedate_to_datetime(str(m["Date"]))
    except Exception:
        bad.append(f); continue
    offs[str(d.utcoffset())] += 1
    local = d.replace(tzinfo=None)
    if local > REF:
        out_of_range.append((f, str(m["Date"])))
    # New York DST: -0400 from 2026-03-08 to 2026-11-01, else -0500
    exp = "-1 day, 20:00:00" if datetime(2026, 3, 8) <= local < datetime(2026, 11, 1) else "-1 day, 19:00:00"
    if str(d.utcoffset()) != exp:
        bad.append((f, str(m["Date"]), "offset not New York"))
print("offset counts:", dict(offs)); print("unparseable / non-NY offset:", bad); print("emails dated after reference date:", out_of_range)
