"""Chat pieces shared by the Overview side panel and the Ask AI page. PRESENTATION ONLY: every answer comes from the
Agent Core (core.ask_sync); this file holds no business logic, no SQL and no data access.

What it adds on top of the plain answer text:
  - answer blocks: the model writes FACTS / AI ASSESSMENT / CAVEATS (see the system prompt). We show them as separate blocks,
    CAVEATS under the name "ASSUMPTIONS & CAVEATS". SOURCES is built here in Python from the [file:id] references in the answer.
  - the "Candidate Ranking Breakdown" chart: drawn from the rank_candidates_for_job tool result of THIS answer (Python scores),
    so it can not disagree with the answer. Candidates without feedback are shown as "not measured", never as 0.
Privacy: the question and the answer are never logged. Logs hold counts only.
"""
import json
import re
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from backend import config
from backend.agent import core
from web import evidence, theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"
AVATAR = {"user": ":material/person:", "assistant": str(ASSETS / "logo_icon.png")}
PANEL_TITLE = "How this was calculated"
MAX_INPUT_CHARS = 80
RANK_TOOL = "rank_candidates_for_job"


def safe(text):
    """Text for display: API key removed (second guard), and $ escaped so prices do not turn into math."""
    return core.scrub(text or "").replace("$", "\\$")


# ---------------------------------------------------------------- MCP status (free: no model call)
@st.cache_data(ttl=300, show_spinner=False)
def mcp_status():
    """(connected, number of tools). The MCP server is started and asked for its tool list; cached for 5 minutes."""
    return core.check_mcp()


# ---------------------------------------------------------------- answer blocks
_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?\**\s*(FACTS|AI ASSESSMENT|ASSUMPTIONS|CAVEATS)\b\s*\**\s*:?\s*\**\s*(.*)$")   # uppercase only, as the prompt asks
_LABEL = {"FACTS": "FACTS", "AI ASSESSMENT": "AI ASSESSMENT", "ASSUMPTIONS": "ASSUMPTIONS", "CAVEATS": "ASSUMPTIONS & CAVEATS"}
_REF = re.compile(r"^[A-Za-z_]+(?:\.[A-Za-z]+)?:[\w.@-]+$")


def parse_answer(text):
    """Split an answer into [(label, body)]. Text before the first heading has the label "". An answer with no known
    heading comes back as one block with label "" (shown as plain text, nothing is dropped)."""
    blocks, label, body = [], "", []
    for line in (text or "").splitlines():
        m = _HEADING.match(line)
        if m:
            blocks.append((label, "\n".join(body).strip()))
            label, body = _LABEL[m.group(1)], ([m.group(2)] if m.group(2) else [])
        else:
            body.append(line)
    blocks.append((label, "\n".join(body).strip()))
    return [(lab, b) for lab, b in blocks if b or lab]


def extract_sources(text):
    """Unique [file:id] references from the answer, in order of appearance. Done in Python, not by the model."""
    seen = []
    for group in re.findall(r"\[([^\[\]]+)\]", text or ""):
        for part in re.split(r"[;,]", group):
            ref = part.strip()
            if _REF.match(ref) and ref not in seen:
                seen.append(ref)
    return seen


# ---------------------------------------------------------------- ranking chart (from the tool result, not from the answer text)
def ranking_chart_data(tool_calls):
    """Rows for the Candidate Ranking Breakdown from the last successful rank_candidates_for_job result, or None."""
    for c in reversed(tool_calls or []):
        if c.get("name") != RANK_TOOL or not c.get("ok") or not c.get("result"):
            continue
        try:
            data = (json.loads(c["result"]) or {}).get("data") or {}
        except (ValueError, TypeError):
            return None                                           # a truncated result is not valid JSON: no chart, no guess
        ranked = data.get("ranked") or []
        if not ranked:
            return None
        fb, pr = data["formula"]["feedback_weight"], data["formula"]["progress_weight"]
        return {"title": data.get("title", ""), "feedback_weight": fb, "progress_weight": pr,
                "rows": [{"name": r["name"], "score": r["score"], "feedback": r["components"]["feedback"]["points"],
                          "progress": r["components"]["progress"]["points"], "thin": r.get("evidence_level") == "thin",
                          "rank": r.get("rank"), "stage": r.get("current_stage"), "application_id": r.get("application_id"),
                          "open_tasks": len(r.get("open_tasks") or []), "stage_conflict": bool(r.get("stage_conflict"))} for r in ranked],
                "not_measured": [r["name"] for r in (data.get("not_scored") or [])[:2]]}
    return None


