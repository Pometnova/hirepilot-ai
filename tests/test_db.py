"""Phase 2 tests: prove data/hirepilot.db is correct.

The tests read the raw files themselves (they do not call the loader's helpers), so a mistake in
the loader cannot hide itself. The `built` fixture rebuilds the database once per test session.
"""
import csv
import email
import email.policy
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime

import pytest

from backend import config
from backend.ingest.build import TABLES, build_database
from backend.ingest.normalize import raw_file_hashes

RAW = config.RAW_DIR


def raw_json(name):
    with open(RAW / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def raw_csv():
    with open(RAW / "stage_events.csv", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


@pytest.fixture(scope="session")
def built():
    before = raw_file_hashes()
    counts = build_database(config.DB_PATH)
    after = raw_file_hashes()
    return dict(before=before, after=after, counts=counts)


@pytest.fixture()
def con(built):
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def q(con, sql, *args):
    return con.execute(sql, args).fetchall()


# ------------------------------------------------------------------ 1. row counts
def test_row_counts_match_raw_files(con, built):
    counts = built["counts"]
    assert counts["jobs"] == len(raw_json("jobs")) == 3
    assert counts["candidates"] == len(raw_json("candidates")) == 45
    assert counts["applications"] == len(raw_json("applications")) == 45
    assert counts["stage_events"] == len(raw_csv()) - 1 == 89          # minus the header line
    assert counts["scorecards"] == len(raw_json("scorecards")) == 80
    assert counts["activity_notes"] == len(raw_json("activity")) == 16
    assert counts["emails"] == len(list((RAW / "emails").glob("*.eml"))) == 235
    assert counts["cvs"] == len([p for p in (RAW / "cvs").iterdir() if p.is_file()]) == 43
    assert counts["job_stages"] == sum(len(j["stages"]) for j in raw_json("jobs"))


def test_person_count_difference_is_explained(con):
    # 45 candidate records, 44 persons: the difference is the one merged person (P01).
    merged = q(con, "SELECT person_id, COUNT(*) n FROM candidates GROUP BY person_id HAVING n > 1")
    assert len(merged) == 1 and merged[0]["n"] == 2
    assert q(con, "SELECT COUNT(*) FROM persons")[0][0] == 45 - 1
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE problem_id='P01' AND issue_type='duplicate_person'")[0][0] == 1


# ------------------------------------------------------------------ 2. foreign keys
def test_foreign_keys_are_valid(con):
    assert q(con, "PRAGMA foreign_key_check") == []
    assert q(con, "PRAGMA integrity_check")[0][0] == "ok"


# ------------------------------------------------------------------ 3. stages
def test_every_event_stage_exists_in_the_jobs_stages(con):
    bad = q(con, """
        SELECT e.id, e.from_stage, e.to_stage FROM stage_events e
        JOIN applications a ON a.id = e.application_id
        WHERE (e.to_stage NOT IN (SELECT stage FROM job_stages WHERE job_id = a.job_id_effective))
           OR (e.from_stage IS NOT NULL AND e.from_stage NOT IN
               (SELECT stage FROM job_stages WHERE job_id = a.job_id_effective))""")
    assert bad == []
    # the alias really was needed: raw 'Phone Screen' rows exist and were mapped
    assert q(con, "SELECT COUNT(*) FROM stage_events WHERE from_stage_raw='Phone Screen' OR to_stage_raw='Phone Screen'")[0][0] == 6
    assert q(con, "SELECT COUNT(*) FROM stage_events WHERE from_stage='Phone Screen' OR to_stage='Phone Screen'")[0][0] == 0


# ------------------------------------------------------------------ 4. duplicate person
def test_duplicate_person_is_merged_and_both_ids_kept(con):
    rows = q(con, "SELECT id, person_id, person_link_method, person_link_confidence FROM candidates WHERE id IN ('c-105','c-121')")
    assert {r["id"] for r in rows} == {"c-105", "c-121"}
    assert len({r["person_id"] for r in rows}) == 1
    assert all(r["person_link_method"] == "same_phone+same_email_normalized+same_cv" for r in rows)
    assert all(r["person_link_confidence"] == "high" for r in rows)
    # both applications still exist, one per original id (a-399 stays a real CSM rejection)
    apps = {r["candidate_id"]: r["id"] for r in q(con, "SELECT id, candidate_id FROM applications WHERE candidate_id IN ('c-105','c-121')")}
    assert apps == {"c-105": "a-399", "c-121": "a-105"}
    # Maya Chen x2 are NOT merged
    assert len({r["person_id"] for r in q(con, "SELECT person_id FROM candidates WHERE name='Maya Chen'")}) == 2


# ------------------------------------------------------------------ 5. missing is not negative
def test_unsubmitted_scorecards_are_no_feedback_yet(con):
    raw_empty = {s["id"] for s in raw_json("scorecards") if not s["submitted_at"] and not s["text"]}
    assert raw_empty == {"s-131", "s-208", "s-209", "s-211", "s-315"}
    rows = q(con, "SELECT id, feedback_status, text, submitted_at FROM scorecards WHERE feedback_status='no_feedback_yet'")
    assert {r["id"] for r in rows} == raw_empty
    assert all(r["text"] is None and r["submitted_at"] is None for r in rows)
    # no score rows (so nothing can be averaged as zero)
    assert q(con, "SELECT COUNT(*) FROM scorecard_scores WHERE scorecard_id IN (%s)" % ",".join("?" * 5), *raw_empty)[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM scorecards WHERE feedback_status='submitted'")[0][0] == 75


def test_no_empty_strings_anywhere(con):
    for table in TABLES:
        for col in q(con, f"PRAGMA table_info({table})"):
            if col["type"] == "TEXT":
                n = q(con, f"SELECT COUNT(*) FROM {table} WHERE {col['name']} = '' OR TRIM({col['name']}) = ''")[0][0]
                assert n == 0, f"{table}.{col['name']} has {n} empty strings (must be NULL)"


# ------------------------------------------------------------------ 6. no fuzzy links
def test_no_email_or_cv_is_linked_by_fuzzy_match(con):
    assert q(con, "SELECT COUNT(*) FROM emails WHERE link_status='linked' AND link_method='fuzzy_name'")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM emails WHERE link_method='fuzzy_name' AND link_status<>'ambiguous'")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM cvs WHERE link_status IN ('linked','corrected') AND link_method LIKE '%fuzzy%'")[0][0] == 0
    # every linked email has a method and a confidence; unlinked/ambiguous ones have no candidate
    assert q(con, "SELECT COUNT(*) FROM emails WHERE link_status='linked' AND (link_method IS NULL OR link_confidence IS NULL)")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM emails WHERE link_status<>'linked' AND candidate_id IS NOT NULL")[0][0] == 0


def test_email_link_methods_match_the_audit(con):
    rows = {(r["link_method"], r["link_confidence"]): r["n"] for r in q(
        con, "SELECT link_method, link_confidence, COUNT(*) n FROM emails WHERE link_status='linked' GROUP BY 1,2")}
    # audit P15: 210 exact + 14 exact (duplicate person) = 224 high; 7 by CV address; 4 by exact name
    assert rows == {("exact_email", "high"): 224, ("cv_email", "medium"): 7, ("exact_name", "medium"): 4}


def test_staff_emails_are_matched_by_recipient(con):
    for r in q(con, "SELECT file, sender, recipient, counterparty_address FROM emails WHERE direction='outbound'"):
        assert r["sender"].endswith("@" + config.STAFF_DOMAIN)
        assert r["counterparty_address"] == r["recipient"]
    for r in q(con, "SELECT sender, counterparty_address FROM emails WHERE direction='inbound'"):
        assert r["counterparty_address"] == r["sender"]
    assert q(con, "SELECT COUNT(*) FROM emails WHERE direction='outbound'")[0][0] == 154


# ------------------------------------------------------------------ 7. tasks
def test_every_task_has_a_due_date_or_a_data_issue(con):
    for t in q(con, "SELECT id, source_file, source_id FROM tasks WHERE due_date IS NULL"):
        n = q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='task_no_due_date' AND source_file=? AND source_id=?",
              t["source_file"], t["source_id"])[0][0]
        assert n == 1, f"task {t['id']} has no due_date and no data_issues row"


def test_tasks_contains_open_done_and_closed_rows(con):
    status = {r["status"]: r["n"] for r in q(con, "SELECT status, COUNT(*) n FROM tasks GROUP BY status")}
    assert set(status) == {"open", "done", "closed"}
    assert all(n > 0 for n in status.values())


def test_closed_rows_say_how_they_were_closed(con):
    assert q(con, "SELECT COUNT(*) FROM tasks WHERE status<>'open' AND (closed_by IS NULL OR close_method IS NULL OR close_confidence IS NULL)")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM tasks WHERE status='open' AND (closed_at IS NOT NULL OR closed_by IS NOT NULL OR close_method IS NOT NULL)")[0][0] == 0
    # closed_at may be NULL only where the data does not say: the hired offer (a-306)
    no_time = q(con, "SELECT id FROM tasks WHERE status<>'open' AND closed_at IS NULL")
    assert [r["id"] for r in no_time] == ["offer_deadline:a-306"]


def test_tasks_has_no_overdue_column_and_dates_are_plain_dates(con):
    cols = {c["name"] for c in q(con, "PRAGMA table_info(tasks)")}
    assert not any("overdue" in c for c in cols)
    for r in q(con, "SELECT id, due_date FROM tasks WHERE due_date IS NOT NULL"):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["due_date"]), r["id"]
        date.fromisoformat(r["due_date"])          # comparable in Python


