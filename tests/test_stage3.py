"""Stage 3 of the Overview redesign: side panel, tiles, answer blocks, ranking chart, MCP status, Open Positions, Priority
Actions, Recent Activity. FREE: the agent is always the fake agent from test_app.py. No API call, no key."""
import csv
import email
import email.policy
import json
from datetime import date, datetime

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.agent import core
from backend.services import analytics, ranking
from tests.test_app import FakeAgent, result
from web import chat, dashboard

RAW = config.RAW_DIR
D = analytics.dashboard()
APP = str(config.ROOT / "web" / "app.py")
ANSWER = ("Intro line.\n\nFACTS\n- Fact one. [scorecards.json:s-131]\n- Fact two. [applications.json:a-105; emails:20261014-1645-m-2022.eml]\n\n"
          "AI ASSESSMENT\nMy own judgement.\n\nCAVEATS\n- The weights are an assumption.")


def start(page="Overview", fake=None, monkeypatch=None):
    if fake is not None:
        monkeypatch.setattr(core, "ask_sync", fake)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = page
    return at.run()


def md(at):
    return " ".join(m.value for m in at.markdown)


# ---------- data issues: severity ----------
def test_task_no_due_date_issues_are_low_severity_and_the_counts_are_unchanged():
    rows = [r for r in D["issues"]["records"] if r["type"] == "task_no_due_date"]
    assert len(rows) == 3 and {r["severity"] for r in rows} == {"Low"}
    assert (D["kpis"]["data_issues"], D["kpis"]["high_severity_issues"]) == (57, 37)       # only Medium -> Low, High is unchanged
    assert D["issues"]["by_severity"] == {"High": 37, "Medium": 7, "Low": 13}


# ---------- Recent Activity: real dates, newest first, checked against the raw files ----------
def raw_events():
    out = []
    for n in json.load(open(RAW / "activity.json", encoding="utf-8")):
        out.append(datetime.fromisoformat(n["created_at"]))
    for s in json.load(open(RAW / "scorecards.json", encoding="utf-8")):
        if s["submitted_at"]:
            out.append(datetime.fromisoformat(s["submitted_at"]))
    for f in (RAW / "emails").glob("*.eml"):
        msg = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
        out.append(email.utils.parsedate_to_datetime(msg["Date"]).replace(tzinfo=None))
    return sorted((e for e in out if e.date() <= config.REFERENCE_DATE), reverse=True)


def test_recent_activity_is_the_newest_real_records_with_dates_not_relative_times():
    act = D["activity"]
    assert 1 <= len(act) <= 5
    newest = raw_events()
    got = [datetime.fromisoformat(a["at"]).replace(tzinfo=None) for a in act]
    assert got == newest[:len(act)]                                                           # same timestamps as the raw files, same order
    assert all(g.date() <= config.REFERENCE_DATE for g in got)
    assert act[0]["date"] == "Oct 14" and act[0]["source"] == "emails:20261014-1645-m-2022.eml"
    text = json.dumps(act)
    assert "ago" not in text and "yesterday" not in text.lower()                                # no invented relative times
    assert all(a["source"] for a in act) and not any(len(a["text"]) > 90 for a in act)          # source kept; no note or email body copied


def test_recent_activity_card_on_the_page():
    at = start("Candidates")                                                                    # moved off the Overview in Part C
    text = md(at)
    assert "Recent Activity" in text and "Email sent to Theo Lindqvist" in text and "Oct 14" in text and " ago" not in text


# ---------- Open Positions ----------
def test_open_positions_numbers_and_stage_bar_come_from_the_data():
    for r in D["roles"]:
        assert sum(x["count"] for x in r["active_by_stage"]) == r["active"]                    # the bar adds up to the active candidates
        assert [x["stage"] for x in r["active_by_stage"]] == list(EXP_STAGES(r["job_id"]))      # pipeline order
    assert [(r["applications"], r["active"], r["hired"]) for r in D["roles"]] == [(20, 7, 0), (12, 5, 1), (13, 5, 0)]


