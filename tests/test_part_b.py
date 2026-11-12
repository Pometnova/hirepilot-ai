"""UI polish, Part B: the Ask AI page (buttons, answer layout by question kind, expanders, readable sources, highlighted
names), "Ask AI about this" opening the Ask AI page, the global footer, page endings, consistency. FREE: fake agent only."""
import json
import re
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.agent import core
from backend.services import analytics, sources, trust
from tests.test_app import FakeAgent, result
from tests.test_stage3 import ANSWER, md, ranking_call, start, with_ranking
from web import answer, chat, dashboard, panel, theme

D = analytics.dashboard()
CANDS = json.loads((config.RAW_DIR / "candidates.json").read_text(encoding="utf-8"))
EXPANDERS = ["Detailed evidence", "Data issues & assumptions", "Sources (3)", "How this was calculated"]


def funnel_call(job="j-csm"):
    return {"round": 1, "name": "get_funnel", "input": {"job_id": job}, "ok": True, "error_code": None, "items": 6, "ms": 3}


def tasks_call():
    return {"round": 1, "name": "list_tasks", "input": {"state": "all"}, "ok": True, "error_code": None, "items": 11, "ms": 3}


def ask(click, fake, monkeypatch, typed=None):
    at = start("Ask AI", fake, monkeypatch)
    if typed:
        return at.chat_input[0].set_value(typed).run()
    return at.button(key=f"askbtn-{click}").click().run()


# ---------- 1. "Ask AI about this" opens the Ask AI page ----------
def test_ask_ai_about_this_opens_the_ask_ai_page_and_shows_the_answer_there(monkeypatch):
    fake = FakeAgent([result(answer="FACTS\n- Rafael Mendoza is marked rejected. [applications.json:a-201]\n\nAI ASSESSMENT\nCheck it.")])
    at = start("Candidates", fake, monkeypatch)                                                          # Part C: the decision box is on Candidates
    at = at.button(key="decision-ask-0").click().run()
    assert fake.calls == [] and not at.chat_message                                                      # first a clean Ask AI page, nothing asked yet
    at = at.run()
    assert at.session_state["page"] == "Ask AI" and [q for q, _ in fake.calls] == [D["decisions"][0]["question"]]
    assert len(at.chat_message) == 2 and "##### AI ASSESSMENT" in md(at)                                # the full answer, on the Ask AI page
    assert "pending" not in at.session_state                                                             # used once, not repeated
    at = at.button(key="askbtn-tasks").click().run()
    assert len(fake.calls) == 2                                                                          # a rerun / next click does not resend it


# ---------- 2. the three buttons ----------
def test_ask_page_has_the_same_three_buttons_as_the_panel(monkeypatch):
    at = start("Ask AI", FakeAgent(), monkeypatch)
    assert [b.label for b in at.main.button] == [t[1] for t in panel.tiles("X")] == ["Find Top Candidates", "Find Drop-offs", "Check Pending Tasks"]
    assert [b.icon for b in at.main.button] == [t[3] for t in panel.tiles("X")]
    assert [b.key for b in at.main.button] == ["askbtn-top", "askbtn-dropoffs", "askbtn-tasks"]
    css = theme.CSS
    rule = css[css.index('[class*="st-key-askbtn-"] button {'):]
    rule = rule[:rule.index("}") + 1]
    assert "background: #1A0B3F" in rule and "color: #FFFFFF" in rule and "border-radius: 10px" in rule and "white-space: nowrap" in rule   # all three the same
    assert 'st-key-askbtn-top' not in css and 'st-key-askbtn-tasks' not in css and 'st-key-askbtn-dropoffs' not in css            # no per-button styles
    assert 'span[data-testid="stIconMaterial"] { color: #FF7964' in css and "button:hover { background: #34245D" in css
    assert "button:focus-visible { outline: 2px solid #FF7964" in css and "cursor: pointer" in css