def test_task_counts_and_open_tasks_match_the_audit(con):
    per_type = {r["task_type"]: r["n"] for r in q(con, "SELECT task_type, COUNT(*) n FROM tasks GROUP BY 1")}
    n_offer = sum(1 for a in raw_json("applications") if a["offer_deadline"])
    n_inbound = q(con, "SELECT COUNT(*) FROM emails WHERE direction='inbound'")[0][0]
    assert per_type == {"offer_deadline": n_offer, "scorecard_pending": 80,
                        "email_unanswered": n_inbound, "application_unreviewed": 3}
    assert (n_offer, n_inbound) == (3, 81)
    open_ids = {r["id"] for r in q(con, "SELECT id FROM tasks WHERE status='open'")}
    assert open_ids == {
        "offer_deadline:a-105",
        "scorecard_pending:s-131", "scorecard_pending:s-211", "scorecard_pending:s-315",
        "scorecard_pending:s-208", "scorecard_pending:s-209",
        "email_unanswered:20261007-1015-m-1067.eml", "email_unanswered:20261007-1015-m-3073.eml",
        "application_unreviewed:a-120", "application_unreviewed:a-206", "application_unreviewed:a-311"}


def test_overdue_rule_on_known_tasks(con):
    """The loader stores no 'overdue'. This only shows the stored dates support the rule
    (overdue = due_date < REFERENCE_DATE; due today is NOT overdue), compared in Python."""
    due = {r["id"]: date.fromisoformat(r["due_date"]) for r in q(con, "SELECT id, due_date FROM tasks WHERE due_date IS NOT NULL")}
    ref = config.REFERENCE_DATE
    assert due["offer_deadline:a-105"] < ref                       # overdue (3 days)
    assert due["scorecard_pending:s-131"] < ref and due["scorecard_pending:s-211"] < ref
    assert due["scorecard_pending:s-315"] == ref                   # due today: not overdue
    assert due["scorecard_pending:s-208"] > ref and due["scorecard_pending:s-209"] > ref


