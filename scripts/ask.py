"""Ask the agent one question.   .venv/bin/python -I scripts/ask.py "Which tasks are overdue?"

  --dry-run       FREE. Starts the MCP server, prints the model, limits, system prompt and tools. No API call.
  --show-results  also print the raw tool results (can be long)
Without --dry-run this makes REAL, PAID API calls (up to the round limit).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # -I removes the project folder from sys.path

from backend import config                 # noqa: E402
from backend.agent.core import Agent       # noqa: E402


async def dry_run():
    async with Agent() as agent:
        print(f"model            : {agent.model}")
        print(f"effort           : {config.AGENT_EFFORT}")
        print(f"max tool rounds  : {agent.max_rounds}")
        print(f"max_tokens       : {config.AGENT_MAX_TOKENS}")
        print(f"request timeout  : {config.AGENT_REQUEST_TIMEOUT_S} s   tool timeout: {agent.tool_timeout} s")
        print(f"max tool result  : {agent.max_result_chars} chars")
        print(f"reference date   : {config.REFERENCE_DATE}")
        print(f"\n--- SYSTEM PROMPT ({len(agent.system_prompt)} chars) ---\n{agent.system_prompt}")
        print(f"--- TOOLS ({len(agent.tools)}), as passed to the Claude API ---")
        for t in agent.tools:
            props = ", ".join(f"{k}{'*' if k in t['input_schema'].get('required', []) else ''}" for k in t["input_schema"].get("properties", {}))
            print(f"* {t['name']}({props})\n    {t['description'][:150].replace(chr(10), ' ')}...")
        print("\n(* = required)  No API call was made.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show-results", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        asyncio.run(dry_run())
        return 0
    if not a.question:
        ap.error("give a question, or use --dry-run")
    from backend.agent.core import ask_sync
    r = ask_sync(a.question, keep_results=a.show_results)
    print(f"\n=== ANSWER (status: {r.status}) ===\n{r.answer}\n")
    print("=== TOOL CALLS ===")
    for c in r.tool_calls:
        state = "ok" if c["ok"] else f"ERROR {c['error_code']}"
        print(f"round {c['round']}: {c['name']}({json.dumps(c['input'])})  -> {state}, items={c['items']}, {c['ms']} ms")
        if a.show_results:
            print("   ", c.get("result", "")[:2000])
    u = r.usage
    print(f"\n=== USAGE === rounds={r.rounds} requests={u['requests']} input={u['input_tokens']} output={u['output_tokens']} "
          f"cache_read={u['cache_read_tokens']} cache_write={u['cache_creation_tokens']}  est. cost ~ ${r.estimated_cost_usd}")
    return 0 if r.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
