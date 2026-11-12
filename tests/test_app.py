"""Phase 5 tests for web/app.py. FREE: Streamlit's AppTest runs the real app script, and core.ask_sync is replaced by a
fake agent. No Claude API call, no MCP server, no key."""
import ast
import tomllib
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Block

from backend import config
from backend.agent import core
from backend.agent.core import AgentResult
from web import panel

APP = str(config.ROOT / "web" / "app.py")
QUESTIONS = [t[4] for t in panel.tiles("Senior Backend Engineer")]        # the three buttons of the Ask AI page (same as the panel tiles)
SENTINEL = "sk-ant-api03-TESTSENTINEL0123456789abcdef"


# ---------- helpers ----------
def result(answer="FACTS\n- Five tasks are overdue. [applications.json:a-105]", status="ok", error=None, calls=None, cost=0.03, **kw):
    r = AgentResult(question="q", answer=answer, status=status, rounds=2, model="claude-sonnet-5-5", error=error,
                    tool_calls=calls if calls is not None else [
                        {"round": 1, "name": "list_tasks", "input": {"state": "all"}, "ok": True, "error_code": None, "items": 11, "ms": 12}],
                    estimated_cost_usd=cost, **kw)
    r.usage = {"input_tokens": 8, "output_tokens": 1260, "cache_read_tokens": 7197, "cache_creation_tokens": 6271, "requests": 2}
    return r


