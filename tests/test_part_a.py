"""UI polish, Part A: status conflicts, why candidates leave, data coverage, plain-English data quality, decision alerts,
the panel summary, tiles, no cost labels, layout order. FREE: the agent is always the fake agent. Numbers are checked
against the raw files in data/raw."""
import json
import re

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.agent import core
from backend.services import analytics, ranking, trust
from tests.test_app import FakeAgent, result
from tests.test_stage3 import ANSWER, md, ranking_call, start, with_ranking
from web import chat, dashboard, evidence, panel

RAW = config.RAW_DIR
APPS = json.loads((RAW / "applications.json").read_text(encoding="utf-8"))
D = analytics.dashboard()
CANDS = {c["id"]: c for c in json.loads((RAW / "candidates.json").read_text(encoding="utf-8"))}


def all_text(at):
    out = [m.value for m in at.markdown] + [c.value for c in at.caption] + [b.label for b in at.button] + [e.label for e in at.expander]
    out += [str(getattr(m, "help", "") or "") for m in at.metric]
    return "\n".join(out)


# ---------- status conflict rule (services) ----------
def test_status_conflict_rule_matches_the_raw_applications():
    expected = {a["id"] for a in APPS if a["offer_deadline"] and a["status"] in ("rejected", "withdrawn")}
    assert expected == {"a-201"} and {c["application_id"] for c in trust.status_conflicts()} == expected
    ok_ids = {a["id"] for a in APPS if a["offer_deadline"] and a["status"] in ("active", "hired")}
    assert ok_ids == {"a-105", "a-306"} and not ok_ids & expected                                  # active/hired with a deadline are fine


def test_status_conflict_text_and_explanation():
    c = trust.status_conflicts()[0]
    assert c["text"] == "Verify status: Rafael Mendoza — offer deadline Oct 20, but marked rejected"
    assert "Rafael Mendoza is marked rejected on Oct 9" in c["explanation"] and "no reason for the rejection" in c["explanation"]
    assert "Nothing was changed" in c["explanation"] and c["source"] == "applications.json:a-201"


def test_candidates_table_marks_the_status_conflict():
    flagged = [r["candidate"] for r in analytics.candidates_table() if r["status_conflict"]]
    assert flagged == ["Rafael Mendoza"] and D["conflicts"][0]["application_id"] == "a-201"


def test_candidates_page_has_a_flag_column_and_a_coral_box(monkeypatch):
    at = start("Candidates")
    assert not at.exception
    frame = at.dataframe[0].value
    assert "Flags" in frame.columns and "Rafael Mendoza" in set(frame["Candidate"]) and "⚠ Status conflict" in set(frame["Flags"])  # flagged rows first
    assert "**Status conflict: Rafael Mendoza**" in md(at) and "5 candidates need your attention" in md(at)       # 4 earlier flags + Rosa (score/text conflict)
    at.session_state["cand-tab"] = "By Role"
    at = at.run()
    at = at.selectbox(key="cand-pick-By Role").select("j-backend").run()                                   # another role: no conflict row
    assert "⚠ Status conflict" not in set(at.dataframe[0].value["Flags"])


def test_priority_actions_lists_the_status_conflict_first():
    at = start()
    text = md(at)
    assert "**Verify status: Rafael Mendoza**" in text and ":primary-badge[⚠ Status conflict]" in text
    assert any("offer deadline Oct 20, but marked rejected" in c.value for c in at.caption)
    first_task = D["tasks"]["priority"][0]
    assert text.index("Verify status: Rafael Mendoza") < text.index(f"**{first_task['task'].capitalize()}** · {first_task['candidate']}")


def test_offer_deadline_kpi_table_flags_the_rejected_application():
    at = start()
    at = at.button(key="kpi-btn-upcoming_offer_deadlines").click().run()
    frame = next(t.value for t in at.dataframe if "Application status" in t.value.columns)
    assert list(frame.loc[frame["Candidate"] == "Rafael Mendoza", "Flag"]) == [dashboard.CONFLICT_FLAG]