def test_buttons_follow_the_role_selected_on_the_overview(monkeypatch):
    fake = FakeAgent([result()])
    at = start("Overview", fake, monkeypatch)
    at = at.selectbox(key="dash-role").select("j-designer").run()
    at.session_state["page"] = "Ask AI"
    at = at.run()
    at = at.button(key="askbtn-top").click().run()
    assert fake.calls[0][0] == "Who are the top 3 candidates for Product Designer, and why?"


# ---------- 3. layout by kind ----------
def test_top_candidates_layout_cards_then_chart_then_ai_then_collapsed_expanders(monkeypatch):
    at = ask("top", FakeAgent([with_ranking()]), monkeypatch)
    text = md(at)
    for i in (1, 2, 3):
        assert f"### #{i}" in text
    assert ":primary-badge[⚠ Offer deadline overdue]" in text and text.count("**Interview & Progress Score**") == 1
    assert text.index("### #1") < text.index("**Interview & Progress Score**") < text.index("##### AI ASSESSMENT")
    assert "##### FACTS" not in text and "##### ASSUMPTIONS" not in text                                # these two live in expanders on this layout
    assert [e.label for e in at.expander] == EXPANDERS and not any(e.proto.expanded for e in at.expander)
    assert any(e.key.startswith("rank-ask") for e in at.get("plotly_chart"))
    fig = next(json.loads(e.proto.spec) for e in at.get("plotly_chart") if e.key.startswith("rank-ask"))
    assert any("not measured" in a.get("text", "") for a in fig["layout"]["annotations"])                 # never 0


def test_a_typed_question_gets_the_layout_of_the_tools_the_agent_used(monkeypatch):
    at = ask(None, FakeAgent([with_ranking()]), monkeypatch, typed="Who is strongest for backend?")
    assert "### #1" in md(at) and any(e.key.startswith("rank-ask") for e in at.get("plotly_chart"))
    other = result(answer=ANSWER, calls=[{**tasks_call(), "name": "get_data_issues"}])
    at = ask(None, FakeAgent([other]), monkeypatch, typed="Anything odd in the data?")
    text = md(at)
    assert "##### FACTS" in text and "##### AI ASSESSMENT" in text and "##### ASSUMPTIONS & CAVEATS" in text
    assert [e.label for e in at.expander] == ["Sources (3)", "How this was calculated"]
    assert not at.get("plotly_chart")


def test_drop_offs_layout_uses_the_services_for_the_role_the_agent_asked_about(monkeypatch):
    at = ask("dropoffs", FakeAgent([result(answer=ANSWER, calls=[funnel_call("j-csm")])]), monkeypatch)
    assert "Viewing: **Customer Success Manager**" in md(at)
    keys = [e.key for e in at.get("plotly_chart")]
    assert [k.split("-ask")[0] for k in keys] == ["funnel", "dwell", "exits"]
    funnel = json.loads(at.get("plotly_chart")[0].proto.spec)["data"][0]
    assert funnel["x"] == [s["reached"] for s in D["funnels"]["j-csm"]["stages"]]
    assert md(at).index("Viewing:") < md(at).index("##### AI ASSESSMENT")
    assert [e.label for e in at.expander] == EXPANDERS


def test_tasks_layout_has_counts_and_a_urgency_sorted_table(monkeypatch):
    at = ask("tasks", FakeAgent([result(answer=ANSWER, calls=[tasks_call()])]), monkeypatch)
    text = md(at)
    for n in D["tasks"]["counts"].values():
        assert f"## {n}" in text
    frame = at.dataframe[0].value
    assert len(frame) == 11 and list(frame["State"][:5]) == ["Overdue"] * 5
    order = {"Overdue": 0, "Due today": 1, "Pending": 2, "Pending, no due date": 3}
    assert [order[s] for s in frame["State"]] == sorted(order[s] for s in frame["State"])
    assert text.index("## 5") < text.index("##### AI ASSESSMENT")


