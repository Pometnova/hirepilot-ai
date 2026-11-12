"""FREE: re-score saved eval reports (notes/demo/evals_*.md) with the CURRENT questions.yaml. No API call.

    .venv/bin/python -I evals/rescore.py                 # all saved reports
    .venv/bin/python -I evals/rescore.py --detail        # also the text of every FAIL and WARN

It reads each saved answer, status and tool list, and runs the current checks on them. Use it after changing a check.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import build_expected, run_evals  # noqa: E402
from evals.checks import run_checks, verdict  # noqa: E402


def parse_report(text):
    """-> {question_id: {status, tools, answer}} from a saved report."""
    out = {}
    for sec in text.split("\n## ")[1:]:
        qid = sec.split()[0]
        if not re.match(r"q\d\d_", qid) or "**Answer:**" not in sec:
            continue
        status = re.search(r"\*\*Status:\*\* (\w+)", sec)
        tools = re.search(r"\*\*Tool calls:\*\* (.*)", sec)
        out[qid] = {"status": status.group(1) if status else "ok",
                    "tools": re.findall(r"`(\w+)\(", tools.group(1)) if tools else [],
                    "answer": sec.split("**Answer:**")[1].split("\n## ")[0].strip()}
    return out


def rescore(report_path, expected, questions):
    rows = []
    for qid, saved in parse_report(Path(report_path).read_text(encoding="utf-8")).items():
        q = questions.get(qid)
        if q:
            label, hard, warns = verdict(run_checks(q, saved["status"], saved["answer"], saved["tools"], expected))
            rows.append((qid, label, hard, warns))
    return rows


def main():
    detail = "--detail" in sys.argv
    expected = build_expected.build()
    questions = {q["id"]: q for q in run_evals.load_questions()}
    for path in sorted((ROOT / "notes" / "demo").glob("evals_*.md")):
        rows = rescore(path, expected, questions)
        print(f"\n== {path.name}: {len(rows)} questions")
        for qid, label, hard, warns in rows:
            mark = label + (f" (+{len(warns)} WARN)" if warns else "")
            print(f"  {mark:<16} {qid}")
            if detail:
                for n, _, d, _ in hard:
                    print(f"        FAIL: {n} -> {d[:150]}")
                for n, _, d, _ in warns:
                    print(f"        WARN: {n} -> {d[:150]}")
        passed = sum(r[1] == "PASS" for r in rows)
        print(f"  => {passed}/{len(rows)} pass all hard checks, {sum(bool(r[3]) for r in rows)} with WARNs")


if __name__ == "__main__":
    main()
