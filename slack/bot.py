"""HirePilot Slack bot (Slack Bolt, Socket Mode). PRESENTATION ONLY: every answer comes from the Agent Core
(core.ask_sync); this file holds no business logic, no SQL and no data access.

Run from the project root:   .venv/bin/python -I slack/bot.py
Needs in .env: SLACK_BOT_TOKEN (xoxb-...), SLACK_APP_TOKEN (xapp-...). Optional: SLACK_ALLOWED_USER_IDS=U123,U456.
If SLACK_ALLOWED_USER_IDS is empty, EVERYONE in the Slack workspace can use the bot (and spend the API budget).

How it works: an @mention in a channel, or a direct message, starts a thread. The bot posts "Working on it...", asks the
agent, then replaces that message with the answer. A reply in the same thread sends the earlier thread messages as history.
Privacy: logs hold counts only (status, rounds, tool count, lengths); question and answer text are never logged.
"""
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # `python -I slack/bot.py` does not add the project root

from slack_sdk.errors import SlackApiError  # noqa: E402

from backend import config  # noqa: E402  (also loads .env)
from backend.agent import core  # noqa: E402
from slack.format import split_message, to_mrkdwn  # noqa: E402

WORKING = "Working on it…"
WARN = "⚠️ "                                  # every status message starts with this, so history can skip them
NOT_ALLOWED = WARN + "Sorry, you are not on the list of people who can use this bot."
EMPTY = WARN + "Ask me a question about the recruiting data, for example: _Which tasks are pending or overdue?_"
FOOTER_PREFIX = "_Tools: "
_MENTION = re.compile(r"<@[A-Z0-9]+(\|[^>]*)?>")
_SEEN_MAX = 500


# ---------------------------------------------------------------- small helpers
def parse_allowlist(value):
    """'U1, U2' -> {'U1', 'U2'}. Empty or missing -> empty set, which means: everyone may use the bot."""
    return {x.strip() for x in (value or "").split(",") if x.strip()}


def clean_question(text):
    return _MENTION.sub("", text or "").strip()


def footer(result):
    tools = list(dict.fromkeys(c["name"] for c in result.tool_calls))
    cost = result.estimated_cost_usd
    shown = "under $0.01" if cost < 0.005 else f"${cost:.2f}"
    return f"{FOOTER_PREFIX}{', '.join(tools) if tools else 'none'} · est. cost {shown}_"


def status_text(result):
    """Friendly message for a non-ok status (or None when the answer is fine). Same wording as the web app."""
    s = result.status
    if s == "ok":
        return None
    if s == "api_error":
        return WARN + "I couldn't get an answer from the AI service. Please try again in a moment."
    if s == "config_error":
        return WARN + "The AI service is not set up: the API key is missing. Ask the admin to check the .env file."
    if s == "app_error":
        return WARN + "Something went wrong while getting the answer. Please try again."
    if s == "max_tool_rounds":
        return WARN + (f"This question needed more steps than allowed ({config.AGENT_MAX_TOOL_ROUNDS} model rounds), "
                       "so the answer below is incomplete. Try a narrower question.")
    if s == "refusal":
        return WARN + "The model declined to answer this request. Try rephrasing it as a question about the recruiting data."
    if s == "max_tokens":
        return WARN + "The answer was cut off because it was too long. Try a narrower question."
    if s == "invalid_input":
        return WARN + core.scrub(result.answer or "Please ask a shorter question.")
    return WARN + "The answer may be incomplete (the model stopped unexpectedly)."


def thread_history(client, channel, thread_ts, current_ts, bot_user_id):
    """Earlier question/answer pairs of this thread, text only, oldest first, capped like the web app.
    Skipped: the current message, 'Working on it', warnings, footers, and questions that got no answer."""
    try:
        msgs = client.conversations_replies(channel=channel, ts=thread_ts, limit=200).get("messages", [])
    except SlackApiError:
        core.log.warning("slack: could not read the thread, continuing without history")
        return []
    turns = []
    for m in msgs:
        if m.get("ts") == current_ts or m.get("subtype"):
            continue
        text = m.get("text") or ""
        if m.get("user") == bot_user_id or m.get("bot_id"):
            if text == WORKING or text.startswith(WARN) or not text.strip():
                continue
            lines = [ln for ln in text.split("\n") if not ln.startswith(FOOTER_PREFIX)]
            turns.append({"role": "assistant", "content": "\n".join(lines).strip()})
        else:
            q = clean_question(text)
            if q:
                turns.append({"role": "user", "content": q})
    pairs = []
    for a, b in zip(turns, turns[1:]):                      # keep a user message only when an answer follows it
        if a["role"] == "user" and b["role"] == "assistant":
            pairs += [a, b]
    return pairs[-2 * config.UI_MAX_HISTORY_TURNS:]


