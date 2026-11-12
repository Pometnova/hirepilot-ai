"""Phase 7 tests. FREE: a fake agent and a fake Slack client. No network, no Slack connection, no API key."""
import ast
import logging
from pathlib import Path

import pytest
from slack_sdk.errors import SlackApiError

from backend import config
from backend.agent.core import AgentResult
from slack import bot as slackbot
from slack.format import split_message, to_mrkdwn

ROOT = Path(__file__).resolve().parents[1]
BOT = "UBOT"
SENTINEL = "sk-ant-api03-TESTSENTINEL0123456789abcdef"


# ---------- fakes ----------
class FakeSlack:
    def __init__(self, thread=None, update_fails=False):
        self.posts, self.updates, self.thread, self.update_fails, self.n = [], [], thread or [], update_fails, 0

    def chat_postMessage(self, channel, thread_ts, text):
        self.n += 1
        self.posts.append({"channel": channel, "thread_ts": thread_ts, "text": text, "ts": f"9{self.n}.0"})
        return {"ok": True, "ts": f"9{self.n}.0"}

    def chat_update(self, channel, ts, text):
        if self.update_fails:
            raise SlackApiError("cannot edit", {"ok": False, "error": "message_not_found"})
        self.updates.append({"channel": channel, "ts": ts, "text": text})
        return {"ok": True}

    def conversations_replies(self, channel, ts, limit):
        return {"messages": self.thread}


class FakeAgent:
    def __init__(self, answer="Hello **world**", status="ok", cost=0.034, raises=None, tools=("get_funnel", "list_jobs", "get_funnel")):
        self.answer, self.status, self.cost, self.raises, self.tools, self.calls = answer, status, cost, raises, tools, []

    def __call__(self, question, history=None):
        self.calls.append({"question": question, "history": history})
        if self.raises:
            raise self.raises
        r = AgentResult(question=question, answer=self.answer, status=self.status, rounds=2, model="m",
                        tool_calls=[{"name": n, "input": {}, "ok": True} for n in self.tools], estimated_cost_usd=self.cost)
        return r


def make(agent=None, allowed=None, **kw):
    client = FakeSlack(**kw)
    agent = agent or FakeAgent()
    return slackbot.Bot(client, BOT, allowed, agent), client, agent


def mention(text="<@UBOT> Which tasks are overdue?", ts="100.1", **extra):
    return {"type": "app_mention", "user": "U1", "channel": "C1", "text": text, "ts": ts, **extra}


def dm(text="Which tasks are overdue?", ts="200.1", **extra):
    return {"type": "message", "channel_type": "im", "user": "U1", "channel": "D1", "text": text, "ts": ts, **extra}


# ---------- mentions, DMs, threads ----------
def test_mention_starts_a_thread_and_replaces_working_on_it():
    b, client, agent = make()
    b.handle(mention(), "mention")
    assert client.posts[0]["text"] == slackbot.WORKING and client.posts[0]["thread_ts"] == "100.1"       # thread = the message
    assert len(client.updates) == 1 and client.updates[0]["ts"] == client.posts[0]["ts"]                  # same message replaced
    assert "Working on it" not in client.updates[0]["text"] and "*world*" in client.updates[0]["text"]    # mrkdwn bold
    assert agent.calls[0]["question"] == "Which tasks are overdue?" and agent.calls[0]["history"] == []   # mention removed
    assert len(client.posts) == 1                                                                         # no extra message


def test_direct_message_is_answered_in_a_thread():
    b, client, agent = make()
    b.handle(dm(), "message")
    assert client.posts[0]["thread_ts"] == "200.1" and client.posts[0]["channel"] == "D1" and len(client.updates) == 1


def test_reply_inside_a_thread_stays_in_that_thread():
    b, client, _ = make(thread=[])
    b.handle(mention(ts="100.5", thread_ts="100.1"), "mention")
    assert client.posts[0]["thread_ts"] == "100.1"


