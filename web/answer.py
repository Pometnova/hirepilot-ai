"""The full answer of the Ask AI page. PRESENTATION ONLY. The layout depends on WHICH question was asked (the button, or the
tools the agent used, see chat.answer_kind), never on reading the answer text:
  top       3 candidate cards + "Interview & Progress Score" chart (both from the ranking tool result) -> AI ASSESSMENT -> expanders
  dropoffs  funnel, median days and exits donut for the role (from services)                            -> AI ASSESSMENT -> expanders
  tasks     counts and the task table, most urgent first (from services)                                -> AI ASSESSMENT -> expanders
  other     FACTS / AI ASSESSMENT / ASSUMPTIONS & CAVEATS blocks                                        -> expanders
Collapsed expanders: Detailed evidence (FACTS), Data issues & assumptions (CAVEATS), Sources (N), How this was calculated.
Source labels and candidate names come from a DB lookup in the services, not from the model.
"""
import re

import pandas as pd
import streamlit as st

from web import chat, dashboard, evidence

AI_SUBTITLE = "AI reasoning based on the facts above"
CAVEAT_LABELS = ("ASSUMPTIONS", "ASSUMPTIONS & CAVEATS")
_JUDGEMENT = re.compile(r"^\s*\**\(my judgement[^)\n]*\)\**[\s:.\-–—]*", re.IGNORECASE)
HOW = {"top": "Score = 100 × (feedback weight × interview feedback + progress weight × stage progress). Feedback is the mean of the "
              "interview scores; progress is the position of the stage in the pipeline. The weights are our assumption. It does not "
              "measure fit to the role. A candidate with no submitted feedback is “not measured”, which is missing feedback, not a "
              "low score. Risk flags are rule-based: offer deadline passed, status conflict, score/text conflict, stage conflict, open tasks, thin evidence.",
       "dropoffs": "Drop-off into a stage = (rejected + withdrew at the previous stage) ÷ (reached the previous stage). Candidates still "
                   "waiting are not lost. The numbers come from the funnel service, not from the AI text.",
       "tasks": "Overdue means the due date is before the data date (Oct 15, 2026). The table is sorted overdue, due today, pending, no "
                "due date, from the task service, not from the AI text.",
       "other": "The AI called the tools listed below and wrote the answer from their results."}


# ---------------------------------------------------------------- small helpers
@st.cache_data(show_spinner=False)
def names():
    return evidence.candidate_names()


def highlight(text):
    """Make candidate names bold and coloured. Display only: the text is not parsed for anything else."""
    found = names()
    if not found or not text:
        return text
    pattern = re.compile(r"(?<![\w*])\**(" + "|".join(re.escape(n) for n in found) + r")\**(?![\w*])")
    return pattern.sub(lambda m: f"**:violet[{m.group(1)}]**", text)


def show(text):
    st.markdown(chat.safe(highlight(text)))


def body_of(blocks, labels):
    return "\n\n".join(b for label, b in blocks if label in labels and b)


# ---------------------------------------------------------------- blocks
def render_block(label, body, uid, n):
    slug = "caveats" if label in CAVEAT_LABELS or label.startswith("ASSUMPTIONS") else label.split()[0].lower()
    if label == "AI ASSESSMENT":
        body = _JUDGEMENT.sub("", body)                       # hide a leading "(my judgement…)" in the UI only
    with st.container(key=f"answer-block-{slug}-{uid}-{n}"):
        st.markdown(f"##### {label}")
        if label == "AI ASSESSMENT":
            st.caption(AI_SUBTITLE)
        show(body)


# ---------------------------------------------------------------- the three question-specific views
def render_top(chart, uid):
    for i, (col, r) in enumerate(zip(st.columns(3), chart["rows"][:3])):
        with col, st.container(key=f"cand-card-{uid}-{i}" + ("-urgent" if r.get("urgent") else "")):
            st.markdown(f"### #{r.get('rank') or i + 1}")
            st.markdown(f"**{chat.safe(r['name'])}**")
            st.markdown(f"**{r['score']:.0f}**/100")
            badges = [f":violet-badge[{chat.safe(r.get('stage') or 'stage unknown')}]"]
            for f in r.get("flags") or []:
                badges.append(f":primary-badge[⚠ {f}]" if f in chat.URGENT_FLAGS else f":gray-badge[{f}]")
            st.markdown(" ".join(badges))
    with st.container(key=f"ranking-card-{uid}"):
        st.markdown("**Interview & Progress Score**")
        st.plotly_chart(chat.ranking_figure(chart), width="stretch", config=dashboard.CHART_CONFIG, key=f"rank-{uid}")
        st.caption(f"Score = {round(chart['feedback_weight'] * 100)}% interview feedback + {round(chart['progress_weight'] * 100)}% "
                   "stage progress (weights are our assumption). It does not measure fit to the role. A candidate with no "
                   "feedback yet is “not measured”: that is missing feedback, not a low score.")


