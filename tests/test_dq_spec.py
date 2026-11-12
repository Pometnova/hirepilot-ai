"""Data Quality section, approved layout. FREE: no model, no key. Numbers are checked against the audit records and the raw files."""
import json

from streamlit.testing.v1 import AppTest

from backend import config
from backend.services import analytics, trust
from web import dashboard

D = analytics.dashboard()
Q = D["quality_summary"]
REC = Q["records"]
APP = str(config.ROOT / "web" / "app.py")


def start():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = "Overview"
    return at.run()


def test_counts_come_from_the_audit_and_add_up():
    g = {k: v["total"] for k, v in Q["groups"].items()}
    assert sum(g.values()) == Q["total"] == len(REC) == 57 and (g["fixed"], g["human"], g["left"]) == (34, 7, 16)
    assert Q["high"] == sum(r["severity"] == "High" for r in REC) == 37          # severity is counted on its own, not from the groups
    assert sum(r["group"] == "human" for r in REC) == Q["to_review"] == 7


def test_severity_and_resolution_are_different_things():
    assert any(r["severity"] == "High" and r["group"] == "fixed" for r in REC)      # a high-severity issue can already be fixed
    assert len({r["severity"] for r in REC if r["group"] == "human"}) >= 2


def test_stacked_bar_widths_tooltips_and_legend():
    start_html = " ".join(h.value for h in start().main.get("html"))
    assert "flex:34;background:#75619B" in start_html and "flex:7;background:#FF674C" in start_html and "flex:16;background:#D8D0E5" in start_html
    assert 'title="Needs Your Review — 7 issues (12.3%)"' in start_html and "34 Fixed" in start_html and "7 Need Review" in start_html


def test_three_cards_show_the_group_counts_and_spec_wording():
    text = " ".join(m.value for m in start().markdown)
    for n, title in ((34, "Fixed Automatically"), (7, "Needs Your Review"), (16, "Left Unchanged")):
        assert f"# {n}" in text and f"**{title}**" in text
    assert "Issues corrected during processing." in " ".join(c.value for c in start().caption)
    assert dashboard.QUALITY_ICON == {"fixed": ":material/check_circle:", "human": ":material/warning:", "left": ":material/remove_circle:"}


def test_preview_has_only_unresolved_issues_with_real_sources_and_names():
    rows = dashboard.attention_rows(REC)
    assert len(rows) == 7 and all(r["group"] == "human" for r in rows)
    raw = json.loads((config.RAW_DIR / "applications.json").read_text(encoding="utf-8"))
    a201 = next(r for r in rows if r["source"] == "applications.json:a-201")
    assert "Rafael Mendoza" in a201["record"] and any(a["id"] == "a-201" and a["status"] == "rejected" for a in raw)
    assert all(":" in r["source"] for r in rows) and all(r["content"] for r in rows)
    html = " ".join(h.value for h in start().main.get("html"))
    assert html.count("Needs Review</span>") == 7 and "applications.json:a-201" in html


def test_issues_table_headings_and_badge():
    at = start()
    html = " ".join(h.value for h in at.main.get("html"))
    for col in ("Issue", "Affected Record", "Severity", "Status", "Source", "Content"):
        assert f"<th>{col}</th>" in html
    assert "7 to review</span>" in html and not any("0 to review" in h.value for h in at.main.get("html"))


def test_full_audit_has_every_issue_in_a_table_and_filters_work():
    at = start()
    assert any(e.label == "View All Issues & Sources" for e in at.expander)
    every = next(t.value for t in at.dataframe if "Handling" in t.value.columns)
    assert len(every) == 57 and set(every["Resolution"]) == {"Fixed Automatically", "Needs Review", "Left Unchanged"}
    grouped = next(t.value for t in at.dataframe if "Explanation" in t.value.columns)
    assert grouped["Count"].sum() == 57 and list(grouped.columns) == ["Issue", "Count", "Resolution", "Severity", "Explanation", "Source"]
    at.session_state["dq-resolution"] = "Needs Your Review"
    at = at.run()
    every = next(t.value for t in at.dataframe if "Handling" in t.value.columns)
    assert len(every) == 7 and set(every["Resolution"]) == {"Needs Review"}
    at.session_state["dq-severity"] = "High"
    at = at.run()
    every = next(t.value for t in at.dataframe if "Handling" in t.value.columns)
    assert set(every["Severity"]) == {"High"} and len(every) == sum(r["group"] == "human" and r["severity"] == "High" for r in REC)


def test_filter_records_keeps_resolution_and_severity_separate():
    assert len(dashboard.filter_records(REC, "All Issues", "All severities")) == 57
    assert len(dashboard.filter_records(REC, "Fixed Automatically", None)) == 34
    assert len(dashboard.filter_records(REC, "All Issues", "High")) == 37
    assert len(dashboard.filter_records(REC, "Fixed Automatically", "High")) < 37


def test_no_unsubmitted_scorecards_in_the_audit_and_no_ai_call(monkeypatch):
    assert not any(r["type"] == "no_feedback_yet" for r in REC)
    from backend.agent import core
    calls = []
    monkeypatch.setattr(core, "ask_sync", lambda *a, **k: calls.append(a))
    start()
    assert calls == []


def test_every_source_reference_is_valid_and_nothing_is_dropped():
    files = {"activity.json", "applications.json", "candidates.json", "cvs", "emails", "scorecards.json", "stage_events.csv"}
    assert {r["source"].split(":")[0] for r in REC} <= files and all(r["source"].split(":")[1] for r in REC)
    assert sum(len(l["sources"]) for g in Q["groups"].values() for l in g["lines"]) == len(REC)
    assert set(trust.ISSUE_TITLE) >= {r["type"] for r in REC}                       # every type has a readable title
