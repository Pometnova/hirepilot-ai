"""Step 8: link each CV file to a candidate.

Method order (as agreed):
  1. attachment reference in candidates.json (filename)      -> 'attachment'
  2. exact normalized name in the CV text (first lines)       -> 'exact_name'
  3. fuzzy name (difflib >= 0.85) is ONLY 'ambiguous', never 'linked'.
Extra evidence (not a method): email / phone printed inside the CV text.

Status per CV:
  linked           attachment and exact name agree on one candidate
  linked_samename  attachment decides, but the name fits 2 candidates (corroborate with email/phone)
  shared           same file attached to several candidates (duplicate-person evidence)
  conflict         attachment points to candidate A but the CV text names candidate B
  linked_by_name   no attachment, one exact-name match
  ambiguous        only fuzzy matches, or several exact-name matches and no attachment
  unlinked         nothing fits
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import difflib, re, collections as C
import docx, pypdf
from common import *

CVS = RAW / "cvs"
cands = load_json("candidates")
cid = {c["id"]: c for c in cands}


def cv_text(p):
    s = p.suffix.lower()
    if s == ".pdf":
        return "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(p)).pages)
    if s == ".docx":
        return "\n".join(x.text for x in docx.Document(str(p)).paragraphs)
    return p.read_text(encoding="utf-8", errors="replace")


by_attach = C.defaultdict(list)
for c in cands:
    for a in c["attachments"]:
        by_attach[a["filename"]].append(c["id"])
by_name = C.defaultdict(list)
for c in cands:
    by_name[norm_name(c["name"])].append(c["id"])

print(f"cv files: {len(list(CVS.iterdir()))}; attachment refs in candidates.json: {sum(len(v) for v in by_attach.values())}")
res = []
for p in sorted(CVS.iterdir()):
    t = cv_text(p)
    head = " ".join([l.strip() for l in t.splitlines() if l.strip()][:2])
    first_line = next((l.strip() for l in t.splitlines() if l.strip()), "")
    att = by_attach.get(p.name, [])
    exact = by_name.get(norm_name(first_line), [])
    fuzzy = [c["id"] for c in cands if c["id"] not in exact and
             difflib.SequenceMatcher(None, norm_name(first_line), norm_name(c["name"])).ratio() >= 0.85]
    emails = {norm_email(e) for e in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", t)}
    by_mail = [c["id"] for c in cands if emails & {norm_email(e) for e in c["emails"]}]
    phones = {norm_phone(x) for x in re.findall(r"\+?\d[\d\- ()]{8,}\d", t)}
    by_phone = [c["id"] for c in cands if phones & {norm_phone(x) for x in c["phones"]}]
    if len(att) > 1:
        status = "shared"            # same file attached to several candidates
    elif att and exact and att[0] in exact:
        status = "linked" if len(exact) == 1 else "linked_samename"  # attachment decides; name alone is ambiguous
    elif att and exact:
        status = "conflict"          # attachment says A, CV text names B
    elif att:
        status = "attachment_only"   # name line not parseable
    elif len(exact) == 1:
        status = "linked_by_name"
    elif exact or fuzzy:
        status = "ambiguous"         # fuzzy never counts as linked
    else:
        status = "unlinked"
    res.append((p.name, status, att, exact, fuzzy, by_mail, by_phone))

print("\nstatus counts:", dict(C.Counter(r[1] for r in res)))
print("\nnot cleanly linked:")
for name, st, att, exact, fuzzy, bm, bp in res:
    if st != "linked":
        print(f"  {st:16} {name}: attachment={att} exact_name={exact} fuzzy={fuzzy} email_in_cv->{bm} phone_in_cv->{bp}")
print("\nCVs referenced by >1 candidate:", {k: v for k, v in by_attach.items() if len(v) > 1})
print("candidates with no attachment:", [c["id"] + " " + c["name"] for c in cands if not c["attachments"]])
cv_cand = {x for r in res for x in r[2]}
print("candidates whose attached CV is a conflict/missing:", [r[2] for r in res if r[1] == "conflict"])
print("\nsame-name candidates (by exact name) and their CVs:")
for k, v in by_name.items():
    if len(v) > 1:
        print("  ", k, {i: [a["filename"] for a in cid[i]["attachments"]] for i in v})
print("\nCV text email/phone differs from the attached candidate's record:")
for name, st, att, exact, fuzzy, bm, bp in res:
    for a in att:
        c = cid[a]
        txt = cv_text(CVS / name)
        em = {norm_email(e) for e in re.findall(r"[\w.+-]+@[\w.-]+\.\w+", txt)}
        if em and not (em & {norm_email(e) for e in c["emails"]}):
            print(f"  {name}: CV emails {sorted(em)} vs record {c['id']} emails {c['emails']}")
print("\nCV contact info missing from candidates.json:")
for name, st, att, exact, fuzzy, bm, bp in res:
    for a in att:
        if not cid[a]["emails"]:
            print(f"  {a} has no email in candidates.json; CV {name} shows:", sorted(set(re.findall(r"[\w.+-]+@[\w.-]+\.\w+", cv_text(CVS / name)))))