# ---------------------------------------------------------------- the handler
class Bot:
    def __init__(self, client, bot_user_id, allowed=None, ask=None):
        self.client, self.bot_user_id = client, bot_user_id
        self.allowed = set(allowed or ())
        self.ask = ask or core.ask_sync                      # injected in tests
        self.seen = OrderedDict()

    def _is_new(self, event):
        key = (event.get("channel"), event.get("ts"))
        if key in self.seen:
            return False
        self.seen[key] = True
        while len(self.seen) > _SEEN_MAX:
            self.seen.popitem(last=False)
        return True

    def wants(self, event, kind):
        """kind = 'mention' (app_mention event) or 'message' (message event: only direct messages count)."""
        if event.get("bot_id") or event.get("subtype") or event.get("user") in (None, self.bot_user_id):
            return False
        return kind == "mention" or event.get("channel_type") == "im"

    def handle(self, event, kind):
        if not self.wants(event, kind) or not self._is_new(event):
            return
        channel, user, ts = event["channel"], event["user"], event["ts"]
        thread_ts = event.get("thread_ts") or ts             # always reply in a thread
        if self.allowed and user not in self.allowed:
            core.log.info("slack: blocked a user who is not on the allowlist")
            self._post(channel, thread_ts, NOT_ALLOWED)
            return
        question = clean_question(event.get("text"))
        if not question:
            self._post(channel, thread_ts, EMPTY)
            return
        placeholder = self._post(channel, thread_ts, WORKING)
        history = thread_history(self.client, channel, thread_ts, ts, self.bot_user_id) if event.get("thread_ts") else []
        try:
            result = self.ask(question, history=history)
        except Exception as e:                               # e.g. the MCP server could not start. Never show the details.
            core.log.error("slack: agent call failed: %s", type(e).__name__)
            self._replace(channel, thread_ts, placeholder, [WARN + "Something went wrong while getting the answer. Please try again."])
            return
        core.log.info("slack: status=%s rounds=%d tools=%d question_chars=%d history_msgs=%d", result.status, result.rounds,
                      len(result.tool_calls), len(question), len(history))
        problem = status_text(result)
        has_answer = result.status in ("ok", "max_tool_rounds", "max_tokens", "unexpected_stop", "refusal")
        body = core.scrub(to_mrkdwn(result.answer)) if (result.answer and has_answer) else ""
        if problem and not body:
            texts = [problem]
        else:
            parts = split_message(body or "(no answer)")
            if problem:
                parts[0] = problem + "\n\n" + parts[0]
            parts[-1] += "\n\n" + footer(result)
            texts = parts
        self._replace(channel, thread_ts, placeholder, texts)

    # -- Slack calls (all text passes through core.scrub, the second guard against the API key)
    def _post(self, channel, thread_ts, text):
        r = self.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=core.scrub(text))
        return r.get("ts")

    def _replace(self, channel, thread_ts, placeholder_ts, texts):
        first, rest = core.scrub(texts[0]), texts[1:]
        try:
            self.client.chat_update(channel=channel, ts=placeholder_ts, text=first)
        except (SlackApiError, TypeError):                   # the placeholder cannot be edited: post a new message
            core.log.warning("slack: could not update the placeholder, posting a new message")
            self._post(channel, thread_ts, first)
        for t in rest:
            self._post(channel, thread_ts, t)


def register(app, bot_user_id, allowed=None, ask=None):
    bot = Bot(app.client, bot_user_id, allowed, ask)

    @app.event("app_mention")
    def on_mention(event):
        bot.handle(event, "mention")

    @app.event("message")
    def on_message(event):
        bot.handle(event, "message")

    return bot


def main():
    bot_token, app_token = os.environ.get("SLACK_BOT_TOKEN", ""), os.environ.get("SLACK_APP_TOKEN", "")
    missing = [n for n, v in (("SLACK_BOT_TOKEN", bot_token), ("SLACK_APP_TOKEN", app_token)) if not v.strip()]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}. See the Slack section of the README.")
        return 2
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    app = App(token=bot_token)
    bot_user_id = app.client.auth_test()["user_id"]
    allowed = parse_allowlist(os.environ.get("SLACK_ALLOWED_USER_IDS"))
    register(app, bot_user_id, allowed)
    print(f"HirePilot Slack bot running. Allowlist: {len(allowed)} user(s)"
          f"{'' if allowed else ' (EMPTY: everyone in the workspace can use the bot)'}.")
    SocketModeHandler(app, app_token).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
