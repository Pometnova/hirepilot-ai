"""Overview page of the web app. PRESENTATION ONLY: all numbers come from backend.services.analytics (which only
combines the existing services). No model call, no SQL. Charts use Plotly with the shared style in web/theme.py.
"""
import html

import pandas as pd
from html import escape as esc
import plotly.graph_objects as go
import streamlit as st

from backend import config
from backend.agent import core
from backend.services import analytics, trust
from web import chat, panel, theme

STATUS_COLORS = [("active", "Active", theme.PURPLE), ("hired", "Hired", theme.SIDEBAR),
                 ("rejected", "Rejected", theme.CORAL), ("withdrawn", "Withdrawn", theme.PURPLE_SOFT)]
TASK_LABELS = [("overdue", "Overdue", theme.CORAL), ("due_today", "Due today", theme.CORAL_SOFT),
               ("pending", "Pending", theme.PURPLE), ("pending_no_due_date", "Pending, no due date", theme.PURPLE_SOFT)]
CHART_CONFIG = {"displayModeBar": False}
STATE_TEXT = {"overdue": "Overdue", "due_today": "Due today", "pending": "Pending", "pending_no_due_date": "Pending, no due date"}


@st.cache_data(show_spinner=False)
def load():
    """The database is read-only and fixed at the export date, so one load per server run is enough."""
    return analytics.dashboard()


def pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def pct0(x):
    return "–" if x is None else f"{x * 100:.0f}%"


def money(text):
    return text.replace("$", "\\$")


# ---------------------------------------------------------------- figures (pure functions, tested without a browser)
def roles_figure(roles):
    labels = [f"{r['title']} ({r['days_open']} days open)" for r in roles]
    fig = go.Figure()
    for key, name, color in STATUS_COLORS:
        fig.add_bar(y=labels, x=[r[key] for r in roles], name=name, orientation="h", marker_color=color,
                    hovertemplate="%{y}<br>" + name + ": %{x}<extra></extra>")
    fig.update_layout(barmode="stack", legend_traceorder="normal")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title_text="Applications", dtick=5)
    pad(fig, [r["applications"] for r in roles], factor=1.05)
    return theme.style_figure(fig)


def funnel_figure(f):
    """One bar per stage in pipeline order. Bar value = applications that reached the stage. At the right of every bar:
    the drop-off from the previous stage = (rejected + withdrew there) / reached there. Applications still waiting are not
    lost; the tooltip lists them as still in progress. The largest drop-off is coral (bar and %). Others are purple."""
    stages = f["stages"]
    big = f["largest_dropoff"]["to_stage"] if f["largest_dropoff"] else None
    custom = []
    for s in stages:
        if s["dropoff_pct"] is None and s["dropoff_from"] is None:
            drop = "First stage"
        elif s["dropoff_base"]:
            drop = (f"Drop-off from {s['dropoff_from']}: {s['dropoff_lost']} of {s['dropoff_base']} "
                    f"({pct0(s['dropoff_pct'])}) rejected or withdrew")
        else:
            drop = f"Nobody reached {s['dropoff_from']}"
        custom.append([s["reached"], s["rejected"], s["withdrew"], s["still_in_progress"], s["moved_on"], drop])
    fig = go.Figure(go.Bar(
        y=[s["stage"] for s in stages], x=[s["reached"] for s in stages], orientation="h", customdata=custom,
        marker_color=[theme.CORAL if s["stage"] == big else theme.PURPLE for s in stages],
        text=[s["reached"] for s in stages], textposition="auto", textangle=0, insidetextanchor="middle", cliponaxis=False,
        insidetextfont=dict(color="#FFFFFF", size=13), outsidetextfont=dict(color=theme.TEXT, size=13),
        hovertemplate=("<b>%{y}</b><br>Reached: %{customdata[0]}<br>Rejected here: %{customdata[1]}<br>Withdrew here: %{customdata[2]}"
                       "<br>Still in progress: %{customdata[3]}<br>Moved on: %{customdata[4]}<br>%{customdata[5]}<extra></extra>")))
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=[s["stage"] for s in stages])
    fig.update_xaxes(title_text="Applications that reached the stage", range=[0, max(s["reached"] for s in stages) * 1.04])
    for s in stages:                                                                             # right-hand column of drop-off %
        fig.add_annotation(x=1, xref="paper", xanchor="left", y=s["stage"], yref="y", showarrow=False, xshift=10,
                           text=pct0(s["dropoff_pct"]), font=dict(color=theme.CORAL if s["stage"] == big else theme.MUTED,
                                                                  size=13, family=theme.FONT))
    fig.add_annotation(x=1, xref="paper", xanchor="left", y=1, yref="paper", yanchor="bottom", showarrow=False, xshift=10,
                       text="Drop-off", font=dict(color=theme.MUTED, size=11, family=theme.FONT))
    theme.style_figure(fig)
    fig.update_layout(margin=dict(l=8, r=70, t=30, b=8))
    return fig