def EXP_STAGES(job_id):
    from evals import build_expected
    return build_expected.build()["funnel"][job_id]


def test_clicking_a_role_sets_the_role_filter_and_no_percent_of_stages_is_shown():
    at = start()
    assert at.selectbox(key="dash-role").value == "j-backend"
    at = at.button(key="role-btn-j-csm").click().run()
    assert at.selectbox(key="dash-role").value == "j-csm" and not at.exception
    assert "Recruitment Funnel — Customer Success Manager" in md(at)
    assert not any("stages" in m.value and "%" in m.value and "/ 6" in m.value for m in at.markdown)   # no "N/6 stages %" bars
    classes = " ".join(str(b) for b in at.get("button"))
    assert "role-btn-j-csm" in classes


# ---------- Priority Actions ----------
def test_priority_actions_order_badges_and_deadline_source():
    pr = D["tasks"]["priority"]
    order = ["overdue", "due_today", "pending", "pending_no_due_date"]
    assert [order.index(t["state"]) for t in pr] == sorted(order.index(t["state"]) for t in pr) and len(pr) == 11
    days = [t["days_overdue"] for t in pr if t["state"] == "overdue"]
    assert days == sorted(days, reverse=True)
    at = start()
    text = md(at)
    assert text.count(":primary-badge[OVERDUE]") == 4                                           # the status conflict takes the first row; 4 task rows follow
    assert text.count(":primary-badge[⚠ Status conflict]") == 1
    assert "Showing 5 of 12" in " ".join(c.value for c in at.caption)                          # 11 tasks + 1 status conflict
    offer = next(t for t in pr if t["task_type"] == "offer_deadline")
    assert offer["deadline_source"] == "From the data" and dashboard.DEADLINE_NOTE["From the data"] == "deadline from the data"
    assert "assumed deadline" in " ".join(c.value for c in at.caption)                          # scorecards and emails are assumptions


# ---------- Data Quality card ----------
def test_data_quality_card_is_compact_with_details_and_source_refs():
    at = start()
    text = md(at)
    assert "57 issues found" in text and "37 high severity" in text                                           # the number and the severity are on the card
    assert any(e.label == "View All Issues & Sources" for e in at.expander)
    table = next(t.value for t in at.dataframe if "Handling" in t.value.columns)   # the table with every record
    assert len(table) == 57 and table["Source"].str.contains(":").all()


# ---------- top bar: MCP status ----------
def test_top_bar_shows_connected_or_disconnected_without_any_model_call(monkeypatch):
    fake = FakeAgent()
    at = start("Overview", fake, monkeypatch)
    assert ":green[●] Connected" in md(at) and "Recruiter" in md(at) and fake.calls == []
    chat.mcp_status.clear()
    monkeypatch.setattr(core, "check_mcp", lambda: (False, 0))
    assert ":gray[●] Disconnected" in md(start("Overview", fake, monkeypatch)) and fake.calls == []


def test_the_real_status_check_starts_the_mcp_server_and_lists_the_tools(monkeypatch):
    monkeypatch.undo()                                                                           # undo the fast fake from conftest
    assert core.check_mcp() == (True, 8)                                                         # free: no model, no key


def test_a_broken_mcp_server_gives_disconnected_not_a_crash(monkeypatch):
    monkeypatch.undo()
    from mcp import StdioServerParameters
    original = core.Agent.__init__

    def broken(self, *a, **kw):
        original(self, *a, server_params=StdioServerParameters(command="/nonexistent/python", args=[]), **kw)
    monkeypatch.setattr(core.Agent, "__init__", broken)
    assert core.check_mcp() == (False, 0)


# ---------- answer blocks, sources, ranking chart ----------
def test_answer_blocks_are_split_and_sources_are_built_in_python():
    labels = [lab for lab, _ in chat.parse_answer(ANSWER)]
    assert labels == ["", "FACTS", "AI ASSESSMENT", "ASSUMPTIONS & CAVEATS"]
    assert chat.extract_sources(ANSWER) == ["scorecards.json:s-131", "applications.json:a-105", "emails:20261014-1645-m-2022.eml"]
    assert chat.parse_answer("Plain text, no headings. Facts are nice.") == [("", "Plain text, no headings. Facts are nice.")]
    assert chat.extract_sources("No refs. [not a ref] [a b:c]") == []


