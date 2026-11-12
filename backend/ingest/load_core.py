"""Load the JSON/CSV files: jobs, persons, candidates, applications, stage events,
scorecards, scores, activity notes. Every doubtful value gets a data_issues row."""
import csv
import re
from collections import defaultdict

from backend import config
from .dates import event_datetime, json_datetime, parse_iso, plain_date
from .normalize import insert, nn, norm_email, norm_name, norm_phone, read_json

STAGE_ALIASES = {"Phone Screen": "Recruiter Call"}   # audit P05

# 'Label: n/d' (same pattern the audit used). Lazy label = the words just before the number.
SCORE_RE = re.compile(r"([A-Za-z][A-Za-z ]*?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)")
UNSCALED_RE = re.compile(r"([A-Za-z]+)\s*:\s*(\d+(?:\.\d+)?)(?![\d/]|\s*/|\.\d)")


# ---------------------------------------------------------------- jobs
def load_jobs(con):
    jobs = read_json("jobs")
    for j in jobs:
        insert(con, "jobs", dict(id=j["id"], title=j["title"], department=nn(j.get("department")),
                                 opened_at=plain_date(j.get("opened_at")), status=nn(j.get("status")),
                                 source_file="jobs.json", source_id=j["id"]))
        for pos, stage in enumerate(j["stages"], start=1):
            insert(con, "job_stages", dict(job_id=j["id"], position=pos, stage=stage,
                                           source_file="jobs.json", source_id=j["id"]))
    for alias, stage in STAGE_ALIASES.items():
        insert(con, "stage_aliases", dict(alias=alias, stage=stage,
                                          source_file="docs/DATA_AUDIT.md", source_id="P05"))
    return jobs


# ---------------------------------------------------------------- persons + candidates
def _person_groups(cands):
    """Merge candidate records that share a phone AND a normalized email (audit P01).
    Returns {candidate_id: (person_id, method, confidence)}."""
    parent = {c["id"]: c["id"] for c in cands}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    pair_signals = {}
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            phones = {norm_phone(p) for p in a["phones"] if norm_phone(p)} & {norm_phone(p) for p in b["phones"] if norm_phone(p)}
            mails = {norm_email(e) for e in a["emails"]} & {norm_email(e) for e in b["emails"]}
            if phones and mails:
                signals = ["same_phone", "same_email_normalized"]
                if {x["filename"] for x in a["attachments"]} & {x["filename"] for x in b["attachments"]}:
                    signals.append("same_cv")
                pair_signals[(a["id"], b["id"])] = signals
                ra, rb = find(a["id"]), find(b["id"])
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    groups = defaultdict(list)
    for c in cands:
        groups[find(c["id"])].append(c["id"])

    result = {}
    for root, members in groups.items():
        person_id = "p-" + root.split("-", 1)[1]
        if len(members) == 1:
            result[root] = (person_id, "single_record", None)
            continue
        signals = next(s for (a, b), s in pair_signals.items() if a in members and b in members)
        confidence = "high" if len(signals) >= 3 else "medium"
        for m in members:
            result[m] = (person_id, "+".join(signals), confidence)
    return result