def test_email_tasks_close_only_on_same_thread_and_same_person(con):
    done = q(con, """SELECT t.id, t.closed_at, t.close_method, t.close_confidence, t.closed_by,
                            e.thread_id, e.person_id, e.sent_at, r.thread_id r_thread, r.person_id r_person,
                            r.sent_at r_sent, r.direction r_dir, r.in_reply_to r_irt, e.message_id
                     FROM tasks t JOIN emails e ON e.file = t.source_id
                     JOIN emails r ON 'emails#' || r.file = t.closed_by
                     WHERE t.task_type='email_unanswered' AND t.status='done'""")
    assert len(done) == 79
    for r in done:
        assert r["close_method"] == "same_thread"
        assert r["r_dir"] == "outbound"
        assert r["r_thread"] == r["thread_id"] and r["r_person"] == r["person_id"]
        assert datetime.fromisoformat(r["r_sent"]) > datetime.fromisoformat(r["sent_at"])
        assert r["closed_at"] == r["r_sent"]
        assert r["close_confidence"] == ("high" if r["r_irt"] == r["message_id"] else "medium")
    # an open email task is either one of the 2 the audit found, or has a "same subject only" issue
    for t in q(con, "SELECT source_id FROM tasks WHERE task_type='email_unanswered' AND status='open'"):
        n = q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='possible_answer_same_subject_only' AND source_id=?", t["source_id"])[0][0]
        assert n == 1 or t["source_id"] in ("20261007-1015-m-1067.eml", "20261007-1015-m-3073.eml")