def test_the_button_decides_the_layout_even_if_the_agent_used_other_tools(monkeypatch):
    at = ask("tasks", FakeAgent([result(answer=ANSWER, calls=[funnel_call()])]), monkeypatch)
    assert len(at.dataframe[0].value) == 11 and not at.get("plotly_chart")


def test_top_without_a_ranking_result_falls_back_to_the_plain_blocks(monkeypatch):
    at = ask("top", FakeAgent([result(answer=ANSWER, calls=[])]), monkeypatch)
    assert "##### FACTS" in md(at) and "### #1" not in md(at)


# ---------- 4. block headers, judgement, names ----------
def test_ai_block_has_subtitle_and_the_leading_judgement_tag_is_hidden_in_the_ui_only(monkeypatch):
    raw = "FACTS\n- One. [applications.json:a-105]\n\nAI ASSESSMENT\n(my judgement) Jonah looks strongest.\n\nCAVEATS\n- Weights are assumed."
    fake = FakeAgent([result(answer=raw, calls=[])])
    at = ask("tasks", fake, monkeypatch)
    text = md(at)
    assert "(my judgement)" not in text and "Jonah looks strongest" in text
    assert "AI reasoning based on the facts above" in [c.value for c in at.caption]
    assert at.session_state["messages"][1]["content"] == raw                                             # the stored answer is untouched
    css = theme.CSS
    assert "answer-block-ai-\"] h5 { color: #FF674C" in css and "answer-block-facts\"] h5 { color: #75619B" in css
    assert "answer-block-caveats\"] { border-left-color: #B7A9D3; background: rgba(233,227,242" in css


def test_candidate_names_stand_out():
    assert answer.highlight("Jonah Whitfield is strong.") == "**:violet[Jonah Whitfield]** is strong."
    assert answer.highlight("**Jonah Whitfield** and Maya Chen") == "**:violet[Jonah Whitfield]** and **:violet[Maya Chen]**"
    assert answer.highlight("No names here, only Jonahs.") == "No names here, only Jonahs."
    assert answer.highlight("") == ""
    assert set(answer.names()) == {c["name"] for c in CANDS}


def test_names_are_highlighted_in_the_answer_blocks(monkeypatch):
    raw = "FACTS\n- Maya Chen has been in Onsite for 34 days.\n\nAI ASSESSMENT\nMaya Chen needs a nudge."
    at = ask("tasks", FakeAgent([result(answer=raw, calls=[])]), monkeypatch)
    assert md(at).count("**:violet[Maya Chen]**") == 2                                                   # AI block + the collapsed "Detailed evidence"
    assert "Detailed evidence" in [e.label for e in at.expander]
    at = ask(None, FakeAgent([result(answer=raw, calls=[{**tasks_call(), "name": "get_data_issues"}])]), monkeypatch, typed="x")
    assert md(at).count("**:violet[Maya Chen]**") == 2


# ---------- 5. readable sources ----------
def test_source_labels_are_a_db_lookup_grouped_by_candidate():
    refs = ["scorecards.json:s-104", "applications.json:a-105", "emails:20261014-1645-m-2022.eml", "stage_events.csv:71",
            "jobs.json:j-backend", "bogus:ref"]
    out = sources.source_labels(refs)
    assert out["count"] == 6
    by = {g["candidate"]: [i["label"] for i in g["items"]] for g in out["groups"]}
    assert by["Jonah Whitfield"] == ["Scorecard s-104 · Technical Screen · Jonah Whitfield", "Application a-105 · Senior Backend Engineer · Jonah Whitfield"]
    assert by["Theo Lindqvist"] == ["Email to Theo Lindqvist · Oct 14"] and by["Maya Chen"][0].startswith("Stage change (line 71) · Take-Home → Onsite")
    assert by["Other"] == ["Role j-backend · Senior Backend Engineer", "bogus:ref"]                       # unknown refs keep the raw text
    assert [g["candidate"] for g in out["groups"]][-1] == "Other"
    cards = json.loads((config.RAW_DIR / "scorecards.json").read_text(encoding="utf-8"))
    raw = next(c for c in cards if c["id"] == "s-104")
    assert raw["interview"] == "Technical Screen"                                                        # the label matches the raw file
    assert sources.source_labels([])["groups"] == [] and sources.source_labels(["a:b", "a:b"])["count"] == 1