def dwell_figure(f):
    stages = [s for s in f["stages"] if s["median_days_in_stage"] is not None]
    if not stages:
        return None
    slowest = f["slowest_stage"]["stage"] if f["slowest_stage"] else None
    fig = go.Figure(go.Bar(
        y=[s["stage"] for s in stages], x=[s["median_days_in_stage"] for s in stages], orientation="h",
        customdata=[s["median_days_n"] for s in stages],
        marker_color=[theme.CORAL if s["stage"] == slowest else theme.PURPLE for s in stages],
        text=[s["median_days_in_stage"] for s in stages], textposition="outside", cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>median %{x} days, based on %{customdata} candidates<extra></extra>"))
    fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=[s["stage"] for s in f["stages"]])
    fig.update_xaxes(title_text="Median days in the stage")
    pad(fig, [s["median_days_in_stage"] for s in stages])
    return theme.style_figure(fig)


def tasks_figure(counts):
    names = [name for _, name, _ in TASK_LABELS]
    values = [counts[key] for key, _, _ in TASK_LABELS]
    fig = go.Figure(go.Bar(y=names, x=values, orientation="h", marker_color=[c for _, _, c in TASK_LABELS],
                           text=values, textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x} open tasks<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title_text="Open tasks", dtick=1)
    pad(fig, values)
    return theme.style_figure(fig)


EXIT_COLORS = [("rejected", "Rejected", theme.CORAL), ("withdrew", "Withdrew", theme.PURPLE), ("unknown", "Unknown", theme.PURPLE_SOFT)]


def exits_figure(e):
    """Donut: rejected / withdrew / unknown. Total exits in the centre; counts and % on hover. None when there is nothing to show."""
    if e["note"]:
        return None
    parts = [(name, e[key], color) for key, name, color in EXIT_COLORS if e[key]]
    fig = go.Figure(go.Pie(labels=[p[0] for p in parts], values=[p[1] for p in parts], hole=0.64, sort=False, direction="clockwise",
                           marker=dict(colors=[p[2] for p in parts], line=dict(color="#FFFFFF", width=2)), textinfo="none",
                           hovertemplate="<b>%{label}</b><br>%{value} candidates (%{percent})<extra></extra>"))
    fig.add_annotation(text=f"<b>{e['total']}</b><br><span style='font-size:11px;color:{theme.MUTED}'>exits</span>", showarrow=False,
                       font=dict(size=30, color=theme.TEXT, family=theme.FONT))
    theme.style_figure(fig, height=300)
    fig.update_layout(margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5))
    return fig


def ring_figure(c):
    """Small ring: share of the data that is there. The % is in the centre; hover shows the counts."""
    fig = go.Figure(go.Pie(labels=["Have it", "Missing"], values=[c["have"], c["of"] - c["have"]], hole=0.74, sort=False,
                           direction="clockwise", marker=dict(colors=[theme.PURPLE, theme.CORAL], line=dict(color="#FFFFFF", width=2)),
                           textinfo="none", hovertemplate="<b>%{label}</b>: %{value} of " + str(c["of"]) + " (%{percent})<extra></extra>"))
    fig.add_annotation(text=f"<b>{c['pct'] * 100:.0f}%</b>", showarrow=False, font=dict(size=22, color=theme.TEXT, family=theme.FONT))
    theme.style_figure(fig, height=150)
    fig.update_layout(margin=dict(l=4, r=4, t=4, b=4), showlegend=False)
    return fig


def table_height(n_rows):
    """Height that shows every row, so a table never scrolls inside the page (the page itself scrolls)."""
    return 35 * (n_rows + 1) + 3


