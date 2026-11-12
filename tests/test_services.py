"""Phase 3 service tests. They use the real data/hirepilot.db and read the raw files themselves
for the independent checks (so a bug in a service cannot hide itself)."""
import contextlib
import io
import json
import sqlite3
from datetime import date

import pandas as pd
import pytest

from backend import config
from backend.services import candidates, funnel, issues, jobs, ranking, tasks
from backend.services.common import connect

RAW = config.RAW_DIR


def task_by_id(result, task_id):
    return next((t for t in result["data"]["tasks"] if t["task_id"] == task_id), None)


# ---------- overdue rule (REFERENCE_DATE, never today) ----------
def test_reference_date_is_the_export_date():
    assert config.REFERENCE_DATE == date(2026, 10, 15)


def test_overdue_rule_on_known_tasks():
    all_open = tasks.list_tasks("all")
    assert all_open["ok"]
    expect = {  # task id -> (due date, state)
        "scorecard_pending:s-131": ("2026-10-08", "overdue"),
        "scorecard_pending:s-315": ("2026-10-15", "due_today"),     # due ON the reference date: not overdue
        "scorecard_pending:s-208": ("2026-10-16", "pending"),
        "offer_deadline:a-105": ("2026-10-12", "overdue"),
        "application_unreviewed:a-120": (None, "pending_no_due_date"),
    }
    for task_id, (due, state) in expect.items():
        t = task_by_id(all_open, task_id)
        assert t is not None, task_id
        assert (t["due_date"], t["state"]) == (due, state), task_id

    overdue = {t["task_id"] for t in tasks.list_tasks("overdue")["data"]["tasks"]}
    assert {"scorecard_pending:s-131", "offer_deadline:a-105"} <= overdue
    assert "scorecard_pending:s-315" not in overdue and "scorecard_pending:s-208" not in overdue
    assert "application_unreviewed:a-120" not in overdue            # no due date: never overdue
    assert task_by_id(tasks.list_tasks("due_today"), "scorecard_pending:s-315")
    pending = tasks.list_tasks("pending")
    assert task_by_id(pending, "scorecard_pending:s-208") and task_by_id(pending, "application_unreviewed:a-120")
    assert task_by_id(pending, "scorecard_pending:s-315") is None   # due today is its own state


def test_tasks_carry_candidate_name_and_other_records_for_duplicate_people():
    all_open = tasks.list_tasks("all")
    offer = task_by_id(all_open, "offer_deadline:a-105")
    assert offer["application_id"] == "a-105" and offer["candidate_id"] == "c-121" and offer["candidate_name"] == "Jonah Whitfield"
    assert offer["other_records"] == ["c-105"]
    assert "same person" in offer["other_records_note"] and "numbered separately" in offer["other_records_note"]
    assert all("person_id" not in t for t in all_open["data"]["tasks"])           # internal id is not shown
    # ordinary candidates get no such field, and every task has a name
    plain = task_by_id(all_open, "scorecard_pending:s-131")
    assert plain["candidate_name"] == "Irene Kowalczyk" and "other_records" not in plain and "other_records_note" not in plain
    assert all(t["candidate_name"] for t in all_open["data"]["tasks"])
    # the same fields are in the ranking's open_tasks
    r = ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]
    a105 = next(x for x in r["ranked"] if x["application_id"] == "a-105")
    t = next(t for t in a105["open_tasks"] if t["task_id"] == "offer_deadline:a-105")
    assert t["candidate_name"] == "Jonah Whitfield" and t["other_records"] == ["c-105"] and "same person" in t["other_records_note"]
    # which people have duplicate records at all: only Jonah Whitfield
    assert {t["candidate_name"] for t in tasks.list_tasks("all", include_closed=True)["data"]["tasks"] if "other_records" in t} == {"Jonah Whitfield"}