@pytest.mark.parametrize("event,kind", [
    (dict(mention(), bot_id="B9"), "mention"),                               # another bot
    (dict(mention(), user=BOT), "mention"),                                  # the bot's own message
    (dict(dm(), subtype="message_changed"), "message"),                      # an edit
    (dict(dm(), channel_type="channel"), "message"),                         # a plain channel message (no mention)
    ({"type": "message", "channel": "C1", "text": "hi", "ts": "1.1"}, "message"),   # no user
])
def test_events_the_bot_must_ignore(event, kind):
    b, client, agent = make()
    b.handle(event, kind)
    assert client.posts == [] and agent.calls == []


def test_the_same_event_twice_is_answered_once():
    b, client, agent = make()
    b.handle(mention(), "mention")
    b.handle(mention(), "mention")
    assert len(agent.calls) == 1 and len(client.posts) == 1


def test_empty_question_gets_a_hint_and_no_agent_call():
    b, client, agent = make()
    b.handle(mention(text="<@UBOT>  "), "mention")
    assert agent.calls == [] and client.posts[0]["text"] == slackbot.EMPTY


# ---------- thread history ----------
def test_follow_up_uses_earlier_thread_messages_as_history():
    thread = [
        {"ts": "100.1", "user": "U1", "text": "<@UBOT> Which tasks are overdue?"},
        {"ts": "100.2", "user": BOT, "text": slackbot.WORKING},
        {"ts": "100.3", "user": BOT, "text": "*FACTS*\n• 5 tasks are overdue.\n\n_Tools: list_tasks · est. cost $0.03_"},
        {"ts": "100.4", "user": "U1", "text": "<@UBOT> And which are due today?"},
    ]
    b, client, agent = make(thread=thread)
    b.handle(mention(text="<@UBOT> And which are due today?", ts="100.4", thread_ts="100.1"), "mention")
    assert agent.calls[0]["question"] == "And which are due today?"
    assert agent.calls[0]["history"] == [{"role": "user", "content": "Which tasks are overdue?"},
                                        {"role": "assistant", "content": "*FACTS*\n• 5 tasks are overdue."}]   # no footer, no mention


def test_history_skips_warnings_working_and_unanswered_questions_and_is_capped():
    thread = [{"ts": "1.0", "user": "U1", "text": "lost question"},
              {"ts": "1.1", "user": BOT, "text": slackbot.WARN + "I couldn't get an answer"}]
    for i in range(10):
        thread += [{"ts": f"2.{i}0", "user": "U1", "text": f"q{i}"}, {"ts": f"2.{i}1", "user": BOT, "text": f"a{i}"}]
    thread.append({"ts": "3.0", "user": "U1", "text": "now"})
    hist = slackbot.thread_history(FakeSlack(thread=thread), "C1", "1.0", "3.0", BOT)
    assert len(hist) == 2 * config.UI_MAX_HISTORY_TURNS
    assert hist[-1] == {"role": "assistant", "content": "a9"} and hist[0] == {"role": "user", "content": "q4"}
    assert all("lost question" not in m["content"] and "couldn't" not in m["content"] for m in hist)


def test_a_thread_that_cannot_be_read_still_gets_an_answer():
    class Broken(FakeSlack):
        def conversations_replies(self, channel, ts, limit):
            raise SlackApiError("no", {"ok": False, "error": "missing_scope"})
    client = Broken()
    b = slackbot.Bot(client, BOT, None, FakeAgent())
    b.handle(mention(ts="100.5", thread_ts="100.1"), "mention")
    assert len(client.updates) == 1


# ---------- footer ----------
def test_footer_has_unique_tools_and_estimated_cost():
    b, client, _ = make()
    b.handle(mention(), "mention")
    last_line = client.updates[0]["text"].strip().split("\n")[-1]
    assert last_line == "_Tools: get_funnel, list_jobs · est. cost $0.03_"
    b2, c2, _ = make(FakeAgent(cost=0.001, tools=()))
    b2.handle(mention(), "mention")
    assert c2.updates[0]["text"].strip().endswith("_Tools: none · est. cost under $0.01_")


