"""Deterministic checks for eval answers. No LLM judge, no network. Each check returns (ok, detail).

A question in questions.yaml lists checks like  {check: includes, any: ["a", "b"]}. Facts that depend on the data
(names, scores, numbers) are NOT written in the YAML: they come from evals/build_expected.py (raw files only).
The status 'ok' and the style checker (backend/agent/style.py) are always applied on top.
"""
import re

from backend.agent.style import style_problems

NEGATIONS = ("not ", "n't", "no ", "none", "never", "without", "neither", "nor ")


def _has(answer, text):
    return text.lower() in answer.lower()


def _sentences(answer):
    """Sentences and lines (a table row or bullet is one unit). Decimals like 78.4 do not split."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", answer) if s.strip()]


def _number_in(text, n):
    return re.search(rf"(?<![\d.]){re.escape(str(n))}(?![\d]|\.\d)", text) is not None


def _numbers(answer):
    return [float(x) for x in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", answer)]


# ---------- the checks ----------
def tool_called(spec, answer, tools, exp):
    wanted = spec.get("any") or [spec["tool"]]
    hit = [t for t in wanted if t in tools]
    return bool(hit), f"called {sorted(set(tools))}; wanted one of {wanted}"


def includes(spec, answer, tools, exp):
    if "all" in spec:
        missing = [t for t in spec["all"] if not _has(answer, t)]
        return not missing, f"missing: {missing}" if missing else "all present"
    hit = [t for t in spec["any"] if _has(answer, t)]
    return bool(hit), f"found {hit}" if hit else f"none of {spec['any']} found"


def excludes(spec, answer, tools, exp):
    found = [t for t in spec["any"] if _has(answer, t)]
    return not found, f"forbidden text found: {found}" if found else "none found"


def includes_regex(spec, answer, tools, exp):
    m = re.search(spec["pattern"], answer, re.I)
    return bool(m), f"matched '{m.group(0)}'" if m else f"pattern {spec['pattern']!r} not found"


def excludes_regex(spec, answer, tools, exp):
    m = re.search(spec["pattern"], answer, re.I)
    return not m, f"forbidden pattern matched '{m.group(0)}'" if m else "not found"


def top_names_in_order(spec, answer, tools, exp):
    names = [r["name"] for r in exp["ranking"][spec["job"]]["ranked"][: spec.get("n", 3)]]
    pos = [answer.find(n) for n in names]
    if -1 in pos:
        return False, f"missing names: {[n for n, p in zip(names, pos) if p == -1]}"
    return pos == sorted(pos), f"expected order {names}; first positions {pos}"


def top_scores_shown(spec, answer, tools, exp):
    nums = _numbers(answer)
    top = exp["ranking"][spec["job"]]["ranked"][: spec.get("n", 3)]
    missing = [f"{r['name']} {r['score']}" for r in top if not any(abs(x - r["score"]) <= spec.get("tolerance", 0.5) for x in nums)]
    return not missing, f"score not found for: {missing}" if missing else "all scores found"


def names_present(spec, answer, tools, exp):
    names = sorted({t["owner"] for t in exp["tasks"]}) if spec["group"] == "task_owners" else []
    missing = [n for n in names if n not in answer]
    return not missing, f"missing owners: {missing}" if missing else f"all {len(names)} owners named"


def funnel_numbers(spec, answer, tools, exp):
    """For every stage: some line that names the stage also has its 'entered' number."""
    alias = {"Recruiter Call": ["Phone Screen"]}
    lines = _sentences(answer)
    bad = []
    for stage, v in exp["funnel"][spec["job"]].items():
        names = [stage] + alias.get(stage, [])
        ok = any(any(_has(l, n) for n in names) and _number_in(l, v["entered"]) for l in lines)
        if not ok:
            bad.append(f"{stage} (entered {v['entered']})")
    return not bad, f"stage line without its entered number: {bad}" if bad else "all stage rows match"


def line_has_numbers(spec, answer, tools, exp):
    lines = [l for l in _sentences(answer) if _has(l, spec["line_contains"])]
    ok = any(all(_number_in(l, n) for n in spec["numbers"]) for l in lines)
    return ok, f"a line with '{spec['line_contains']}' and numbers {spec['numbers']}" + ("" if ok else " not found")


def no_claim(spec, answer, tools, exp):
    """No sentence may put `word` next to a subject, unless that sentence is negated ('not overdue', 'no due date')."""
    subjects = spec.get("subjects") or []
    if spec.get("subjects_from") == "tasks_not_overdue":
        subjects += sorted({t["owner"] for t in exp["tasks"] if t["state"] != "overdue"})
    elif spec.get("subjects_from") == "tasks_not_due_today":
        subjects += sorted({t["owner"] for t in exp["tasks"] if t["due"] != exp["reference_date"]})
    bad = []
    for s in _sentences(answer):
        if _has(s, spec["word"]) and any(_has(s, x) for x in subjects) and not any(n in s.lower() for n in NEGATIONS):
            bad.append(s[:120])
    return not bad, f"claims '{spec['word']}' for: {bad}" if bad else "no wrong claim found"


def sentence_has(spec, answer, tools, exp):
    """One sentence (or line) must match EVERY pattern in `all` (so the words must be about the same thing)."""
    for sentence in _sentences(answer):
        if all(re.search(p, sentence, re.I) for p in spec["all"]):
            return True, f"matched in: {sentence[:140]}"
    return False, f"no single sentence matches all of {spec['all']}"


def no_candidate_names(spec, answer, tools, exp):
    found = [n for n in exp["candidate_names"] if n in answer]
    return not found, f"candidate names in the answer: {found}" if found else "no candidate name invented"


CHECKS = {f.__name__: f for f in (tool_called, includes, excludes, includes_regex, excludes_regex, top_names_in_order,
                                  top_scores_shown, names_present, funnel_numbers, line_has_numbers, no_claim, sentence_has,
                                  no_candidate_names)}


def run_checks(question, result_status, answer, tools, exp):
    """question = one entry of questions.yaml. Returns a list of (name, ok, detail, level), level = 'hard' or 'soft'.
    Always includes the status check and the style check (both hard)."""
    out = [("status is ok", result_status == "ok", f"status={result_status}", "hard")]
    for spec in question["checks"]:
        fn = CHECKS[spec["check"]]
        ok, detail = fn(spec, answer, tools, exp)
        out.append((spec.get("name") or spec["check"], bool(ok), detail, spec.get("level", "hard")))
    problems = style_problems(answer)
    out.append(("style (no internal ids, no closing offers, no 'I did not check')", not problems,
                "; ".join(problems) if problems else "clean", "hard"))
    return out


def verdict(results):
    """('PASS' | 'FAIL', hard failures, warnings). A question passes when every HARD check passes.
    A missed SOFT check (wording of an interpretation) is a WARN: read the answer by hand."""
    hard = [r for r in results if r[3] == "hard" and not r[1]]
    warns = [r for r in results if r[3] == "soft" and not r[1]]
    return ("FAIL" if hard else "PASS"), hard, warns