def test_each_task_says_which_rule_sets_its_due_date():
    all_open = tasks.list_tasks("all")
    rule = lambda i: task_by_id(all_open, i)["due_rule"]
    assert rule("offer_deadline:a-105") == "data"
    assert rule("scorecard_pending:s-131") == "assumption"
    assert "SCORECARD_OVERDUE_DAYS" in task_by_id(all_open, "scorecard_pending:s-131")["due_rule_detail"]
    assert rule("application_unreviewed:a-120") == "none"
    assert task_by_id(all_open, "scorecard_pending:s-131")["days_overdue"] == 7
    assert "days_overdue" not in task_by_id(all_open, "scorecard_pending:s-208")
    assert task_by_id(all_open, "scorecard_pending:s-208")["days_until_due"] == 1


def test_task_state_function_uses_given_reference_date():
    ref = date(2026, 10, 15)
    assert tasks.task_state(date(2026, 10, 14), ref) == "overdue"
    assert tasks.task_state(ref, ref) == "due_today"
    assert tasks.task_state(date(2026, 10, 16), ref) == "pending"
    assert tasks.task_state(None, ref) == "pending_no_due_date"


# ---------- funnel vs an independent count from the raw files ----------
def test_funnel_counts_match_raw_csv_for_j_backend():
    alias = {"Phone Screen": "Recruiter Call"}
    apps = json.load(open(RAW / "applications.json", encoding="utf-8"))
    # audit decision P06: a-113 is a backend application although its job_id says j-designer
    mine = {a["id"]: a for a in apps if (a["job_id"] == "j-backend") != (a["id"] == "a-113")}
    stages = json.load(open(RAW / "jobs.json", encoding="utf-8"))
    stages = next(j["stages"] for j in stages if j["id"] == "j-backend")

    ev = pd.read_csv(RAW / "stage_events.csv", dtype=str, keep_default_na=False)
    ev = ev[ev["application_id"].isin(mine)].copy()
    ev["from_stage"] = ev["from_stage"].replace(alias)
    ev["to_stage"] = ev["to_stage"].replace(alias)

    result = funnel.get_funnel("j-backend")
    assert result["ok"]
    got = {s["stage"]: s for s in result["data"]["stages"]}
    assert list(got) == stages
    # a-116: the chain ends at Take-Home (its date-sorted last stage would be Technical Screen). Raw CSV counts must
    # now match with NO exception, and the rejection must be counted at Take-Home.
    for stage in stages:
        entered = set(ev.loc[ev["to_stage"] == stage, "application_id"]) | set(ev.loc[ev["from_stage"] == stage, "application_id"])
        if stage == stages[0]:
            entered |= set(mine)                                     # the first stage has no entry event
        moved = set(ev.loc[ev["from_stage"] == stage, "application_id"])
        assert got[stage]["entered"] == len(entered), stage
        assert got[stage]["moved_on"] == len(moved), stage
    assert (got["Technical Screen"]["moved_on"], got["Technical Screen"]["rejected"]) == (11, 2)
    assert (got["Take-Home"]["entered"], got["Take-Home"]["rejected"]) == (11, 1)
    assert got["Take-Home"]["rejection_reasons"] == {"Take-home: no tests, and the idempotency requirement was not handled": 1}
    # exits by status, summed over stages, equal the status counts in applications.json
    for key, status in (("rejected", "rejected"), ("withdrew", "withdrawn"), ("hired", "hired")):
        assert sum(s[key] for s in got.values()) == sum(a["status"] == status for a in mine.values())
    assert sum(s["still_in_stage"] for s in got.values()) == sum(a["status"] == "active" for a in mine.values())


