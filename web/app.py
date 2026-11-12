"""HirePilot web app (Streamlit). PRESENTATION ONLY: every chat answer comes from the Agent Core (core.ask_sync, via
web/chat.py); the Overview page (web/dashboard.py) shows numbers from backend.services.analytics, next to the AI panel
(web/panel.py). Pages: Overview, Ask AI, Candidates, Tasks (sidebar buttons set st.session_state.page). This file holds no
business logic, no SQL and no data access.

Run from the project root:   .venv/bin/streamlit run web/app.py
Privacy: names and contact details from the data can appear in answers. Logs hold counts only
(status, rounds, tool count); the question and answer text are never logged. History lives in the browser session.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # `streamlit run` puts web/ on the path, not the project

import streamlit as st  # noqa: E402

from backend import config  # noqa: E402
from web import answer, chat, dashboard, panel, theme  # noqa: E402
from web.dashboard import render_dashboard  # noqa: E402
from web.pages_data import render_candidates, render_tasks  # noqa: E402

# ---------------------------------------------------------------- pages
ASSETS = Path(__file__).resolve().parents[1] / "assets"
PAGES = [("Overview", ":material/bar_chart:"), ("Ask AI", ":material/chat_bubble:"),
         ("Candidates", ":material/group:"), ("Tasks", ":material/task_alt:")]


def nice_snapshot(d):
    return f"{d:%b} {d.day}, {d.year}"


def nice_date(d):
    return f"{d.day} {d:%b} {d.year}"


def render_header(title, subtitle=None, two_lines=False, lead=None):
    """Top bar (breadcrumb, MCP status, user), large title, divider and subtitle. The decorative shapes are CSS (web/theme.py)."""
    with st.container(key="page-header"):
        left, right = st.columns([3, 2], vertical_alignment="center")
        left.caption(f"Quillfeather Labs  /  Data as of {nice_date(config.REFERENCE_DATE)}")
        connected, tools = chat.mcp_status()
        with right, st.container(key="topbar-status"):
            st.markdown((":green[●] Connected" if connected else ":gray[●] Disconnected") + "  ·  :material/account_circle: Recruiter",
                        help=(f"The MCP server started and listed {tools} tools. Checked without calling the AI model."
                              if connected else "The MCP server did not start or did not answer. The AI panel will not work."))
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left, st.container(key="title-two-line" if two_lines else "title-one-line"):
            st.title(title)
            if lead:
                st.caption(lead)
        if subtitle:
            with right, st.container(key="header-sub"):
                st.markdown(subtitle)


def render_sidebar():
    with st.sidebar:
        st.image(str(ASSETS / "logo_sidebar.png"), width=theme.LOGO_WIDTH)
        for name, icon in PAGES:
            key = "nav-" + name.lower().replace(" ", "-")
            if st.button(name, key=key, icon=icon, use_container_width=True,
                         type="primary" if st.session_state.page == name else "secondary"):
                st.session_state.page = name
                st.rerun()
        st.divider()
        if st.button("New chat", key="new-chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        st.caption("Answers can show names and contact details from the data. The server log keeps counts only.")


SCROLL_TO_LAST = """<script>
setTimeout(function () {
  var m = document.querySelectorAll('[data-testid="stChatMessage"]');
  if (m.length) { m[m.length - 1].scrollIntoView({block: "start", behavior: "smooth"}); }
}, 250);
</script>"""                                                                   # fixed text, no data in it


def process_queued():
    """Runs the question that came from another page ("Ask AI about this"). The first pass only draws the clean Ask AI page; the
    timer then calls this again, and the agent runs with its spinner on that page. A page that is already finished has no faded
    leftovers of the old page. In a test (no timer) the next run does the same."""
    queued = st.session_state.get("queued")
    if not queued:
        return
    if not queued["armed"]:
        queued["armed"] = True
        return
    st.session_state.pop("queued")
    answer.exchange(queued["question"], "ask-q", kind=queued["kind"])
    st.session_state["scroll_last"] = True
    st.rerun()


def render_ask_page():
    render_header("Ask AI")
    st.info(f"**Data as of {config.REFERENCE_DATE.isoformat()}** (the export date). "
            "“Overdue”, “pending” and “open for N months” are judged against this day, not today.")
    typed = st.chat_input("Ask about candidates, the hiring funnel or tasks…")      # only on this page
    clicked, kind = None, None
    with st.container(key="ask-actions"):
        for col, (key, title, _, icon, text, k) in zip(st.columns(3), panel.tiles(dashboard.selected_role_title())):
            if col.button(title, key=f"askbtn-{key}", icon=icon, help=text, use_container_width=True):
                clicked, kind = text, k
    pending = st.session_state.pop("pending", None)                                  # "Ask AI about this" on the Candidates page
    pending_kind = st.session_state.pop("pending_kind", None)
    if pending and not (clicked or typed):
        st.session_state["queued"] = {"question": pending, "kind": pending_kind, "armed": False}

    answer.show_history("ask")
    question = clicked or typed
    if question:
        st.session_state.pop("queued", None)
        answer.exchange(question, "ask", kind=kind if clicked else None)
    elif st.session_state.get("queued"):
        st.fragment(run_every=0.3)(process_queued)()
    if st.session_state.pop("scroll_last", False) and st.session_state.messages:
        st.html(SCROLL_TO_LAST, unsafe_allow_javascript=True)


def render_footer():
    """Global footer, after the content of every page: normal flow (not fixed, not floating), so it never covers the chat input."""
    with st.container(key="site-footer"):
        logo, tagline, snapshot = st.columns([1.1, 2, 2.4], vertical_alignment="center")
        logo.image(str(ASSETS / "logo_sidebar.png"), width=140)
        with tagline:
            st.markdown("**Smarter hiring. Clearer decisions.**")
            st.caption("Quillfeather Labs")
        with snapshot, st.container(key="footer-meta"):
            st.markdown(f"Data snapshot: **{nice_snapshot(config.REFERENCE_DATE)}**")
            st.caption("AI-assisted insights · Human-reviewed decisions")


st.set_page_config(page_title="HirePilot AI", page_icon=str(ASSETS / "logo_icon.png"), layout="wide")
theme.apply()
st.session_state.setdefault("messages", [])
st.session_state.setdefault("page", "Overview")

render_sidebar()
page = st.session_state.page
if page == "Overview":
    render_header("Recruiting Overview", "Track progress. Find insights.  \nMake data-driven hiring decisions.", two_lines=True)
    render_dashboard()
elif page == "Ask AI":
    render_ask_page()
elif page == "Candidates":
    render_header("Candidates", "Every application, by role.", lead="Explore candidates, review flags, and take action.")
    render_candidates()
else:
    render_header("Tasks", "Open tasks, overdue first.")
    render_tasks()
if page != "Ask AI":                       # the chat page has no footer
    render_footer()
