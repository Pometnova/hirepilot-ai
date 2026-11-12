"""Agent Core: MCP client + Claude API tool loop. The web app and the Slack bot will both call this.

    async with Agent() as agent:
        result = await agent.ask("Which tasks are overdue?")
    result = ask_sync("Which tasks are overdue?")           # one question, own event loop

Flow: start backend/mcp_server.py over stdio -> list_tools -> pass them to Claude as tools ->
loop { messages.create -> tool_use -> call_tool -> tool_result } until the model answers or the round limit.

Rules: the API key is read from the environment (.env) only, is never logged or returned, and is not passed to the
server subprocess. Logs go to stderr: tool names and counts only, no question text and no candidate records.
"""
import asyncio
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend import config
from backend.agent.prompt import SYSTEM_PROMPT
from backend.services.common import log

MAX_QUESTION_CHARS = 4000
_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}")


@dataclass
class AgentResult:
    question: str
    answer: str
    status: str            # ok | max_tool_rounds | max_tokens | refusal | api_error | config_error | invalid_input
    rounds: int = 0
    model: str = ""
    tool_calls: list = field(default_factory=list)   # {round, name, input, ok, error_code, items, ms[, result]}
    usage: dict = field(default_factory=lambda: {
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0, "requests": 0})
    estimated_cost_usd: float = 0.0
    error: str | None = None

    def to_dict(self):
        return asdict(self)


def estimate_cost(usage):
    """Rough USD cost from config.PRICE_PER_MTOK. An estimate, not a bill."""
    p = config.PRICE_PER_MTOK
    return round((usage["input_tokens"] * p["input"] + usage["output_tokens"] * p["output"]
                  + usage["cache_read_tokens"] * p["cache_read"] + usage["cache_creation_tokens"] * p["cache_write"]) / 1e6, 4)


def _secrets():
    return [v for v in (os.environ.get("ANTHROPIC_API_KEY"),) if v]


def scrub(text):
    """Remove the API key (exact value, or anything shaped like one) from a message."""
    text = str(text)
    for s in _secrets():
        text = text.replace(s, "[redacted]")
    return _KEY_PATTERN.sub("[redacted]", text)


def _text_of(blocks):
    return "\n".join(b.text for b in blocks if getattr(b, "type", None) == "text" and getattr(b, "text", None)).strip()


def _count_items(parsed):
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if isinstance(data, dict):
        return next((len(v) for v in data.values() if isinstance(v, list)), 0)
    return len(data) if isinstance(data, list) else 0


def _classify_api_error(e):
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "The API key was rejected. Check ANTHROPIC_API_KEY in .env."
    if isinstance(e, anthropic.RateLimitError):
        return "Rate limit reached. Try again in a moment."
    if isinstance(e, anthropic.APITimeoutError):
        return "The model request timed out."
    if isinstance(e, anthropic.APIConnectionError):
        return "Could not reach the API (connection problem)."
    if isinstance(e, anthropic.APIStatusError):
        return f"The API returned an error (HTTP {getattr(e, 'status_code', '?')})."
    return f"Unexpected error: {type(e).__name__}."