class FakeAgent:
    """Replaces core.ask_sync. Records every call (question, history). `plan` is a list of results/exceptions or a callable."""

    def __init__(self, plan=None):
        self.plan, self.calls = plan if plan is not None else [result()], []

    def __call__(self, question, history=None, **kw):
        self.calls.append((question, list(history or [])))
        item = self.plan(question) if callable(self.plan) else self.plan[min(len(self.calls) - 1, len(self.plan) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake(monkeypatch):
    f = FakeAgent()
    monkeypatch.setattr(core, "ask_sync", f)
    return f


def start(page="Ask AI"):
    """The chat lives on the Ask AI page (Stage 1 redesign); the sidebar buttons set st.session_state.page."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["page"] = page
    return at.run()


def page_text(at):
    """Every piece of text on the page (main area and sidebar), including expander labels and error boxes."""
    out = []

    def walk(block):
        for el in block.children.values():
            if isinstance(el, Block):
                out.append(str(getattr(el, "label", "") or ""))
                walk(el)
            else:
                for attr in ("value", "label", "body", "help", "placeholder", "icon"):
                    v = getattr(el, attr, None)
                    if isinstance(v, str):
                        out.append(v)
    walk(at.main)
    walk(at.sidebar)
    return "\n".join(out)


def click_example(at, i):
    return at.main.button[i].click().run()


# ---------- 1. renders ----------
def test_app_renders_with_banner_and_three_example_buttons(fake):
    at = start()
    assert not at.exception
    assert any("Data as of 2026-10-15" in i.value for i in at.info)
    assert [b.label for b in at.main.button] == ["Find Top Candidates", "Find Drop-offs", "Check Pending Tasks"] and len(at.main.button) == 3
    assert len(at.chat_input) == 1 and len(at.chat_message) == 0
    assert fake.calls == []                                           # nothing is asked until the user acts


def test_banner_date_comes_from_config(fake, monkeypatch):
    monkeypatch.setattr(config, "REFERENCE_DATE", date(2030, 1, 2))
    assert any("Data as of 2030-01-02" in i.value for i in start().info)


# ---------- 2. buttons send their question, the answer is shown ----------
@pytest.mark.parametrize("i", [0, 1, 2])
def test_clicking_a_button_sends_that_question_and_shows_the_answer(fake, i):
    at = click_example(start(), i)
    assert not at.exception
    assert fake.calls == [(QUESTIONS[i], [])]              # exact question, empty history
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    text = page_text(at)
    assert QUESTIONS[i] in text and "Five tasks are overdue" in text


def test_how_this_was_calculated_panel_is_collapsed_and_lists_tools_and_has_no_cost(fake):
    at = click_example(start(), 2)
    panels = [e for e in at.expander if e.label == "How this was calculated"]
    assert len(panels) == 1 and panels[0].proto.expanded is False
    inside = "\n".join(str(getattr(c, "value", "")) for c in panels[0].children.values())
    assert "list_tasks" in inside and '{"state": "all"}' in inside and "ok" in inside
    assert "Rounds: 2" in inside and "1260 output" in inside and "7197 cache read" in inside
    assert "cost" not in inside.lower() and "estimate" not in inside.lower() and "$" not in inside        # no cost label anywhere


def test_typed_question_and_followup_history(fake):
    at = start()
    at = click_example(at, 0)
    at = at.chat_input[0].set_value("and who is second?").run()
    assert fake.calls[1][0] == "and who is second?"
    assert fake.calls[1][1] == [{"role": "user", "content": QUESTIONS[0]},
                                {"role": "assistant", "content": result().answer}]
    assert [m.name for m in at.chat_message] == ["user", "assistant", "user", "assistant"]
    assert "This chat" not in page_text(at) and "estimate" not in page_text(at).lower()      # the running cost estimate is gone


def test_history_is_capped_and_failed_answers_are_left_out(monkeypatch):
    monkeypatch.setattr(config, "UI_MAX_HISTORY_TURNS", 2)
    plan = [result("A1"), result("", "api_error", "Rate limit reached. Try again in a moment."), result("A3"), result("A4"), result("A5")]
    f = FakeAgent(plan)
    monkeypatch.setattr(core, "ask_sync", f)
    at = start()
    for q in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        at = at.chat_input[0].set_value(q).run()
    history = f.calls[4][1]                                           # what Q5 was sent with
    assert [m["content"] for m in history] == ["Q3", "A3", "Q4", "A4"]           # last 2 good pairs; Q2 (failed) is gone
    assert f.calls[2][1] == [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]


def test_new_chat_clears_everything(fake):
    at = click_example(start(), 0)
    assert len(at.chat_message) == 2
    at = at.sidebar.button(key="new-chat").click().run()
    assert len(at.chat_message) == 0 and "This chat" not in page_text(at)
    at = click_example(at, 1)
    assert fake.calls[-1][1] == []                                    # no history after a new chat


# ---------- 3. friendly errors, no traceback ----------
@pytest.mark.parametrize("res,expect", [
    (result("", "api_error", "Rate limit reached. Try again in a moment.", calls=[]), "couldn't get an answer"),
    (result("", "config_error", "ANTHROPIC_API_KEY is not set.", calls=[]), "API key is missing"),
    (ValueError("anything"), "Something went wrong"),
])
def test_errors_show_a_friendly_message_and_no_traceback(monkeypatch, res, expect):
    monkeypatch.setattr(core, "ask_sync", FakeAgent([res]))
    at = click_example(start(), 0)
    assert not at.exception                                          # Streamlit shows uncaught errors as exception elements
    assert len(at.error) == 1 and expect in at.error[0].value
    assert "Traceback" not in page_text(at) and "File \"" not in page_text(at)


def test_api_error_message_has_the_reason_and_a_retry_hint(monkeypatch):
    monkeypatch.setattr(core, "ask_sync", FakeAgent([result("", "api_error", "Rate limit reached. Try again in a moment.", calls=[])]))
    at = click_example(start(), 0)
    assert "Rate limit reached" in at.error[0].value and "try again" in at.error[0].value.lower()


def test_max_rounds_refusal_and_cut_off_have_their_own_warnings(monkeypatch):
    cases = [("max_tool_rounds", "I could not finish within 10 model rounds.", "more steps than allowed (10 model rounds)"),
             ("refusal", "", "declined to answer"), ("max_tokens", "Partial answer", "cut off")]
    for status, answer, expect in cases:
        monkeypatch.setattr(core, "ask_sync", FakeAgent([result(answer, status)]))
        at = click_example(start(), 0)
        assert not at.exception and len(at.warning) == 1 and expect in at.warning[0].value, status
        assert not at.error
        if answer:
            assert answer in page_text(at)                           # partial text is still shown


# ---------- 4. the API key never reaches the page ----------
def test_api_key_never_appears_in_the_rendered_page(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL)
    leaky_calls = [{"round": 1, "name": "list_tasks", "input": {"note": SENTINEL}, "ok": False, "error_code": f"E {SENTINEL}",
                    "items": 0, "ms": 1, "result": f"RAW RECORD {SENTINEL}"}]
    plans = [
        [result(f"answer with {SENTINEL} and sk-ant-api03-OTHERKEY1234567890", calls=leaky_calls)],
        [result("", "api_error", f"401 invalid key {SENTINEL}", calls=[])],
        [RuntimeError(f"boom {SENTINEL}")],
    ]
    for plan in plans:
        monkeypatch.setattr(core, "ask_sync", FakeAgent(plan))
        at = click_example(start(), 0)
        text = page_text(at)
        assert SENTINEL not in text and "sk-ant-" not in text and "OTHERKEY" not in text
        assert "RAW RECORD" not in text                                # raw tool results are never shown
        assert not at.exception


# ---------- 5. rendering safety ----------
def test_dollar_signs_are_escaped_and_html_is_not_rendered(monkeypatch):
    nasty = "The band is $90k to $120k. <b>bold</b> <script>alert(1)</script>"
    monkeypatch.setattr(core, "ask_sync", FakeAgent([result(nasty)]))
    at = click_example(start(), 0)
    md = [m for m in at.markdown if "band is" in m.value]
    assert len(md) == 1 and "\\$90k" in md[0].value and "\\$120k" in md[0].value
    assert md[0].proto.allow_html is False


# ---------- 6. structure ----------
def test_app_has_no_business_logic_or_data_access():
    imported = set()
    for node in ast.walk(ast.parse(open(APP, encoding="utf-8").read())):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {"json", "sys", "pathlib", "streamlit", "backend", "backend.agent", "backend.agent.examples",
                        "web", "web.dashboard", "web.pages_data"}, imported
    assert not any(m and ("sqlite3" in m or "services" in m or "pandas" in m or "ingest" in m) for m in imported)
    source = open(APP, encoding="utf-8").read()
    assert "SELECT " not in source and "unsafe_allow_html" not in source


def test_dashboard_module_only_reads_analytics():
    path = config.ROOT / "web" / "dashboard.py"
    source = path.read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {"html", "pandas", "plotly.graph_objects", "streamlit", "backend", "backend.agent", "backend.services", "web"}, imported
    assert "altair" not in source
    assert not any("sqlite3" in m or "ingest" in m for m in imported)
    assert "SELECT " not in source and "unsafe_allow_html" not in source and "ask_sync" not in source


def test_theme_module_has_no_data_access_and_only_static_css():
    source = (config.ROOT / "web" / "theme.py").read_text(encoding="utf-8")
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (getattr(n, "names", None) or [None])}
    assert imported <= {"streamlit"}, imported
    assert "unsafe_allow_html" not in source and "SELECT " not in source and "sqlite3" not in source


def test_streamlit_settings_hide_tracebacks_and_usage_stats():
    cfg = tomllib.loads((config.ROOT / ".streamlit" / "config.toml").read_text())
    assert cfg["client"]["showErrorDetails"] == "none"
    assert cfg["browser"]["gatherUsageStats"] is False
    assert cfg["server"]["address"] == "localhost"


def test_the_app_logs_counts_only(monkeypatch):
    import io
    import logging
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    core.log.addHandler(handler)
    try:
        monkeypatch.setattr(core, "ask_sync", FakeAgent([result("SECRET ANSWER about Jonah Whitfield")]))
        at = start()
        at = at.chat_input[0].set_value("What is Jonah Whitfield's phone number?").run()
    finally:
        core.log.removeHandler(handler)
    logged = buf.getvalue()
    assert "web: status=ok" in logged
    assert "Jonah" not in logged and "SECRET" not in logged and "phone" not in logged


# ---------- 7. Stage 1 redesign: sidebar, pages, header, logos, theme ----------
def test_sidebar_has_logo_and_the_four_pages_with_overview_active():
    at = start("Overview")
    assert not at.exception
    nav = [b for b in at.sidebar.button if b.key.startswith("nav-")]
    assert [b.label for b in nav] == ["Overview", "Ask AI", "Candidates", "Tasks"]
    assert [b.proto.type for b in nav] == ["primary", "secondary", "secondary", "secondary"]
    assert not any("settings" in b.label.lower() for b in at.sidebar.button)       # no Settings item (author's decision)
    assert [type(c).__name__ for c in at.sidebar.children.values()].count("Image") == 1       # the sidebar logo


def test_overview_header_and_no_chat_input_and_no_llm_call(fake):
    at = start("Overview")
    text = page_text(at)
    assert "Quillfeather Labs  /  Data as of 15 Oct 2026" in text
    assert [t.value for t in at.title] == ["Recruiting Overview"]
    assert "Track progress. Find insights." in text and "Make data-driven hiring decisions." in text
    assert len(at.chat_input) == 0 and fake.calls == []


def test_header_date_comes_from_config(monkeypatch, fake):
    monkeypatch.setattr(config, "REFERENCE_DATE", date(2030, 1, 2))
    assert "Data as of 2 Jan 2030" in page_text(start("Overview"))


def test_clicking_a_nav_button_switches_page_and_only_ask_ai_has_the_chat(fake):
    at = start("Overview")
    at = at.sidebar.button(key="nav-ask-ai").click().run()
    assert at.session_state["page"] == "Ask AI" and len(at.chat_input) == 1
    assert [b.proto.type for b in at.sidebar.button if b.key.startswith("nav-")] == ["secondary", "primary", "secondary", "secondary"]
    at = at.sidebar.button(key="nav-overview").click().run()
    assert len(at.chat_input) == 0 and not at.exception and fake.calls == []


@pytest.mark.parametrize("page", ["Candidates", "Tasks"])
def test_candidates_and_tasks_pages_are_built(page):
    at = start(page)
    assert not at.exception and [t.value for t in at.title] == [page]
    assert not any("next stage" in i.value for i in at.info)                                              # no placeholder any more
    if page == "Tasks":
        assert at.selectbox(key="page-role").options[0] == "All roles"                                    # role filter present
    else:                                                                                                 # Part C: filter tabs + search instead
        assert at.segmented_control(key="cand-tab").options and at.text_input(key="cand-search")


def test_logos_exist_and_the_sidebar_colour_is_the_logo_background():
    from PIL import Image
    from web import theme
    src = Image.open(config.ROOT / "assets" / "logo_dark.png").convert("RGB")
    px = [src.getpixel(p) for p in [(5, 5), (src.width - 6, 5), (5, src.height - 6), (src.width - 6, src.height - 6)]]
    rgb = tuple(int(theme.SIDEBAR[i:i + 2], 16) for i in (1, 3, 5))
    assert all(max(abs(a - b) for a, b in zip(rgb, p)) <= 12 for p in px), (rgb, px)
    side = Image.open(config.ROOT / "assets" / "logo_sidebar.png")
    icon = Image.open(config.ROOT / "assets" / "logo_icon.png")
    assert side.mode == "RGBA" and icon.mode == "RGBA"
    assert side.width / side.height > 3 and icon.width / icon.height < 1.6          # full logo is wide, icon has no text
    assert side.getpixel((2, 2))[3] == 0 and icon.getpixel((2, 2))[3] == 0          # background is transparent


def test_theme_config_matches_theme_module():
    from web import theme
    cfg = tomllib.loads((config.ROOT / ".streamlit" / "config.toml").read_text())
    assert cfg["theme"]["primaryColor"].upper() == theme.CORAL and cfg["theme"]["backgroundColor"].upper() == theme.BG
    assert cfg["theme"]["sidebar"]["backgroundColor"].upper() == theme.SIDEBAR
    assert "plotly==" in (config.ROOT / "requirements.txt").read_text()


# ---------- 8. Stage 1.1 style fixes (CSS is a fixed string, so it can be checked) ----------
def test_sidebar_is_210px_and_logo_is_exported_at_2x():
    from PIL import Image
    from web import theme
    assert "width: 210px !important" in theme.CSS and "max-width: 210px !important" in theme.CSS
    assert Image.open(config.ROOT / "assets" / "logo_sidebar.png").width == 2 * theme.LOGO_WIDTH
    assert "width=theme.LOGO_WIDTH" in open(APP, encoding="utf-8").read()
    assert "2 * DISPLAY_WIDTH" in (config.ROOT / "scripts" / "make_logos.py").read_text() and theme.LOGO_WIDTH == 170


def test_nav_buttons_are_flat_and_coral_on_hover_and_active():
    from web import theme
    css = " ".join(theme.CSS.split())
    nav = 'section[data-testid="stSidebar"] [class*="st-key-nav-"] button'
    assert f"{nav}, section" in css and "background: transparent !important" in css                       # flat, no white buttons
    assert f"{nav}:hover" in css and f"{nav}[kind=\"primary\"]" in css
    hover = css[css.index(f"{nav}:hover"):][:160]
    active = css[css.index(f"{nav}[kind=\"primary\"]"):][:200]
    assert theme.CORAL in hover and "border-left-color: " + theme.CORAL in active and f"color: {theme.CORAL}" in active
    assert "rgba(117,97,155" in active                                                                    # subtle purple background


def test_one_coral_highlight_for_hover_focus_and_selection():
    from web import theme
    css = " ".join(theme.CSS.split())
    for needle in (".stMain .stButton button:hover", '[data-baseweb="select"] > div:focus-within', '[data-testid="stChatInput"]:focus-within',
                   'li[aria-selected="true"]'):
        assert needle in css, needle
    assert ".stButton > button" not in css                      # the main-area rule must match buttons inside tooltip wrappers too


def test_header_has_css_shapes_and_no_image():
    from web import theme
    css = " ".join(theme.CSS.split())
    start_at = css.index('[class*="st-key-page-header"]::before')
    block = css[start_at:][:1100]
    assert block.count("linear-gradient") == 1 and "rgba(203,197,219" in block                    # soft grey-lavender diagonal bands
    assert '[class*="st-key-page-header"]::after' in block and "clip-path: polygon" in block and "background: #FF674C" in block   # one solid coral parallelogram
    assert "url(" not in block                                                                    # shapes only, no image file (nothing copied from the mockup)
    at = start("Overview")
    assert not at.exception and [t.value for t in at.title] == ["Recruiting Overview"]
