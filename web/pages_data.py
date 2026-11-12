"""Candidates page (filter tabs, flags, search, paging, decisions and activity) and Tasks page (table with a role filter). PRESENTATION ONLY: the rows come from
backend.services.analytics (built on the existing services). No model call, no SQL.
"""
import pandas as pd
import streamlit as st

from backend.services import analytics
from web import dashboard

ALL = "All roles"


@st.cache_data(show_spinner=False)
def tasks(job_id):
    return analytics.tasks_table(job_id)


def role_filter(roles):
    titles = {r["job_id"]: r["title"] for r in roles}
    options = [None] + list(titles)
    picker, _ = st.columns([1, 2])
    job_id = picker.selectbox("Role", options, format_func=lambda j: ALL if j is None else titles[j], key="page-role")
    return job_id


TABS = ["All", "By Role", "By Stage", "With Flags", "By Status"]
PAGE_SIZE = 10
STATUS_CSS = {"Active": "background-color: #DDF2E3; color: #14532D; font-weight: 600",
              "Rejected": "background-color: #FFE1DA; color: #7A1F0E; font-weight: 600",
              "Withdrawn": "background-color: #E9E3F2; color: #3F3361; font-weight: 600",
              "Hired": "background-color: #DCD2F0; color: #1A0B3F; font-weight: 600"}
FLAG_CSS = "background-color: #FFE1DA; color: #7A1F0E; font-weight: 600"


def tab_label(tab, n_all, n_flags):
    return {"All": f"All Candidates ({n_all})", "With Flags": f"With Flags ({n_flags})"}.get(tab, tab)


def day(iso):
    return "–" if not iso else f"{pd.Timestamp(iso):%b} {pd.Timestamp(iso).day}"


def filter_rows(rows, tab, pick, query):
    """The rows for a tab, the sub-filter (role, stage or status) and the search text. Search: name, role or application id."""
    if tab == "By Role" and pick:
        rows = [r for r in rows if r["job_id"] == pick]
    elif tab == "By Stage" and pick:
        rows = [r for r in rows if r["stage"] == pick]
    elif tab == "By Status" and pick:
        rows = [r for r in rows if r["status"] == pick]
    elif tab == "With Flags":
        rows = [r for r in rows if r["flags"]]
    q = (query or "").strip().lower()
    if q:
        rows = [r for r in rows if q in r["candidate"].lower() or q in r["role"].lower() or q in r["application_id"].lower()]
    rows = sorted(rows, key=lambda r: r["candidate"])                       # three stable passes: name, newest update, flagged first
    rows.sort(key=lambda r: r["last_update"] or "", reverse=True)
    rows.sort(key=lambda r: not r["flags"])
    return rows


def candidate_frame(rows):
    return pd.DataFrame([{"Candidate": r["candidate"], "Role": r["role"], "Stage": r["stage"] or "—", "Status": r["status"].capitalize(),
                          "Flags": ", ".join(f"⚠ {f}" for f in r["flags"]) or "—", "Last update": day(r["last_update"]),
                          "Source": r["source"]} for r in rows])


def style_frame(frame):
    def row_tint(row):
        return ["background-color: #FFF4F1" if "Status conflict" in row["Flags"] else "" for _ in row]
    return (frame.style.apply(row_tint, axis=1).map(lambda v: "font-weight: 700", subset=["Candidate"])
            .map(lambda v: STATUS_CSS.get(v, ""), subset=["Status"]).map(lambda v: FLAG_CSS if v.startswith("⚠") else "", subset=["Flags"]))


def go_page(n):
    st.session_state["cand-page"] = n


def pager(total, page, n_pages):
    """‹ 1 2 3 4 5 › as buttons. The current page is the filled one."""
    first = min(max(page - 2, 0), max(n_pages - 5, 0))
    numbers = list(range(first, min(first + 5, n_pages)))
    cols = st.columns([5] + [1] * (len(numbers) + 2))
    start = page * PAGE_SIZE
    cols[0].caption(f"Showing {start + 1 if total else 0}–{min(start + PAGE_SIZE, total)} of {total}")
    cols[1].button("", key="pg-prev", icon=":material/chevron_left:", disabled=page == 0, on_click=go_page, args=(page - 1,))
    for col, n in zip(cols[2:], numbers):
        col.button(str(n + 1), key=f"pg-{n}", type="primary" if n == page else "secondary", on_click=go_page, args=(n,))
    cols[-1].button("", key="pg-next", icon=":material/chevron_right:", disabled=page >= n_pages - 1, on_click=go_page, args=(page + 1,))