def selected_role_title():
    """Title of the role selected on the Overview (default: the first role). Used by the Ask AI buttons."""
    d = load_or_error()
    if d is None:
        return "the selected role"
    chosen = st.session_state.get("role-chosen") or st.session_state.get("dash-role")
    return next((r["title"] for r in d["roles"] if r["job_id"] == chosen), d["roles"][0]["title"])


def pad(fig, values, axis="x", factor=1.18):
    """Leave room after the longest bar so the value label next to it is not cut off."""
    top = max(values) if values else 1
    getattr(fig, f"update_{axis}axes")(range=[0, (top or 1) * factor])


def show(fig, key):
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG, key=key)


# ---------------------------------------------------------------- building blocks
def card(key, title, body, caption=None, subtitle=None, size="half"):
    """One card = title, optional subtitle, content, caption below. Same style for charts and tables."""
    with st.container(key=f"card-{size}-{key}"):
        st.markdown(f"**{title}**")
        if subtitle:
            st.caption(subtitle)
        body()
        if caption:
            st.caption(caption)


def toggle_kpi(name):
    """Button callback: open the records of this KPI, or close them when it is already open."""
    st.session_state["kpi"] = None if st.session_state.get("kpi") == name else name


def pick_role(job_id):
    """Button callback: the role clicked in Open Positions becomes the role filter of the page."""
    st.session_state["dash-role"] = job_id


def go_to(page):
    st.session_state["page"] = page


KPI_ICON = {"overdue_tasks": ":material/warning:", "pending_scorecards": ":material/description:",
            "unanswered_emails": ":material/mail:", "upcoming_offer_deadlines": ":material/calendar_month:"}
KPI_TITLES = {"overdue_tasks": "Overdue tasks", "pending_scorecards": "Pending scorecards", "unanswered_emails": "Unanswered emails",
              "upcoming_offer_deadlines": "Upcoming offer deadlines"}


def kpi_card(name, value, sub=None, urgent=False):
    """One clickable KPI card. The whole card is an invisible button (CSS in web/theme.py). The open card has a coral border;
    the most urgent card has a coral bar on its left."""
    selected = st.session_state.get("kpi") == name
    key = f"kpi-card-{name}" + ("-urgent" if urgent else "") + ("-selected" if selected else "")
    with st.container(key=key):
        with st.container(key=f"kpi-icon-{name}"):
            st.markdown(KPI_ICON[name])
        st.metric(KPI_TITLES[name], f"{value:02d}")
        if sub:
            st.caption(sub)
        st.button(f"Show records: {KPI_TITLES[name]}", key=f"kpi-btn-{name}", on_click=toggle_kpi, args=(name,))


SUB_WORDS = {"overdue": "overdue", "due_today": "due today", "pending": "waiting", "pending_no_due_date": "no due date"}


def by_state_text(by_state):
    """Plain words, for example "2 overdue · 1 due today · 2 waiting"."""
    parts = [f"{n} {SUB_WORDS[k]}" for k, n in by_state.items() if n]
    return " · ".join(parts) if parts else None


def kpi_section(d):
    """Row 1: four KPI cards. Click one to open its records below; click again to close."""
    k = d["kpis"]
    offers = d["tasks"]["by_kpi"]["upcoming_offer_deadlines"]
    closed = [o for o in offers if o["status"] != "active"]
    offers_sub = (f"{len(closed)} more on a rejected application · ⚠ status conflict" if closed else None)
    cards = [("overdue_tasks", k["overdue_tasks"], f"of {k['open_tasks']} open tasks"),
             ("pending_scorecards", k["pending_scorecards"], by_state_text(k["pending_scorecards_by_state"])),
             ("unanswered_emails", k["unanswered_emails"], by_state_text(k["unanswered_emails_by_state"])),
             ("upcoming_offer_deadlines", k["upcoming_offer_deadlines"], offers_sub)]
    urgent = next((name for name, value, _ in cards if value), None)      # the first card that has something to do
    for col, (name, value, sub) in zip(st.columns(4), cards):
        with col:
            kpi_card(name, value, sub, urgent=name == urgent)
    selected = st.session_state.get("kpi")
    if selected in d["tasks"]["by_kpi"]:
        kpi_records(selected, d)


CONFLICT_FLAG = "⚠ Status conflict"


def flag_style(frame):
    """Coral badge look for the Flag column of a table (a light coral cell, dark text)."""
    css = f"background-color: #FFE1DA; color: #5A1608; font-weight: 600; border-radius: 6px"
    return frame.style.map(lambda v: css if v else "", subset=["Flag"])