URGENT_FLAGS = ("Offer deadline overdue", "Status conflict", "Score/text conflict")


def add_flags(chart):
    """Risk flags per ranked row. Rule-based: two from the services (deadline, status conflict), three from the tool result
    itself (stage conflict, open tasks, thin evidence). Urgent = one of the two service flags. Never read from the answer text."""
    if not chart:
        return chart
    try:
        service = evidence.service_flags([r["application_id"] for r in chart["rows"] if r.get("application_id")])
    except Exception as e:                                        # a flag is an extra: the answer must not fail because of it
        core.log.error("web: risk flags failed: %s", type(e).__name__)
        service = {}
    for r in chart["rows"]:
        flags = list(service.get(r.get("application_id"), []))
        if r["stage_conflict"]:
            flags.append("Stage conflict")
        if r["open_tasks"]:
            flags.append(f"{r['open_tasks']} open task{'s' if r['open_tasks'] != 1 else ''}")
        if r["thin"]:
            flags.append("Thin evidence (1 scorecard)")
        r["flags"], r["urgent"] = flags, any(f in URGENT_FLAGS for f in flags)
    return chart


def ranking_figure(chart):
    """Stacked bar: points from interview feedback + points from stage progress = score. A candidate with no feedback has
    NO bar: the row says "not measured"."""
    names = [r["name"] for r in chart["rows"]] + [n for n in chart["not_measured"] if n not in {r["name"] for r in chart["rows"]}]
    fig = go.Figure()
    fig.add_bar(y=names, x=[r["feedback"] for r in chart["rows"]] + [None] * (len(names) - len(chart["rows"])), orientation="h",
                name=f"Interview feedback ({round(chart['feedback_weight'] * 100)}%)", marker_color=theme.PURPLE,
                hovertemplate="%{y}<br>Feedback: %{x} points<extra></extra>")
    fig.add_bar(y=names, x=[r["progress"] for r in chart["rows"]] + [None] * (len(names) - len(chart["rows"])), orientation="h",
                name=f"Stage progress ({round(chart['progress_weight'] * 100)}%)", marker_color=theme.PURPLE_SOFT,
                hovertemplate="%{y}<br>Progress: %{x} points<extra></extra>")
    for r in chart["rows"]:
        fig.add_annotation(x=r["score"], y=r["name"], text=f" {r['score']:.0f}", showarrow=False, xanchor="left",
                           font=dict(color=theme.TEXT, size=12))
    for n in names[len(chart["rows"]):]:
        fig.add_annotation(x=0, y=n, text="not measured", showarrow=False, xanchor="left",
                           font=dict(color=theme.MUTED, size=11))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 112], title_text="Score (0 to 100)")
    return theme.style_figure(fig, height=60 + 38 * len(names))


# ---------------------------------------------------------------- which kind of question was asked
KIND_TOOLS = (("top", "rank_candidates_for_job"), ("dropoffs", "get_funnel"), ("tasks", "list_tasks"))


def answer_kind(asked_kind, tool_calls):
    """"top" | "dropoffs" | "tasks" | "other". The button that was clicked wins. A typed question is classified by the tools the
    agent used (rank_candidates_for_job, get_funnel, list_tasks), never by reading the answer text."""
    if asked_kind:
        return asked_kind
    used = {c.get("name") for c in tool_calls or [] if c.get("ok")}
    return next((kind for kind, tool in KIND_TOOLS if tool in used), "other")


