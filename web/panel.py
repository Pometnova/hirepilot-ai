"""The right-hand AI panel of the Overview page. PRESENTATION ONLY.
Nothing is sent to the model until the user clicks a tile or submits a question. A tile or a form only stores the question
in st.session_state["pending"]; the panel answers it in the run that follows, through the same Agent Core as the Ask AI page.
The conversation (st.session_state.messages) is shared with the Ask AI page. No sticky CSS: the panel is a normal column.
"""
import streamlit as st

from web import chat

SUBTITLE = "Ask questions, get analysis, and explore your data."
FOLLOW_UP = "Ask a follow-up question..."


def tiles(role_title):
    """The three assignment questions as (key, title, description, icon, question, kind). The first uses the selected role.
    The same three buttons (same titles and icons) are used on the Ask AI page."""
    return [("top", "Find Top Candidates", "Compare the best matches", ":material/emoji_events:",
             f"Who are the top 3 candidates for {role_title}, and why?", "top"),
            ("dropoffs", "Find Drop-offs", "Where candidates leave the process", ":material/bar_chart:",
             "This role has been open for 4 months. Where is our process losing candidates?", "dropoffs"),
            ("tasks", "Check Pending Tasks", "See what needs attention", ":material/check_box:",
             "Which tasks are pending or overdue?", "tasks")]


def submit_from(key):
    """Form callback: take the typed question from the input and remember it for the panel."""
    question = (st.session_state.get(key) or "").strip()
    if question:
        chat.ask_later(question)


def render_tiles(role_title):
    """Three full-width tiles, stacked: coral icon on the left, title and short description on the right. The whole tile is an
    invisible button on top (CSS in web/theme.py). Clicking only stores the question; the model is called in the next run."""
    for key, title, description, icon, question, kind in tiles(role_title):
        with st.container(key=f"ptile-{key}"):
            left, right = st.columns([1, 6], vertical_alignment="center")
            left.markdown(icon)
            right.markdown(f"**{title}**")
            right.caption(description)
            st.button(title, key=f"pbtn-{key}", on_click=chat.ask_later, args=(question, kind), help=question)


def render_ai_panel(role_title):
    pending = st.session_state.pop("pending", None)
    pending_kind = st.session_state.pop("pending_kind", None)
    with st.container(key="ai-panel"):
        with st.container(key="ai-head"):
            st.markdown("**Ask AI**")                                   # the only tab
            st.markdown("### Recruiting Intelligence")
            st.caption(SUBTITLE)
            render_tiles(role_title)
        with st.container(key="ai-body"):
            with st.container(key="ai-chat"):                          # no inner scrolling: the panel shows the latest exchange only
                if not st.session_state.messages and not pending:
                    st.caption("Click a tile or type a question. Nothing is sent to the AI until you do.")
                chat.show_history("panel", mode="panel", last=0 if pending else 2)
                if pending:
                    chat.exchange(pending, "panel", kind=pending_kind, mode="panel")
            with st.form("ai-form", clear_on_submit=True, border=False):
                left, right = st.columns([6, 1], vertical_alignment="center")
                left.text_input("Follow-up question", key="ai-q", placeholder=FOLLOW_UP, label_visibility="collapsed")
                right.form_submit_button("", key="ai-send", icon=":material/arrow_forward:", on_click=submit_from, args=("ai-q",))
            st.button("Open full chat", key="open-chat", icon=":material/open_in_full:", on_click=chat.go_to, args=("Ask AI",))