# ---------- why candidates leave ----------
def test_exits_match_the_raw_statuses_and_never_use_emails():
    total = trust.exit_reasons()
    raw_rejected = sum(a["status"] == "rejected" for a in APPS)
    raw_withdrawn = sum(a["status"] == "withdrawn" for a in APPS)
    assert total["withdrew"] == raw_withdrawn == 8
    assert total["rejected"] + total["unknown"] == raw_rejected == 19 and total["total"] == 27
    unknown_raw = [a["id"] for a in APPS if a["status"] == "rejected" and (not a["rejection_reason"] or a["offer_deadline"])]
    assert unknown_raw == ["a-201"] and total["unknown"] == 1
    per_role = [trust.exit_reasons(j) for j in D["funnels"]]
    assert sum(e["total"] for e in per_role) == total["total"] and sum(e["unknown"] for e in per_role) == 1
    import inspect
    source = inspect.getsource(trust.exit_reasons)
    assert "emails" not in source and "email" not in source.lower().replace("emails are never used", "")


def test_exits_donut_has_the_total_in_the_centre_and_a_note_when_there_is_nothing_to_show():
    e = trust.exit_reasons("j-designer")
    fig = dashboard.exits_figure(e)
    assert list(fig.data[0].labels) == ["Rejected", "Withdrew", "Unknown"] and list(fig.data[0].values) == [5, 2, 1]
    assert fig.data[0].hole > 0.5 and any(str(e["total"]) in a.text for a in fig.layout.annotations)
    assert "percent" in fig.data[0].hovertemplate and "value" in fig.data[0].hovertemplate
    empty = trust.exit_reasons("j-nobody")
    assert empty["total"] == 0 and "Nobody has left" in empty["note"] and dashboard.exits_figure(empty) is None
    mostly_unknown = {**e, "rejected": 0, "withdrew": 1, "unknown": 5, "total": 6, "note": "Most exits have no usable reason in the data, so a chart would mislead."}
    assert dashboard.exits_figure(mostly_unknown) is None


def test_exit_donut_follows_the_role_filter():
    at = start()
    first = [json.loads(e.proto.spec) for e in at.get("plotly_chart") if e.key == "chart-exits"][0]["data"][0]["values"]
    assert first == [8, 5]                                                                              # Senior Backend Engineer: rejected 8, withdrew 5
    at = at.selectbox(key="dash-role").select("j-designer").run()
    assert [json.loads(e.proto.spec) for e in at.get("plotly_chart") if e.key == "chart-exits"][0]["data"][0]["values"] == [5, 2, 1]


# ---------- data coverage ----------
def test_coverage_numbers_match_the_raw_files():
    cov = {c["label"]: c for c in trust.coverage()}
    cards = json.loads((RAW / "scorecards.json").read_text(encoding="utf-8"))
    submitted = sum(bool(c["text"]) for c in cards)
    assert (cov["Submitted scorecards"]["have"], cov["Submitted scorecards"]["of"]) == (submitted, len(cards)) == (75, 80)
    people = 44
    assert cov["CVs"]["of"] == cov["Recruiter emails"]["of"] == people == len(CANDS) - 1               # 45 records, one duplicate person
    assert len(list((RAW / "cvs").iterdir())) == 43 and cov["CVs"]["have"] == 42                      # 43 files, one shared by the duplicate pair
    assert len(list((RAW / "emails").glob("*.eml"))) == 235 and cov["Recruiter emails"]["have"] == 44
    assert all(c["available"] and c["pct"] == pytest.approx(c["have"] / c["of"]) for c in cov.values())


def test_coverage_says_not_available_when_it_cannot_be_computed(monkeypatch):
    def broken():
        raise RuntimeError("no db")
    monkeypatch.setattr(trust, "connect", broken)
    cov = trust.coverage()
    assert all(not c["available"] and c["pct"] is None and c["have"] is None for c in cov)


