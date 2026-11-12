"""Score/text conflict: a submitted scorecard whose numeric score and written verdict point in opposite directions.

  * score high (overall >= 0.8)  + an explicit NEGATIVE verdict phrase in the text  -> conflict
  * score low  (overall <= 0.4)  + an explicit POSITIVE verdict phrase in the text  -> conflict

Plain phrase lists and regular expressions, no model. It is a REVIEW FLAG only: it never changes the ranking score, the audit
counts or any stored data. The score is the card's "overall" if it has one, otherwise the mean of its other numeric scores (the same
rule the ranking uses). A card without a numeric score, or without text, is never flagged. Unsubmitted scorecards have no text.
"""
import re

from .common import connect, rows

HIGH, LOW = 0.8, 0.4

# Small on purpose: only explicit hiring verdicts. Matched on whole words, case-insensitive.
NEGATIVE = ("would not hire", "wouldn't hire", "do not hire", "don't hire", "no hire", "not a hire", "strong no")
POSITIVE = ("strong yes", "would hire", "strong hire")

FLAG = "Score/text conflict"


def _pattern(phrases):
    return re.compile(r"(?<![\w'])(" + "|".join(re.escape(p) for p in phrases) + r")(?![\w'])", re.I)


_NEG, _POS = _pattern(NEGATIVE), _pattern(POSITIVE)


def short_quote(text, match, limit=90):
    """The sentence (or the part after a colon) that holds the verdict phrase, cut to `limit` characters around the phrase."""
    pos = 0
    for part in re.split(r"(?<=[.!?:])\s+", text):
        found = text.index(part, pos)
        pos = found + len(part)
        if found <= match.start() < pos:
            quote = part
            if len(quote) > limit:
                a = max(match.start() - found - limit // 3, 0)
                quote = ("…" if a else "") + quote[a:a + limit].strip() + "…"
            return quote.rstrip(".")
    return match.group(1)


def conflict(text, value):
    """(match, "negative"|"positive") when the text and the normalised score disagree, else (None, None)."""
    if value >= HIGH and (m := _NEG.search(text)):
        return m, "negative"
    if value <= LOW and (m := _POS.search(text)):
        return m, "positive"
    return None, None


def _score(scores):
    """(normalised 0..1, display text) for one card, or (None, None)."""
    by_label = {s["label"]: s for s in scores}
    if "overall" in by_label:
        s = by_label["overall"]
        return s["normalized"], f"{s['value']:g}/{s['scale']}"
    if not by_label:
        return None, None
    mean = sum(s["normalized"] for s in by_label.values()) / len(by_label)
    return mean, f"{round(mean * 100)}% (mean)"


def score_text_conflicts():
    """All flagged submitted scorecards, active applications first, then by scorecard id."""
    out = []
    with connect() as con:
        cards = rows(con, "SELECT s.id, s.application_id, s.interview, s.interviewer, s.text, a.status, a.job_id_effective AS job, "
                          "c.name, j.title FROM scorecards s JOIN applications a ON a.id = s.application_id "
                          "JOIN candidates c ON c.id = a.candidate_id JOIN jobs j ON j.id = a.job_id_effective "
                          "WHERE s.feedback_status = 'submitted' AND s.text IS NOT NULL ORDER BY s.id")
        scores = {}
        for r in rows(con, "SELECT scorecard_id, label, value, scale, normalized FROM scorecard_scores"):
            scores.setdefault(r["scorecard_id"], []).append(r)
    for c in cards:
        value, shown = _score(scores.get(c["id"], []))
        if value is None:
            continue
        match, verdict = conflict(c["text"], value)
        if not match:
            continue
        out.append({"scorecard_id": c["id"], "application_id": c["application_id"], "candidate": c["name"], "job_id": c["job"],
                    "role": c["title"], "status": c["status"], "interview": c["interview"], "interviewer": c["interviewer"],
                    "score": value, "score_text": shown, "verdict": verdict, "phrase": match.group(1).lower(),
                    "quote": short_quote(c["text"], match), "source": f"scorecards.json:{c['id']}"})
    out.sort(key=lambda o: (o["status"] != "active", o["scorecard_id"]))
    for o in out:
        o["text"] = (f"{o['candidate']}: scorecard {o['scorecard_id']} scores {o['score_text']} but says '{o['quote']}' — "
                     f"confirm with {o['interviewer'] or 'the interviewer'}")
    return out


def conflict_application_ids():
    return {o["application_id"] for o in score_text_conflicts()}