# ------------------------------------------------------------------ 8. rebuild, raw files
def _digest(path):
    c = sqlite3.connect(path)
    h = hashlib.sha256()
    for table in TABLES:
        h.update(table.encode())
        for row in c.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):
            h.update(repr(row).encode())
    c.close()
    return h.hexdigest()


def test_rebuilding_twice_gives_identical_results(tmp_path, built):
    first = build_database(tmp_path / "one.db")
    second = build_database(tmp_path / "two.db")
    assert first == second == built["counts"]
    assert _digest(tmp_path / "one.db") == _digest(tmp_path / "two.db")      # same content, not only same counts


def test_raw_files_are_unchanged_by_the_build(built, tmp_path):
    assert len(built["before"]) == 285
    assert built["before"] == built["after"]
    build_database(tmp_path / "again.db")
    assert raw_file_hashes() == built["before"]
    assert not list(RAW.rglob("*.db"))                       # nothing was written into data/raw/


# ------------------------------------------------------------------ 9. dates
ISO_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00")


def test_timestamps_have_the_new_york_offset_and_date_only_fields_are_plain(con):
    for table, col in [("applications", "applied_at"), ("applications", "rejected_at"),
                       ("stage_events", "changed_at"), ("scorecards", "interview_at"),
                       ("scorecards", "submitted_at"), ("activity_notes", "created_at"), ("emails", "sent_at")]:
        for r in q(con, f"SELECT {col} v FROM {table} WHERE {col} IS NOT NULL"):
            assert ISO_OFFSET.fullmatch(r["v"]), (table, col, r["v"])
    for table, col in [("jobs", "opened_at"), ("candidates", "created_at"), ("applications", "offer_deadline")]:
        for r in q(con, f"SELECT {col} v FROM {table} WHERE {col} IS NOT NULL"):
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["v"]), (table, col, r["v"])


def test_slash_dates_use_the_documented_rule_and_missing_date_is_null(con):
    r = {x["id"]: x for x in q(con, "SELECT id, changed_at, changed_at_raw, date_parse_rule FROM stage_events")}
    assert r[3]["changed_at"] == "2026-09-01T10:00:00-04:00" and r[3]["date_parse_rule"] == "ddmm_24h"   # 01/09/2026 10:00
    assert r[27]["changed_at"] == "2026-10-01T11:00:00-04:00" and r[27]["date_parse_rule"] == "mmdd_ampm"  # 10/01/2026 11:00 AM
    assert r[53]["changed_at"] == "2026-08-13T10:00:00-04:00"                                              # 08/13/2026 10:00 AM
    assert r[87]["changed_at"] == "2026-09-02T14:00:00-04:00"                                              # 09/02/2026 2:00 PM
    assert r[59]["changed_at"] is None and r[59]["changed_at_raw"] is None and r[59]["date_parse_rule"] is None
    assert q(con, "SELECT COUNT(*) FROM stage_events WHERE date_parse_rule='ddmm_24h'")[0][0] == 3
    assert q(con, "SELECT COUNT(*) FROM stage_events WHERE date_parse_rule='mmdd_ampm'")[0][0] == 5
    issues = {(x["issue_type"], x["source_id"]) for x in q(con, "SELECT issue_type, source_id FROM data_issues WHERE source_file='stage_events.csv'")}
    assert ("missing_date", "59") in issues and ("suspect_date", "2") in issues     # a-116's event is NOT silently fixed