def test_coverage_rings_show_percent_in_the_centre_and_n_of_m():
    at = start()
    text = md(at)                                                                                      # Part C: one plain sentence per ring
    assert "42 of 44 candidates have a CV" in text and ":primary[ — 2 missing]" in text
    assert "All 44 candidates have recruiter emails" in text
    assert "75 of 80 interviews have feedback" in text and ":primary[ — 5 not submitted yet]" in text
    fig = dashboard.ring_figure(D["coverage"][0])
    assert fig.data[0].hole > 0.6 and "95%" in fig.layout.annotations[0].text
    assert "%{value} of 44" in fig.data[0].hovertemplate


# ---------- data quality in plain English ----------
def test_every_issue_type_in_the_data_has_a_plain_english_line():
    types = {i["type"] for i in D["issues"]["records"]}
    assert types <= set(trust.ISSUE_TEXT), types - set(trust.ISSUE_TEXT)


def test_quality_groups_add_up_to_the_issue_total_and_use_the_agreed_wording():
    q = D["quality"]
    assert [g["title"] for g in q.values()] == ["Fixed Automatically", "Needs Your Review", "Left Unchanged"]
    assert sum(g["total"] for g in q.values()) == D["issues"]["total"] == 57
    assert (q["fixed"]["total"], q["human"]["total"], q["left"]["total"]) == (34, 7, 16)
    lines = {l["type"]: l for g in q.values() for l in g["lines"]}
    assert lines["email_on_merged_person"]["text"] == "14 emails were linked to a duplicate candidate record — merged"
    assert lines["duplicate_person"]["text"].startswith("1 person had two candidate records")
    assert all(re.match(r"^\d+ ", l["text"]) and l["n"] == len(l["sources"]) for l in lines.values())    # every line starts with its count
    assert "no_feedback_yet" not in lines                                                                # missing feedback is not a data error


def test_unknown_issue_types_default_to_needs_a_human(monkeypatch):
    monkeypatch.setattr(trust, "ISSUE_TEXT", {k: v for k, v in trust.ISSUE_TEXT.items() if k != "missing_date"})
    q = trust.quality_groups()
    assert any(l["type"] == "missing_date" for l in q["human"]["lines"])


def test_trust_card_shows_three_columns_rings_and_the_details_expander():
    at = start()
    text = md(at)
    for title in ("Data Health Check", "Data Quality", "Fixed Automatically**", "Needs Your Review**", "Left Unchanged**"):
        assert title in text
    assert "57 issues found" in text and "37 high severity" in text and "# 34" in text and "# 7" in text and "# 16" in text
    keys = " ".join(h.value for h in at.main.get("html"))                                               # legend under the stacked bar
    assert "34 Fixed" in keys and "7 Need Review" in keys and "16 Left Unchanged" in keys           # legend wording from the approved spec
    grouped = next(t.value for t in at.dataframe if "Explanation" in t.value.columns)                  # tables instead of bullet lists
    assert "14 emails were linked to a duplicate candidate record — merged" in set(grouped["Explanation"])
    assert any(e.label == "View All Issues & Sources" for e in at.expander)
    table = next(t.value for t in at.dataframe if "Handling" in t.value.columns)
    assert len(table) == 57 and table["Source"].str.contains(":").all()


# ---------- needs your decision ----------
def test_decision_alerts_are_rule_based_and_at_most_four():
    kinds = [a["kind"] for a in D["decisions"]]
    assert kinds == ["status_conflict", "offer_passed", "score_text", "stalled"] and len(D["decisions"]) <= 4
    by = {a["kind"]: a for a in D["decisions"]}
    deadline = next(a for a in APPS if a["id"] == "a-105")
    assert deadline["status"] == "active" and deadline["offer_deadline"] < config.REFERENCE_DATE.isoformat()     # raw data: the deadline passed
    assert "Jonah Whitfield" in by["offer_passed"]["title"] and "ranked #1" in by["offer_passed"]["text"]
    top = ranking.rank_candidates_for_job("j-backend", 3)["data"]["ranked"][0]
    assert top["name"] == "Jonah Whitfield" and top["rank"] == 1                                        # the rule really used the ranking service
    first = D["stalled"]["rows"][0]
    assert first["candidate"] in by["stalled"]["title"] and str(first["days_in_stage"]) in by["stalled"]["text"]
    assert all(a["question"] and a["source"] for a in D["decisions"])


