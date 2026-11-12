"""Stage 2 of the Overview redesign. FREE: no model call. Numbers are checked against data/raw (build_expected reads only raw
files), so these tests do not grade the services by themselves."""
import csv
import json
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.services import analytics
from evals import build_expected
from web import dashboard, theme

RAW = config.RAW_DIR
EXP = build_expected.build()
D = analytics.dashboard()
APP = str(config.ROOT / "web" / "app.py")
APPS = json.load(open(RAW / "applications.json", encoding="utf-8"))
SCORECARDS = json.load(open(RAW / "scorecards.json", encoding="utf-8"))
CSV_LINES = open(RAW / "stage_events.csv", encoding="utf-8").read().splitlines()      # source id = line number in this file


# ---------- funnel: reached, drop-off %, still in progress (per role, against the raw files) ----------
@pytest.mark.parametrize("job_id", EXP["jobs"])
def test_reached_counts_and_the_still_in_progress_split_match_the_raw_files(job_id):
    for s in D["funnels"][job_id]["stages"]:
        e = EXP["funnel"][job_id][s["stage"]]
        assert s["reached"] == e["entered"]
        assert (s["rejected"], s["withdrew"], s["still_in_progress"]) == (e["rejected"], e["withdrew"], e["still_there"])
        assert s["reached"] == s["moved_on"] + s["rejected"] + s["withdrew"] + e["hired"] + s["still_in_progress"]   # nobody is lost from the count


@pytest.mark.parametrize("job_id", EXP["jobs"])
def test_dropoff_percent_is_lost_at_the_previous_stage_over_reached_there(job_id):
    stages = D["funnels"][job_id]["stages"]
    assert stages[0]["dropoff_pct"] is None                                       # the first stage has nothing before it
    for prev, s in zip(stages, stages[1:]):
        e = EXP["funnel"][job_id][prev["stage"]]
        if e["entered"]:
            want = (e["rejected"] + e["withdrew"]) / e["entered"]                 # still waiting is NOT lost
            assert s["dropoff_pct"] == pytest.approx(want)
            assert (s["dropoff_lost"], s["dropoff_base"]) == (e["rejected"] + e["withdrew"], e["entered"])
        else:
            assert s["dropoff_pct"] is None


@pytest.mark.parametrize("job_id", EXP["jobs"])
def test_largest_dropoff_and_slowest_stage(job_id):
    f = D["funnels"][job_id]
    names = list(EXP["funnel"][job_id])
    best = None
    for prev, name in zip(names, names[1:]):
        e = EXP["funnel"][job_id][prev]
        lost = e["rejected"] + e["withdrew"]
        if e["entered"] and lost and (best is None or lost / e["entered"] > best[0]):
            best = (lost / e["entered"], prev, name, lost, e["entered"])         # ties: the earlier stage wins
    big = f["largest_dropoff"]
    assert (big["from_stage"], big["to_stage"], big["lost"], big["base"]) == best[1:]
    assert big["pct"] == pytest.approx(best[0])
    assert f["summary"].startswith(f"The role has been open for {f['days_open']} days as of Oct 15, 2026.")
    assert f"{big['lost']} of {big['base']} candidates did not progress ({big['rejected']} rejected, {big['withdrew']} withdrew)" in f["summary"]
    assert f"The slowest stage is {f['slowest_stage']['stage']}" in f["summary"] and f["summary"].endswith("first.")


def test_summary_numbers_are_the_same_as_the_chart_numbers_for_the_biggest_stage():
    f = D["funnels"]["j-backend"]                                                 # Take-Home -> Onsite: 5 of 11 = 45.45%, shown as 45%
    big = f["largest_dropoff"]
    assert (big["from_stage"], big["to_stage"], big["lost"], big["base"]) == ("Take-Home", "Onsite", 5, 11)
    assert dashboard.pct0(big["pct"]) == "45%"


@pytest.mark.parametrize("job_id", EXP["jobs"])
def test_applications_without_stage_history_are_counted_from_the_raw_files(job_id):
    with_history = {r["application_id"] for r in csv.DictReader(open(RAW / "stage_events.csv", encoding="utf-8"))}
    want = sum(1 for a in APPS if a["job_id"] == job_id and a["id"] not in with_history)
    assert D["funnels"][job_id]["no_history"] == want


