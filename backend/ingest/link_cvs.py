"""CV text extraction and CV -> candidate linking.

Order (CLAUDE.md): 1) attached-file reference in candidates.json, 2) exact normalized name.
Fuzzy name matches are only 'ambiguous', never 'linked'.

link_status:
  linked     attachment points to one candidate (name / email in the CV agree or are not contradicting)
  corrected  attachment says A, but the CV names B and B's email/phone is printed in the CV (audit P04).
             The source value stays in source_candidate_id and a data_issues row is written.
  shared     one file attached to several candidate records of the SAME person (audit P01)
  ambiguous  cannot decide; candidate_id stays NULL
  unlinked   nothing fits
"""
import difflib
from collections import defaultdict

from backend import config
from .normalize import (EMAIL_RE, PHONE_RE, extract_cv_text, insert, norm_email, norm_name,
                        norm_phone, read_json)


def _first_line(text):
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def _add_contacts(con, candidate_ids, filename, emails, phones):
    """Addresses/phones printed in the CV become contacts (source 'cv_text') when new."""
    for cid in candidate_ids:
        known_mail = {v.lower() for (v,) in con.execute(
            "SELECT value FROM candidate_contacts WHERE candidate_id=? AND kind='email'", (cid,))}
        known_phone = {v for (v,) in con.execute(
            "SELECT value_norm FROM candidate_contacts WHERE candidate_id=? AND kind='phone'", (cid,))}
        for e in sorted(emails):
            if e.lower() not in known_mail:
                insert(con, "candidate_contacts", dict(candidate_id=cid, kind="email", value=e.lower(),
                       value_norm=norm_email(e), source="cv_text", source_file="cvs", source_id=filename))
        for p in sorted(phones):
            if norm_phone(p) not in known_phone:
                insert(con, "candidate_contacts", dict(candidate_id=cid, kind="phone", value=p,
                       value_norm=norm_phone(p), source="cv_text", source_file="cvs", source_id=filename))


def load_cvs(con, issues):
    cands = read_json("candidates")
    person_of = dict(con.execute("SELECT id, person_id FROM candidates"))
    by_attach, by_name = defaultdict(list), defaultdict(list)
    for c in cands:
        for a in c["attachments"]:
            by_attach[a["filename"]].append(c["id"])
        by_name[norm_name(c["name"])].append(c["id"])
    rec_mail = {c["id"]: {norm_email(e) for e in c["emails"]} for c in cands}
    rec_phone = {c["id"]: {norm_phone(p) for p in c["phones"]} for c in cands}

    files = sorted(p for p in (config.RAW_DIR / "cvs").iterdir() if p.is_file() and not p.name.startswith("."))
    for path in files:
        fmt, text, status, error = extract_cv_text(path)
        if status != "ok":
            issues.add("cv_extraction_" + status, "Medium", "cvs", path.name, error or "", "recorded")
        first = _first_line(text)
        att = by_attach.get(path.name, [])
        exact = by_name.get(norm_name(first), []) if first else []
        cv_mails = {norm_email(e) for e in EMAIL_RE.findall(text or "")}
        cv_phones = {norm_phone(p) for p in PHONE_RE.findall(text or "")}
        mail_hits = [c for c in rec_mail if rec_mail[c] & cv_mails]
        phone_hits = [c for c in rec_phone if rec_phone[c] & cv_phones]

        cand = person = method = conf = source_cand = None
        link_status = "unlinked"
        contact_targets = []

        if len(att) > 1:
            persons = {person_of[c] for c in att}
            source_cand = ",".join(sorted(att))
            if len(persons) == 1:
                link_status, method, conf, person = "shared", "attachment", "high", persons.pop()
                contact_targets = sorted(att)
                issues.add("cv_shared_by_duplicate_records", "Medium", "cvs", path.name,
                           f"The same file is attached to {source_cand}, which are one person. "
                           "Linked at person level; candidate_id stays NULL.", "recorded", problem_id="P01",
                           value_source=source_cand, value_used=person)
            else:
                link_status = "ambiguous"
                issues.add("cv_attached_to_different_people", "High", "cvs", path.name,
                           f"The same file is attached to different people: {source_cand}.", "recorded",
                           value_source=source_cand)
        elif len(att) == 1:
            a = att[0]
            if not exact or a in exact:
                evidence = ["attachment"]
                if exact and a in exact and len(exact) == 1:
                    evidence.append("exact_name")
                if a in mail_hits:
                    evidence.append("email_in_cv")
                link_status, cand, person = "linked", a, person_of[a]
                method = "+".join(evidence)
                conf = "high" if len(evidence) > 1 else "medium"
                contact_targets = [a]
            else:
                # attachment says `a`, the CV text names someone else
                source_cand = a
                proof = [c for c in exact if c in mail_hits or c in phone_hits]
                if len(proof) == 1:
                    target = proof[0]
                    how = "email_in_cv" if target in mail_hits else "phone_in_cv"
                    link_status, cand, person = "corrected", target, person_of[target]
                    method, conf = f"exact_name+{how}", "high"
                    contact_targets = [target]
                    issues.add("cv_attached_to_wrong_candidate", "High", "candidates.json", a,
                               f"{path.name} is attached to {a}, but the CV text names "
                               f"{[c['name'] for c in cands if c['id'] == target][0]} and prints an address "
                               f"that belongs to {target}. Linked to {target}; source value kept in "
                               "cvs.source_candidate_id. Author decision after Phase 1 review.",
                               "normalized", problem_id="P04", related_source_id=path.name,
                               value_source=a, value_used=target)
                else:
                    link_status = "ambiguous"
                    issues.add("cv_attached_to_wrong_candidate", "High", "candidates.json", a,
                               f"{path.name} is attached to {a}, but the CV text names {exact} and no "
                               "email/phone proves which one. Not linked.", "recorded", problem_id="P04",
                               related_source_id=path.name, value_source=a)
        else:
            # no attachment reference: exact name, otherwise only 'ambiguous'
            if len(exact) == 1:
                link_status, cand, person = "linked", exact[0], person_of[exact[0]]
                method, conf = "exact_name", "medium"
                contact_targets = [cand]
            else:
                fuzzy = [c["id"] for c in cands if c["id"] not in exact and first and
                         difflib.SequenceMatcher(None, norm_name(first), norm_name(c["name"])).ratio() >= 0.85]
                if exact or fuzzy:
                    link_status = "ambiguous"
                    method = "exact_name" if exact else "fuzzy_name"
                    issues.add("cv_link_ambiguous", "Medium", "cvs", path.name,
                               f"No attachment reference. Name matches {exact or fuzzy}. Not linked.", "recorded")

        insert(con, "cvs", dict(
            filename=path.name, format=fmt, text=text, extract_status=status, extract_error=error,
            candidate_id=cand, person_id=person, link_method=method, link_confidence=conf,
            link_status=link_status, source_candidate_id=source_cand, source_file="cvs", source_id=path.name))
        # Only email addresses become contacts. Phone-like digit runs in CV text are used as
        # evidence above but not stored (dates such as "2019-2022" can look like phone numbers).
        _add_contacts(con, contact_targets, path.name, {e for e in EMAIL_RE.findall(text or "")}, set())