def test_funnel_rows_sum_to_entered_for_every_stage_of_every_job():
    """Each application counts once per stage: entered = moved_on + rejected + withdrew + hired + still_in_stage."""
    job_ids = [j["job_id"] for j in jobs.list_jobs()["data"]]
    assert len(job_ids) == 3
    checked = 0
    for job_id in job_ids:
        for s in funnel.get_funnel(job_id)["data"]["stages"]:
            parts = s["moved_on"] + s["rejected"] + s["withdrew"] + s["hired"] + s["still_in_stage"]
            assert parts == s["entered"], (job_id, s["stage"], parts, s["entered"])
            checked += 1
    assert checked == 16


def test_funnel_counts_each_application_in_one_final_place():
    """Every application of a job ends in exactly one stage, so the final-status columns add up to all applications."""
    for job_id in [j["job_id"] for j in jobs.list_jobs()["data"]]:
        d = funnel.get_funnel(job_id)["data"]
        finals = sum(s["rejected"] + s["withdrew"] + s["hired"] + s["still_in_stage"] for s in d["stages"])
        assert finals == d["applications"], job_id


def test_funnel_lists_conflicts_and_chain_resolutions_as_notes():
    notes = funnel.get_funnel("j-backend")["notes"]
    a114 = [n for n in notes if n.startswith("a-114")]
    a116 = [n for n in notes if n.startswith("a-116")]
    assert len(a114) == 1 and "applications.json says 'Technical Screen'" in a114[0] and "Take-Home" in a114[0]
    assert len(a116) == 1 and "event chain ends at 'Take-Home'" in a116[0] and "'Technical Screen'" in a116[0]
    assert "stage_resolved_by_chain" in a116[0]
    final = funnel.get_funnel("j-backend")["data"]["stages"][-1]
    assert final["is_final_stage"] and final["conversion_rate"] is None


def test_a116_is_a_take_home_rejection_everywhere():
    prof = candidates.get_candidate_profile("c-116")["data"]
    assert prof["applications"][0]["current_stage"] == "Take-Home" and prof["applications"][0]["status"] == "rejected"
    listed = next(a for a in jobs.list_candidates_for_job("j-backend", "rejected")["data"]["applications"] if a["application_id"] == "a-116")
    assert listed["current_stage"] == "Take-Home" and listed["stage_conflict"] is False
    assert any(i["issue_type"] == "stage_resolved_by_chain" for i in issues.get_data_issues("a-116")["data"]["issues"])


# ---------- ranking ----------
def test_ranking_is_deterministic():
    a = ranking.rank_candidates_for_job("j-backend", top_n=50)
    b = ranking.rank_candidates_for_job("j-backend", top_n=50)
    assert a["ok"] and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_unscored_candidates_are_in_a_separate_list_and_not_negative():
    r = ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]
    cards = json.load(open(RAW / "scorecards.json", encoding="utf-8"))
    submitted = {c["application_id"] for c in cards if c["submitted_at"] and c["text"]}
    ranked_apps = {x["application_id"] for x in r["ranked"]}
    unscored_apps = {x["application_id"] for x in r["not_scored"]}
    assert ranked_apps and unscored_apps
    assert ranked_apps <= submitted and not (unscored_apps & submitted)       # lists split on real feedback
    assert not (ranked_apps & unscored_apps)
    assert all(x["score"] is None for x in r["not_scored"])                   # no score, so not low
    assert all(isinstance(x["score"], float) for x in r["ranked"])
    assert "a-120" in unscored_apps                                           # active, no scorecard at all
    assert [x["rank"] for x in r["ranked"]] == list(range(1, len(r["ranked"]) + 1))
    assert [x["score"] for x in r["ranked"]] == sorted((x["score"] for x in r["ranked"]), reverse=True)


def test_ranking_parts_add_up_and_use_config_weights():
    r = ranking.rank_candidates_for_job("j-backend")["data"]
    assert (r["formula"]["feedback_weight"], r["formula"]["progress_weight"]) == (config.RANK_WEIGHT_FEEDBACK, config.RANK_WEIGHT_PROGRESS)
    assert config.RANK_WEIGHT_FEEDBACK + config.RANK_WEIGHT_PROGRESS == pytest.approx(1.0)
    for x in r["ranked"]:
        c = x["components"]
        assert x["score"] == pytest.approx(c["feedback"]["points"] + c["progress"]["points"], abs=0.02)
        assert x["evidence"], "every ranked candidate must show its evidence"
    thin = [x for x in ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]["ranked"] if len(x["evidence"]) == 1]
    assert all(x["evidence_level"] == "thin" for x in thin)