# ---------------------------------------------------------------- calling the agent
def run_agent(question, history, kind=None):
    """Returns a message dict. Never raises, never shows a stack trace."""
    try:
        r = core.ask_sync(question, history=history, keep_results=True)
    except Exception as e:                                        # e.g. the MCP server could not start
        core.log.error("web: agent call failed: %s", type(e).__name__)
        return {"role": "assistant", "content": "", "status": "app_error", "error": None, "meta": None, "chart": None, "kind": "other"}
    core.log.info("web: status=%s rounds=%d tools=%d", r.status, r.rounds, len(r.tool_calls))
    meta = {"model": r.model, "rounds": r.rounds, "usage": dict(r.usage),
            "tool_calls": [{k: v for k, v in c.items() if k != "result"} for c in r.tool_calls]}
    return {"role": "assistant", "content": r.answer, "status": r.status, "error": r.error, "meta": meta,
            "chart": add_flags(ranking_chart_data(r.tool_calls)) if r.status == "ok" else None,
            "kind": answer_kind(kind, r.tool_calls)}


def agent_history(messages):
    """Earlier question/answer pairs (text only) for follow-ups. Only pairs whose answer was ok; the last N."""
    pairs = []
    for user, assistant in zip(messages[0::2], messages[1::2]):
        if assistant.get("status") == "ok":
            pairs += [{"role": "user", "content": user["content"]}, {"role": "assistant", "content": assistant["content"]}]
    return pairs[-2 * config.UI_MAX_HISTORY_TURNS:]


def exchange(question, uid, kind=None, mode="full", render=None):
    """Ask one question with the shared conversation as context, show it, and keep it in session_state.
    kind = the button that was clicked ("top", "dropoffs", "tasks") or None for a typed question."""
    render = render or render_message
    history = agent_history(st.session_state.messages)
    user_msg = {"role": "user", "content": question}
    with st.chat_message("user", avatar=AVATAR["user"]):
        render(user_msg, f"{uid}-new-u", mode)
    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
        with st.spinner("Checking the data… this can take 10 to 30 seconds."):
            reply = run_agent(question, history, kind)
        render(reply, f"{uid}-new-a", mode)
    st.session_state.messages += [user_msg, reply]


def show_history(uid, mode="full", render=None, last=None):
    """Show the shared conversation. last=N shows only the newest N messages (the panel shows the latest exchange)."""
    render = render or render_message
    start = max(len(st.session_state.messages) - last, 0) if last else 0
    for i, m in enumerate(st.session_state.messages):
        if i < start:
            continue
        with st.chat_message(m["role"], avatar=AVATAR[m["role"]]):
            render(m, f"{uid}-{i}", mode)


def ask_and_open(question, kind=None):
    """Button callback ("Ask AI about this"): the question is answered on the Ask AI page, where the full answer is shown."""
    ask_later(question, kind)
    go_to("Ask AI")


def ask_later(question, kind=None):
    """Button callback: remember the question (and which button it came from); the panel answers it in the run that follows."""
    st.session_state["pending"] = question
    st.session_state["pending_kind"] = kind


def go_to(page):
    st.session_state["page"] = page
    if page == "Ask AI":
        st.session_state["scroll_last"] = True                       # the Ask AI page scrolls to the newest answer


# ---------------------------------------------------------------- rendering
def render_notice(msg):
    status = msg.get("status")
    if status == "api_error":
        st.error(f"I couldn't get an answer from the AI service. {safe(msg.get('error'))} Please try again in a moment.")
    elif status == "config_error":
        st.error("The AI service is not set up: the API key is missing. Add ANTHROPIC_API_KEY to the .env file and restart the app.")
    elif status == "app_error":
        st.error("Something went wrong while getting the answer. Please try again. If it keeps happening, check the server log.")
    elif status == "max_tool_rounds":
        st.warning(f"This question needed more steps than allowed ({config.AGENT_MAX_TOOL_ROUNDS} model rounds), "
                   "so the answer below is incomplete. Try a narrower question.")
    elif status == "refusal":
        st.warning("The model declined to answer this request. Try rephrasing it as a question about the recruiting data.")
    elif status == "max_tokens":
        st.warning("The answer was cut off because it was too long. Try a narrower question.")
    elif status == "invalid_input":
        st.info(safe(msg.get("content")))
    elif status not in ("ok", None):
        st.warning("The answer may be incomplete (the model stopped unexpectedly).")