# ---------- allowlist ----------
def test_allowlist_blocks_other_users_without_calling_the_agent():
    b, client, agent = make(allowed={"U9"})
    b.handle(mention(), "mention")                                           # U1 is not on the list
    assert agent.calls == [] and client.posts[0]["text"] == slackbot.NOT_ALLOWED and client.updates == []


def test_allowlist_lets_listed_users_in_and_empty_list_allows_everyone():
    b, client, agent = make(allowed={"U1"})
    b.handle(mention(), "mention")
    assert len(agent.calls) == 1
    b2, _, agent2 = make(allowed=set())
    b2.handle(mention(), "mention")
    assert len(agent2.calls) == 1


def test_parse_allowlist():
    assert slackbot.parse_allowlist(" U1, U2 ,,U3") == {"U1", "U2", "U3"}
    assert slackbot.parse_allowlist("") == set() and slackbot.parse_allowlist(None) == set()


# ---------- errors: friendly, no traceback, no key ----------
@pytest.mark.parametrize("status,needle", [
    ("api_error", "couldn't get an answer"), ("config_error", "API key is missing"), ("refusal", "declined"),
    ("max_tool_rounds", "more steps than allowed"), ("max_tokens", "cut off"), ("unexpected_stop", "incomplete")])
def test_every_failed_status_gets_a_friendly_warning(status, needle):
    agent = FakeAgent(answer=f"raw error text with {SENTINEL}", status=status)
    b, client, _ = make(agent)
    b.handle(mention(), "mention")
    text = client.updates[0]["text"]
    assert text.startswith(slackbot.WARN) and needle in text and SENTINEL not in text and "Traceback" not in text


def test_a_crashing_agent_gives_a_friendly_message_and_no_details(caplog):
    b, client, _ = make(FakeAgent(raises=RuntimeError(f"boom {SENTINEL} /Users/x/secret.py")))
    with caplog.at_level(logging.INFO):
        b.handle(mention(), "mention")
    text = client.updates[0]["text"]
    assert "Something went wrong" in text and "boom" not in text and SENTINEL not in text and "/Users" not in text
    assert SENTINEL not in caplog.text and "boom" not in caplog.text


def test_the_key_is_scrubbed_from_an_ok_answer(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL)
    b, client, _ = make(FakeAgent(answer=f"The key is {SENTINEL}"))
    b.handle(mention(), "mention")
    assert SENTINEL not in client.updates[0]["text"] and "[redacted]" in client.updates[0]["text"]


def test_if_the_placeholder_cannot_be_edited_a_new_message_is_posted():
    b, client, _ = make(update_fails=True)
    b.handle(mention(), "mention")
    assert len(client.posts) == 2 and "world" in client.posts[1]["text"] and client.posts[1]["thread_ts"] == "100.1"


def test_logs_hold_counts_only(caplog):
    b, client, _ = make(FakeAgent(answer="Secret candidate Jonah Whitfield"))
    with caplog.at_level(logging.INFO):
        b.handle(mention(text="<@UBOT> Tell me about Jonah Whitfield"), "mention")
    assert "status=ok" in caplog.text and "Jonah" not in caplog.text and "Whitfield" not in caplog.text


# ---------- long answers ----------
def test_a_long_answer_is_split_and_the_footer_is_on_the_last_part_only():
    long_answer = "\n".join(f"- line {i} " + "x" * 80 for i in range(120))
    b, client, _ = make(FakeAgent(answer=long_answer))
    b.handle(mention(), "mention")
    messages = [client.updates[0]["text"]] + [p["text"] for p in client.posts[1:]]
    assert len(messages) >= 2 and all(len(m) < 4000 for m in messages)
    assert "est. cost" in messages[-1] and all("est. cost" not in m for m in messages[:-1])


