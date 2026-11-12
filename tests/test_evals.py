"""Tests for the eval tooling. FREE: no API call, no key. The paid runner is only checked for refusing to run."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from backend import config
from backend.services import funnel, jobs, ranking, tasks
from evals import build_expected, checks, rescore, run_evals

ROOT = Path(__file__).resolve().parents[1]
EXP = build_expected.build()
QUESTIONS = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))
BY_ID = {q["id"]: q for q in QUESTIONS}


# ---------- the question file ----------
def test_question_file_is_valid():
    assert len(QUESTIONS) == 14
    assert len({q["id"] for q in QUESTIONS}) == 14
    for q in QUESTIONS:
        assert q["question"].strip() and q["checks"], q["id"]
        assert q["verified_by"] in ("hand", "independent script")
        for c in q["checks"]:
            assert c["check"] in checks.CHECKS, (q["id"], c)
    # the author hand-checks exactly these five; everything else is "independent script"
    assert {q["id"][:3] for q in QUESTIONS if q["verified_by"] == "hand"} == {"q01", "q02", "q03", "q08", "q09"}


def test_every_question_covers_the_planned_topics():
    ids = " ".join(BY_ID)
    for topic in ("top3_backend", "funnel_backend", "tasks_pending_overdue", "top3_csm", "top3_designer", "funnel_csm",
                  "funnel_designer", "due_today", "a120", "profile", "no_feedback", "unknown_role", "maya", "offer_deadline"):
        assert topic in ids, topic


def test_check_arguments_exist_in_the_expected_facts():
    for q in QUESTIONS:
        for c in q["checks"]:
            if "job" in c:
                assert c["job"] in EXP["jobs"], (q["id"], c)


# ---------- independent expected facts vs the services (the cross-check) ----------
def test_expected_funnel_matches_services():
    for job_id in EXP["jobs"]:
        got = {s["stage"]: s for s in funnel.get_funnel(job_id)["data"]["stages"]}
        for stage, v in EXP["funnel"][job_id].items():
            for mine, theirs in (("entered", "entered"), ("moved_on", "moved_on"), ("rejected", "rejected"),
                                 ("withdrew", "withdrew"), ("hired", "hired"), ("still_there", "still_in_stage")):
                assert v[mine] == got[stage][theirs], (job_id, stage, mine)


def test_expected_ranking_matches_services():
    for job_id in EXP["jobs"]:
        svc = ranking.rank_candidates_for_job(job_id, top_n=50)["data"]
        mine = EXP["ranking"][job_id]
        assert [(r["application"], r["score"]) for r in mine["ranked"]] == [(r["application_id"], r["score"]) for r in svc["ranked"]]
        assert {r["application"] for r in mine["not_scored"]} == {r["application_id"] for r in svc["not_scored"]}


def test_expected_tasks_match_services():
    svc = {t["task_id"]: t for t in tasks.list_tasks("all")["data"]["tasks"]}
    mine = {t["task_id"]: t for t in EXP["tasks"]}
    assert set(mine) == set(svc)
    for task_id, t in mine.items():
        assert t["due"] == svc[task_id]["due_date"], task_id
        assert t["owner"] == svc[task_id]["candidate_name"], task_id
        same_state = {"pending (no due date in the data)": "pending_no_due_date"}.get(t["state"], t["state"])
        assert same_state == svc[task_id]["state"], task_id


def test_expected_facts_never_touch_the_database_or_services():
    tree = ast.parse((ROOT / "evals" / "build_expected.py").read_text(encoding="utf-8"))
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [None])}
    assert imported <= {"csv", "email", "email.policy", "json", "re", "sys", "datetime", "email.utils", "pathlib", "backend"}, imported
    code_strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any("hirepilot.db" in v or ".db" == v[-3:] for v in code_strings[1:])   # [0] is the docstring
    assert not any(isinstance(n, ast.Attribute) and n.attr in ("DB_PATH", "connect") for n in ast.walk(tree))


def test_known_expected_numbers():
    assert EXP["reference_date"] == "2026-10-15"
    take_home = EXP["funnel"]["j-backend"]["Take-Home"]
    assert (take_home["entered"], take_home["rejected"]) == (11, 1)
    assert [r["name"] for r in EXP["ranking"]["j-backend"]["ranked"][:3]] == ["Jonah Whitfield", "Maya Chen", "Rosa Delgado"]
    assert {t["task_id"] for t in EXP["tasks"] if t["due"] == "2026-10-15"} == {"scorecard_pending:s-315"}
    assert len(EXP["tasks"]) == 11
    assert len(EXP["people"]["Maya Chen"]) == 2 and len(EXP["people"]["Jonah Whitfield"]) == 2


# ---------- the checks: a good answer passes, each kind of wrong answer fails ----------
def failed(qid, answer, tools, status="ok"):
    return [n for n, ok, _, _ in checks.run_checks(BY_ID[qid], status, answer, tools, EXP) if not ok]


GOOD_Q1 = ("Top 3: 1. Jonah Whitfield (score 100.0). 2. Maya Chen (score 92.25). 3. Rosa Delgado (score 87.0). "
           "The data has no role requirements, so fit to the role is not measured.")


def test_good_answer_passes_and_wrong_ones_fail():
    assert failed("q01_top3_backend", GOOD_Q1, ["rank_candidates_for_job"]) == []
    assert failed("q01_top3_backend", GOOD_Q1.replace("Maya Chen (score 92.25). 3. Rosa Delgado (score 87.0)",
                                                      "Rosa Delgado (score 87.0). 3. Maya Chen (score 92.25)"),
                  ["rank_candidates_for_job"]) == ["top_names_in_order"]
    assert failed("q01_top3_backend", GOOD_Q1.replace("92.25", "55.1"), ["rank_candidates_for_job"]) == ["top_scores_shown"]
    assert "tool_called" in failed("q01_top3_backend", GOOD_Q1, [])
    assert "status is ok" in failed("q01_top3_backend", GOOD_Q1, ["rank_candidates_for_job"], status="max_tokens")


def test_style_checker_is_part_of_every_question():
    bad = GOOD_Q1 + " The task is under application a-105 but candidate record c-121. I did not check whether these are the same person."
    assert any(n.startswith("style") for n in failed("q01_top3_backend", bad, ["rank_candidates_for_job"]))


FUNNEL_TABLE = "\n".join(f"| {s} | {v['entered']} | {v['moved_on']} | {v['rejected']} |" for s, v in EXP["funnel"]["j-backend"].items())


def test_funnel_checks():
    assert failed("q02_funnel_backend", FUNNEL_TABLE, ["get_funnel"]) == []
    # the old double count: Take-Home 12 entered instead of 11
    assert failed("q02_funnel_backend", FUNNEL_TABLE.replace("| Take-Home | 11 |", "| Take-Home | 12 |"), ["get_funnel"])
    # right number, but rejected 0 instead of 1
    assert failed("q02_funnel_backend", FUNNEL_TABLE.replace("| Take-Home | 11 | 4 | 1 |", "| Take-Home | 11 | 4 | 0 |"), ["get_funnel"]) \
        == ["Take-Home: 11 entered, 1 rejected (a-116 chain rule)"]


def task_lines(overrides=None):
    rows = []
    for t in EXP["tasks"]:
        state = (overrides or {}).get(t["owner"], t["state"].split(" ")[0])
        rows.append(f"- {t['owner']}: {state}")
    return "\n".join(rows) + "\nSome due dates are assumptions."


def test_task_checks():
    assert failed("q03_tasks_pending_overdue", task_lines(), ["list_tasks"]) == []
    assert "names_present" in failed("q03_tasks_pending_overdue", task_lines().replace("Sana Qureshi", "someone"), ["list_tasks"])
    # a pending / no-due-date person called overdue
    assert failed("q03_tasks_pending_overdue", task_lines({"Lucy Fairbanks": "overdue"}), ["list_tasks"]) \
        == ["no wrong 'overdue' (due today, pending, no due date)"]
    # a negated sentence is fine
    ok = task_lines().replace("Lucy Fairbanks: pending", "Lucy Fairbanks: pending, not overdue (no due date)")
    assert failed("q03_tasks_pending_overdue", ok, ["list_tasks"]) == []


def test_due_today_checks():
    assert failed("q08_tasks_due_today", "Julian Ferreira has a scorecard due today (2026-10-15).", ["list_tasks"]) == []
    assert failed("q08_tasks_due_today", "Julian Ferreira has a scorecard due today. Irene Kowalczyk is also due today.", ["list_tasks"]) \
        == ["only one task is due today"]
    assert failed("q08_tasks_due_today", "Nothing is due today.", ["list_tasks"])


def test_a120_checks():
    good = "Application a-120 (Lucy Fairbanks) is not overdue. It has no due date in the data, so it is pending."
    assert failed("q09_a120_overdue", good, ["list_tasks"]) == []
    assert failed("q09_a120_overdue", "Yes, a-120 is overdue by 3 days. It has no due date.", ["list_tasks"]) \
        == ["does not call a-120 overdue"]
    assert failed("q09_a120_overdue", "It is pending.", ["list_tasks"]) == ["says it has no due date"]


def test_profile_feedback_role_and_name_checks():
    jonah = ("Jonah Whitfield is stored as two records but is the same person. He applied for Customer Success Manager "
             "(rejected) and Senior Backend Engineer (active, at Offer).")
    assert failed("q10_profile_jonah", jonah, ["get_candidate_profile"]) == []
    assert "does not call them two people" in failed("q10_profile_jonah", jonah + " These are two different people.", ["get_candidate_profile"])

    ravi = "Ravi Subramanian is at Recruiter Call for Senior Backend Engineer. There is no feedback yet; that is not negative."
    assert failed("q11_no_feedback_ravi", ravi, ["get_candidate_profile"]) == []
    assert "no feedback is not called negative" in failed("q11_no_feedback_ravi", ravi + " His feedback is weak.", ["get_candidate_profile"])

    assert failed("q12_unknown_role", "There is no role called Head of Quantum Marketing. Open roles: Senior Backend Engineer.", ["list_jobs"]) == []
    assert "names no candidate (no guessing)" in failed(
        "q12_unknown_role", "That role does not exist, but Jonah Whitfield might fit.", ["list_jobs"])

    both = "Two people: Maya Chen (Senior Backend Engineer, Pittsburgh) and Maya Chen (Product Designer, Providence). They are not the same person."
    assert failed("q13_two_maya_chens", both, ["get_candidate_profile"]) == []
    assert failed("q13_two_maya_chens", "Which Maya Chen do you mean? There are two.", ["get_candidate_profile"]) == []
    assert failed("q13_two_maya_chens", "Maya Chen applied to Senior Backend Engineer and Product Designer. She is the same person.",
                  ["get_candidate_profile"]) == ["never merges them"]

    rafael = ("Rafael Mendoza's application is marked rejected (2026-10-09) at Offer, but it has an offer deadline of 2026-10-20. "
              "The data conflicts and does not say whether he declined. His last email says this is wonderful news and does not decline. "
              "The rejected status is likely a data error, so contact Rafael before October 20.")
    assert failed("q14_rejected_with_offer_deadline", rafael, ["get_data_issues"]) == []
    assert "flags the conflict" in failed("q14_rejected_with_offer_deadline",
                                          "The offer is rejected, deadline 2026-10-20.", ["get_data_issues"])
    missing = failed("q14_rejected_with_offer_deadline", "Marked rejected, deadline 2026-10-20, the data conflicts.", ["get_data_issues"])
    assert {"one sentence says Rafael's own email (m-2008) does not decline the offer", "says the rejected status is likely a data error",
            "one sentence tells someone to contact or confirm with Rafael"} <= set(missing)

    # the two accidental matches from the real q14 run must NOT pass any more
    accident = ("The data has no email or note after 2026-10-07. Nothing shows him declining or accepting. The last note, from "
                "2026-10-02, says references were positive. The status is likely wrong. It is marked rejected (2026-10-20 deadline); "
                "the data conflicts.")
    names = {"one sentence says Rafael's own email (m-2008) does not decline the offer",
             "one sentence tells someone to contact or confirm with Rafael"}
    assert names <= set(failed("q14_rejected_with_offer_deadline", accident, ["get_data_issues"]))
    good = ("Rafael sounded positive in his last message (m-2008). The status is likely wrong, marked rejected, data conflicts, "
            "deadline 2026-10-20. Priya Raman should confirm the status with Rafael before then.")
    assert failed("q14_rejected_with_offer_deadline", good, ["get_data_issues"]) == []
    # a recommendation that is not about Rafael, and a statement that is not about his email
    assert "one sentence tells someone to contact or confirm with Rafael" in failed(
        "q14_rejected_with_offer_deadline", good.replace("Priya Raman should confirm the status with Rafael", "Priya Raman should check the ATS"),
        ["get_data_issues"])

    # q12: the wording the real model used on the first run is accepted now
    real_q12 = ('The data has no "Head of Quantum Marketing" job. The only jobs are Senior Backend Engineer. '
                "I can't rank candidates for a role that isn't in the data.")
    assert failed("q12_unknown_role", real_q12, ["list_jobs"]) == []


# ---------- the runner never calls the API by accident ----------
def run_script(*args):
    return subprocess.run([sys.executable, "-I", str(ROOT / "evals" / "run_evals.py"), *args], capture_output=True, text=True, cwd=ROOT)


def test_runner_refuses_without_yes():
    r = run_script()
    assert r.returncode == 2 and "PAID" in r.stdout and "--yes" in r.stdout


def test_runner_list_is_free_and_prints_every_question():
    r = run_script("--list")
    assert r.returncode == 0 and "Nothing was run" in r.stdout
    assert all(q["id"] in r.stdout for q in QUESTIONS)


def test_runner_rejects_unknown_question_id():
    assert run_script("--yes", "--only", "q99_nope").returncode != 0


def test_runner_only_calls_the_agent_after_yes(monkeypatch):
    src = (ROOT / "evals" / "run_evals.py").read_text(encoding="utf-8")
    assert src.index("if not args.yes") < src.index("from backend.agent.core import ask_sync")
    assert config.ANTHROPIC_MODEL and run_evals.load_questions(["q01_top3_backend"])[0]["id"] == "q01_top3_backend"


# ---------- hard and soft checks ----------
SOFT = {
    "q01_top3_backend": {"says fit to the role is not measured"}, "q04_top3_csm": {"says fit to the role is not measured"},
    "q05_top3_designer": {"says fit to the role is not measured"}, "q03_tasks_pending_overdue": {"says some due dates are assumptions"},
    "q10_profile_jonah": {"says it is one person with two records"}, "q12_unknown_role": {"says the role does not exist"},
    "q14_rejected_with_offer_deadline": {"flags the conflict", "says the rejected status is likely a data error",
                                         "one sentence says Rafael's own email (m-2008) does not decline the offer",
                                         "one sentence tells someone to contact or confirm with Rafael"}}


def test_exactly_the_wording_checks_are_soft():
    got = {q["id"]: {c["name"] for c in q["checks"] if c.get("level") == "soft"} for q in QUESTIONS}
    assert {k: v for k, v in got.items() if v} == SOFT
    for q in QUESTIONS:                                           # nothing but 'soft' is ever written as a level
        assert {c.get("level", "hard") for c in q["checks"]} <= {"hard", "soft"}


def test_the_hard_checks_are_the_facts_and_forbidden_claims():
    for q in QUESTIONS:
        hard = {c["check"] for c in q["checks"] if c.get("level", "hard") == "hard"}
        assert "tool_called" in hard, q["id"]                   # every question must call a tool: always a hard check


def results_for(qid, answer, tools, status="ok"):
    return checks.run_checks(BY_ID[qid], status, answer, tools, EXP)


def test_a_missed_soft_check_is_a_warn_and_a_missed_hard_check_is_a_fail():
    # q14: facts right (rejected, 2026-10-20, a conflict), wording of the interpretation missing -> PASS with WARNs
    facts_only = "Marked rejected, deadline 2026-10-20, the data conflicts."
    label, hard, warns = checks.verdict(results_for("q14_rejected_with_offer_deadline", facts_only, ["get_data_issues"]))
    assert label == "PASS" and not hard and len(warns) == 3
    # a missing deadline (a fact) is a hard FAIL
    label, hard, warns = checks.verdict(results_for("q14_rejected_with_offer_deadline", "Marked rejected, the data conflicts.", ["get_data_issues"]))
    assert label == "FAIL" and [h[0] for h in hard] == ["names the offer deadline"]
    # a forbidden claim (a-120 called overdue) is hard
    label, hard, _ = checks.verdict(results_for("q09_a120_overdue", "Yes, a-120 is overdue. It has no due date.", ["list_tasks"]))
    assert label == "FAIL" and hard[0][0] == "does not call a-120 overdue"
    # status and style are hard
    assert checks.verdict(results_for("q12_unknown_role", "Role does not exist.", ["list_jobs"], status="api_error"))[0] == "FAIL"
    assert checks.verdict(results_for("q12_unknown_role", "No such role. I didn't pull the list of jobs.", ["list_jobs"]))[0] == "FAIL"


def test_q12_unknown_role_with_other_words_is_now_a_warn_not_a_fail():
    label, hard, warns = checks.verdict(results_for("q12_unknown_role", "Hmm, I only see three jobs here.", ["list_jobs"]))
    assert label == "PASS" and [w[0] for w in warns] == ["says the role does not exist"]
    assert checks.verdict(results_for("q12_unknown_role", "Try Jonah Whitfield.", ["list_jobs"]))[0] == "FAIL"     # invented name: hard


# ---------- re-scoring saved reports (free) ----------
REPORT = """# Eval run
## q09_a120_overdue  PASS  (expected facts: hand)