def tool_call_table(calls):
    rows = ["| Round | Tool | Inputs | Result | Items | ms |", "|---|---|---|---|---|---|"]
    for c in calls:
        inputs = json.dumps(c["input"], ensure_ascii=False)
        inputs = (inputs[:MAX_INPUT_CHARS] + "…") if len(inputs) > MAX_INPUT_CHARS else inputs
        result = "ok" if c["ok"] else f"error: {c['error_code']}"
        rows.append(f"| {c['round']} | `{c['name']}` | `{inputs.replace('|', '/')}` | {result} | {c['items']} | {c['ms']} |")
    return "\n".join(rows)


def render_panel(meta, note=None):
    with st.expander(PANEL_TITLE, expanded=False):
        if note:
            st.markdown(safe(note))
        if meta["tool_calls"]:
            st.markdown(safe(tool_call_table(meta["tool_calls"])))
        else:
            st.markdown("No tools were used.")
        u = meta["usage"]
        st.caption(safe(f"Model: {meta['model']} · Rounds: {meta['rounds']} · Model calls: {u.get('requests', 0)} · Tokens: "
                        f"{u.get('input_tokens', 0)} new input, {u.get('output_tokens', 0)} output, {u.get('cache_read_tokens', 0)} cache read, "
                        f"{u.get('cache_creation_tokens', 0)} cache write"))


def first_paragraph(body, max_lines=3):
    """The first paragraph of a text, at most max_lines lines (a bullet list counts as one paragraph), plain splitting only."""
    para = (body or "").strip().split("\n\n")[0]
    lines = para.splitlines()
    return "\n".join(lines[:max_lines]) + ("\n…" if len(lines) > max_lines else "")


def summary_text(text):
    """Short summary for the panel: the first paragraph of FACTS (or of the whole answer when there is no FACTS block)."""
    blocks = parse_answer(text)
    facts = next((b for label, b in blocks if label == "FACTS" and b), None)
    return first_paragraph(facts if facts is not None else next((b for _, b in blocks if b), text))


def render_top_rows(chart, uid):
    """Three rows for the panel: rank, name, score, stage, one risk flag. All from the ranking tool result."""
    for i, r in enumerate(chart["rows"][:3]):
        with st.container(key=f"top-row-{uid}-{i}"):
            left, right = st.columns([4, 1.4], vertical_alignment="center")
            left.markdown(f"**#{r.get('rank') or i + 1} {safe(r['name'])}**")
            right.markdown(f"**{r['score']:.0f}**/100")
            flag = (r.get("flags") or [None])[0]
            badge = (":primary-badge[⚠ " + flag + "]") if r.get("urgent") else (f":gray-badge[{flag}]" if flag else ":gray-badge[No risk flag]")
            st.markdown(f":violet-badge[{safe(r.get('stage') or 'stage unknown')}] {badge}")


def render_summary(msg, uid):
    """Panel mode: a short summary and a button to the full answer on the Ask AI page (the same stored answer, no new call)."""
    if msg.get("kind") == "top" and msg.get("chart"):
        render_top_rows(msg["chart"], uid)
    elif msg.get("content"):
        st.markdown(safe(summary_text(msg["content"])))
    if msg.get("content"):
        st.button("Read full answer", key=f"read-full-{uid}", icon=":material/open_in_full:", on_click=go_to, args=("Ask AI",))


def render_message(msg, uid="m", mode="panel"):
    """The panel view (a short summary). The full answer of the Ask AI page is drawn by web/answer.py."""
    if msg["role"] == "user":
        st.markdown(safe(msg["content"]))
        return
    render_notice(msg)
    if msg.get("status") != "invalid_input":
        render_summary(msg, uid)