def test_sources_expander_shows_label_and_raw_ref_small(monkeypatch):
    raw = "FACTS\n- X. [scorecards.json:s-104; applications.json:a-105]\n\nAI ASSESSMENT\nok"
    at = ask("tasks", FakeAgent([result(answer=raw, calls=[tasks_call()])]), monkeypatch)
    assert "Sources (2)" in [e.label for e in at.expander]
    text = md(at)
    assert "**Jonah Whitfield**" in text and "Scorecard s-104 · Technical Screen · Jonah Whitfield" in text
    assert {"scorecards.json:s-104", "applications.json:a-105"} <= {c.value for c in at.caption}


# ---------- 6. footer, page endings, consistency ----------
@pytest.mark.parametrize("page", ["Overview", "Ask AI", "Candidates", "Tasks"])
def test_footer_is_on_every_page_after_the_content(page, monkeypatch):
    at = start(page, FakeAgent(), monkeypatch)
    text = md(at)
    caps = [c.value for c in at.caption]
    if page == "Ask AI":                                                                                # Part C: the chat page has no footer
        assert "Smarter hiring. Clearer decisions." not in text and "Data snapshot" not in text and "Quillfeather Labs" not in caps
        assert not at.chat_message and len(at.chat_input) == 1 and len(at.main.get("image")) == 0
        return
    assert "**Smarter hiring. Clearer decisions.**" in text and "Data snapshot: **Oct 15, 2026**" in text
    assert "Quillfeather Labs" in caps and "AI-assisted insights · Human-reviewed decisions" in caps
    last_content = {"Overview": "Roles compared", "Ask AI": "Data as of", "Candidates": "Stalled candidates", "Tasks": "Open tasks ("}[page]
    assert text.rfind(last_content) < text.index("Smarter hiring")                                      # footer comes last
    assert len(at.main.get("image")) == 1 and len(at.sidebar.get("image")) == 1                         # footer logo in the main area, sidebar logo
    assert not at.exception


def test_footer_snapshot_date_follows_the_config(monkeypatch):
    monkeypatch.setattr(config, "REFERENCE_DATE", date(2030, 1, 2))
    assert "Data snapshot: **Jan 2, 2030**" in md(start("Tasks", FakeAgent(), monkeypatch))


def test_footer_css_is_not_fixed_and_uses_the_sidebar_colour():
    css = theme.CSS
    block = css[css.index('st-key-site-footer"] {'):]
    block = block[:block.index("}") + 1]
    assert "background: #1A0B3F" in block and "position" not in block and "fixed" not in block and "sticky" not in block
    assert "#FFFFFF" in css[css.index('st-key-site-footer"] p'):][:80] and "#BDB3D6" in css                  # white primary, lavender secondary
    assert "border-top: 3px solid #FF674C" in block                                                      # coral accent
    assert "rgba(231,225,244,.18)" in css                                                                # subtle divider
    assert "position: fixed" not in css and "position: sticky" not in css


def test_the_footer_logo_is_the_existing_logo_and_no_mockup_text_is_added():
    source = (config.ROOT / "web" / "app.py").read_text(encoding="utf-8")
    assert 'ASSETS / "logo_sidebar.png"' in source and (config.ROOT / "assets" / "logo_sidebar.png").is_file()