**Question:** x

**Status:** ok, rounds 2, est. $0.05

**Tool calls:** `list_tasks({})`

**Checks:**
- PASS status is ok

**Answer:**

No. Application a-120 (Lucy Fairbanks) has no due date, so it is not overdue.

## q12_unknown_role  FAIL

**Status:** max_tokens, rounds 1, est. $0.01

**Tool calls:** `list_jobs({})`

**Answer:**

Cut off

## Total
1/2
"""


def test_rescore_reads_a_saved_report_without_the_api(tmp_path):
    f = tmp_path / "evals_x.md"
    f.write_text(REPORT, encoding="utf-8")
    parsed = rescore.parse_report(REPORT)
    assert parsed["q09_a120_overdue"]["tools"] == ["list_tasks"] and parsed["q12_unknown_role"]["status"] == "max_tokens"
    rows = {qid: label for qid, label, _, _ in rescore.rescore(f, EXP, BY_ID)}
    assert rows == {"q09_a120_overdue": "PASS", "q12_unknown_role": "FAIL"}
    assert "anthropic" not in (ROOT / "evals" / "rescore.py").read_text(encoding="utf-8").lower().replace("anthropic_", "")


def test_rescore_script_runs_and_prints_a_table():
    r = subprocess.run([sys.executable, "-I", str(ROOT / "evals" / "rescore.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and ("pass all hard checks" in r.stdout or r.stdout.strip() == "")