# ------------------------------------------------------------------ 10. conflicts are recorded, not hidden
def test_conflicts_keep_both_values_and_a_data_issue(con):
    a113 = q(con, "SELECT job_id_source, job_id_effective, job_title_source FROM applications WHERE id='a-113'")[0]
    assert (a113["job_id_source"], a113["job_id_effective"]) == ("j-designer", "j-backend")
    cv = q(con, "SELECT candidate_id, source_candidate_id, link_status, link_method, link_confidence FROM cvs WHERE filename='RosaDelgado_Resume_2026.pdf'")[0]
    assert tuple(cv) == ("c-108", "c-112", "corrected", "exact_name+email_in_cv", "high")
    jonah = q(con, "SELECT candidate_id, person_id, source_candidate_id, link_status FROM cvs WHERE filename='Jonah_Whitfield_Resume.docx'")[0]
    assert jonah["candidate_id"] is None and jonah["source_candidate_id"] == "c-105,c-121" and jonah["link_status"] == "shared"
    conflicts = {r["source_id"] for r in q(con, "SELECT source_id FROM data_issues WHERE issue_type='stage_conflict'")}
    assert conflicts == {"a-114"}                                  # a-116 is resolved by the stage chain (below)
    a114 = q(con, "SELECT current_stage_source, current_stage_from_events FROM applications WHERE id='a-114'")[0]
    assert tuple(a114) == ("Technical Screen", "Take-Home")        # both values stored
    a116 = q(con, "SELECT current_stage_source, current_stage_from_events FROM applications WHERE id='a-116'")[0]
    assert tuple(a116) == ("Take-Home", "Take-Home")               # chain end; dates would say Technical Screen
    rows_ = q(con, "SELECT severity, handling, value_source, value_used, problem_id FROM data_issues WHERE issue_type='stage_resolved_by_chain'")
    assert [tuple(r) for r in rows_] == [("Medium", "normalized", "Technical Screen", "Take-Home", "P05")]
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='suspect_date' AND source_id='2'")[0][0] == 1   # date NOT changed
    assert q(con, "SELECT changed_at FROM stage_events WHERE id=2")[0][0] == "2026-07-08T11:00:00-04:00"
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='stage_chain_not_linear'")[0][0] == 0
    a201 = q(con, "SELECT status, rejection_reason FROM applications WHERE id='a-201'")[0]
    assert a201["status"] == "rejected" and a201["rejection_reason"] is None
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE problem_id='P10' AND source_id='a-201'")[0][0] == 1
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='no_stage_events'")[0][0] == 9
    # withdrawn stays withdrawn
    assert q(con, "SELECT COUNT(*) FROM applications WHERE status='withdrawn'")[0][0] == 8


def test_end_stage_is_the_end_of_the_chain_for_every_application(con):
    """Independent of the loader: read the raw CSV, follow from -> to, compare with current_stage_from_events."""
    alias = {"Phone Screen": "Recruiter Call"}
    steps = {}
    for r in raw_csv()[1:]:
        steps.setdefault(r[0], {})[alias.get(r[1], r[1])] = alias.get(r[2], r[2])
    stored = dict(q(con, "SELECT id, current_stage_from_events FROM applications WHERE current_stage_from_events IS NOT NULL"))
    assert set(stored) == set(steps)
    for app, nxt in steps.items():
        start = (set(nxt) - set(nxt.values())).pop()
        stage = start
        while stage in nxt:
            stage = nxt[stage]
        assert stored[app] == stage, app