def render_candidates():
    d = dashboard.load_or_error()
    if d is None:
        return
    all_rows = d["candidates"]
    n_flags = sum(1 for r in all_rows if r["flags"])
    main, side = st.columns([2.1, 1], gap="medium")
    with main:
        tab = st.segmented_control("Filter", TABS, default="All", key="cand-tab", label_visibility="collapsed",
                                   format_func=lambda t: tab_label(t, len(all_rows), n_flags)) or "All"
        pick = None
        if tab in ("By Role", "By Stage", "By Status"):
            roles = {r["job_id"]: r["title"] for r in d["roles"]}
            options = {"By Role": list(roles), "By Stage": list(dict.fromkeys(r["stage"] for r in all_rows if r["stage"])),
                       "By Status": ["active", "hired", "rejected", "withdrawn"]}[tab]
            names = {"By Role": roles.get, "By Stage": str, "By Status": str.capitalize}[tab]
            picker, _ = st.columns([1, 2])
            pick = picker.selectbox(tab, options, format_func=names, key=f"cand-pick-{tab}")
        if n_flags:
            with st.container(key="attention-banner"):
                text, button = st.columns([4, 1.3], vertical_alignment="center")
                text.markdown(f":material/warning: **{n_flags} candidate{'s' if n_flags != 1 else ''} need{'' if n_flags != 1 else 's'} your attention**")
                text.caption("Status conflicts, deadline issues, or other data that may be incorrect.")
                button.button("View all flags", key="banner-flags", icon=":material/arrow_forward:", icon_position="right",
                              on_click=dashboard.set_tab, args=("With Flags",), use_container_width=True)
        with st.container(key="card-wide-candidates"):
            title, search = st.columns([1, 1], vertical_alignment="center")
            query = search.text_input("Search", key="cand-search", placeholder="Search by name, role, or application ID", label_visibility="collapsed")
            rows = filter_rows(all_rows, tab, pick, query)
            title.markdown(f"**Candidates ({len(all_rows)} applications)**")
            signature = (tab, pick, query)
            if st.session_state.get("cand-sig") != signature:                 # a new filter or search starts on page 1
                st.session_state["cand-sig"], st.session_state["cand-page"] = signature, 0
            n_pages = max(-(-len(rows) // PAGE_SIZE), 1)
            page = min(st.session_state.get("cand-page", 0), n_pages - 1)
            shown = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            if shown:
                st.dataframe(style_frame(candidate_frame(shown)), hide_index=True, width="stretch", height=dashboard.table_height(len(shown)))
            else:
                st.info("No candidate matches this filter or search.")
            pager(len(rows), page, n_pages)
            st.caption("Flags come from rules: “Status conflict” = offer deadline on a rejected or withdrawn application; “Offer deadline” = "
                       "still active but the deadline has passed; “Stage conflict” = applications.json and the stage events disagree; "
                       "“Longest stalled” = the active candidate with the most days in their stage. Last update = newest dated record "
                       "of the application (stage change, scorecard, note, rejection).")
    with side:
        dashboard.decision_block(d)
        dashboard.activity_block(d)
    dashboard.stalled_block(d, None)


def render_tasks():
    d = dashboard.load()
    job_id = role_filter(d["roles"])
    rows = tasks(job_id)
    counts = {k: sum(r["state"] == k for r in rows) for k in dashboard.STATE_TEXT}
    dashboard.card("tasks-chart", "Open tasks by state", lambda: dashboard.show(dashboard.tasks_figure(counts), "chart-tasks"),
                   "Overdue means the due date is before the data date.", size="wide")   # moved here from the Overview
    with st.container(key="card-wide-tasks"):
        st.markdown(f"**Open tasks ({len(rows)})**")
        st.caption("Overdue first. Deadline = where the due date comes from: “From the data” is a date in the export, "
                   "“Assumed” is our rule (for example interview date + 2 days).")
        st.dataframe(dashboard.task_frame(rows), hide_index=True, width="stretch", height=dashboard.table_height(len(rows)))