def ranking_call():
    return {"round": 1, "name": "rank_candidates_for_job", "input": {"job_id": "j-backend"}, "ok": True, "error_code": None,
            "items": 3, "ms": 5, "result": json.dumps(ranking.rank_candidates_for_job("j-backend", 3))}


def test_ranking_chart_data_comes_from_the_tool_result_and_missing_scores_are_not_zero():
    svc = ranking.rank_candidates_for_job("j-backend", 3)["data"]
    chart = chat.ranking_chart_data([ranking_call()])
    assert [r["name"] for r in chart["rows"]] == [r["name"] for r in svc["ranked"]]
    assert [r["score"] for r in chart["rows"]] == [r["score"] for r in svc["ranked"]]
    assert all(r["feedback"] + r["progress"] == pytest.approx(r["score"], abs=0.02) for r in chart["rows"])
    assert chart["not_measured"] == [r["name"] for r in svc["not_scored"][:2]] and chart["not_measured"]
    fig = chat.ranking_figure(chart)
    assert list(fig.data[0].y)[-len(chart["not_measured"]):] == chart["not_measured"]
    assert all(v is None for v in list(fig.data[0].x)[len(chart["rows"]):])                      # not measured = no bar, never 0
    assert sum("not measured" in a.text for a in fig.layout.annotations) == len(chart["not_measured"])
    assert chat.ranking_chart_data([]) is None and chat.ranking_chart_data([{**ranking_call(), "result": "{broken"}]) is None
    assert chat.ranking_chart_data([{**ranking_call(), "name": "list_tasks"}]) is None


# ---------- the panel, end to end with the fake agent ----------
def with_ranking(answer=ANSWER):
    return result(answer=answer, calls=[ranking_call()])


def test_panel_shows_a_short_summary_and_the_full_answer_is_on_the_ask_ai_page(monkeypatch):
    fake = FakeAgent([with_ranking()])
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="pbtn-top").click().run()
    assert not at.exception and len(fake.calls) == 1
    assert not at.get("plotly_chart") or not any(e.key.startswith("rank-") for e in at.get("plotly_chart"))      # no chart in the panel
    assert not any(e.label in ("Candidate Ranking Breakdown", "Interview & Progress Score", "How this was calculated") for e in at.expander)
    assert not {"FACTS", "AI ASSESSMENT", "SOURCES"} & {c.value for c in at.caption}                      # no answer blocks in the panel
    assert any(b.key.startswith("read-full-") for b in at.button)
    at = next(b for b in at.button if b.key.startswith("read-full-")).click().run()                      # Read full answer
    assert at.session_state["page"] == "Ask AI" and len(fake.calls) == 1                                  # same stored answer, no new call
    keys = [e.key for e in at.get("plotly_chart")]
    assert any(k.startswith("rank-ask") for k in keys)                                                   # the score chart
    text = md(at)
    assert "**Interview & Progress Score**" in text and "##### AI ASSESSMENT" in text                     # chart title and the AI block header
    labels = {e.label: e.proto.expanded for e in at.expander}
    assert labels == {"Detailed evidence": False, "Data issues & assumptions": False, "Sources (3)": False, "How this was calculated": False}
    assert "AI reasoning based on the facts above" in [c.value for c in at.caption]
    assert "scorecards.json:s-131" in [c.value for c in at.caption]                                      # raw ref, small text under its readable label
    assert "Scorecard s-131 · " in text                                                                  # label from the DB lookup
    assert chat.AVATAR == {"user": ":material/person:", "assistant": str(config.ROOT / "assets" / "logo_icon.png")}   # our icon, not the mockup's mark
    assert (config.ROOT / "assets" / "logo_icon.png").is_file()
    avatars = [m.avatar for m in at.chat_message]                                                        # Streamlit turns the file path into a media URL
    assert avatars[0] == ":material/person:" and avatars[1].endswith(".png")