def test_chain_end_rule_and_its_fallback():
    from backend.ingest.load_core import _chain_end
    ev = lambda *pairs: [dict(from_stage=a, to_stage=b) for a, b in pairs]
    assert _chain_end(ev(("A", "B"), ("B", "C"), ("C", "D"))) == "D"
    assert _chain_end(ev(("C", "D"), ("A", "B"), ("B", "C"))) == "D"          # order of the rows does not matter
    assert _chain_end(ev(("A", "B"))) == "B"
    assert _chain_end(ev(("A", "B"), ("B", "A"))) is None                       # loop -> fall back to dates
    assert _chain_end(ev(("A", "B"), ("A", "C"))) is None                       # branch
    assert _chain_end(ev(("A", "B"), ("C", "D"))) is None                       # a missing step (two chains)
    assert _chain_end(ev((None, "B"))) is None                                  # no origin


def test_cvs_are_extracted_and_every_link_has_method_and_confidence(con):
    assert q(con, "SELECT COUNT(*) FROM cvs WHERE extract_status<>'ok' OR text IS NULL")[0][0] == 0
    fmts = {r["format"]: r["n"] for r in q(con, "SELECT format, COUNT(*) n FROM cvs GROUP BY 1")}
    assert set(fmts) == {"pdf", "docx", "txt"} and sum(fmts.values()) == 43
    assert q(con, "SELECT COUNT(*) FROM cvs WHERE link_status IN ('linked','corrected','shared') AND (link_method IS NULL OR link_confidence IS NULL)")[0][0] == 0
    assert q(con, "SELECT COUNT(*) FROM cvs WHERE link_status IN ('ambiguous','unlinked')")[0][0] == 0
    # the two Maya Chen CVs go to different candidates
    maya = {r["filename"]: r["candidate_id"] for r in q(con, "SELECT filename, candidate_id FROM cvs WHERE filename LIKE 'MayaChen%'")}
    assert maya == {"MayaChen-backend-resume.txt": "c-110", "MayaChen_ProductDesign_CV.pdf": "c-210"}


def test_scores_keep_scale_and_are_normalized(con):
    assert q(con, "SELECT COUNT(DISTINCT scorecard_id) FROM scorecard_scores")[0][0] == 75
    assert {r["scale"] for r in q(con, "SELECT DISTINCT scale FROM scorecard_scores")} == {5, 10}
    assert {r["label"] for r in q(con, "SELECT DISTINCT label FROM scorecard_scores")} == {
        "overall", "communication", "technical", "ownership", "craft", "empathy", "collaboration"}
    for r in q(con, "SELECT value, scale, normalized FROM scorecard_scores"):
        assert abs(r["normalized"] - r["value"] / r["scale"]) < 1e-9
    s126 = {(r["label"], r["value"], r["scale"]) for r in q(con, "SELECT label, value, scale FROM scorecard_scores WHERE scorecard_id='s-126'")}
    assert s126 == {("technical", 4.0, 5), ("communication", 8.0, 10), ("overall", 4.0, 5)}
    assert q(con, "SELECT COUNT(*) FROM data_issues WHERE issue_type='score_without_scale' AND source_id='s-250'")[0][0] == 1


# ------------------------------------------------------------------ 11. spot checks: raw record vs database
def test_spot_check_candidate_c101(con):
    raw = next(c for c in raw_json("candidates") if c["id"] == "c-101")
    row = q(con, "SELECT * FROM candidates WHERE id='c-101'")[0]
    assert (row["name"], row["location"], row["created_at"]) == (raw["name"], raw["location"], raw["created_at"])
    assert (row["source_file"], row["source_id"]) == ("candidates.json", "c-101")
    contacts = {(r["kind"], r["value"]) for r in q(con, "SELECT kind, value FROM candidate_contacts WHERE candidate_id='c-101' AND source='candidates.json'")}
    assert contacts == {("email", e) for e in raw["emails"]} | {("phone", p) for p in raw["phones"]}
    cv = q(con, "SELECT candidate_id, link_method FROM cvs WHERE filename=?", raw["attachments"][0]["filename"])[0]
    assert cv["candidate_id"] == "c-101"


