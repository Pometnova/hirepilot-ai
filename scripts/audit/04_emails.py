"""Step 9: link each email to a candidate; build threads for Q3.

Counterparty rule: if the sender is on the company domain (quillfeather.example.com),
the candidate is the RECIPIENT (To/Cc, excluding company addresses). Otherwise the
candidate is the SENDER.

Methods (best first), each with a confidence:
  exact_email        address equals a candidate email                      high
  normalized_email   equal after lower-casing and removing '+tag'           high  (flag if >1 candidate)
  cv_email           address printed in that candidate's CV text            medium
  exact_name         display name equals one candidate's name               medium
  ambiguous          fuzzy name, or the match hits >1 candidate             -- never 'linked'
  unlinked           no match
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import difflib, email, email.policy, os, re, collections as C
from email.utils import getaddresses, parsedate_to_datetime
import docx, pypdf
from common import *

cands = load_json("candidates")
cid = {c["id"]: c for c in cands}
EM = RAW / "emails"

# emails printed inside CVs (only used as 'cv_email' evidence)
def cv_text(p):
    s = p.suffix.lower()
    if s == ".pdf":
        return "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(p)).pages)
    if s == ".docx":
        return "\n".join(x.text for x in docx.Document(str(p)).paragraphs)
    return p.read_text(encoding="utf-8", errors="replace")

cv_mail = C.defaultdict(set)
for c in cands:
    for a in c["attachments"]:
        for e in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", cv_text(RAW / "cvs" / a["filename"])):
            cv_mail[norm_email(e)].add(c["id"])

exact = C.defaultdict(set); normd = C.defaultdict(set); names = C.defaultdict(set)
for c in cands:
    for e in c["emails"]:
        exact[e.lower()].add(c["id"]); normd[norm_email(e)].add(c["id"])
    names[norm_name(c["name"])].add(c["id"])


def link(addr, display):
    a = addr.lower()
    if a in exact:
        ids, m, conf = exact[a], "exact_email", "high"
    elif norm_email(a) in normd:
        ids, m, conf = normd[norm_email(a)], "normalized_email", "high"
    elif norm_email(a) in cv_mail:
        ids, m, conf = cv_mail[norm_email(a)], "cv_email", "medium"
    elif norm_name(display) in names:
        ids, m, conf = names[norm_name(display)], "exact_name", "medium"
    else:
        fz = [c["id"] for c in cands if display and difflib.SequenceMatcher(None, norm_name(display), norm_name(c["name"])).ratio() >= 0.85]
        return ("ambiguous" if fz else "unlinked"), sorted(fz), "-", ""
    if len(ids) > 1:
        return "ambiguous", sorted(ids), conf, m
    if len(normd.get(norm_email(a), ())) > 1:
        # address belongs to a person stored under 2 IDs (c-105 / c-121): linked, but flagged
        return "linked_dup_pair", sorted(normd[norm_email(a)]), conf, m + "+dup_person"
    return "linked", sorted(ids), conf, m


rows = []
for f in sorted(os.listdir(EM)):
    m = email.message_from_binary_file(open(EM / f, "rb"), policy=email.policy.default)
    frm = getaddresses([str(m["From"])])[0]
    to = [x for x in getaddresses([str(m["To"]), str(m["Cc"] or "")]) if x[1]]
    staff_sent = frm[1].lower().endswith("@" + STAFF_DOMAIN)
    others = [x for x in to if not x[1].lower().endswith("@" + STAFF_DOMAIN)]
    party = others[0] if staff_sent and others else (None if staff_sent else frm)
    body = m.get_body(preferencelist=("plain",)).get_content() if m.get_body(preferencelist=("plain",)) else ""
    dt = parsedate_to_datetime(str(m["Date"])).replace(tzinfo=None)
    if party is None:
        st, ids, conf, meth = "unlinked", [], "-", "no non-company party"
    else:
        st, ids, conf, meth = link(party[1], party[0])
    rows.append(dict(f=f, mid=str(m["Message-ID"]).strip("<>").split("@")[0], irt=str(m["In-Reply-To"] or "").strip("<>").split("@")[0],
                     staff_sent=staff_sent, party=party, st=st, ids=ids, conf=conf, meth=meth, dt=dt, subj=str(m["Subject"]),
                     body=body, n_other=len(others), sender=frm[1]))

print("emails:", len(rows), "| staff-sent:", sum(r["staff_sent"] for r in rows), "| inbound:", sum(not r["staff_sent"] for r in rows))
print("link status:", dict(C.Counter(r["st"] for r in rows)))
print("method x confidence (linked):", dict(C.Counter((r["meth"], r["conf"]) for r in rows if r["st"].startswith("linked"))))
print("staff-sent emails with >1 external recipient:", [r["f"] for r in rows if r["staff_sent"] and r["n_other"] > 1])
print("staff senders:", dict(C.Counter(r["sender"] for r in rows if r["staff_sent"])))

print("\n## NOT CLEANLY LINKED")
for r in rows:
    if r["st"] != "linked":
        print(f"  {r['st']:10} {r['f']}: party={r['party']} -> {r['ids']} ({r['meth']}) subj={r['subj'][:50]!r}")
print("\n## DUPLICATE-PERSON EMAILS (address shared by 2 candidate IDs):", sum(r["st"] == "linked_dup_pair" for r in rows), "emails; ids:", sorted({tuple(r["ids"]) for r in rows if r["st"] == "linked_dup_pair"}))
print("\n## LINKED BUT NOT BY EXACT ADDRESS (check)")
for r in rows:
    if r["st"] == "linked" and r["meth"] != "exact_email":
        print(f"  {r['f']}: {r['party'][1]} -> {r['ids']} via {r['meth']}/{r['conf']}")
print("\n## candidates with no linked email:", [c["id"] for c in cands if not any(c["id"] in r["ids"] for r in rows)])

# ---- threads (for Q3: emails waiting for a reply) ----
byid = {r["mid"]: r for r in rows}
def root(r):
    seen = set()
    while r["irt"] and r["irt"] in byid and r["mid"] not in seen:
        seen.add(r["mid"]); r = byid[r["irt"]]
    return r["mid"]
th = C.defaultdict(list)
for r in rows:
    th[root(r)].append(r)
print("\n## THREADS:", len(th), "| sizes:", dict(C.Counter(len(v) for v in th.values())))
print("In-Reply-To pointing to a message not in the mailbox:", [(r["f"], r["irt"]) for r in rows if r["irt"] and r["irt"] not in byid])
print("subject patterns:", dict(C.Counter(re.sub(r"^(Re: )+", "", r["subj"]).split(" - ")[0][:40] for r in rows).most_common(12)))
print("\n## THREADS WHOSE LAST MESSAGE IS INBOUND (candidate wrote last, no staff reply yet)")
for k, v in sorted(th.items(), key=lambda kv: max(x["dt"] for x in kv[1])):
    v.sort(key=lambda x: x["dt"]); last = v[-1]
    if not last["staff_sent"]:
        days = (REFERENCE_DATE - last["dt"]).days
        print(f"  {last['f']} cand={last['ids']} {last['dt']:%Y-%m-%d} ({days}d before ref) subj={last['subj'][:50]!r} | {last['body'].strip()[:100]!r}")
print("\n## THREADS WHOSE LAST MESSAGE IS OUTBOUND AND CONTAINS A QUESTION OR REQUEST (waiting on candidate), oldest first")
for k, v in sorted(th.items(), key=lambda kv: max(x["dt"] for x in kv[1])):
    last = sorted(v, key=lambda x: x["dt"])[-1]
    if last["staff_sent"] and re.search(r"\?|let me know|please (send|confirm|reply)|by (monday|tuesday|wednesday|thursday|friday)|deadline", last["body"], re.I):
        days = (REFERENCE_DATE - last["dt"]).days
        print(f"  {last['f']} cand={last['ids']} {last['dt']:%Y-%m-%d} ({days}d) subj={last['subj'][:45]!r}")