def task_frame(records):
    return pd.DataFrame([{"Candidate": r["candidate"], "Task": r["task"], "Role": r["role"], "Due": r["due_date"],
                          "State": STATE_TEXT.get(r["state"], r["state"]), "Deadline": r["deadline_source"],
                          "Days overdue": r["days_overdue"], "Source": r["source"]} for r in records])


def kpi_records(name, d):
    records = d["tasks"]["by_kpi"][name]

    def body():
        if name == "upcoming_offer_deadlines":
            live = [o for o in records if o["status"] == "active"]
            if not live:
                st.info(f"No offer deadline on or after {analytics.fmt_date(config.REFERENCE_DATE)} belongs to an active application.")
            if records:
                st.dataframe(flag_style(pd.DataFrame([{"Candidate": o["candidate"], "Role": o["role"], "Deadline": o["deadline"],
                                                       "Application status": o["status"], "Flag": CONFLICT_FLAG if o["status"] != "active" else "",
                                                       "Source": o["source"]} for o in records])), hide_index=True, width="stretch")
                st.caption("A deadline on a rejected application is a conflict in the data (audit): the offer may still be open. "
                           "It is not counted in the number above.")
        elif records:
            st.dataframe(task_frame(records), hide_index=True, width="stretch")
            st.caption("Deadline = where the due date comes from: “From the data” is a date in the export, “Assumed” is our rule "
                       "(for example interview date + 2 days).")
        else:
            st.success("No records.")
    card("kpi-records", f"{KPI_TITLES[name]} ({len(records)})", body, subtitle="Click the card again to close this table.", size="wide")


# ---------------------------------------------------------------- row 2: Open Positions | Priority Actions
STAGE_SHADES = ["#B7A9D3", "#9A88C0", "#75619B", "#54417F", "#37245F", "#1A0B3F"]       # light to dark along the pipeline


def stage_bar(active_by_stage):
    """A small bar: active candidates by current stage, in pipeline order. Only counts, no percentages. The text is escaped."""
    total = sum(x["count"] for x in active_by_stage)
    n = len(active_by_stage)
    if not total:
        st.html('<div class="stagebar"></div>')
        return
    parts = []
    for i, x in enumerate(active_by_stage):
        if x["count"]:
            shade = STAGE_SHADES[round(i * (len(STAGE_SHADES) - 1) / max(n - 1, 1))]
            parts.append(f'<span style="flex:{x["count"]};background:{shade}" title="{html.escape(x["stage"])}: {x["count"]}"></span>')
    st.html('<div class="stagebar">' + "".join(parts) + "</div>")


def role_row(r, selected):
    key = f"role-row-{r['job_id']}" + ("-selected" if selected else "")
    with st.container(key=key):
        left, right = st.columns([5, 6], vertical_alignment="center")
        left.markdown(f"**{r['title']}**")
        left.caption(f"{r['applications']} applicants · {r['days_open']} days open")
        with right:
            st.markdown(f"**{r['active']}** active · **{r['hired']}** hired")
            stage_bar(r["active_by_stage"])
        where = " · ".join(f"{x['stage']} {x['count']}" for x in r["active_by_stage"] if x["count"])
        st.caption(f"Active by stage: {where}" if where else "No active candidates.")
        st.button(f"Select role: {r['title']}", key=f"role-btn-{r['job_id']}", on_click=pick_role, args=(r["job_id"],))


def positions_block(d, chosen):
    with st.container(key="card-half-positions"):
        title, link = st.columns([3, 1], vertical_alignment="center")
        title.markdown("**Open Positions**")
        link.button("View all", key="positions-all", icon=":material/arrow_forward:", icon_position="right", type="tertiary",
                    on_click=go_to, args=("Candidates",))
        st.caption("Click a role to use it as the role filter.")
        for r in d["roles"]:
            role_row(r, r["job_id"] == chosen)


PRIORITY_ROWS = 5
BADGE = {"overdue": ":primary-badge[OVERDUE]", "due_today": ":violet-badge[DUE TODAY]", "pending": ":gray-badge[PENDING]",
         "pending_no_due_date": ":gray-badge[NO DUE DATE]"}