# ---------- markdown -> mrkdwn ----------
def test_bold_headings_bullets_links_and_escaping():
    out = to_mrkdwn("# Title\n**bold** and *italic* and ~~gone~~\n- item\n  - sub\n[site](https://example.com) a < b & c")
    assert out.split("\n")[0] == "*Title*"
    assert "*bold* and _italic_ and ~gone~" in out
    assert "• item" in out and "  ◦ sub" in out
    assert "<https://example.com|site>" in out and "a &lt; b &amp; c" in out


def test_answer_labels_become_bold_and_code_is_untouched():
    out = to_mrkdwn("FACTS\nAI ASSESSMENT (my judgement)\n**CAVEATS**\nuse `a_b **x**` here\n```\n**raw** <tag>\n```")
    lines = out.split("\n")
    assert lines[0] == "*FACTS*" and lines[1] == "*AI ASSESSMENT (my judgement)*" and lines[2] == "*CAVEATS*"
    assert "`a_b **x**`" in out and "**raw** &lt;tag&gt;" in out


def test_funnel_answer_table_becomes_a_code_block():
    md = ("FACTS\n- Funnel by stage:\n\n| Stage | Entered | Moved on |\n|---|---|---|\n| Application Review | 20 | 16 |\n"
          "| Take-Home | 11 | 4 |\n\n- **Take-Home** is the biggest loss.\n")
    out = to_mrkdwn(md)
    block = out.split("```")[1]
    assert block.strip().split("\n")[0] == "| Stage | Entered | Moved on |" and "| Take-Home | 11 | 4 |" in block
    assert out.count("```") == 2 and "• *Take-Home* is the biggest loss." in out and "**" not in out


def test_the_real_funnel_answer_from_the_eval_run_converts_cleanly():
    reports = [r for r in sorted((ROOT / "notes" / "demo").glob("evals_*.md")) if "## q02_funnel_backend" in r.read_text(encoding="utf-8")]
    if not reports:
        pytest.skip("no saved eval report with the funnel answer on this machine (notes/ is git-ignored)")
    text = reports[-1].read_text(encoding="utf-8")
    answer = text.split("## q02_funnel_backend")[1].split("**Answer:**")[1].split("\n## ")[0].strip()
    out = to_mrkdwn(answer)
    assert "**" not in out and out.count("```") == 2 and "| Take-Home | 11 | 4 | 1 | 4 |" in out
    assert not any(line.lstrip().startswith("#") for line in out.split("\n"))


def test_split_message_keeps_code_blocks_closed():
    text = "```\n" + "\n".join(f"| row {i} | " + "y" * 60 + " |" for i in range(100)) + "\n```"
    parts = split_message(text, limit=1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts) and all(p.count("```") % 2 == 0 for p in parts)


# ---------- the file itself ----------
def test_bot_imports_no_database_or_service_code():
    tree = ast.parse((ROOT / "slack" / "bot.py").read_text(encoding="utf-8"))
    mods = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [None])}
    assert not any(m and (m.startswith("backend.services") or m.startswith("backend.ingest") or "sqlite" in m) for m in mods)
    assert "backend.agent" in mods and "slack.format" in mods


def test_missing_tokens_give_a_clear_message_without_starting(monkeypatch, capsys):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_APP_TOKEN", "")
    assert slackbot.main() == 2
    out = capsys.readouterr().out
    assert "SLACK_BOT_TOKEN" in out and "SLACK_APP_TOKEN" in out


def test_env_example_has_the_names_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USER_IDS"):
        assert f"\n{name}=\n" in text or text.endswith(f"{name}=")
    assert "xoxb" not in text and "xapp" not in text


def test_manifest_has_minimum_scopes_and_socket_mode():
    import yaml
    m = yaml.safe_load((ROOT / "slack" / "manifest.yaml").read_text(encoding="utf-8"))
    assert m["settings"]["socket_mode_enabled"] is True
    assert set(m["oauth_config"]["scopes"]["bot"]) == {"app_mentions:read", "chat:write", "im:history", "channels:history", "groups:history"}
    assert set(m["settings"]["event_subscriptions"]["bot_events"]) == {"app_mention", "message.im"}
    assert "request_url" not in m["settings"]["event_subscriptions"]
