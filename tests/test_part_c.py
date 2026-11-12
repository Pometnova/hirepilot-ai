"""Part C: Data Health Check, Data Quality, Candidates page, footer, viewing text. FREE: no model, no key. Numbers are
checked against the raw files in data/raw."""
import json
from datetime import date

from streamlit.testing.v1 import AppTest

from backend import config
from backend.services import analytics, trust
from web import dashboard, pages_data

RAW = config.RAW_DIR
APPS = json.loads((RAW / "applications.json").read_text(encoding="utf-8"))
D = analytics.dashboard()
ROWS = D["candidates"]
APP = str(config.ROOT / "web" / "app.py")


def start(page="Overview"):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = page
    return at.run()


def md(at):
    return " ".join(m.value for m in at.markdown)


def test_health_sentences_have_counts_and_the_missing_part():
    s = {c["label"]: c for c in D["coverage"]}
    texts = [c["sentence"] + c["missing_text"] for c in D["coverage"]]
    assert "42 of 44 candidates have a CV — 2 missing" in texts
    assert "All 44 candidates have recruiter emails" in texts
    assert "75 of 80 interviews have feedback — 5 not submitted yet" in texts
    cards = json.loads((RAW / "scorecards.json").read_text(encoding="utf-8"))
    assert len(cards) == 80 and len(s) == 3


def test_quality_summary_adds_up_and_lists_the_attention_rows():
    q = D["quality_summary"]
    assert q["total"] == 57 and q["high"] == 37 and q["to_review"] == 7
    assert [g["total"] for g in q["groups"].values()] == [34, 7, 16]
    assert sum(r["count"] for r in q["attention"]) == q["to_review"]
    assert [r["issue"] for r in q["attention"]][:3] == ["Rejected application has an offer deadline",
                                                       "Interview feedback may refer to another application", "Hiring stage conflicts with history"]


def test_flags_come_from_rules_and_match_the_raw_offer_deadlines():
    by_id = {r["application_id"]: r for r in ROWS}
    assert len(ROWS) == len(APPS) == 45
    assert "Status conflict" in by_id["a-201"]["flags"] and "Offer deadline" in by_id["a-105"]["flags"] and "Longest stalled" in by_id["a-110"]["flags"]
    raw = {a["id"]: a for a in APPS}
    assert raw["a-201"]["status"] == "rejected" and raw["a-201"]["offer_deadline"]                  # the raw data really has the conflict
    assert sum(1 for r in ROWS if r["flags"]) == 5                                    # + Rosa a-108 (score/text conflict)


def test_last_update_is_between_applied_and_the_reference_date_and_not_invented():
    raw = {a["id"]: a for a in APPS}
    for r in ROWS:
        applied = raw[r["application_id"]]["applied_at"][:10]
        assert r["last_update"] is None or applied <= r["last_update"] <= config.REFERENCE_DATE.isoformat(), r["application_id"]
    rej = next(r for r in ROWS if r["application_id"] == "a-201")
    assert rej["last_update"] >= raw["a-201"]["rejected_at"][:10]


def test_candidate_filters_search_and_paging():
    f = pages_data.filter_rows
    assert len(f(ROWS, "All", None, "")) == 45 and len(f(ROWS, "With Flags", None, "")) == 5
    assert len(f(ROWS, "By Role", "j-csm", "")) == 12 and len(f(ROWS, "By Status", "active", "")) == 17
    assert [r["application_id"] for r in f(ROWS, "All", None, "a-201")] == ["a-201"]                # search by application id
    assert all("rafael" in r["candidate"].lower() for r in f(ROWS, "All", None, "RAFAEL"))          # by name, any case
    assert f(ROWS, "All", None, "zzz-nobody") == []
    first = f(ROWS, "All", None, "")[:3]
    assert all(r["flags"] for r in first)                                                           # flagged rows come first
    assert pages_data.PAGE_SIZE == 10


def test_candidates_page_paging_and_banner_button():
    at = start("Candidates")
    assert len(at.dataframe[0].value) == 10 and any("Showing 1–10 of 45" in c.value for c in at.caption)
    at = at.button(key="pg-1").click().run()
    assert any("Showing 11–20 of 45" in c.value for c in at.caption)
    at = at.button(key="banner-flags").click().run()
    assert at.session_state["cand-tab"] == "With Flags" and len(at.dataframe[0].value) == 5
    assert any("Showing 1–5 of 5" in c.value for c in at.caption)                                   # a new filter starts on page 1


def test_status_badge_colours_and_flag_style():
    assert pages_data.STATUS_CSS["Active"].startswith("background-color: #DDF2E3")
    assert "#FFE1DA" in pages_data.STATUS_CSS["Rejected"] and "#E9E3F2" in pages_data.STATUS_CSS["Withdrawn"]
    assert pages_data.day("2026-10-09T10:00:00") == "Oct 9" and pages_data.day(None) == "–"


def test_overview_no_longer_has_activity_or_decisions_and_candidates_has_both():
    ov, ca = md(start()), md(start("Candidates"))
    assert "Recent Activity" not in ov and "Needs your decision" not in ov
    assert "Recent Activity" in ca and "Needs your decision (4)" in ca


def test_viewing_text_is_short(monkeypatch):
    at = start()
    assert "Viewing: **" in md(at) and "— the charts below show this role." in md(at)


def test_ask_page_has_no_footer_and_other_pages_do():
    assert "Smarter hiring" not in md(start("Ask AI"))
    for page in ("Overview", "Candidates", "Tasks"):
        assert "Smarter hiring. Clearer decisions." in md(start(page))


