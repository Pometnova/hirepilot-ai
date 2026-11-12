"""Load emails/*.eml and link each one to a candidate.

Counterparty: if the sender is on STAFF_DOMAIN, the candidate is the RECIPIENT; otherwise the SENDER.
Methods (best first), each with a confidence:
  exact_email       address equals a candidate email from candidates.json         high
  normalized_email  equal after lower-casing and removing '+tag'                   high
  cv_email          address printed in that candidate's CV                         medium
  exact_name        display name equals one candidate's name                       medium
  fuzzy name        only 'ambiguous'. NEVER 'linked'.
"""
import difflib
import email
import email.policy
from collections import defaultdict
from email.utils import getaddresses

from backend import config
from .dates import email_datetime
from .normalize import insert, nn, norm_email, norm_name, read_json


def _mid(value):
    return str(value).strip().strip("<>") if value else None


def _staff(addr):
    return addr.lower().endswith("@" + config.STAFF_DOMAIN)


def load_emails(con, issues):
    cands = read_json("candidates")
    person_of = dict(con.execute("SELECT id, person_id FROM candidates"))
    persons = defaultdict(list)
    for cid, pid in person_of.items():
        persons[pid].append(cid)

    exact, normd, cv_mail, names = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
    for cid, value, source in con.execute("SELECT candidate_id, value, source FROM candidate_contacts WHERE kind='email'"):
        if source == "candidates.json":
            exact[value.lower()].add(cid)
            normd[norm_email(value)].add(cid)
        elif source == "cv_text":
            cv_mail[norm_email(value)].add(cid)
    for c in cands:
        names[norm_name(c["name"])].add(c["id"])

    def link(addr, display):
        a = addr.lower()
        if a in exact:
            ids, method, conf = exact[a], "exact_email", "high"
        elif norm_email(a) in normd:
            ids, method, conf = normd[norm_email(a)], "normalized_email", "high"
        elif norm_email(a) in cv_mail:
            ids, method, conf = cv_mail[norm_email(a)], "cv_email", "medium"
        elif display and norm_name(display) in names:
            ids, method, conf = names[norm_name(display)], "exact_name", "medium"
        else:
            fuzzy = sorted(c["id"] for c in cands if display and
                           difflib.SequenceMatcher(None, norm_name(display), norm_name(c["name"])).ratio() >= 0.85)
            return ("ambiguous", fuzzy, "fuzzy_name", "low") if fuzzy else ("unlinked", [], None, None)
        if len(ids) > 1:
            return "ambiguous", sorted(ids), method, conf
        return "linked", sorted(ids), method, conf

    parsed = []
    for path in sorted((config.RAW_DIR / "emails").iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        with open(path, "rb") as f:
            m = email.message_from_binary_file(f, policy=email.policy.default)
        from_name, from_addr = getaddresses([str(m["From"])])[0]
        to = [x for x in getaddresses([str(m["To"]), str(m["Cc"] or "")]) if x[1]]
        body_part = m.get_body(preferencelist=("plain",))
        staff_sent = _staff(from_addr)
        others = [x for x in to if not _staff(x[1])]
        party = (others[0] if others else None) if staff_sent else (from_name, from_addr)
        parsed.append(dict(
            file=path.name, message_id=_mid(m["Message-ID"]), in_reply_to=_mid(m["In-Reply-To"]),
            sent_at=email_datetime(m["Date"]), sent_at_raw=str(m["Date"]),
            direction="outbound" if staff_sent else "inbound", sender=from_addr,
            recipient=to[0][1] if to else None, party=party, subject=nn(str(m["Subject"] or "")),
            body=body_part.get_content() if body_part else None))

    # threads: follow In-Reply-To up to the root that exists in the mailbox
    by_mid = {p["message_id"]: p for p in parsed}
    for p in parsed:
        cur, seen = p, set()
        while cur["in_reply_to"] in by_mid and cur["message_id"] not in seen:
            seen.add(cur["message_id"])
            cur = by_mid[cur["in_reply_to"]]
        p["thread_id"] = cur["message_id"]
        if p["in_reply_to"] and p["in_reply_to"] not in by_mid:
            issues.add("reply_to_missing_message", "Medium", "emails", p["file"],
                       f"In-Reply-To {p['in_reply_to']} is not in the mailbox. The thread starts at this message.",
                       "recorded", problem_id="P15", value_source=p["in_reply_to"])

    for p in parsed:
        party = p["party"]
        if party is None:
            status, ids, method, conf = "unlinked", [], None, None
        else:
            status, ids, method, conf = link(party[1], party[0])
        cand = ids[0] if status == "linked" else None
        person = person_of[cand] if cand else None
        insert(con, "emails", dict(
            file=p["file"], message_id=p["message_id"], in_reply_to=p["in_reply_to"], thread_id=p["thread_id"],
            sent_at=p["sent_at"], sent_at_raw=p["sent_at_raw"], direction=p["direction"], sender=p["sender"],
            recipient=p["recipient"], counterparty_address=party[1] if party else None,
            counterparty_name=nn(party[0]) if party else None, subject=p["subject"], body=p["body"],
            candidate_id=cand, person_id=person,
            candidate_options=",".join(ids) if status == "ambiguous" else None,
            link_method=method, link_confidence=conf, link_status=status,
            source_file="emails", source_id=p["file"]))
        if status == "ambiguous":
            issues.add("email_link_ambiguous", "Medium", "emails", p["file"],
                       f"Could not link with certainty: options {ids} via {method}. Not linked.", "recorded",
                       problem_id="P15", value_source=party[1])
        if status == "unlinked":
            issues.add("email_unlinked", "Medium", "emails", p["file"],
                       "No candidate found for this email.", "recorded", problem_id="P15")
        if cand and method == "exact_name":
            # the address is new for this candidate (e.g. a second home address)
            known = {v.lower() for (v,) in con.execute(
                "SELECT value FROM candidate_contacts WHERE candidate_id=? AND kind='email'", (cand,))}
            if party[1].lower() not in known:
                insert(con, "candidate_contacts", dict(
                    candidate_id=cand, kind="email", value=party[1].lower(), value_norm=norm_email(party[1]),
                    source="email_exact_name", source_file="emails", source_id=p["file"]))
        if person and len(persons[person]) > 1:
            issues.add("email_on_merged_person", "High", "emails", p["file"],
                       f"Linked to {cand} by address, but the person has {len(persons[person])} candidate "
                       f"records ({', '.join(sorted(persons[person]))}). The content may be about the other "
                       "record's application. Linked at person level.", "recorded", problem_id="P01",
                       related_source_id=",".join(sorted(persons[person])), value_source=cand, value_used=person)
