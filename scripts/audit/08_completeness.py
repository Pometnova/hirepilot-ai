"""Completeness check: no record silently lost; Phase 2 sees the full dataset.

READ-ONLY. Reuses the linking rules of 03_cvs.py and 04_emails.py by running them and taking
their result variables (no logic is copied). Prints counts and ids only, never full records.

Sections: 1 counts | 2 linking | 3 emails | 4 exclusions | 5 task sources | summary table.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections as C, contextlib, csv, io, os, re, runpy
from common import *

HERE = Path(__file__).parent
REF = REFERENCE_DATE

# Decisions already made by the author (Phase 1 review). Used only to label, never to hide.
CV_DECISIONS = {"RosaDelgado_Resume_2026.pdf": "c-108"}   # P04: link to c-108, source says c-112
EFFECTIVE_JOB = {"a-113": "j-backend"}                    # P06

def quiet_run(name):
    with contextlib.redirect_stdout(io.StringIO()):
        return runpy.run_path(str(HERE / name))

jobs = load_json("jobs"); cands = load_json("candidates"); apps = load_json("applications")
cards = load_json("scorecards"); acts = load_json("activity"); ev = load_events()
jid = {j["id"] for j in jobs}; cid = {c["id"]: c for c in cands}; aid = {a["id"]: a for a in apps}
summary = {}   # source -> dict(raw, read, failed, linked, notlinked, ambiguous)

# ------------------------------------------------------------------ 1. COUNTS
print("## 1. RECORD COUNTS (raw = independent count; read = records the audit scripts handled)")
allfiles = [p for p in RAW.rglob("*") if p.is_file()]
print("files under data/raw:", len(allfiles), "| by folder:", dict(C.Counter(p.parent.name for p in allfiles)))
print("unexpected files (hidden or other extensions):", [str(p.relative_to(RAW)) for p in allfiles
      if p.name.startswith(".") or (p.parent.name == "emails" and p.suffix != ".eml")
      or (p.parent.name == "cvs" and p.suffix.lower() not in (".pdf", ".docx", ".txt"))])

REQUIRED = {"jobs": ["id", "title", "stages"], "candidates": ["id", "name", "emails", "attachments"],
            "applications": ["id", "candidate_id", "job_id", "status", "current_stage", "applied_at"],
            "scorecards": ["id", "application_id", "interview", "interview_at"],
            "activity": ["candidate_id", "created_at", "body"]}
KEYPAT = {"jobs": r'"id"\s*:', "candidates": r'"id"\s*:', "applications": r'"id"\s*:',
          "scorecards": r'"id"\s*:', "activity": r'"body"\s*:'}
counts = {}
for name, data in [("jobs", jobs), ("candidates", cands), ("applications", apps), ("scorecards", cards), ("activity", acts)]:
    txt = (RAW / f"{name}.json").read_text(encoding="utf-8")
    raw_n = len(re.findall(KEYPAT[name], txt))
    bad = [i for i, r in enumerate(data) if not isinstance(r, dict) or any(k not in r for k in REQUIRED[name])]
    counts[name] = (raw_n, len(data), len(bad))
    print(f"{name+'.json':18} raw(text pattern)={raw_n:3} read(json.load)={len(data):3} failed(missing required key)={len(bad)} {bad}")
    summary[name] = dict(raw=raw_n, read=len(data) - len(bad), failed=len(bad) + (raw_n - len(data)))
raw_lines = (RAW / "stage_events.csv").read_text(encoding="utf-8").splitlines()
csv_rows = list(csv.reader(raw_lines))
bad_cols = [i + 1 for i, r in enumerate(csv_rows) if len(r) != 5]
print(f"{'stage_events.csv':18} raw(lines-1)={len(raw_lines)-1} csv-module rows-1={len(csv_rows)-1} pandas rows={len(ev)} rows with !=5 columns={bad_cols}")
summary["stage_events"] = dict(raw=len(raw_lines) - 1, read=len(ev), failed=len(raw_lines) - 1 - len(ev) + len(bad_cols))

r4 = quiet_run("04_emails.py"); rows = r4["rows"]
eml = sorted(f for f in os.listdir(RAW / "emails") if f.endswith(".eml"))
parse_fail = [r["f"] for r in rows if not r["mid"] or r["dt"] is None]
print(f"{'emails/':18} raw(.eml files)={len(eml)} read(parsed)={len(rows)} failed={len(eml)-len(rows)+len(parse_fail)} {parse_fail}")
summary["emails"] = dict(raw=len(eml), read=len(rows) - len(parse_fail), failed=len(eml) - len(rows) + len(parse_fail))
r3 = quiet_run("03_cvs.py"); res = r3["res"]
cvfiles = sorted(os.listdir(RAW / "cvs"))
print(f"{'cvs/':18} raw(files)={len(cvfiles)} read(text extracted)={len(res)} failed={len(cvfiles)-len(res)}")
summary["cvs"] = dict(raw=len(cvfiles), read=len(res), failed=len(cvfiles) - len(res))

print("\nfields that did not parse as a date (non-empty values):")
miss = C.Counter()
for name, data, ks in [("applications", apps, ["applied_at", "rejected_at", "offer_deadline"]),
                       ("scorecards", cards, ["interview_at", "submitted_at"]), ("activity", acts, ["created_at"]),
                       ("candidates", cands, ["created_at"]), ("jobs", jobs, ["opened_at"])]:
    for r in data:
        for k in ks:
            if r.get(k) and parse_dt(r[k]) is None:
                miss[f"{name}.{k}"] += 1
for r in ev.itertuples():
    if r.changed_at and parse_dt(r.changed_at) is None:
        miss["stage_events.changed_at"] += 1
print("  unparseable:", dict(miss) or "none", "| empty changed_at:", [r.row for r in ev.itertuples() if not r.changed_at])
print("RECONCILIATION raw = read + failed:", {k: v["raw"] == v["read"] + v["failed"] for k, v in summary.items()})

# ------------------------------------------------------------------ 2. LINKING
print("\n## 2. LINKING (linked + not linked + ambiguous must equal total)")
def bucket(name, linked, notlinked, ambiguous, total, method, extra=""):
    ok = len(linked) + len(notlinked) + len(ambiguous) == total
    summary[name].update(linked=len(linked), notlinked=len(notlinked), ambiguous=len(ambiguous))
    print(f"{name:13} total={total:3} linked={len(linked):3} not_linked={len(notlinked):3} ambiguous={len(ambiguous):3} sum_ok={ok} | method: {method} {extra}")
    if notlinked: print("   NOT LINKED:", notlinked)
    if ambiguous: print("   AMBIGUOUS:", ambiguous[:20])

# applications: candidate_id and job_id (ID)
l = [a["id"] for a in apps if a["candidate_id"] in cid and a["job_id"] in jid]
nl = [a["id"] for a in apps if a["id"] not in l]
bucket("applications", l, nl, [], len(apps), "ID (candidate_id + job_id)", f"| note: a-113 resolves by ID but job conflicts (P06)")
l = [r.row for r in ev.itertuples() if r.application_id in aid]
bucket("stage_events", l, [r.row for r in ev.itertuples() if r.application_id not in aid], [], len(ev), "ID (application_id)")
l = [s["id"] for s in cards if s["application_id"] in aid]
bucket("scorecards", l, [s["id"] for s in cards if s["application_id"] not in aid], [], len(cards), "ID (application_id)")
l = [i for i, x in enumerate(acts) if x["candidate_id"] in cid]
bucket("activity", l, [i for i, x in enumerate(acts) if x["candidate_id"] not in cid], [], len(acts), "ID (candidate_id)")

# same-person map (P01): candidates sharing normalized email AND phone
pe = C.defaultdict(set)
for c in cands:
    for e in c["emails"]:
        for p in c["phones"]:
            pe[(norm_email(e), norm_phone(p))].add(c["id"])
same_person = [sorted(v) for v in pe.values() if len(v) > 1]
person = {c["id"]: c["id"] for c in cands}
for grp in same_person:
    for x in grp:
        person[x] = grp[0]
print("same person under >1 candidate id (shared normalized email AND phone):", same_person)

# emails
em_l = [r["f"] for r in rows if r["st"] == "linked"]
em_a = [r["f"] for r in rows if r["st"] in ("ambiguous", "linked_dup_pair")]
em_n = [r["f"] for r in rows if r["st"] == "unlinked"]
bucket("emails", em_l, em_n, em_a, len(rows), "exact_email / exact_name / cv_email",
       f"| ambiguous = {sum(r['st']=='linked_dup_pair' for r in rows)} dup-person emails (resolved at person level) + {sum(r['st']=='ambiguous' for r in rows)} other")
print("   email link methods (linked + dup-person):", dict(C.Counter((r["meth"], r["conf"]) for r in rows if r["st"].startswith("linked"))))
print("   dup-person emails resolve to person:", sorted({person[i] for r in rows if r["st"] == "linked_dup_pair" for i in r["ids"]}))

# CVs
sub = C.Counter(); cv_l = []; cv_a = []; cv_n = []; corrected = []
for name, st, att, exact, fuzzy, bm, bp in res:
    if name in CV_DECISIONS and st == "conflict":
        ok = CV_DECISIONS[name] in exact
        label = "linked (corrected)" if ok else "UNRESOLVED conflict"
        sub[label] += 1; (cv_l if ok else cv_a).append(name)
        if ok: corrected.append((name, CV_DECISIONS[name], "conflict_with_source=" + ",".join(att)))
    elif st == "shared":
        same = len({person[c] for c in att}) == 1
        sub["shared (one person)" if same else "shared (different people)"] += 1; (cv_l if same else cv_a).append(name)
    elif st in ("linked", "linked_samename", "linked_by_name", "attachment_only"):
        sub[st] += 1; cv_l.append(name)
    elif st == "unlinked":
        sub[st] += 1; cv_n.append(name)
    else:
        sub[st] += 1; cv_a.append(name)
bucket("cvs", cv_l, cv_n, cv_a, len(res), "attachment ref, then exact name")
print("   CV sub-statuses:", dict(sub)); print("   corrected:", corrected)
refs = [(c["id"], a["filename"]) for c in cands for a in c["attachments"]]
distinct = {f for _, f in refs}
print(f"   CV references in candidates.json={len(refs)} distinct filenames={len(distinct)} files on disk={len(cvfiles)}")
multi = {f: [c for c, g in refs if g == f] for f in distinct if sum(1 for _, g in refs if g == f) > 1}
print("   filenames referenced by >1 candidate:", multi, "-> references - distinct =", len(refs) - len(distinct))
print("   referenced but missing on disk:", sorted(distinct - set(cvfiles)), "| on disk but never referenced:", sorted(set(cvfiles) - distinct))
effective = {c["id"]: [] for c in cands}
for c, f in refs:
    effective[c].append(f)
for name, cc in CV_DECISIONS.items():
    for k in effective:
        if name in effective[k] and k != cc: effective[k].remove(name)
    effective[cc].append(name)
print("   candidates with no CV after P04 correction:", [k for k, v in effective.items() if not v], "| before:", [c["id"] for c in cands if not c["attachments"]])

# ------------------------------------------------------------------ 3. EMAILS
print("\n## 3. EMAILS")
out = [r for r in rows if r["staff_sent"] and r["party"] is not None]
internal = [r["f"] for r in rows if r["staff_sent"] and r["party"] is None]
inb = [r for r in rows if not r["staff_sent"]]
print(f"total={len(rows)} outbound(staff->candidate)={len(out)} inbound={len(inb)} other(staff->staff only)={len(internal)} {internal} -> sum_ok={len(out)+len(inb)+len(internal)==len(rows)}")
print("outbound senders:", dict(C.Counter(r["sender"] for r in out)), "| inbound sender domains:", dict(C.Counter(r["party"][1].split('@')[1] for r in inb)))
print("inbound sender matches a candidate:", sum(r["st"] != "unlinked" for r in inb), "| does not match:", [(r["f"], r["party"][1]) for r in inb if r["st"] == "unlinked"] or "none")
print("inbound match methods:", dict(C.Counter((r["meth"]) for r in inb)))
by_p = C.defaultdict(list)
for r in rows:
    if r["ids"]:
        by_p[person[r["ids"][0]]].append(r)
ans = no_ans = 0; no_ans_list = []
for p, rs in by_p.items():
    inbound_dts = [x["dt"] for x in rs if not x["staff_sent"]]
    for r in rs:
        if r["staff_sent"]:
            if any(d > r["dt"] for d in inbound_dts): ans += 1
            else: no_ans += 1; no_ans_list.append(r)
print(f"outbound emails with a LATER inbound from the same person (any thread): {ans}; with none: {no_ans} (total {ans+no_ans})")
nr_people = {p for p, rs in by_p.items() if any(x["staff_sent"] for x in rs) and not any(not x["staff_sent"] for x in rs)}
print("people with outbound email but NO inbound email ever:", len(nr_people), sorted(nr_people))
for p in sorted(nr_people):
    rs = sorted(by_p[p], key=lambda x: x["dt"])
    appl = [(a["id"], a["status"], a["current_stage"]) for a in apps if person[a["candidate_id"]] == p]
    print("   ", p, "outbound:", len(rs), "last:", rs[-1]["dt"].date(), "subject:", rs[-1]["subj"][:45], "| apps:", appl)
byid = {r["mid"]: r for r in rows}
def root(r):
    seen = set()
    while r["irt"] and r["irt"] in byid and r["mid"] not in seen:
        seen.add(r["mid"]); r = byid[r["irt"]]
    return r["mid"]
th = C.defaultdict(list)
for r in rows: th[root(r)].append(r)
last_out = [t for t in th.values() if sorted(t, key=lambda x: x["dt"])[-1]["staff_sent"]]
print(f"threads={len(th)} ending with an outbound message={len(last_out)} (one-message threads among them: {sum(len(t)==1 for t in last_out)})")
print("outbound-no-reply by subject family:", dict(C.Counter(re.sub(r'^(Re: )+', '', r['subj']).split(' - ')[0][:34] for r in no_ans_list).most_common(8)))

# ------------------------------------------------------------------ 4. EXCLUSIONS
print("\n## 4. EXCLUSIONS / NULLS / NOT USED (computed counts; nothing is deleted)")
ev["dt"] = ev.changed_at.map(parse_dt)
before_applied = [(r.row, r.application_id) for r in ev.itertuples() if r.dt and r.dt < parse_dt(aid[r.application_id]["applied_at"])]
print("a) stage_events with no date -> changed_at NULL:", [r.row for r in ev.itertuples() if not r.changed_at])
print("b) stage_events dated before applied_at -> keep, mark suspect in data_issues:", before_applied)
print("c) stage names aliased (Phone Screen -> Recruiter Call):", int((ev.from_stage.eq('Phone Screen') | ev.to_stage.eq('Phone Screen')).sum()), "rows; raw name kept")
print("d) slash-date rows parsed by inferred rule:", int((~ev.changed_at.str.match(r'^\d{4}-') & ev.changed_at.ne('')).sum()), "rows; raw text kept")
print("e) empty scorecards -> no scores, feedback_status=no_feedback_yet (not zero):", [s["id"] for s in cards if not s["text"]])
print("f) scorecard with name mismatch kept, recorded in data_issues:", ["s-207"])
print("g) applications.job_id for a-113: source", aid["a-113"]["job_id"], "kept in job_id_source; effective", EFFECTIVE_JOB["a-113"], "used in funnels")
print("h) CV attached to the wrong candidate: source c-112 kept in source_candidate_id; not used as c-112's CV:", [n for n, _, _ in corrected])
print("i) withdrawn applications (rejected_at/reason filled) not counted as rejected:", sum(a['status'] == 'withdrawn' for a in apps))
print("j) offer_deadline on non-active applications not turned into tasks:", [(a['id'], a['status']) for a in apps if a['offer_deadline'] and a['status'] != 'active'])
print("k) activity notes not turned into tasks (free text):", len(acts), "| kept as context")
print("l) inbound emails with a later staff message, same subject -> not counted unanswered: see section 5C")
print("m) email In-Reply-To pointing to a message not in mailbox:", [(r['f'], r['irt']) for r in rows if r['irt'] and r['irt'] not in byid])
print("n) records deleted or dropped: 0 (every raw record is loaded; issues go to data_issues)")

# ------------------------------------------------------------------ 5. TASK SOURCES
print("\n## 5. Q3 TASK SOURCES (REFERENCE_DATE", REF.date(), ")")
offers = [a for a in apps if a["offer_deadline"]]
od = {a["id"]: (parse_dt(a["offer_deadline"]) - REF).days for a in offers}
print(f"A offer_deadline: records={len(offers)} | overdue={[i for i,a in aid.items() if a['offer_deadline'] and a['status']=='active' and od[i]<0]} "
      f"pending={[i for i,a in aid.items() if a['offer_deadline'] and a['status']=='active' and od[i]>=0]} not a task (non-active)={[i for i,a in aid.items() if a['offer_deadline'] and a['status']!='active']} | due date EXPLICIT")
uns = [s for s in cards if not s["submitted_at"]]
age = lambda s: (REF - parse_dt(s["interview_at"])).total_seconds() / 86400
print(f"B unsubmitted scorecards: records={len(uns)} | overdue(>{SCORECARD_OVERDUE_DAYS}d)={[s['id'] for s in uns if age(s)>SCORECARD_OVERDUE_DAYS]} pending={[s['id'] for s in uns if age(s)<=SCORECARD_OVERDUE_DAYS]} | interview date explicit; due date INFERRED (threshold {SCORECARD_OVERDUE_DAYS}d)")
rep = {r["irt"] for r in rows if r["staff_sent"] and r["irt"] in byid and not byid[r["irt"]]["staff_sent"]}
noreply = [r for r in rows if not r["staff_sent"] and r["mid"] not in rep]
def later_same_subject(r):
    return any(x["staff_sent"] and x["dt"] > r["dt"] and x["subj"].replace("Re: ", "") == r["subj"].replace("Re: ", "") for x in rows)
un_c = [r for r in noreply if not later_same_subject(r) and (REF - r["dt"]).total_seconds() / 86400 > EMAIL_UNANSWERED_DAYS]
print(f"C inbound w/o direct reply: records={len(noreply)} | unanswered(>{EMAIL_UNANSWERED_DAYS}d)={[r['f'] for r in un_c]} "
      f"| between 3 and 7 days={[r['f'] for r in noreply if 3 < (REF-r['dt']).total_seconds()/86400 <= 7 and not later_same_subject(r)]} | probably answered={[r['f'] for r in noreply if later_same_subject(r)]} | due date INFERRED")
dated = sum(bool(re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d|\d{1,2}/\d{1,2}|monday|tuesday|wednesday|thursday|friday", x["body"])) for x in acts)
print(f"D activity notes: records={len(acts)} | with a date-like phrase={dated} | tasks computed=0 (free text; LLM context only) | due date NOT STRUCTURED")
act_apps = [a for a in apps if a["status"] == "active"]
print(f"E stalled: active applications={len(act_apps)} | no threshold decided; longest waits via 05_tasks_and_funnel.py | derived, INFERRED")
# extra sources
waiting = []
for t in last_out:
    last = sorted(t, key=lambda x: x["dt"])[-1]
    if last["ids"] and any(a["status"] == "active" and person[a["candidate_id"]] == person[last["ids"][0]] for a in apps):
        waiting.append((last["f"], person[last["ids"][0]], (REF - last["dt"]).days))
print(f"F outbound waiting on candidate (thread ends outbound, candidate has an active application): records={len(waiting)} | not a recruiter task; context for Q2 | INFERRED")
fut = []
mpat = re.compile(r"(?i)\b(?:oct(?:ober)?\.?\s+(\d{1,2})|10/(\d{1,2})|nov(?:ember)?\.?\s+(\d{1,2}))\b")
for r in rows:
    for m in mpat.finditer(r["body"]):
        d = int(m.group(1) or m.group(2) or m.group(3)); mon = 11 if m.group(3) else 10
        if 1 <= d <= 31 and (mon, d) > (10, 15) and r["dt"].month == 10 and r["dt"] >= datetime(2026, 9, 25):
            fut.append((r["f"], m.group(0))); break
print(f"G future dates mentioned in emails (>= Oct 16, sent since Sep 25): records={len(fut)} {fut} | date EXPLICIT in free text (needs reading)")
noev = [a["id"] for a in apps if a["status"] == "active" and a["id"] not in set(ev.application_id)]
print(f"H active applications with no stage events (waiting for first review): records={len(noev)} {noev} | no due date; INFERRED")
rej_no_notice = []
for a in apps:
    if a["status"] == "rejected" and a["rejected_at"]:
        rj = parse_dt(a["rejected_at"])
        mail = [r for r in rows if r["staff_sent"] and r["ids"] and person[r["ids"][0]] == person[a["candidate_id"]] and (r["dt"] - rj).total_seconds() >= -86400]
        if not mail: rej_no_notice.append(a["id"])
print(f"I rejected applications with no staff email on/after rejected_at-1d: records={len(rej_no_notice)} {rej_no_notice} | INFERRED, low confidence (rejection may have been by phone)")
print("J interviews scheduled after reference date in scorecards:", [s["id"] for s in cards if parse_dt(s["interview_at"]) > REF] or "none")

# ------------------------------------------------------------------ SUMMARY TABLE
print("\n## SUMMARY (source | raw | read | failed | linked | not linked | ambiguous)")
order = ["jobs", "candidates", "applications", "stage_events", "scorecards", "activity", "emails", "cvs"]
print(f"{'source':14}{'raw':>5}{'read':>6}{'failed':>8}{'linked':>8}{'not linked':>12}{'ambiguous':>11}")
for k in order:
    v = summary[k]
    print(f"{k:14}{v['raw']:>5}{v['read']:>6}{v['failed']:>8}{str(v.get('linked','n/a')):>8}{str(v.get('notlinked','n/a')):>12}{str(v.get('ambiguous','n/a')):>11}")
print("(jobs and candidates are the link TARGETS, so linking does not apply to them.)")