def test_footer_pushed_down_by_css_without_fixed_or_sticky():
    from web import theme
    assert "margin-top: auto" in theme.CSS and "min-height: calc(100vh" in theme.CSS
    assert "position: fixed" not in theme.CSS and "position: sticky" not in theme.CSS


def test_ask_page_leaves_room_under_the_last_answer_for_the_chat_input():
    from web import theme
    assert '[class*="st-key-ask-actions"]) { padding-bottom: 9rem !important; }' in theme.CSS.replace("{{", "{").replace("}}", "}")


def test_footer_layout_rule_is_scoped_to_pages_with_a_footer():
    from web import theme
    css = theme.CSS.replace("{{", "{")
    assert 'stMainBlockContainer"]:has([class*="st-key-site-footer"]) { display: flex' in css      # not on Ask AI: it made answers overflow
    assert 'stMainBlockContainer"] { display: flex' not in css


# ---------- widget keys of the Sources list never depend on the source text ----------
def test_unique_groups_keeps_the_first_of_a_repeated_ref_in_each_group():
    from web import answer
    g = [{"candidate": "A", "items": [{"ref": "x:1", "label": "one"}, {"ref": "x:1", "label": "again"}, {"ref": "x:2", "label": "two"}]},
         {"candidate": "B", "items": [{"ref": "x:1", "label": "one"}]}, {"candidate": "C", "items": []}]
    out = answer.unique_groups(g)
    assert [[i["label"] for i in x["items"]] for x in out] == [["one", "two"], ["one"]]                 # first kept, same ref in group B stays


def test_repeated_refs_in_groups_and_in_two_answers_do_not_clash(monkeypatch):
    from backend.agent import core
    from tests.test_app import FakeAgent, result
    from tests.test_stage3 import start
    from web import evidence
    ref = "applications.json:a-105"
    text = f"FACTS\n- One. [{ref}]\n- Two. [{ref}; {ref}]\n- Three. [{ref}, scorecards.json:s-103]\n\nAI ASSESSMENT\nOk."

    def labels(refs):                                    # the same ref twice in one group and also in a second candidate group
        item = {"ref": ref, "label": "Application a-105 · Jonah Whitfield"}
        return {"count": 4, "groups": [{"candidate": "Jonah Whitfield", "items": [item, dict(item), {"ref": "scorecards.json:s-103", "label": "Scorecard s-103"}]},
                                       {"candidate": "Other person", "items": [dict(item)]}]}
    monkeypatch.setattr(evidence, "source_labels", labels)
    fake = FakeAgent([result(answer=text), result(answer=text)])                  # two answers on one page with the same refs
    at = start("Ask AI", fake, monkeypatch)
    at = at.button(key="askbtn-tasks").click().run()
    at = at.button(key="askbtn-tasks").click().run()
    assert not at.exception, at.exception
    assert len(fake.calls) == 2 and sum(e.label == "Sources (3)" for e in at.expander) == 2         # duplicates removed: 2 + 1 items


# ---------- hide a leading "(my judgement ...)" in AI ASSESSMENT (display only) ----------
def test_leading_my_judgement_tags_are_hidden_but_the_stored_answer_is_unchanged(monkeypatch):
    from tests.test_app import FakeAgent, result
    from tests.test_stage3 import start
    for tag in ("(my judgement)", "(my judgement, not data)", "(My judgement — not from the data)", "**(my judgement)**"):
        raw = f"FACTS\n- One. [applications.json:a-105]\n\nAI ASSESSMENT\n{tag} Jonah looks strongest.\n\nCAVEATS\n- Weights are assumed."
        at = start("Ask AI", FakeAgent([result(answer=raw)]), monkeypatch)
        at = at.button(key="askbtn-tasks").click().run()
        text = " ".join(m.value for m in at.markdown)
        assert "my judgement" not in text.lower() and "Jonah looks strongest" in text, tag
        assert tag in at.session_state["messages"][-1]["content"]                                 # the stored answer keeps the tag
    from web import answer
    assert answer._JUDGEMENT.sub("", "He said (my judgement) is fine.") == "He said (my judgement) is fine."   # only a LEADING tag is hidden


# ---------- Inter is bundled: no web font from the internet ----------
def test_inter_font_is_bundled_with_its_licence_and_nothing_loads_from_google():
    import hashlib
    from web import theme
    fonts = config.ROOT / "assets" / "fonts"
    served = config.ROOT / "web" / "static" / "fonts"
    for w in (400, 500, 600, 700):
        data = (fonts / f"Inter-{w}.woff2").read_bytes()
        assert data[:4] == b"wOF2"                                                         # a real woff2 file
        assert hashlib.sha256(data).digest() == hashlib.sha256((served / f"Inter-{w}.woff2").read_bytes()).digest()   # served copy is identical
        assert f"font-weight: {w}" in theme.CSS and f"/app/static/fonts/Inter-{w}.woff2" in theme.CSS
    assert "SIL OPEN FONT LICENSE" in (fonts / "OFL.txt").read_text(encoding="utf-8") and (served / "OFL.txt").exists()
    assert "googleapis" not in theme.CSS and "gstatic" not in theme.CSS and "@import" not in theme.CSS
    assert "sans-serif" in theme.FONT and theme.FONT.startswith("Inter,")                  # system fallback kept
    assert "enableStaticServing = true" in (config.ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