def test_no_nested_scrolling_and_a_normal_gap_at_the_page_end():
    for name in ("app", "dashboard", "panel", "chat", "answer", "pages_data"):
        source = (config.ROOT / "web" / f"{name}.py").read_text(encoding="utf-8")
        assert "container(height=" not in source and "min(35" not in source, name                       # no scroll boxes, no capped tables
    assert dashboard.table_height(45) == 35 * 46 + 3                                                     # every row is shown
    pad = re.search(r"\.block-container \{ padding: ([\d.]+)rem [\d.]+rem ([\d.]+)rem", theme.CSS.replace("{{", "{"))
    assert pad and float(pad.group(2)) <= 2


def test_every_table_is_as_tall_as_its_rows():
    for name in ("pages_data", "dashboard", "answer"):
        source = (config.ROOT / "web" / f"{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"dataframe\([^\n]*height=\d", source) and "height=min" not in source
    assert "height=dashboard.table_height(len(rows))" in (config.ROOT / "web" / "pages_data.py").read_text(encoding="utf-8")


def test_one_chart_style_everywhere(monkeypatch):
    for page in ("Overview", "Tasks"):
        for el in start(page, FakeAgent(), monkeypatch).get("plotly_chart"):
            layout = json.loads(el.proto.spec)["layout"]
            assert layout["font"]["family"] == theme.FONT and layout["paper_bgcolor"] == "rgba(0,0,0,0)", el.key
            assert layout["hoverlabel"]["bordercolor"] == theme.CORAL, el.key


def test_cards_expanders_and_candidate_cards_share_the_same_radius_and_hover_is_coral():
    css = theme.CSS
    for selector in ('[class*="st-key-card-"] {', '[data-testid="stExpander"] {', '[class*="st-key-cand-card-"] {',
                     '[class*="st-key-ranking-card-"], [class*="st-key-answer-view-"] {', '[class*="st-key-site-footer"] {'):
        i = css.index(selector)
        assert "border-radius: 12px" in css[i:css.index("}", i)], selector
    assert '[data-testid="stExpander"] summary:hover' in css and "color: #FF674C !important" in css


def test_no_appearance_or_settings_items(monkeypatch):
    for page in ("Overview", "Ask AI"):
        at = start(page, FakeAgent(), monkeypatch)
        text = " ".join([m.value for m in at.markdown] + [b.label for b in at.button])
        assert "Appearance" not in text and "Settings" not in text


def test_answer_module_has_no_data_access_and_no_model_call():
    import ast
    source = (config.ROOT / "web" / "answer.py").read_text(encoding="utf-8")
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])}
    assert not any(m and ("sqlite3" in m or "services" in m or "ingest" in m or "anthropic" in m) for m in imported), imported
    assert "SELECT " not in source and "unsafe_allow_html" not in source and "ask_sync" not in source


def test_footer_is_responsive_and_only_existing_images_are_used():
    css = theme.CSS
    assert 'st-key-site-footer"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap' in css and "min-width: 190px" in css       # columns wrap
    assert "@media (max-width: 900px)" in css and "border-left: 0; padding-left: 0" in css                                # compact on small screens
    assert ".stMain { overflow-x: hidden; }" in css                                                                       # no sideways scrolling
    app = (config.ROOT / "web" / "app.py").read_text(encoding="utf-8")
    assert set(re.findall(r'ASSETS / "([\w.]+)"', app)) == {"logo_sidebar.png", "logo_icon.png"}                          # the existing logo and mark only
    assert sorted(p.name for p in (config.ROOT / "assets").iterdir() if p.suffix == ".png") == ["logo_dark.png", "logo_icon.png", "logo_sidebar.png"]   # no new images


def test_the_existing_icons_are_kept():
    src = (config.ROOT / "web" / "app.py").read_text(encoding="utf-8")
    for icon in (":material/bar_chart:", ":material/chat_bubble:", ":material/group:", ":material/task_alt:"):
        assert icon in src                                                                                              # the sidebar icons
    assert dashboard.KPI_ICON == {"overdue_tasks": ":material/warning:", "pending_scorecards": ":material/description:",
                                  "unanswered_emails": ":material/mail:", "upcoming_offer_deadlines": ":material/calendar_month:"}