TASK_ICON = {"scorecard_pending": ":material/description:", "email_unanswered": ":material/mail:",
             "offer_deadline": ":material/calendar_month:", "application_unreviewed": ":material/fact_check:"}
DEADLINE_NOTE = {"From the data": "deadline from the data", "Assumed": "assumed deadline", "No due date": "no due date"}


def priority_block(d):
    """Status conflicts first (a deadline is attached to them), then the open tasks. Five rows in all."""
    items = d["tasks"]["priority"]
    conflicts = d["conflicts"]
    total = len(conflicts) + len(items)
    with st.container(key="card-half-priority"):
        title, link = st.columns([3, 1], vertical_alignment="center")
        title.markdown("**Priority Actions**")
        link.button("View all", key="priority-all", icon=":material/arrow_forward:", icon_position="right", type="tertiary",
                    on_click=go_to, args=("Tasks",))
        st.caption(f"Status conflicts first, then overdue, due today, pending, no due date. Showing {min(PRIORITY_ROWS, total)} of {total}.")
        shown = 0
        for c in conflicts[:PRIORITY_ROWS]:
            with st.container(key=f"prio-row-{shown}"):
                icon, text, badge = st.columns([1, 6, 4], vertical_alignment="center")
                icon.markdown(":material/warning:")
                text.markdown(f"**Verify status: {c['candidate']}**")
                text.caption(f"offer deadline {analytics.fmt_date(pd.Timestamp(c['offer_deadline']).date()).rsplit(',', 1)[0]}, but marked {c['status']}")
                badge.markdown(f":primary-badge[{CONFLICT_FLAG}]")
            shown += 1
        for t in items[:PRIORITY_ROWS - shown]:
            with st.container(key=f"prio-row-{shown}"):
                icon, text, badge = st.columns([1, 8, 3], vertical_alignment="center")
                icon.markdown(TASK_ICON.get(t["task_type"], ":material/task_alt:"))
                due = f"due {pd.Timestamp(t['due_date']):%b} {pd.Timestamp(t['due_date']).day}" if t["due_date"] else "no due date"
                text.markdown(f"**{t['task'].capitalize()}** · {t['candidate']}")
                text.caption(f"{t['role'] or 'no role'} · {due} · {DEADLINE_NOTE[t['deadline_source']]}")
                badge.markdown(BADGE[t["state"]])
            shown += 1


# ---------------------------------------------------------------- row 3: Funnel | Median Days | Data Quality
def funnel_block(d, titles, chosen):
    """The funnel card holds the role filter. Returns the selected job id."""
    with st.container(key="card-tall-funnel"):
        st.markdown(f"**Recruitment Funnel — {titles[chosen]}**")
        st.caption("Candidate progression & drop-off")
        job_id = st.selectbox("Role", list(titles), format_func=titles.get, key="dash-role", label_visibility="collapsed")
        f = d["funnels"][job_id]
        big = f["largest_dropoff"]
        show(funnel_figure(f), "chart-funnel")
        if big:
            with st.container(key="warn-line"):
                st.markdown(f"⚠ Largest drop-off: {big['from_stage']} → {big['to_stage']} ({pct0(big['pct'])})")
        st.markdown(f["summary"])
        if f["no_history"]:
            st.caption(f"{f['no_history']} application(s) have no stage history. They are counted only at the first stage, where "
                       "applications.json also places them. Their path is not guessed.")
    return job_id


def dwell_block(f):
    fig = dwell_figure(f)
    card("dwell", "Median Days in Stage", lambda: show(fig, "chart-dwell") if fig is not None else st.write(""),
         "Median days between entering a stage and leaving it. The slowest stage is coral. The last stage has no value because "
         "nobody has left it. Stages with few candidates are rough.", subtitle=f"{f['title']}", size="tall")


def exits_block(d, job_id):
    """"Why candidates leave": the same role filter as the funnel. Counted from application status only."""
    e = d["exits"][job_id]
    with st.container(key="card-tall-exits"):
        st.markdown("**Why candidates leave**")
        st.caption("Rejected, withdrew or unknown")
        if e["note"]:
            st.info(e["note"])
        else:
            show(exits_figure(e), "chart-exits")
        st.caption("Counted from the status of each application. Unknown = rejected with no reason in the data, or a status "
                   "conflict. Hired and active candidates are not exits. We never guess a withdrawal from unanswered emails.")