def funnel_job(msg, d):
    """The role of the funnel question: the job_id the agent asked get_funnel about, else the role selected on the Overview."""
    for c in (msg.get("meta") or {}).get("tool_calls", []):
        if c.get("name") == "get_funnel" and c.get("ok") and (c.get("input") or {}).get("job_id") in d["funnels"]:
            return c["input"]["job_id"]
    chosen = st.session_state.get("role-chosen") or st.session_state.get("dash-role")
    return chosen if chosen in d["funnels"] else next(iter(d["funnels"]))


def render_dropoffs(msg, uid):
    d = dashboard.load_or_error()
    if d is None:
        return
    job = funnel_job(msg, d)
    f = d["funnels"][job]
    st.markdown(f"Viewing: **{dashboard.money(f['title'])}**")
    left, mid, right = st.columns(3)
    with left, st.container(key=f"answer-view-funnel-{uid}"):
        st.markdown("**Recruitment funnel**")
        dashboard.show(dashboard.funnel_figure(f), f"funnel-{uid}")
    with mid, st.container(key=f"answer-view-dwell-{uid}"):
        st.markdown("**Median days in stage**")
        fig = dashboard.dwell_figure(f)
        if fig is not None:
            dashboard.show(fig, f"dwell-{uid}")
    with right, st.container(key=f"answer-view-exits-{uid}"):
        st.markdown("**Why candidates leave**")
        e = d["exits"][job]
        if e["note"]:
            st.info(e["note"])
        else:
            dashboard.show(dashboard.exits_figure(e), f"exits-{uid}")


def render_tasks(uid):
    d = dashboard.load_or_error()
    if d is None:
        return
    counts = d["tasks"]["counts"]
    with st.container(key=f"answer-view-tasks-{uid}"):
        for col, (key, name) in zip(st.columns(4), dashboard.STATE_TEXT.items()):
            col.markdown(f"## {counts[key]}")
            col.caption(name)
        rows = d["tasks"]["priority"]
        st.dataframe(dashboard.task_frame(rows), hide_index=True, width="stretch", height=dashboard.table_height(len(rows)))
        st.caption("Most urgent first: overdue, due today, pending, no due date.")


# ---------------------------------------------------------------- expanders
def unique_groups(groups):
    """Source groups with each reference once per group (the first one is kept), empty groups dropped."""
    out = []
    for g in groups:
        seen, items = set(), []
        for item in g["items"]:
            if item["ref"] not in seen:
                seen.add(item["ref"])
                items.append(item)
        if items:
            out.append({**g, "items": items})
    return out


def render_sources(text, uid):
    """The Sources expander. Widget keys come from the message uid + group index + item index, never from the text of a source,
    so the same reference in two groups or in two answers on the page cannot clash."""
    refs = chat.extract_sources(text)
    if not refs:
        return
    groups = unique_groups(evidence.source_labels(refs)["groups"])
    with st.expander(f"Sources ({sum(len(g['items']) for g in groups)})", expanded=False):
        for gi, g in enumerate(groups):
            st.markdown(f"**{chat.safe(g['candidate'])}**" if g["candidate"] != "Other" else "**Other**")
            for ii, item in enumerate(g["items"]):
                with st.container(key=f"src-row-{uid}-{gi}-{ii}"):
                    st.markdown(chat.safe(item["label"]))
                    st.caption(chat.safe(item["ref"]))


def render_expanders(msg, blocks, kind, uid):
    facts, caveats = body_of(blocks, ("FACTS",)), body_of(blocks, CAVEAT_LABELS)
    if kind != "other":                                                  # on the other layout these two are shown as blocks
        if facts:
            with st.expander("Detailed evidence", expanded=False):
                show(facts)
        if caveats:
            with st.expander("Data issues & assumptions", expanded=False):
                show(caveats)
    render_sources(msg["content"], uid)
    if msg.get("meta"):
        chat.render_panel(msg["meta"], note=HOW[kind])


# ---------------------------------------------------------------- the whole answer
def render_answer(msg, uid):
    kind = chat.answer_kind(msg.get("kind"), [])
    if kind == "top" and not msg.get("chart"):
        kind = "other"                                                   # no ranking result: nothing to draw
    blocks = chat.parse_answer(msg["content"])
    known = any(label for label, _ in blocks)
    if blocks and not blocks[0][0]:                                      # text before the first heading (or the whole text)
        show(blocks[0][1])
    if kind == "top":
        render_top(msg["chart"], uid)
    elif kind == "dropoffs":
        render_dropoffs(msg, uid)
    elif kind == "tasks":
        render_tasks(uid)
    if known:
        keep = ("AI ASSESSMENT",) if kind != "other" else ("FACTS", "AI ASSESSMENT") + CAVEAT_LABELS
        for n, (label, body) in enumerate(blocks):
            if label in keep:
                render_block(label, body, uid, n)
    render_expanders(msg, blocks, kind, uid)


def render_message(msg, uid="m", mode="full"):
    if msg["role"] == "user":
        st.markdown(chat.safe(msg["content"]))
        return
    chat.render_notice(msg)
    if msg.get("content") and msg.get("status") != "invalid_input":
        render_answer(msg, uid)


def show_history(uid):
    chat.show_history(uid, render=render_message)


def exchange(question, uid, kind=None):
    chat.exchange(question, uid, kind=kind, render=render_message)
