"""Score/text conflict rule. FREE: no model. The raw scorecards are read again here, independently of the service."""
import json
import re

from streamlit.testing.v1 import AppTest

from backend import config
from backend.services import analytics, ranking, score_conflict as sc, trust
from web import chat

RAW = json.loads((config.RAW_DIR / "scorecards.json").read_text(encoding="utf-8"))
D = analytics.dashboard()
APP = str(config.ROOT / "web" / "app.py")


def raw_overall(text):
    """Independent of the service: the 'Overall: n/d' value of a raw scorecard, else the mean of its 'Label: n/d' scores, else None."""
    pairs = re.findall(r"([A-Za-z ]+?):\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)", text)
    vals = {label.strip().lower(): float(v) / float(d) for label, v, d in pairs}
    if "overall" in vals:
        return vals["overall"]
    return sum(vals.values()) / len(vals) if vals else None


def test_rule_flags_exactly_the_scorecards_a_hand_check_expects():
    flagged = {o["scorecard_id"] for o in sc.score_text_conflicts()}
    assert flagged == {"s-115"}                                   # Rosa Delgado: Overall 10/10 but "I would not hire Rosa for this team"
    o = sc.score_text_conflicts()[0]
    assert (o["candidate"], o["application_id"], o["interviewer"], o["verdict"], o["score_text"]) == ("Rosa Delgado", "a-108", "Marcus Feld", "negative", "10/10")
    assert o["text"] == "Rosa Delgado: scorecard s-115 scores 10/10 but says 'I would not hire Rosa for this team' — confirm with Marcus Feld"


def test_the_service_agrees_with_an_independent_scan_of_the_raw_file():
    by_hand = set()
    for card in RAW:
        text = card.get("text") or ""
        value = raw_overall(text)
        low = text.lower()
        if value is not None and ((value >= 0.8 and any(p in low for p in sc.NEGATIVE)) or (value <= 0.4 and any(p in low for p in sc.POSITIVE))):
            by_hand.add(card["id"])
    assert by_hand == {o["scorecard_id"] for o in sc.score_text_conflicts()}


def test_consistent_cards_are_not_flagged():
    for card_id in ("s-104", "s-107", "s-123", "s-308"):          # 'strong yes' with 5/5: score and text agree
        assert card_id not in {o["scorecard_id"] for o in sc.score_text_conflicts()}


def test_rule_unit_cases():
    assert sc.conflict("Overall: 5/5. Would not hire.", 1.0)[1] == "negative"
    assert sc.conflict("Great, but do not hire.", 0.8)[1] == "negative"
    assert sc.conflict("It was a no hire for me", 0.9)[1] == "negative"
    assert sc.conflict("Overall 1/5. Strong yes!", 0.2)[1] == "positive"
    assert sc.conflict("Overall 2/5, I would hire her.", 0.4)[1] == "positive"
    assert sc.conflict("Overall 1/5. I would not hire.", 0.2) == (None, None)       # low score + negative text agree
    assert sc.conflict("Overall 5/5. Strong yes.", 1.0) == (None, None)             # high score + positive text agree
    assert sc.conflict("Overall 3/5. Would not hire.", 0.6) == (None, None)         # a middle score is not a conflict
    assert sc.conflict("No hiring freeze, no hired date.", 1.0) == (None, None)     # whole words only


def test_review_flag_only_the_ranking_score_and_audit_counts_are_unchanged():
    assert D["issues"]["total"] == 57 and D["quality_summary"]["total"] == 57
    ranked = {x["application_id"]: x["score"] for x in ranking.rank_candidates_for_job("j-backend", top_n=50)["data"]["ranked"]}
    assert (ranked["a-105"], ranked["a-110"], ranked["a-108"]) == (100.0, 92.25, 87.0)       # Rosa keeps her score: the flag is review-only


def test_flag_in_candidates_data_top_card_flags_and_decisions():
    row = next(r for r in D["candidates"] if r["application_id"] == "a-108")
    assert "Score/text conflict" in row["flags"]
    assert sum("Score/text conflict" in r["flags"] for r in D["candidates"]) == 1
    assert trust.risk_flags(["a-108", "a-105"])["a-108"] == ["Score/text conflict"]
    chart = {"rows": [{"name": "Rosa Delgado", "application_id": "a-108", "stage_conflict": False, "open_tasks": 0, "thin": False}]}
    out = chat.add_flags(chart)["rows"][0]
    assert out["flags"] == ["Score/text conflict"] and out["urgent"] is True
    alert = next(a for a in D["decisions"] if a["kind"] == "score_text")
    assert alert["title"] == "Score/text conflict: Rosa Delgado" and alert["source"] == "scorecards.json:s-115"
    assert alert["text"].endswith("confirm with Marcus Feld") and "scorecard s-115 scores 10/10 but says 'I would not hire Rosa" in alert["text"]


def test_candidates_page_shows_the_flag_and_the_decision_item():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = "Candidates"
    at = at.run()
    table = at.dataframe[0].value
    assert "⚠ Score/text conflict" in set(table["Flags"]) and "Rosa Delgado" in set(table["Candidate"])
    text = " ".join(m.value for m in at.markdown)
    assert "Score/text conflict: Rosa Delgado" in text and "Needs your decision (4)" in text and "5 candidates need your attention" in text