def coverage_rings(d):
    """Three rings, each with a plain label and one sentence. The missing part is coral (ring slice and text)."""
    cols = st.columns(len(d["coverage"]))
    for col, c in zip(cols, d["coverage"]):
        with col:
            st.markdown(f"**{c['label']}**")
            if not c["available"]:
                st.caption("Not available")
                continue
            show(ring_figure(c), f"chart-cov-{c['label'].lower().replace(' ', '-')}")
            st.markdown(f"{c['sentence']}" + (f":primary[{c['missing_text']}]" if c["missing_text"] else ""), help=c["definition"])


def health_block(d):
    with st.container(key="card-wide-health"):
        st.markdown("**Data Health Check**")
        st.caption("AI answers are only as good as the data behind them. Here's what we have — and what's missing.")
        coverage_rings(d)


QUALITY_ICON = {"fixed": ":material/check_circle:", "human": ":material/warning:", "left": ":material/remove_circle:"}
QUALITY_COLOR = {"fixed": theme.PURPLE, "human": theme.CORAL, "left": "#D8D0E5"}
QUALITY_LEGEND = {"fixed": "Fixed", "human": "Need Review", "left": "Left Unchanged"}
ATTENTION_ROWS = 7                                    # the preview shows at most this many unresolved issues
RESOLUTION_FILTER = ["All Issues", "Fixed Automatically", "Needs Your Review", "Left Unchanged"]
SEVERITY_FILTER = ["All severities", "High", "Medium", "Low"]


def quality_bar(groups):
    """One stacked bar: fixed / need review / left unchanged, widths in proportion to the counts. Plain HTML, no chart library.
    Hovering a segment shows its name, count and share of the total."""
    total = sum(g["total"] for g in groups.values()) or 1
    spans = "".join(f'<span title="{g["title"]} — {g["total"]} issue{"s" if g["total"] != 1 else ""} ({100 * g["total"] / total:.1f}%)" '
                    f'style="flex:{g["total"]};background:{QUALITY_COLOR[k]}"></span>' for k, g in groups.items() if g["total"])
    keys = "".join(f'<span class="dqkey"><i style="background:{QUALITY_COLOR[k]}"></i>{g["total"]} {QUALITY_LEGEND[k]}</span>' for k, g in groups.items())
    st.html(f'<div class="dqbar">{spans}</div><div class="dqkeys">{keys}</div>')


def attention_rows(records):
    """The unresolved issues (group "human"), the three best-known types first, at most ATTENTION_ROWS of them."""
    order = list(trust.ATTENTION_FIRST)
    open_ = [r for r in records if r["group"] == "human"]
    open_.sort(key=lambda r: order.index(r["type"]) if r["type"] in order else len(order))
    return open_[:ATTENTION_ROWS]


def attention_table(rows):
    """A compact HTML table (wrapping text, thin dividers, coral Needs Review badge, muted source). Text is escaped."""
    head = "".join(f"<th>{h}</th>" for h in ("Issue", "Affected Record", "Severity", "Status", "Source", "Content"))
    body = "".join(f"<tr><td class='dq-issue'>{esc(r['issue'])}</td><td>{esc(money(r['record']))}</td><td>{esc(r['severity'])}</td>"
                   f"<td><span class='dq-badge'>Needs Review</span></td><td class='dq-src'>{esc(r['source'])}</td>"
                   f"<td class='dq-content'>{esc(money(r['content']))}</td></tr>" for r in rows)
    st.html(f"<div class='dqtable'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")


def audit_groups(records):
    """The audit grouped by issue type (the existing grouping), with the count, resolution, severity, what was done and every source."""
    out = {}
    for r in records:
        g = out.setdefault(r["type"], {"Issue": r["issue"], "Count": 0, "Resolution": r["resolution"], "Severity": set(), "Source": []})
        g["Count"] += 1
        g["Severity"].add(r["severity"])
        g["Source"].append(r["source"])
    rows = []
    for kind, g in out.items():
        text = trust.ISSUE_TEXT.get(kind, ("human", "{n} problem", "{n} problems"))
        rows.append({**g, "Severity": " / ".join(sorted(g["Severity"], key=SEVERITY_FILTER.index)), "Explanation": money((text[1] if g["Count"] == 1 else text[2]).format(n=g["Count"])),
                     "Source": "; ".join(g["Source"])})
    rows.sort(key=lambda r: (["Fixed Automatically", "Needs Review", "Left Unchanged"].index(r["Resolution"]), -r["Count"], r["Issue"]))
    return rows