# ---------- KPIs ----------
def test_new_kpis_match_the_raw_files():
    k = D["kpis"]
    assert k["pending_scorecards"] == 5 == sum(t["task_id"].startswith("scorecard_pending") for t in EXP["tasks"])
    assert k["unanswered_emails"] == 2 == sum(t["task_id"].startswith("email_unanswered") for t in EXP["tasks"])
    assert k["upcoming_offer_deadlines"] == 0
    upcoming = [a for a in APPS if a["offer_deadline"] and a["status"] == "active" and a["offer_deadline"] >= config.REFERENCE_DATE.isoformat()]
    assert len(upcoming) == k["upcoming_offer_deadlines"]
    closed = [a["id"] for a in APPS if a["offer_deadline"] and a["status"] != "active" and a["offer_deadline"] >= config.REFERENCE_DATE.isoformat()]
    assert closed == ["a-201"] and k["offer_deadlines_on_closed_applications"] == 1
    assert [o["application_id"] for o in D["tasks"]["by_kpi"]["upcoming_offer_deadlines"]] == ["a-201"]


def test_unsubmitted_scorecards_are_not_data_issues():
    k = D["kpis"]
    unsubmitted = [s for s in SCORECARDS if not s["text"]]
    assert k["incomplete_feedback"] == len(unsubmitted) == 5
    assert (k["data_issues"], k["high_severity_issues"]) == (57, 37)             # before this change: 62 and 42
    assert k["data_issues"] + k["incomplete_feedback"] == 62 and k["high_severity_issues"] + 5 == 42
    assert all(r["type"] != "no_feedback_yet" for r in D["issues"]["records"]) and "no_feedback_yet" not in D["issues"]["by_type"]


def test_card_subtitles_show_the_overlap_with_overdue_tasks():
    assert dashboard.by_state_text(D["kpis"]["pending_scorecards_by_state"]) == "2 overdue · 1 due today · 2 waiting"
    assert dashboard.by_state_text(D["kpis"]["unanswered_emails_by_state"]) == "2 overdue"


# ---------- stalled candidates ----------
def test_stalled_rows_are_active_over_14_days_sorted_and_traceable_to_the_raw_csv():
    s = D["stalled"]
    assert s["min_days"] == 14 == config.STALLED_DAYS
    status = {a["id"]: a["status"] for a in APPS}
    days = [r["days_in_stage"] for r in s["rows"]]
    assert days == sorted(days, reverse=True) and all(n > 14 for n in days)
    assert all(status[r["application_id"]] == "active" for r in s["rows"])
    assert len(s["rows"]) == 11 and s["unknown_stage_date"] == []
    for r in s["rows"]:
        line = int(r["source"].split("stage_events.csv:")[1])
        row = next(csv.DictReader([CSV_LINES[0], CSV_LINES[line - 1]]))           # the raw line the row points to
        assert row["application_id"] == r["application_id"] and row["to_stage"] == r["stage"]
        if row["changed_at"][4] == "-":                                           # ISO dates only; the others are ambiguous (d/m or m/d)
            assert (config.REFERENCE_DATE - date.fromisoformat(row["changed_at"][:10])).days == r["days_in_stage"]


@pytest.mark.parametrize("app_id,line,days", [("a-110", 71, 34), ("a-114", 19, 24), ("a-105", 74, 17)])
def test_stalled_examples_checked_by_hand(app_id, line, days):
    r = next(x for x in D["stalled"]["rows"] if x["application_id"] == app_id)
    assert r["source"].endswith(f"stage_events.csv:{line}") and r["days_in_stage"] == days
    assert app_id in CSV_LINES[line - 1]


def test_an_application_exactly_14_days_in_stage_is_not_stalled():
    shorter = analytics.stalled_candidates(min_days=16)["rows"]
    assert all(r["days_in_stage"] > 16 for r in shorter) and len(shorter) == 10   # a-203 (16 days) drops out at "> 16"


# ---------- candidates and tasks tables ----------
def test_candidates_and_tasks_tables_and_their_role_filter():
    assert len(analytics.candidates_table()) == len(APPS) == 45
    assert len(analytics.candidates_table("j-csm")) == sum(a["job_id"] == "j-csm" for a in APPS) == 12
    assert all(r["source"].startswith("applications.json:") for r in analytics.candidates_table())
    assert len(analytics.tasks_table()) == len(EXP["tasks"]) == 11
    assert len(analytics.tasks_table("j-designer")) == 4


def start(page="Overview"):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = page
    return at.run()


def test_candidates_page_filters_by_role():
    at = start("Candidates")
    assert not at.exception and len(at.dataframe[0].value) == 10 and any("of 45" in c.value for c in at.caption)     # 10 rows per page, 45 in all
    at.session_state["cand-tab"] = "By Role"
    at = at.run()
    at = at.selectbox(key="cand-pick-By Role").select("j-csm").run()
    assert any("of 12" in c.value for c in at.caption)