def load_candidates(con, issues):
    cands = read_json("candidates")
    link = _person_groups(cands)
    seen_persons = {}
    for c in cands:
        pid = link[c["id"]][0]
        seen_persons.setdefault(pid, c["name"])
    members = defaultdict(list)
    for cid, (pid, _, _) in link.items():
        members[pid].append(cid)
    for pid in sorted(seen_persons):
        insert(con, "persons", dict(id=pid, display_name=seen_persons[pid], source_file="candidates.json",
                                    source_id=",".join(sorted(members[pid]))))

    for c in cands:
        pid, method, conf = link[c["id"]]
        insert(con, "candidates", dict(
            id=c["id"], person_id=pid, name=c["name"], location=nn(c.get("location")),
            created_at=plain_date(c.get("created_at")), person_link_method=method,
            person_link_confidence=conf, source_file="candidates.json", source_id=c["id"]))
        for e in c["emails"]:
            insert(con, "candidate_contacts", dict(candidate_id=c["id"], kind="email", value=e,
                   value_norm=norm_email(e), source="candidates.json", source_file="candidates.json", source_id=c["id"]))
        for p in c["phones"]:
            insert(con, "candidate_contacts", dict(candidate_id=c["id"], kind="phone", value=p,
                   value_norm=norm_phone(p), source="candidates.json", source_file="candidates.json", source_id=c["id"]))
        if not c["emails"]:
            issues.add("no_email_in_record", "Medium", "candidates.json", c["id"],
                       "candidates.json has no email for this candidate. An address may be added later "
                       "from the CV text (source 'cv_text').", "recorded", problem_id="P14")

    # P01: duplicate person, both ids kept
    for pid, ids in sorted(members.items()):
        if len(ids) > 1:
            ids = sorted(ids)
            issues.add("duplicate_person", "High", "candidates.json", ids[0],
                       f"Same person stored under {len(ids)} candidate ids "
                       f"(signals: {link[ids[0]][1]}). Both records are kept and share one person_id.",
                       "normalized", problem_id="P01", related_source_id=",".join(ids[1:]),
                       value_source=",".join(ids), value_used=pid)

    # P11: same name, different people -> never merged
    names = defaultdict(list)
    for c in cands:
        names[norm_name(c["name"])].append(c["id"])
    for ids in names.values():
        persons = {link[i][0] for i in ids}
        if len(persons) > 1:
            issues.add("same_name_different_people", "Medium", "candidates.json", ids[0],
                       "Same name, different phone, email and job. Kept as separate persons; "
                       "always link by id, never by name alone.", "left", problem_id="P11",
                       related_source_id=",".join(ids[1:]), value_used=",".join(sorted(persons)))
    return link


# ---------------------------------------------------------------- applications
def load_applications(con, issues, jobs):
    apps = read_json("applications")
    job_by_id = {j["id"]: j for j in jobs}
    job_by_title = {j["title"]: j["id"] for j in jobs}
    for a in apps:
        effective = a["job_id"]
        title = nn(a.get("job_title"))
        if title and job_by_id[a["job_id"]]["title"] != title:
            if title in job_by_title:
                effective = job_by_title[title]
                issues.add("job_id_title_mismatch", "High", "applications.json", a["id"],
                           f"job_id is {a['job_id']} ({job_by_id[a['job_id']]['title']}) but job_title is "
                           f"'{title}'. Stages, events, scorecards and rejection reason also point to "
                           f"{effective}. Author decision after Phase 1 review: use {effective}.",
                           "normalized", problem_id="P06", value_source=a["job_id"], value_used=effective)
            else:
                issues.add("job_id_title_mismatch", "High", "applications.json", a["id"],
                           f"job_id {a['job_id']} does not match job_title '{title}' and no job has that title.",
                           "recorded", problem_id="P06", value_source=a["job_id"], value_used=a["job_id"])
        insert(con, "applications", dict(
            id=a["id"], candidate_id=a["candidate_id"], job_id_source=a["job_id"], job_id_effective=effective,
            job_title_source=title, applied_at=json_datetime(a.get("applied_at")), status=a["status"],
            current_stage_source=nn(a.get("current_stage")), current_stage_from_events=None,
            rejected_at=json_datetime(a.get("rejected_at")), rejection_reason=nn(a.get("rejection_reason")),
            source_channel=nn(a.get("source")), offer_deadline=plain_date(a.get("offer_deadline")),
            source_file="applications.json", source_id=a["id"]))
    # P10: rejected at Offer stage with no reason and a deadline in the future
    ref = config.REFERENCE_DATE.isoformat()
    for a in apps:
        if (a["status"] == "rejected" and a.get("offer_deadline")
                and (a.get("offer_deadline") >= ref or not nn(a.get("rejection_reason")))):
            issues.add("rejected_with_offer_deadline", "High", "applications.json", a["id"],
                       f"Status is rejected (rejected_at {a.get('rejected_at')}), but there is an offer_deadline "
                       f"{a['offer_deadline']} and rejection_reason is "
                       f"{'empty' if not nn(a.get('rejection_reason')) else 'set'}. "
                       "The data cannot say whether the candidate declined or the record is wrong. "
                       "Kept as in the source.", "recorded", problem_id="P10",
                       value_source=a["status"], value_used=a["status"])
    return apps