def filter_records(records, resolution, severity):
    """Resolution and severity are two different filters: how it was handled vs how serious it is."""
    keep = {"Fixed Automatically": "fixed", "Needs Your Review": "human", "Left Unchanged": "left"}.get(resolution)
    return [r for r in records if (keep is None or r["group"] == keep) and (severity in (None, "All severities") or r["severity"] == severity)]


def quality_block(d):
    """Data Quality (approved layout): header, stacked bar, three cards, Issues Requiring Attention, full audit in an expander.
    All numbers come from backend.services.trust.quality_summary()."""
    q = d["quality_summary"]
    groups, records = q["groups"], q["records"]
    with st.container(key="card-wide-quality"):
        st.markdown(":primary[:material/gpp_maybe:] **Data Quality**")
        st.caption("See what was fixed, what still needs review, and what was left unchanged.")
        st.markdown(f"## {q['total']} issues found  :primary-badge[{q['high']} high severity]")
        quality_bar(groups)
        for col, (key, g) in zip(st.columns(3), groups.items()):
            with col, st.container(key=f"dq-tile-{key}"):
                st.markdown(QUALITY_ICON[key])
                st.markdown(f"# {g['total']}")
                st.markdown(f"**{g['title']}**")
                st.caption(g["note"])
        shown = attention_rows(records)
        head, badge = st.columns([4, 1], vertical_alignment="center")
        head.markdown("**Issues Requiring Attention**")
        if q["to_review"]:
            with badge:
                st.html(f"<div style='text-align:right'><span class='dq-badge'>{q['to_review']} to review</span></div>")
            attention_table(shown)
            if q["to_review"] > len(shown):
                st.caption(f"Showing {len(shown)} of {q['to_review']}. All of them are in the full audit below.")
        else:
            st.info("No issues currently require manual review.")
        st.caption(f"{d['issues']['incomplete_feedback']} unsubmitted scorecards are not counted: missing feedback is not a data error. "
                   "Every issue is explained in docs/DATA_AUDIT.md.")
        with st.expander("View All Issues & Sources"):
            left, right = st.columns(2)
            resolution = left.segmented_control("Resolution", RESOLUTION_FILTER, default="All Issues", key="dq-resolution") or "All Issues"
            severity = right.segmented_control("Severity", SEVERITY_FILTER, default="All severities", key="dq-severity") or "All severities"
            picked = filter_records(records, resolution, severity)
            st.caption(f"{len(picked)} of {len(records)} issues match. Resolution = how it was handled; severity = how serious it is. They are separate.")
            grouped = audit_groups(picked)
            if grouped:
                st.dataframe(pd.DataFrame(grouped, columns=["Issue", "Count", "Resolution", "Severity", "Explanation", "Source"]), hide_index=True,
                             width="stretch", height=table_height(len(grouped)))
            st.markdown(f"**Every record ({len(picked)})**")
            st.dataframe(pd.DataFrame([{"Problem": r["problem"], "Issue": r["issue"], "Type": r["type"].replace("_", " "), "Resolution": r["resolution"],
                                        "Severity": r["severity"], "Handling": r["handling"], "Source": r["source"], "Content": money(r["content"])}
                                       for r in picked]), hide_index=True, width="stretch", height=table_height(min(len(picked), 12)))


# ---------------------------------------------------------------- row 5: Recent Activity | Needs your decision
ACTIVITY_ICON = {"email": ":material/mail:", "scorecard": ":material/check_box:", "note": ":material/description:"}


def activity_block(d):
    with st.container(key="card-short-activity"):
        st.markdown("**Recent Activity**")
        st.caption(f"Newest records in the data, up to {analytics.fmt_date(config.REFERENCE_DATE)}")
        for i, a in enumerate(d["activity"]):
            with st.container(key=f"activity-row-{i}"):
                icon, text, when = st.columns([1, 8, 2], vertical_alignment="center")
                icon.markdown(ACTIVITY_ICON[a["kind"]])
                text.markdown(a["text"])
                text.caption(a["source"])
                when.markdown(a["date"])


def set_tab(tab):
    """Button callback: switch the Candidates page to a filter tab (the tab widget's own key is set before the run)."""
    st.session_state["cand-tab"] = tab