def test_ranking_by_hand_for_one_candidate():
    """c-121 (a-105, Offer stage): recompute the score from the stored scores."""
    r = ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]
    x = next(i for i in r["ranked"] if i["application_id"] == "a-105")
    with connect() as con:
        interviews = {}
        for sc in con.execute("SELECT id, interview_key FROM scorecards WHERE application_id='a-105' AND feedback_status='submitted'"):
            vals = {l: n for l, n in con.execute("SELECT label, normalized FROM scorecard_scores WHERE scorecard_id=?", (sc[0],))}
            interviews.setdefault(sc[1], []).append(vals.get("overall", sum(vals.values()) / len(vals)))
    feedback = sum(sum(v) / len(v) for v in interviews.values()) / len(interviews)
    assert x["score"] == pytest.approx(round(100 * (0.7 * feedback + 0.3 * 1.0), 2), abs=0.01)   # Offer = last stage -> progress 1


def test_ranking_carries_open_tasks_like_list_tasks():
    r = ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]
    everyone = {x["application_id"]: x for x in r["ranked"] + r["not_scored"]}
    # a-105: the offer deadline has passed (data rule), 3 days overdue
    t = next(t for t in everyone["a-105"]["open_tasks"] if t["task_id"] == "offer_deadline:a-105")
    assert (t["state"], t["days_overdue"], t["due_rule"]) == ("overdue", 3, "data")
    # same state as list_tasks says
    assert task_by_id(tasks.list_tasks("all"), "offer_deadline:a-105")["state"] == t["state"]
    # a-114: scorecard not submitted and overdue (assumption rule); a-120: pending with no due date, never overdue
    assert any(t["task_id"] == "scorecard_pending:s-131" and t["state"] == "overdue" and t["due_rule"] == "assumption"
               for t in everyone["a-114"]["open_tasks"])
    a120 = everyone["a-120"]["open_tasks"]
    assert [t["state"] for t in a120] == ["pending_no_due_date"] and "days_overdue" not in a120[0]
    # no candidate carries a closed task, and every task comes from list_tasks
    open_ids = {t["task_id"] for t in tasks.list_tasks("all")["data"]["tasks"]}
    assert all(t["task_id"] in open_ids for x in everyone.values() for t in x["open_tasks"])
    # tasks do not change the score
    assert [x["score"] for x in r["ranked"]] == sorted((x["score"] for x in r["ranked"]), reverse=True)


# ---------- structured errors ----------
@pytest.mark.parametrize("call", [
    lambda: jobs.get_job("j-nope"), lambda: jobs.list_candidates_for_job("j-nope"),
    lambda: funnel.get_funnel("j-nope"), lambda: ranking.rank_candidates_for_job("j-nope"),
    lambda: tasks.list_tasks("all", "j-nope")])
def test_unknown_job_id_is_a_structured_error(call):
    r = call()
    assert r["ok"] is False and r["error"]["code"] == "unknown_job_id"
    assert "j-backend" in r["error"]["valid_values"]


def test_unknown_candidate_id_is_a_structured_error():
    r = candidates.get_candidate_profile("c-999")
    assert r["ok"] is False and r["error"]["code"] == "unknown_candidate_id"