def test_spot_check_application_a105_and_scorecard_s131(con):
    raw = next(a for a in raw_json("applications") if a["id"] == "a-105")
    row = q(con, "SELECT * FROM applications WHERE id='a-105'")[0]
    assert row["candidate_id"] == raw["candidate_id"] == "c-121"
    assert row["job_id_source"] == row["job_id_effective"] == raw["job_id"]
    assert row["status"] == raw["status"] and row["current_stage_source"] == raw["current_stage"]
    assert row["applied_at"] == raw["applied_at"] + "-04:00"
    assert row["offer_deadline"] == raw["offer_deadline"] == "2026-10-12"
    assert row["rejected_at"] is None and raw["rejected_at"] is None
    assert row["source_channel"] == raw["source"]

    card = next(s for s in raw_json("scorecards") if s["id"] == "s-131")
    r = q(con, "SELECT * FROM scorecards WHERE id='s-131'")[0]
    assert r["application_id"] == card["application_id"] and r["interview"] == card["interview"]
    assert r["interviewer"] == card["interviewer"] and r["interview_at"] == card["interview_at"] + "-04:00"
    assert r["submitted_at"] is None and r["text"] is None and r["feedback_status"] == "no_feedback_yet"

    card = next(s for s in raw_json("scorecards") if s["id"] == "s-101")
    r = q(con, "SELECT * FROM scorecards WHERE id='s-101'")[0]
    assert r["text"] == card["text"] and r["submitted_at"] == card["submitted_at"] + "-04:00"
    scores = {(x["label"], x["value"], x["scale"]) for x in q(con, "SELECT label, value, scale FROM scorecard_scores WHERE scorecard_id='s-101'")}
    assert scores == {("communication", 4.0, 5), ("overall", 3.0, 5)}


def test_spot_check_stage_event_and_email(con):
    rows = raw_csv()
    line = 27                                              # a slash date with AM/PM
    raw = dict(zip(rows[0], rows[line - 1]))
    e = q(con, "SELECT * FROM stage_events WHERE id=?", line)[0]
    assert e["application_id"] == raw["application_id"] and e["from_stage_raw"] == raw["from_stage"]
    assert e["to_stage_raw"] == raw["to_stage"] and e["changed_by"] == raw["changed_by"]
    assert e["changed_at_raw"] == raw["changed_at"] and e["source_id"] == str(line)

    path = RAW / "emails" / "20261007-1015-m-1067.eml"
    with open(path, "rb") as f:
        m = email.message_from_binary_file(f, policy=email.policy.default)
    row = q(con, "SELECT * FROM emails WHERE file=?", path.name)[0]
    assert row["subject"] == str(m["Subject"]) == "Take-home submitted"
    assert row["message_id"] == str(m["Message-ID"]).strip("<>")
    assert row["in_reply_to"] == str(m["In-Reply-To"]).strip("<>")
    assert row["sender"] == "kwame.asante@example.org" and row["recipient"] == "priya.raman@quillfeather.example.com"
    assert datetime.fromisoformat(row["sent_at"]) == email.utils.parsedate_to_datetime(str(m["Date"]))
    assert row["body"] == m.get_body(preferencelist=("plain",)).get_content()
    assert "I submitted the take-home on September 25" in row["body"]
    assert (row["candidate_id"], row["link_method"], row["link_confidence"], row["direction"]) == ("c-112", "exact_email", "high", "inbound")
    assert row["thread_id"] != row["message_id"]          # it is a reply inside a thread


def test_build_meta_records_the_reference_date(con):
    meta = {r["key"]: r["value"] for r in q(con, "SELECT key, value FROM build_meta")}
    assert meta["reference_date"] == "2026-10-15" == config.REFERENCE_DATE.isoformat()
    assert meta["scorecard_overdue_days"] == "2" and meta["email_unanswered_days"] == "3"
    assert re.fullmatch(r"[0-9a-f]{64}", meta["raw_checksum"])