def decision_block(d):
    """Up to three rule-based alerts. "Ask AI about this" opens the Ask AI page with the answer; nothing is sent before the click."""
    n = len(d["decisions"])
    flagged = sum(1 for r in d["candidates"] if r["flags"])
    with st.container(key="card-short-decision"):
        st.markdown(f":material/flag: **Needs your decision ({n})**")
        st.caption("Data issues or time-sensitive items that need a recruiter's review.")
        if not d["decisions"]:
            st.success("Nothing needs a decision right now.")
        for i, a in enumerate(d["decisions"]):
            with st.container(key=f"decision-row-{i}"):
                st.markdown(f"**{money(a['title'])}**  ·  `{a['source'].split(':')[-1]}`")
                st.caption(money(a["text"]))
                st.button("Ask AI about this", key=f"decision-ask-{i}", icon=":material/auto_awesome:", on_click=chat.ask_and_open,
                          args=(a["question"], "other"), use_container_width=True)
        st.button(f"View all {flagged} flags", key="view-all-flags", icon=":material/arrow_forward:", icon_position="right",
                  on_click=set_tab, args=("With Flags",), use_container_width=True)


# ---------------------------------------------------------------- the stalled table (shown on the Candidates page)
def stalled_block(d, job_id=None):
    s = d["stalled"]
    shown = [r for r in s["rows"] if job_id is None or r["job_id"] == job_id]

    def body():
        if shown:
            st.dataframe(pd.DataFrame([{"Candidate": r["candidate"], "Role": r["role"], "Stage": r["stage"],
                                        "Days in stage": r["days_in_stage"], "Entered on": r["entered_on"], "Source": r["source"]}
                                       for r in shown]), hide_index=True, width="stretch", height=table_height(len(shown)))
        else:
            st.success(f"No active application has been in its stage for more than {s['min_days']} days.")
        if s["unknown_stage_date"]:
            st.caption(f"{len(s['unknown_stage_date'])} active application(s) have no usable date for entering their stage and are not listed.")
    card("stalled", f"Stalled candidates ({len(shown)})", body, subtitle=f"Active applications with more than {s['min_days']} days in their current stage "
         f"as of {analytics.fmt_date(config.REFERENCE_DATE)}, longest first", size="wide")


# ---------------------------------------------------------------- page
def load_or_error():
    try:
        return load()
    except analytics.AnalyticsError as e:
        st.error(f"The dashboard could not be built. {e}")
    except Exception as e:                                          # never show a stack trace
        core.log.error("web: dashboard failed: %s", type(e).__name__)
        st.error("The dashboard could not be built. Details are in the server log.")
    return None


def viewing(title):
    with st.container(key="viewing-bar"):
        st.markdown(f"Viewing: **{money(title)}** — the charts below show this role.")


def render_dashboard():
    """The Overview: KPIs and the two top cards next to the AI panel, then full-width rows (see web/app.py for the header)."""
    d = load_or_error()
    if d is None:
        return
    titles = {r["job_id"]: r["title"] for r in d["roles"]}
    if "dash-role" not in st.session_state and st.session_state.get("role-chosen") in titles:
        st.session_state["dash-role"] = st.session_state["role-chosen"]   # come back to the Overview with the same role
    chosen = st.session_state.get("dash-role") or next(iter(titles))      # the role filter (set by Open Positions or the funnel card)

    main, side = st.columns([2.2, 1], gap="medium")                       # top: main area + right panel
    with main:
        kpi_section(d)                                                    # row 1
        left, right = st.columns([1, 1])                                  # row 2
        with left:
            positions_block(d, chosen)
        with right:
            priority_block(d)
    with side:
        panel.render_ai_panel(titles[chosen])

    viewing(titles[chosen])                                               # full width from here on
    cols = st.columns(3)
    with cols[0]:
        job_id = funnel_block(d, titles, chosen)
        st.session_state["role-chosen"] = job_id                          # a widget's own state is dropped when its page is left
    with cols[1]:
        dwell_block(d["funnels"][job_id])
    with cols[2]:
        exits_block(d, job_id)

    health_block(d)
    quality_block(d)

    card("roles", "Roles compared", lambda: show(roles_figure(d["roles"]), "chart-roles"),
         "How many applications each role has, split by where they ended up. A role that has been open longest "
         "with no hire is the one to look at first.", size="wide")