@pytest.mark.parametrize("call,code", [
    (lambda: tasks.list_tasks("late"), "invalid_state"),
    (lambda: jobs.list_candidates_for_job("j-backend", "fired"), "invalid_status"),
    (lambda: ranking.rank_candidates_for_job("j-backend", top_n=0), "invalid_input"),
    (lambda: ranking.rank_candidates_for_job("j-backend", include_statuses=["x"]), "invalid_status"),
    (lambda: jobs.get_job(""), "invalid_input"),
    (lambda: jobs.get_job(None), "invalid_input"),
    (lambda: candidates.get_candidate_profile(123), "invalid_input"),
    (lambda: issues.get_data_issues("zzz"), "unknown_entity_id"),
    (lambda: jobs.get_job("j-backend'; DROP TABLE jobs;--"), "unknown_job_id")])
def test_bad_values_return_structured_errors(call, code):
    r = call()
    assert r["ok"] is False and r["error"]["code"] == code


# ---------- the other tools: shape and source references ----------
def test_list_jobs_open_duration_uses_reference_date():
    data = {j["job_id"]: j for j in jobs.list_jobs()["data"]}
    assert data["j-backend"]["opened_at"] == "2026-06-10"
    assert data["j-backend"]["days_open"] == (date(2026, 10, 15) - date(2026, 6, 10)).days == 127
    assert data["j-backend"]["months_open"] == 4.2


def test_get_job_has_no_requirements_and_says_so():
    r = jobs.get_job("j-csm")
    assert r["data"]["requirements"] is None and any("requirements" in n for n in r["notes"])
    assert [s["stage"] for s in r["data"]["stages"]] == ["Application Review", "Recruiter Call", "Hiring Manager", "Role Play", "Offer"]


def test_list_candidates_for_job_filter_and_a113():
    backend = jobs.list_candidates_for_job("j-backend")["data"]
    assert backend["count"] == 20 and any(a["application_id"] == "a-113" for a in backend["applications"])
    active = jobs.list_candidates_for_job("j-backend", "active")["data"]
    assert active["count"] == 7 and all(a["status"] == "active" for a in active["applications"])


def test_candidate_profile_separates_no_feedback_from_submitted_and_has_sources():
    r = candidates.get_candidate_profile("c-114")
    assert r["ok"]
    d = r["data"]
    s131 = next(s for s in d["scorecards"] if s["scorecard_id"] == "s-131")
    assert s131["feedback_status"] == "no_feedback_yet" and s131["text"] is None and "not negative" in s131["meaning"]
    assert d["scorecard_summary"]["no_feedback_yet"] >= 1
    assert d["source_file"] == "candidates.json" and d["source_id"] == "c-114"
    assert all("source_file" in a and "source_id" in a for a in d["applications"] + d["scorecards"])
    assert len(d["cv"][0]["excerpt"]) <= candidates.CV_EXCERPT_CHARS if d["cv"] else True
    assert any(i["issue_type"] == "stage_conflict" for i in d["data_issues"])


def test_duplicate_person_is_visible():
    d = candidates.get_candidate_profile("c-105")["data"]
    assert d["other_candidate_records_same_person"] == ["c-121"]


def test_s103_is_flagged_low_but_still_counts_in_the_ranking():
    flag = [i for i in issues.get_data_issues("s-103")["data"]["issues"] if i["issue_type"] == "scorecard_mentions_other_application"]
    assert len(flag) == 1
    f = flag[0]
    assert (f["severity"], f["handling"], f["source_file"], f["source_id"], f["related_source_id"], f["problem_id"]) == \
        ("Low", "recorded", "scorecards.json", "s-103", "a-399", None)
    assert f["value_source"] == f["value_used"] == "a-105"                      # not moved
    r = ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]
    a105 = next(x for x in r["ranked"] if x["application_id"] == "a-105")
    assert a105["score"] == 100.0 and a105["components"]["feedback"]["interviews_scored"] == 4   # s-103 still counted
    assert any(e["scorecard_id"] == "s-103" for e in a105["evidence"])
    assert any(fl["issue_type"] == "scorecard_mentions_other_application" for fl in a105["flags"])   # visible in the ranking
    assert any(i["issue_type"] == "scorecard_mentions_other_application" for i in issues.get_data_issues("a-399")["data"]["issues"])