# ---------------------------------------------------------------- stage events
def _order_events(events):
    """Sort by date. An undated event is placed right after the event that reached its from_stage."""
    dated = sorted((e for e in events if e["dt"]), key=lambda e: (e["dt"], e["line"]))
    order = list(dated)
    for u in sorted((e for e in events if not e["dt"]), key=lambda e: e["line"]):
        idx = max((i for i, e in enumerate(order) if e["to_stage"] == u["from_stage"]), default=None)
        if idx is None:
            order.append(u)
        else:
            order.insert(idx + 1, u)
    return order


def _chain_end(events):
    """End stage by following the from -> to chain (dates are NOT used). Returns None unless the events form ONE
    straight line that uses every event: exactly one start, one step out of each stage, no loop, nothing left over."""
    step = {}
    for e in events:
        if e["from_stage"] is None or e["from_stage"] in step:
            return None                                 # no origin, or two events leave the same stage
        step[e["from_stage"]] = e["to_stage"]
    starts = set(step) - set(step.values())
    if len(starts) != 1:
        return None
    stage, used = next(iter(starts)), 0
    while stage in step:
        stage, used = step[stage], used + 1
        if used > len(step):
            return None                                 # loop
    return stage if used == len(events) else None


def load_stage_events(con, issues, apps):
    app_by_id = {a["id"]: a for a in apps}
    effective = dict(con.execute("SELECT id, job_id_effective FROM applications"))
    job_stages = defaultdict(set)
    for job_id, stage in con.execute("SELECT job_id, stage FROM job_stages"):
        job_stages[job_id].add(stage)
    applied = dict(con.execute("SELECT id, applied_at FROM applications"))

    with open(config.RAW_DIR / "stage_events.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    per_app = defaultdict(list)
    for line, r in enumerate(rows, start=2):                # line 1 = header
        iso, rule = event_datetime(r["changed_at"])
        from_raw, to_raw = nn(r["from_stage"]), nn(r["to_stage"])
        from_n = STAGE_ALIASES.get(from_raw, from_raw)
        to_n = STAGE_ALIASES.get(to_raw, to_raw)
        insert(con, "stage_events", dict(
            id=line, application_id=r["application_id"], from_stage_raw=from_raw, to_stage_raw=to_raw,
            from_stage=from_n, to_stage=to_n, changed_at=iso, changed_at_raw=nn(r["changed_at"]),
            date_parse_rule=rule, changed_by=nn(r["changed_by"]),
            source_file="stage_events.csv", source_id=str(line)))
        sid = str(line)
        if (from_raw, to_raw) != (from_n, to_n):
            issues.add("stage_alias_applied", "High", "stage_events.csv", sid,
                       "Stage name is not in the job's stage list; mapped by the alias table.", "normalized",
                       problem_id="P05", value_source=f"{from_raw} -> {to_raw}", value_used=f"{from_n} -> {to_n}")
        if rule in ("ddmm_24h", "mmdd_ampm"):
            issues.add("slash_date_inferred", "High", "stage_events.csv", sid,
                       "Slash date. Rule inferred from the data (24-hour clock = DD/MM/YYYY, "
                       "AM/PM = MM/DD/YYYY); not stated in the source.", "normalized", problem_id="P07",
                       value_source=r["changed_at"], value_used=f"{iso} ({rule})")
        if iso is None:
            issues.add("missing_date", "High", "stage_events.csv", sid,
                       "Event has no date. Stored as NULL. Its place in the order is taken from the stage chain.",
                       "recorded", problem_id="P07", value_source=None, value_used=None)
        elif applied.get(r["application_id"]) and parse_iso(iso) < parse_iso(applied[r["application_id"]]):
            issues.add("suspect_date", "High", "stage_events.csv", sid,
                       f"Event is dated before the application date ({applied[r['application_id']]}). "
                       "Stored as in the source; not corrected (a day/month swap is only a guess).",
                       "recorded", problem_id="P07", value_source=r["changed_at"], value_used=iso)
        job_id = effective.get(r["application_id"])
        for st in (from_n, to_n):
            if st and job_id and st not in job_stages[job_id]:
                issues.add("stage_not_in_job", "High", "stage_events.csv", sid,
                           f"Stage '{st}' is not in the stage list of {job_id}.", "recorded",
                           problem_id="P05", value_source=st)
        per_app[r["application_id"]].append(dict(
            line=line, dt=parse_iso(iso) if iso else None, from_stage=from_n, to_stage=to_n))

    # current stage from events, and conflicts with applications.json.
    # Rule (docs/DATA_AUDIT.md P05): the END OF THE STAGE CHAIN decides where the application is; dates only order
    # things in time. If the events are not one straight line, fall back to the date order and record an issue.
    scorecards = read_json("scorecards")
    for app_id, events in sorted(per_app.items()):
        by_date = _order_events(events)[-1]["to_stage"]
        chain = _chain_end(events)
        if chain is None:
            current = by_date
            issues.add("stage_chain_not_linear", "Medium", "applications.json", app_id,
                       "The stage events do not form one straight chain (loop, branch or a missing step), so the current "
                       f"stage falls back to the last event by date: '{by_date}'.", "recorded", problem_id="P05",
                       related_source_id="stage_events.csv", value_used=by_date)
        else:
            current = chain
        con.execute("UPDATE applications SET current_stage_from_events = ? WHERE id = ?", (current, app_id))
        src = nn(app_by_id[app_id].get("current_stage"))
        src_n = STAGE_ALIASES.get(src, src)
        if chain is not None and chain != by_date:
            suspect = [e["line"] for e in events if e["dt"] and applied.get(app_id)
                       and e["dt"] < parse_iso(applied[app_id])]
            cards = [c["id"] for c in scorecards if c["application_id"] == app_id and c.get("interview") == chain
                     and nn(c.get("text"))]
            facts = [f"applications.json current_stage is '{src}'" + (" (agrees with the chain)" if src_n == chain else "")]
            if nn(app_by_id[app_id].get("rejection_reason")):
                facts.append(f"rejection_reason: \"{app_by_id[app_id]['rejection_reason']}\"")
            if cards:
                facts.append(f"submitted scorecard(s) for the '{chain}' interview: {', '.join(cards)}")
            issues.add("stage_resolved_by_chain", "Medium", "applications.json", app_id,
                       f"Sorted by event date the last stage is '{by_date}', but following the from -> to chain it is "
                       f"'{chain}'. The chain is used because event dates can be wrong"
                       + (f" (event line(s) {', '.join(map(str, suspect))} dated before the application, see suspect_date)" if suspect else "")
                       + ". Supporting evidence: " + "; ".join(facts) + ". Event dates were not changed.",
                       "normalized", problem_id="P05", related_source_id="stage_events.csv",
                       value_source=by_date, value_used=chain)
        if src_n != current:
            issues.add("stage_conflict", "High", "applications.json", app_id,
                       f"current_stage in applications.json is '{src}', but the last stage in the events "
                       f"(end of the stage chain) is '{current}'. Both are stored.", "recorded", problem_id="P05",
                       related_source_id="stage_events.csv", value_source=src, value_used=src)

    # applications with no events (expected: first stage only)
    for a in apps:
        if a["id"] not in per_app:
            issues.add("no_stage_events", "Low", "applications.json", a["id"],
                       f"No stage events for this application (status {a['status']}, stage "
                       f"{nn(a.get('current_stage'))}). current_stage_from_events stays NULL.", "recorded")


# ---------------------------------------------------------------- scorecards
def extract_scores(text):
    """[(label, value, scale)] for every 'Label: n/d' in the text."""
    out = []
    for label, n, d in SCORE_RE.findall(text):
        out.append((re.sub(r"\s+", " ", label).strip().lower(), float(n), int(d)))
    return out


# Findings from a manual review (not detected by a rule). Flag only: the card stays where the source puts it
# and still counts in the ranking. See docs/DATA_AUDIT.md section 10.
REVIEWED_SCORECARD_FLAGS = {
    "s-103": dict(
        related="a-399",
        reason=("The text talks about 'the CSM process' and a 'second conversation', and the person also has a CSM "
                "application (a-399, same person via P01). Checked: the interview date (2026-08-07) falls inside a-105's "
                "Recruiter Call window (2026-08-05 to 2026-08-10), a-399 was rejected on 2026-07-29 and already has its own "
                "Recruiter Call and Hiring Manager cards (s-108, s-109). Most likely it belongs to a-105. Kept on a-105; "
                "flag only. Removing it would not change a-105's score (1.0 feedback either way).")),
}


def load_scorecards(con, issues, apps):
    cards = read_json("scorecards")
    cand_of = {a["id"]: a["candidate_id"] for a in apps}
    cand_names = {c["id"]: c["name"] for c in read_json("candidates")}
    first_names = defaultdict(set)
    for cid, name in cand_names.items():
        first_names[name.split()[0].lower()].add(cid)

    for s in cards:
        text, submitted = nn(s.get("text")), json_datetime(s.get("submitted_at"))
        if text is None and submitted is None:
            status = "no_feedback_yet"
            issues.add("no_feedback_yet", "High", "scorecards.json", s["id"],
                       "Scorecard not submitted (no text, no submitted_at). Stored as 'no_feedback_yet', "
                       "no scores; this is missing feedback, not negative feedback.", "normalized", problem_id="P09")
        elif text is not None and submitted is not None:
            status = "submitted"
        else:
            raise ValueError(f"scorecard {s['id']}: text and submitted_at disagree")
        insert(con, "scorecards", dict(
            id=s["id"], application_id=s["application_id"], interview=nn(s.get("interview")),
            interview_key=f"{s['application_id']}|{s.get('interview')}", interviewer=nn(s.get("interviewer")),
            interview_at=json_datetime(s.get("interview_at")), submitted_at=submitted, text=text,
            feedback_status=status, source_file="scorecards.json", source_id=s["id"]))
        if s["id"] in REVIEWED_SCORECARD_FLAGS:
            flag = REVIEWED_SCORECARD_FLAGS[s["id"]]
            issues.add("scorecard_mentions_other_application", "Low", "scorecards.json", s["id"],
                       flag["reason"], "recorded", related_source_id=flag["related"],
                       value_source=s["application_id"], value_used=s["application_id"])
        if text is None:
            continue
        for label, value, scale in extract_scores(text):
            insert(con, "scorecard_scores", dict(scorecard_id=s["id"], label=label, value=value, scale=scale,
                   normalized=value / scale, source_file="scorecards.json", source_id=s["id"]))
        for label, n in UNSCALED_RE.findall(text):
            issues.add("score_without_scale", "Medium", "scorecards.json", s["id"],
                       f"'{label}: {n}' has no scale (/5 or /10), so it is not stored as a score.",
                       "left", problem_id="P08", value_source=f"{label}: {n}")
        # P12: the text starts with a first name that belongs to another candidate
        first = re.match(r"\W*([A-Z][a-z]+)\b", text)
        own = cand_names.get(cand_of.get(s["application_id"]), "").split()[0].lower()
        if first and first.group(1).lower() != own and first.group(1).lower() in first_names:
            issues.add("scorecard_names_other_person", "Medium", "scorecards.json", s["id"],
                       f"The text starts with '{first.group(1)}', but the card is attached to "
                       f"{cand_of.get(s['application_id'])}. Cannot tell a typo from a misfiled card. "
                       "Kept on the application in the source.", "recorded", problem_id="P12",
                       related_source_id=s["application_id"])


# ---------------------------------------------------------------- activity notes
def load_activity(con, issues, link):
    notes = read_json("activity")
    members = defaultdict(list)
    for cid, (pid, _, _) in link.items():
        members[pid].append(cid)
    for i, n in enumerate(notes):
        pid = link[n["candidate_id"]][0]
        insert(con, "activity_notes", dict(
            id=i, candidate_id=n["candidate_id"], person_id=pid, author=nn(n.get("author")),
            created_at=json_datetime(n.get("created_at")), body=nn(n.get("body")),
            source_file="activity.json", source_id=str(i)))
        if len(members[pid]) > 1:
            issues.add("note_on_merged_person", "High", "activity.json", str(i),
                       f"Note sits on {n['candidate_id']}, but the person has {len(members[pid])} candidate "
                       f"records ({', '.join(sorted(members[pid]))}). The text may describe the other record's "
                       "application. Linked to the person.", "recorded", problem_id="P01",
                       related_source_id=",".join(sorted(members[pid])), value_source=n["candidate_id"], value_used=pid)