def test_decision_alerts_page_buttons_and_no_ask_card():
    assert not [b for b in start().button if b.key.startswith("decision-ask-")]                       # Part C: moved off the Overview
    at = start("Candidates")
    assert [b.label for b in at.button if b.key.startswith("decision-ask-")] == ["Ask AI about this"] * 4
    assert "Ask HirePilot AI" not in all_text(at) and not any(e.key == "ask-q" for e in at.text_input)


# ---------- the panel ----------
def test_tiles_are_stacked_with_title_and_description_and_no_cost():
    at = start()
    assert [b.label for b in at.button if b.key.startswith("pbtn-")] == ["Find Top Candidates", "Find Drop-offs", "Check Pending Tasks"]
    caps = [c.value for c in at.caption]
    for d in ("Compare the best matches", "Where candidates leave the process", "See what needs attention"):
        assert d in caps
    assert [t[1] for t in panel.tiles("X")] == ["Find Top Candidates", "Find Drop-offs", "Check Pending Tasks"]
    assert [t[3] for t in panel.tiles("X")] == [":material/emoji_events:", ":material/bar_chart:", ":material/check_box:"]


@pytest.mark.parametrize("page", ["Overview", "Ask AI", "Candidates", "Tasks"])
def test_no_cost_label_anywhere(page, monkeypatch):
    fake = FakeAgent([with_ranking()])
    at = start(page, fake, monkeypatch)
    if page == "Overview":
        at = at.button(key="pbtn-top").click().run()
    text = all_text(at).lower()
    for word in ("per question", "this chat:", "estimate", "0.03", "cost"):
        assert word not in text, (page, word)
    assert not any("$" in c.value for c in at.caption)


def test_top_candidates_summary_has_three_rows_from_the_tool_result(monkeypatch):
    fake = FakeAgent([with_ranking()])
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="pbtn-top").click().run()
    svc = ranking.rank_candidates_for_job("j-backend", 3)["data"]["ranked"]
    text = md(at)
    for i, r in enumerate(svc, 1):
        assert f"**#{i} {r['name']}**" in text and f"**{r['score']:.0f}**/100" in text and r["current_stage"] in text
    assert text.count("**#") == 3
    assert ":primary-badge[⚠ Offer deadline overdue]" in text                                            # Jonah Whitfield: deadline passed
    assert "Intro line" not in text and "AI ASSESSMENT" not in text                                      # a summary, not the answer


def test_flags_come_from_services_and_the_tool_result_not_from_the_text():
    chart = chat.add_flags(chat.ranking_chart_data([ranking_call()]))
    rows = {r["name"]: r for r in chart["rows"]}
    assert rows["Jonah Whitfield"]["flags"][0] == "Offer deadline overdue" and rows["Jonah Whitfield"]["urgent"]
    svc = {r["name"]: r for r in ranking.rank_candidates_for_job("j-backend", 3)["data"]["ranked"]}
    for name, r in rows.items():
        n = len(svc[name]["open_tasks"])
        assert (f"{n} open task" in " ".join(r["flags"])) == bool(n)
        assert ("Thin evidence (1 scorecard)" in r["flags"]) == (svc[name]["evidence_level"] == "thin")
    assert evidence.service_flags(["a-201"]) == {"a-201": ["Status conflict"]} and evidence.service_flags([]) == {}


def test_other_questions_show_the_first_paragraph_of_facts_only(monkeypatch):
    answer = "FACTS\n- Five tasks are overdue. [applications.json:a-105]\n- Two are due today.\n\n- Hidden second paragraph.\n\nAI ASSESSMENT\nHidden judgement."
    fake = FakeAgent([result(answer=answer)])
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="pbtn-tasks").click().run()
    text = md(at)
    assert "Five tasks are overdue" in text and "Two are due today" in text
    assert "Hidden second paragraph" not in text and "Hidden judgement" not in text
    assert chat.first_paragraph("a\nb\nc\nd\ne") == "a\nb\nc\n…" and chat.first_paragraph("") == ""
    assert chat.summary_text("No headings here.\n\nSecond.") == "No headings here."