def test_follow_up_form_shares_the_conversation_with_the_ask_ai_page(monkeypatch):
    fake = FakeAgent([result(answer="FACTS\n- one [applications.json:a-105]"), result(answer="FACTS\n- two [applications.json:a-110]")])
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="pbtn-tasks").click().run()
    at.text_input(key="ai-q").input("And who is the oldest?")
    at = at.button(key="ai-send").click().run()
    assert [q for q, _ in fake.calls] == ["Which tasks are pending or overdue?", "And who is the oldest?"]
    assert [m["role"] for m in fake.calls[1][1]] == ["user", "assistant"]                        # follow-up carries the first exchange
    assert len(at.chat_message) == 4
    at = at.button(key="open-chat").click().run()                                                # "Open full chat"
    assert at.session_state["page"] == "Ask AI" and len(at.chat_message) == 4                    # same messages on the Ask AI page
    assert len(fake.calls) == 2                                                                  # opening the page asks nothing


def test_empty_follow_up_sends_nothing_and_a_rerun_does_not_repeat_the_question(monkeypatch):
    fake = FakeAgent([result()])
    at = start("Overview", fake, monkeypatch)
    at.text_input(key="ai-q").input("   ")
    at = at.button(key="ai-send").click().run()
    assert fake.calls == [] and len(at.chat_message) == 0
    at = at.button(key="pbtn-top").click().run()
    at = at.selectbox(key="dash-role").select("j-csm").run()                                     # any other rerun
    assert len(fake.calls) == 1 and len(at.chat_message) == 2


def test_ask_ai_about_this_sends_a_prepared_question_to_the_panel(monkeypatch):
    fake = FakeAgent([result(answer="FACTS\n- hi [applications.json:a-105]")])
    at = start("Candidates", fake, monkeypatch)                                                  # the decision box moved here in Part C
    assert fake.calls == []
    question = D["decisions"][0]["question"]
    at = at.button(key="decision-ask-0").click().run()
    at = at.run()                                                                                # the Ask AI page draws clean first, then asks
    assert [q for q, _ in fake.calls] == [question] and len(at.chat_message) == 2
    assert "hi" in md(at) and not any(e.key == "ask-q" for e in at.text_input)                          # the old Ask card is gone


def test_dashboard_interactions_never_call_the_model(monkeypatch):
    fake = FakeAgent()
    at = start("Overview", fake, monkeypatch)
    at = at.selectbox(key="dash-role").select("j-designer").run()
    at = at.button(key="role-btn-j-csm").click().run()
    at = at.button(key="kpi-btn-unanswered_emails").click().run()
    at = at.button(key="kpi-btn-unanswered_emails").click().run()
    assert fake.calls == [] and not at.exception


def test_agent_is_asked_to_keep_tool_results_but_they_are_not_stored(monkeypatch):
    seen = {}

    def spy(question, history=None, **kw):
        seen.update(kw)
        return with_ranking()
    monkeypatch.setattr(core, "ask_sync", spy)
    msg = chat.run_agent("q", [])
    assert seen == {"keep_results": True} and msg["chart"] and "result" not in json.dumps(msg["meta"])
    assert chat.run_agent.__module__ == "web.chat"


def test_failed_answer_has_no_chart(monkeypatch):
    monkeypatch.setattr(core, "ask_sync", lambda q, history=None, **kw: result(answer="", status="api_error", error="x", calls=[ranking_call()]))
    assert chat.run_agent("q", [])["chart"] is None


# ---------- guards ----------
def test_chat_and_panel_modules_have_no_data_access_and_no_unsafe_html():
    import ast
    for name in ("chat", "panel"):
        source = (config.ROOT / "web" / f"{name}.py").read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        assert not any(m and ("sqlite3" in m or "services" in m or "ingest" in m or "pandas" in m) for m in imported), imported
        assert "SELECT " not in source and "unsafe_allow_html" not in source
    assert not any("rank_candidates" in line for line in (config.ROOT / "web" / "chat.py").read_text().splitlines() if "import" in line)