def test_tasks_page_filters_by_role():
    at = start("Tasks")
    assert not at.exception and len(at.dataframe[0].value) == 11
    at = at.selectbox(key="page-role").select("Product Designer").run()
    assert len(at.dataframe[0].value) == 4


# ---------- Overview page: question cards, KPI click, stalled table ----------
def test_tiles_send_the_assignment_questions_to_the_agent_and_follow_the_selected_role():
    from tests.test_app import FakeAgent, result
    from backend.agent import core
    import pytest as _p
    mp = _p.MonkeyPatch()
    fake = FakeAgent([result(answer="FACTS\n- ok [applications.json:a-105]")])
    mp.setattr(core, "ask_sync", fake)
    try:
        at = start()
        assert fake.calls == []                                                   # nothing is asked until the user clicks
        assert [b.label for b in at.button if b.key.startswith("pbtn-")] == ["Find Top Candidates", "Find Drop-offs", "Check Pending Tasks"]
        assert not any("per question" in c.value or "$" in c.value for c in at.caption)         # no cost label under the tiles
        at = at.selectbox(key="dash-role").select("j-csm").run()
        at = at.button(key="pbtn-top").click().run()
        at = at.button(key="pbtn-dropoffs").click().run()
        at = at.button(key="pbtn-tasks").click().run()
        assert [q for q, _ in fake.calls] == ["Who are the top 3 candidates for Customer Success Manager, and why?",
                                              "This role has been open for 4 months. Where is our process losing candidates?",
                                              "Which tasks are pending or overdue?"]
        assert [len(h) for _, h in fake.calls] == [0, 2, 4]                       # follow-ups keep the shared conversation
        assert not at.exception
    finally:
        mp.undo()


def test_clicking_a_kpi_card_opens_its_records_and_clicking_again_closes_them():
    at = start()
    assert at.session_state["kpi"] is None if "kpi" in at.session_state else True                 # nothing open at first
    at = at.button(key="kpi-btn-pending_scorecards").click().run()
    assert at.session_state["kpi"] == "pending_scorecards"
    assert any("Pending scorecards (5)" in m.value for m in at.markdown)
    assert len(at.dataframe) == 3                                                 # records table, data quality: grouped audit + every record
    at = at.button(key="kpi-btn-pending_scorecards").click().run()
    assert at.session_state["kpi"] is None and not any("Pending scorecards (5)" in m.value for m in at.markdown)
    assert len(at.dataframe) == 2                                                 # data quality tables only
    at = at.button(key="kpi-btn-overdue_tasks").click().run()                     # another card replaces the open one
    assert at.session_state["kpi"] == "overdue_tasks" and any("Overdue tasks (5)" in m.value for m in at.markdown)


def test_selected_card_gets_the_coral_selected_style():
    css = theme.CSS
    assert '[class*="st-key-kpi-card-"][class*="-selected"]' in css and theme.CORAL in css
    assert '[class*="-urgent"][class*="st-key-kpi-card-"]' in css and "border-left: 5px solid" in css      # urgent card: coral bar on the left
    at = start()
    assert any("stagebar" in str(el.proto) for el in at.get("html"))                                                           # small stage bars in Open Positions


def test_only_the_first_card_with_something_to_do_is_urgent():
    names = ["overdue_tasks", "pending_scorecards", "unanswered_emails", "upcoming_offer_deadlines"]
    values = [D["kpis"]["overdue_tasks"], D["kpis"]["pending_scorecards"], D["kpis"]["unanswered_emails"], D["kpis"]["upcoming_offer_deadlines"]]
    assert next(n for n, v in zip(names, values) if v) == "overdue_tasks" and values == [5, 5, 2, 0]


def test_stalled_table_is_on_the_candidates_page_and_the_old_trust_section_is_gone():
    at = start()
    assert not any("Stalled candidates" in h.value for h in at.subheader) and not any("Stalled candidates" in m.value for m in at.markdown)
    assert not any("How much to trust" in h.value for h in at.subheader)
    at = start("Candidates")
    assert any("Stalled candidates (11)" in m.value for m in at.markdown)
    assert len(D["stalled"]["rows"]) == 11 and 11 in [len(t.value) for t in at.dataframe]
    at.session_state["cand-tab"] = "By Role"                                                       # the stalled table stays below, for all roles
    at = at.run()
    at = at.selectbox(key="cand-pick-By Role").select("j-csm").run()
    assert any("Stalled candidates (11)" in m.value for m in at.markdown)
    assert len([r for r in D["stalled"]["rows"] if r["job_id"] == "j-csm"]) == 3                  # the 3 CSM rows are part of the 11