def test_read_full_answer_and_open_full_chat_are_buttons_that_ask_nothing(monkeypatch):
    fake = FakeAgent([result(answer="FACTS\n- one [applications.json:a-105]")])
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="pbtn-tasks").click().run()
    assert [b.label for b in at.button if b.key.startswith("read-full-")] == ["Read full answer"]
    assert any(b.key == "open-chat" and b.label == "Open full chat" for b in at.button)
    at = at.button(key="open-chat").click().run()
    assert at.session_state["page"] == "Ask AI" and len(fake.calls) == 1 and "one" in md(at)


def test_the_follow_up_form_is_still_in_the_panel():
    at = start()
    assert at.text_input(key="ai-q").placeholder == "Ask a follow-up question..." and any(b.key == "ai-send" for b in at.button)


def test_a_typed_question_is_classified_by_the_tools_used_not_by_the_text():
    assert chat.answer_kind("top", []) == "top"
    assert chat.answer_kind(None, [{"name": "rank_candidates_for_job", "ok": True}]) == "top"
    assert chat.answer_kind(None, [{"name": "get_funnel", "ok": True}]) == "dropoffs"
    assert chat.answer_kind(None, [{"name": "list_tasks", "ok": True}]) == "tasks"
    assert chat.answer_kind(None, [{"name": "get_funnel", "ok": False}]) == "other" and chat.answer_kind(None, []) == "other"


# ---------- KPI text, selected role, layout ----------
def test_kpi_subtitles_use_plain_words():
    at = start()
    caps = [c.value for c in at.caption]
    assert "2 overdue · 1 due today · 2 waiting" in caps and "2 overdue" in caps
    assert "1 more on a rejected application · ⚠ status conflict" in caps
    assert not any(c.startswith("incl.") for c in caps)


def test_selected_role_is_highlighted_and_viewing_label_follows_it():
    at = start()
    assert "Viewing: **Senior Backend Engineer**" in md(at)
    assert '[class*="st-key-role-row-"][class*="-selected"] {{ border-left: 5px solid' in theme_source()    # coral bar + light background
    at = at.button(key="role-btn-j-csm").click().run()
    assert "Viewing: **Customer Success Manager**" in md(at) and "Viewing: **Senior Backend Engineer**" not in md(at)
    assert at.session_state["dash-role"] == "j-csm"


def theme_source():
    from web import theme
    return open(theme.__file__, encoding="utf-8").read()


def test_overview_order_top_section_then_full_width_rows():
    text = md(at := start())
    order = ["Recruiting Intelligence", "Viewing: **", "Recruitment Funnel", "Median Days in Stage", "Why candidates leave",
             "Data Health Check", "Data Quality", "Roles compared"]
    positions = [text.index(t) for t in order]
    assert positions == sorted(positions), dict(zip(order, positions))
    assert not at.exception


def test_every_mockup_feature_uses_only_free_data_sources(monkeypatch):
    fake = FakeAgent()
    at = start("Overview", fake, monkeypatch)
    at = at.button(key="kpi-btn-overdue_tasks").click().run()
    at = at.button(key="role-btn-j-designer").click().run()
    assert fake.calls == [] and not at.exception


# ---------- guards ----------
def test_evidence_and_trust_modules_have_no_sql_in_the_web_layer():
    import ast
    source = (config.ROOT / "web" / "evidence.py").read_text(encoding="utf-8")
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])}
    assert imported == {"backend.services"} and "SELECT" not in source and "sqlite3" not in source and "ask_sync" not in source
    trust_src = (config.ROOT / "backend" / "services" / "trust.py").read_text(encoding="utf-8")
    assert "print(" not in trust_src and "streamlit" not in trust_src and "anthropic" not in trust_src
