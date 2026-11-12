"""PAID eval run: asks the REAL agent every question in evals/questions.yaml and checks the answers.
Do not run it until the author says "run evals". It needs --yes.

    .venv/bin/python -I evals/run_evals.py --list                 # free: the questions and their checks
    .venv/bin/python -I evals/run_evals.py --yes                  # all questions (PAID)
    .venv/bin/python -I evals/run_evals.py --yes --only q01_top3_backend,q09_a120_overdue

Expected facts come from evals/build_expected.py (raw files only). A failed check is a pointer, not a verdict:
read the saved answer. The report goes to notes/demo/ (git-ignored). The API key is never printed.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from backend import config  # noqa: E402
from evals import build_expected  # noqa: E402
from evals.checks import run_checks, verdict  # noqa: E402

QUESTIONS_FILE = ROOT / "evals" / "questions.yaml"


def load_questions(only=None):
    qs = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    if only:
        unknown = set(only) - {q["id"] for q in qs}
        if unknown:
            raise SystemExit(f"Unknown question id(s): {sorted(unknown)}")
        qs = [q for q in qs if q["id"] in only]
    return qs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="confirm that real, paid API calls are OK")
    ap.add_argument("--list", action="store_true", help="free: print the questions and their checks, then stop")
    ap.add_argument("--only", help="comma-separated question ids")
    args = ap.parse_args()
    questions = load_questions(args.only.split(",") if args.only else None)

    if args.list:
        for q in questions:
            print(f"{q['id']}  [{q['verified_by']}]\n  {q['question']}")
            for c in q["checks"]:
                print("   -", c.get("name") or c["check"], "[soft: WARN only]" if c.get("level") == "soft" else "")
        print(f"\n{len(questions)} questions. Nothing was run.")
        return 0
    if not args.yes:
        print(f"This makes REAL, PAID API calls ({len(questions)} questions, up to {config.AGENT_MAX_TOOL_ROUNDS} model calls each; "
              "earlier real runs cost about $0.03 to $0.10 per question). Re-run with --yes after the author says 'run evals'.")
        return 2

    from backend.agent.core import ask_sync
    expected = build_expected.build()
    out_dir = ROOT / "notes" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"evals_{datetime.now():%Y%m%d_%H%M%S}.md"
    lines = [f"# Eval run, model {config.ANTHROPIC_MODEL}, as of {config.REFERENCE_DATE}\n"]
    passed, warned, cost = 0, 0, 0.0
    for q in questions:
        r = ask_sync(q["question"])
        tools = [c["name"] for c in r.tool_calls]
        results = run_checks(q, r.status, r.answer, tools, expected)
        label, hard, warns = verdict(results)
        passed += label == "PASS"
        warned += bool(warns)
        cost += r.estimated_cost_usd
        shown = label + (f" (+{len(warns)} WARN)" if warns else "")
        print(f"[{shown}] {q['id']}  ({q['verified_by']})  tools={tools}  est. ${r.estimated_cost_usd}")
        for name, _, detail, _ in hard:
            print(f"      FAILED: {name} -> {detail}")
        for name, _, detail, _ in warns:
            print(f"      WARN (read by hand): {name} -> {detail}")
        lines += [f"## {q['id']}  {shown}  (expected facts: {q['verified_by']})\n",
                  f"**Question:** {q['question']}\n", f"**Status:** {r.status}, rounds {r.rounds}, est. ${r.estimated_cost_usd}\n",
                  "**Tool calls:** " + ", ".join(f"`{c['name']}({json.dumps(c['input'])})`" for c in r.tool_calls) + "\n",
                  "**Checks:**\n" + "\n".join(f"- {'PASS' if g else ('FAIL' if lv == 'hard' else 'WARN')} {n}: {d}"
                                              for n, g, d, lv in results) + "\n",
                  f"**Answer:**\n\n{r.answer}\n"]
    print(f"\n{passed}/{len(questions)} questions passed all hard checks; {warned} with WARNs to read by hand. "
          f"Total estimated cost ~ ${round(cost, 4)}")
    lines.append(f"## Total\n{passed}/{len(questions)} passed all hard checks, {warned} with WARNs, est. ${round(cost, 4)}\n")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved: {path.relative_to(ROOT)}")
    return 0 if passed == len(questions) else 1


if __name__ == "__main__":
    sys.exit(main())
