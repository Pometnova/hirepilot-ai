"""Scorecard score formats: scale per card, labels, cards with no number, name mismatch (Q1).

Scores live inside the free text as 'Label: n/d'. This script only counts and lists ids.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import collections as C, re
from common import *

cards = load_json("scorecards")
apps = {a["id"]: a for a in load_json("applications")}
cn = {c["id"]: c for c in load_json("candidates")}
pat = re.compile(r"([A-Za-z][A-Za-z ]*?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+)")

with_text = [s for s in cards if s["text"]]
print("cards:", len(cards), "| with text:", len(with_text), "| empty text:", [s["id"] for s in cards if not s["text"]])
scale = C.defaultdict(list)
for s in with_text:
    found = pat.findall(s["text"])
    scale[tuple(sorted({d for _, _, d in found})) or ("none",)].append(s["id"])
for k, v in scale.items():
    print(f"scale {k}: {len(v)} cards", v if len(v) <= 3 else "")
print("cards with text but no n/d score:", [s["id"] for s in with_text if not pat.findall(s["text"])])
print("score above its own scale:", [(s["id"], n.strip(), v, d) for s in with_text for n, v, d in pat.findall(s["text"]) if float(v) > float(d)])
print("labels:", dict(C.Counter(n.strip().title() for s in with_text for n, v, d in pat.findall(s["text"]))))
first = {c["name"].split()[0] for c in cn.values()}
print("card text names another candidate's first name than its application:")
for s in with_text:
    me = cn[apps[s["application_id"]]["candidate_id"]]["name"].split()[0]
    named = [f for f in first if re.search(rf"\b{f}\b", s["text"])]
    if named and me not in named:
        print("  ", s["id"], s["application_id"], "expected", me, "text names", named)
multi = C.Counter((s["application_id"], s["interview"]) for s in cards)
print("application+interview pairs with >1 card:", sorted(k for k, v in multi.items() if v > 1))
