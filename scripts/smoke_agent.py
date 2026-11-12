"""PAID smoke test: asks the agent the three assignment questions with the REAL Claude API.
Do not run it until the author says "run smoke". Needs --yes.

    .venv/bin/python -I scripts/smoke_agent.py --yes

It prints each answer, the tool calls, tokens and an estimated cost, and a few light checks (not a grade of correctness;
the eval set in Phase 6 does that). The transcript is saved in notes/demo/ (git-ignored). The API key is never printed.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import config  # noqa: E402
from backend.agent.examples import EXAMPLE_QUESTIONS  # noqa: E402
from backend.agent.style import style_problems  # noqa: E402

QUESTIONS = [
    ("Q1 top 3", EXAMPLE_QUESTIONS[0][1],
     lambda tools, a: [("called rank_candidates_for_job", "rank_candidates_for_job" in tools),
                       ("mentions the 70/30 weights", "70" in a and "30" in a),
                       ("says there are no role requirements", "requirement" in a.lower()),
                       ("names the overdue offer (a-105)", "a-105" in a or "offer" in a.lower())]),
    ("Q2 funnel", EXAMPLE_QUESTIONS[1][1],
     lambda tools, a: [("called get_funnel", "get_funnel" in tools),
                       ("called list_jobs", "list_jobs" in tools),
                       ("shows a table", "|" in a),
                       ("mentions a data conflict (a-114 or a-116)", "a-114" in a or "a-116" in a)]),
    ("Q3 tasks", EXAMPLE_QUESTIONS[2][1],
     lambda tools, a: [("called list_tasks", "list_tasks" in tools),
                       ("names s-131", "s-131" in a), ("names the offer a-105", "a-105" in a),
                       ("says some due dates are assumptions", "assum" in a.lower())]),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="confirm that real, paid API calls are OK")
    if not ap.parse_args().yes:
        print("This makes REAL, PAID API calls (3 questions, up to "
              f"{config.AGENT_MAX_TOOL_ROUNDS} model calls each). Re-run with --yes after the author says 'run smoke'.")
        return 2
    from backend.agent.core import ask_sync
    out_dir = config.ROOT / "notes" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"smoke_{datetime.now():%Y%m%d_%H%M%S}.md"
    total = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}
    cost, lines, failed = 0.0, [f"# Smoke run, model {config.ANTHROPIC_MODEL}, as of {config.REFERENCE_DATE}\n"], 0
    for label, question, checks in QUESTIONS:
        r = ask_sync(question)
        tools = [c["name"] for c in r.tool_calls]
        print(f"\n===== {label}: {question}\nstatus={r.status} rounds={r.rounds} tools={tools}\n{r.answer}\n")
        results = checks(tools, r.answer) if r.status == "ok" else []
        problems = style_problems(r.answer)
        results.append(("no internal ids and no closing offers" + (f" ({'; '.join(problems)})" if problems else ""), not problems))
        for name, ok in results:
            print(f"  [{'x' if ok else ' '}] {name}")
            failed += not ok
        failed += r.status != "ok"
        u = r.usage
        print(f"  tokens in={u['input_tokens']} out={u['output_tokens']} cache_read={u['cache_read_tokens']} "
              f"cache_write={u['cache_creation_tokens']} est. ${r.estimated_cost_usd}")
        for k in total:
            total[k] += u[k]
        cost += r.estimated_cost_usd
        lines += [f"## {label}\n**Question:** {question}\n\n**Status:** {r.status}, rounds {r.rounds}\n",
                  "**Tool calls:**\n" + "\n".join(f"- round {c['round']}: `{c['name']}({json.dumps(c['input'])})` -> "
                                                   f"{'ok' if c['ok'] else 'ERROR ' + str(c['error_code'])}, items {c['items']}" for c in r.tool_calls),
                  f"\n**Answer:**\n\n{r.answer}\n", f"**Tokens:** {u}  (est. ${r.estimated_cost_usd})\n",
                  "**Checks:** " + ", ".join(f"{'PASS' if ok else 'FAIL'} {n}" for n, ok in results) + "\n"]
    print(f"\nTOTAL tokens {total}  est. cost ~ ${round(cost, 4)}")
    lines.append(f"## Total\n{total}, est. ${round(cost, 4)}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Transcript saved: {path.relative_to(config.ROOT)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