class Agent:
    def __init__(self, client=None, *, model=None, max_rounds=None, keep_results=False,
                 tool_timeout=None, max_result_chars=None, system_prompt=None, server_params=None):
        self._client = client
        self._owns_client = False            # True when WE created the HTTP client, so we must close it
        self.model = model or config.ANTHROPIC_MODEL
        self.max_rounds = max_rounds or config.AGENT_MAX_TOOL_ROUNDS
        self.keep_results = keep_results
        self.tool_timeout = tool_timeout or config.AGENT_TOOL_TIMEOUT_S
        self.max_result_chars = max_result_chars or config.AGENT_MAX_TOOL_RESULT_CHARS
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self._server = server_params or StdioServerParameters(
            command=sys.executable, args=["-I", str(config.ROOT / "backend" / "mcp_server.py")], cwd=str(config.ROOT))
        self._stack = None
        self._session = None
        self.tools = []                      # in Claude API format

    def __repr__(self):                      # never include the client or any secret
        return f"Agent(model={self.model!r}, tools={len(self.tools)}, max_rounds={self.max_rounds})"

    # ---- MCP lifecycle ----
    async def __aenter__(self):
        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(stdio_client(self._server))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
            listed = await self._session.list_tools()
        except BaseException:
            await self._stack.aclose()
            raise
        self.tools = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                      for t in listed.tools]
        log.info("agent: mcp server started, tools=%d", len(self.tools))
        return self

    async def __aexit__(self, *exc):
        try:
            await self._stack.aclose()
        finally:
            self._session = None
            if self._owns_client and self._client is not None:
                # Close the HTTP client while its event loop is still running. ask_sync uses a new loop per question; without
                # this, the open connections are closed later, after the loop is gone, and Python prints
                # "Task exception was never retrieved ... Event loop is closed".
                client, self._client, self._owns_client = self._client, None, False
                try:
                    await client.close()
                except Exception as e:
                    log.warning("agent: closing the HTTP client failed: %s", type(e).__name__)

    def _get_client(self):
        if self._client is None:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example).")
            self._client = AsyncAnthropic(api_key=key, timeout=config.AGENT_REQUEST_TIMEOUT_S,
                                          max_retries=config.API_MAX_RETRIES)
            self._owns_client = True
        return self._client

    # ---- one tool call ----
    async def _run_tool(self, rnd, block):
        name, args = block.name, dict(block.input or {})
        call = {"round": rnd, "name": name, "input": args, "ok": False, "error_code": None, "items": 0, "ms": 0}
        t0 = asyncio.get_running_loop().time()
        text, is_error = "", True
        try:
            if name not in {t["name"] for t in self.tools}:
                call["error_code"] = "unknown_tool"
                text = json.dumps({"ok": False, "error": {"code": "unknown_tool", "message": f"No tool named '{name}'.",
                                                         "valid_values": [t["name"] for t in self.tools]}})
            else:
                res = await asyncio.wait_for(self._session.call_tool(name, args), timeout=self.tool_timeout)
                text = "\n".join(c.text for c in res.content if getattr(c, "type", None) == "text")
                try:
                    parsed = json.loads(text)
                except ValueError:
                    parsed = None
                ok = isinstance(parsed, dict) and parsed.get("ok") is True and not res.is_error
                is_error = not ok
                call["ok"] = ok
                call["items"] = _count_items(parsed)
                if not ok:
                    err = parsed.get("error") if isinstance(parsed, dict) else None
                    call["error_code"] = (err or {}).get("code") or ("tool_error" if res.is_error else "bad_result")
        except asyncio.TimeoutError:
            call["error_code"] = "tool_timeout"
            text = json.dumps({"ok": False, "error": {"code": "tool_timeout", "message": f"Tool '{name}' took more than {self.tool_timeout} s."}})
        except Exception as e:                # the model gets an error result; the loop goes on
            call["error_code"] = "tool_failed"
            text = json.dumps({"ok": False, "error": {"code": "tool_failed", "message": scrub(f"Tool '{name}' failed: {type(e).__name__}.")}})
        if len(text) > self.max_result_chars:
            text = (text[: self.max_result_chars] + f"\n[TRUNCATED: the result had {len(text)} characters; only the first "
                    f"{self.max_result_chars} are shown. Ask for something narrower.]")
        call["ms"] = round((asyncio.get_running_loop().time() - t0) * 1000)
        if self.keep_results:
            call["result"] = text
        log.info("agent: round=%d tool=%s ok=%s items=%d", rnd, name, call["ok"], call["items"])
        block_out = {"type": "tool_result", "tool_use_id": block.id, "content": text}
        if is_error:
            block_out["is_error"] = True
        return call, block_out

    # ---- one question ----
    async def ask(self, question, history=None):
        res = AgentResult(question=question if isinstance(question, str) else "", answer="", status="ok", model=self.model)
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION_CHARS:
            res.status, res.error = "invalid_input", f"The question must be 1 to {MAX_QUESTION_CHARS} characters."
            res.answer = res.error
            return res
        try:
            client = self._get_client()
        except RuntimeError as e:
            res.status, res.error, res.answer = "config_error", str(e), str(e)
            return res
        messages = [{"role": m["role"], "content": m["content"]} for m in (history or [])
                    if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        messages.append({"role": "user", "content": question.strip()})
        log.info("agent: question chars=%d history=%d", len(question), len(messages) - 1)

        for rnd in range(1, self.max_rounds + 1):
            try:
                resp = await client.messages.create(
                    model=self.model, max_tokens=config.AGENT_MAX_TOKENS, system=self.system_prompt,
                    tools=self.tools, messages=messages, output_config={"effort": config.AGENT_EFFORT},
                    cache_control={"type": "ephemeral"})
            except Exception as e:
                res.status, res.rounds = "api_error", rnd
                res.error = scrub(_classify_api_error(e))
                res.answer = res.error
                log.error("agent: api error %s", type(e).__name__)
                break
            res.rounds = rnd
            u = resp.usage
            res.usage["requests"] += 1
            res.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            res.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
            res.usage["cache_read_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
            res.usage["cache_creation_tokens"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            # echo the whole assistant turn back unchanged (thinking blocks must stay)
            messages.append({"role": "assistant", "content": resp.content})
            text = _text_of(resp.content)
            stop = resp.stop_reason

            if stop == "tool_use":
                if rnd == self.max_rounds:
                    res.status = "max_tool_rounds"
                    res.answer = (f"I could not finish within {self.max_rounds} model rounds, so this question is not fully "
                                  f"answered." + (f"\n\nPartial text:\n{text}" if text else ""))
                    break
                results = []
                for block in (b for b in resp.content if getattr(b, "type", None) == "tool_use"):
                    call, out = await self._run_tool(rnd, block)
                    res.tool_calls.append(call)
                    results.append(out)
                messages.append({"role": "user", "content": results})      # all results in ONE message
                continue
            res.answer = text
            if stop == "max_tokens":
                res.status = "max_tokens"
                res.answer = text + "\n\n[The answer was cut off at the token limit.]"
            elif stop == "refusal":
                res.status = "refusal"
                res.answer = text or "The model declined to answer this request."
            elif stop not in ("end_turn", "stop_sequence", None):
                res.status = "unexpected_stop"
            break

        res.estimated_cost_usd = estimate_cost(res.usage)
        log.info("agent: done status=%s rounds=%d tools=%d tokens in=%d out=%d cache_read=%d", res.status, res.rounds,
                 len(res.tool_calls), res.usage["input_tokens"], res.usage["output_tokens"], res.usage["cache_read_tokens"])
        return res


def ask_sync(question, history=None, **agent_kwargs):
    """One question with its own event loop and MCP server. For Streamlit and Slack handlers."""
    async def one():
        async with Agent(**agent_kwargs) as agent:
            return await agent.ask(question, history)
    return asyncio.run(one())


def check_mcp():
    """Free status check for the UI: start the MCP server, list its tools, stop it. No model call, no API key.
    Returns (connected, number_of_tools). Never raises."""
    async def one():
        async with Agent() as agent:
            return len(agent.tools)
    try:
        n = asyncio.run(one())
    except BaseException as e:                       # the server could not start or answer
        log.warning("agent: mcp status check failed: %s", type(e).__name__)
        return False, 0
    return n > 0, n