def test_data_issues_filter():
    allr = issues.get_data_issues()["data"]
    one = issues.get_data_issues("a-114")["data"]
    assert 0 < one["count"] < allr["count"] and any(i["issue_type"] == "stage_conflict" for i in one["issues"])
    assert all("source_file" in i and "source_id" in i for i in allr["issues"])


def test_every_ok_result_has_the_same_envelope():
    for r in (jobs.list_jobs(), jobs.get_job("j-backend"), funnel.get_funnel("j-csm"), tasks.list_tasks(),
              ranking.rank_candidates_for_job("j-designer"), issues.get_data_issues()):
        assert r["ok"] and r["as_of"] == "2026-10-15" and set(r) == {"ok", "as_of", "data", "notes"}


# ---------- safety ----------
def test_database_is_read_only():
    with connect() as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM jobs")


def test_services_print_nothing_to_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        jobs.list_jobs(); jobs.get_job("j-backend"); jobs.list_candidates_for_job("j-backend")
        candidates.get_candidate_profile("c-101"); ranking.rank_candidates_for_job("j-backend")
        funnel.get_funnel("j-backend"); tasks.list_tasks(); issues.get_data_issues(); jobs.get_job("bad")
    assert buf.getvalue() == ""


def test_thresholds_are_defined_only_in_config():
    import re
    from backend import services
    for path in (config.ROOT / "backend").rglob("*.py"):
        if path.name == "config.py":
            continue
        assert not re.search(r"(SCORECARD_OVERDUE_DAYS|EMAIL_UNANSWERED_DAYS|RANK_WEIGHT_\w+)\s*=", path.read_text()), path


# ---------- emails in the candidate profile ----------
def test_profile_shows_email_text_with_direction_date_subject_and_source():
    d = candidates.get_candidate_profile("c-201")["data"]
    by_file = {m["source_id"]: m for m in d["emails"]}
    m = by_file["20261007-0940-m-2008.eml"]
    assert m["direction"] == "inbound" and m["sent_at"].startswith("2026-10-07T09:40")
    assert m["subject"] == "Your offer from Quillfeather Labs" and "wonderful news" in m["body_excerpt"]
    assert m["source_file"] == "emails" and m["link_method"] and "thread_id" not in m and "body" not in m
    reply = by_file["20261007-1115-m-2009.eml"]
    assert reply["direction"] == "outbound" and "Three weeks' notice is completely fine" in reply["body_excerpt"]
    assert d["emails_total"] == d["emails_shown"] == 9


def test_profile_limits_emails_to_the_10_most_recent_oldest_first():
    r = candidates.get_candidate_profile("c-105")
    d = r["data"]
    assert (d["emails_total"], d["emails_shown"]) == (14, 10) and len(d["emails"]) == 10
    dates = [m["sent_at"] for m in d["emails"]]
    assert dates == sorted(dates)
    with connect() as con:
        newest = [x[0] for x in con.execute("SELECT sent_at FROM emails WHERE candidate_id='c-105' ORDER BY sent_at DESC LIMIT 10")]
    assert sorted(newest) == dates
    assert any("10 most recent of 14" in n for n in r["notes"])


def test_email_excerpt_removes_quoted_replies_and_cuts_long_text():
    text = "Thanks, that works.\n\nOn Mon, Oct 5, 2026 at 9:00 AM Priya Raman wrote:\n> Can you do Friday?\n> Please say."
    assert candidates.email_excerpt(text) == ("Thanks, that works.", False)
    assert candidates.email_excerpt("Yes.\n> quoted line\nNo.") == ("Yes.\nNo.", False)
    out, cut = candidates.email_excerpt("x" * 700)
    assert len(out) == candidates.EMAIL_EXCERPT_CHARS and cut
