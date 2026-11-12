"""Cheap, free checks of an answer's style. Pattern based, so it catches known problems only; it does not judge quality.
Used by tests, scripts/smoke_agent.py and the evals (prompt rules 10, 11 and 12)."""
import re

# internal ids the recruiter should not see (rule 10)
_INTERNAL_ID = re.compile(r"\b(person_id|thread_id|message_id|issue_id)\b|\bp-\d{3}\b", re.I)
# closing offers and "I did not check" hand-backs (rule 11)
_OFFER = re.compile(r"(i can (also )?(check|look|verify|pull|run|find)|would you like|do you want me|want me to|let me know if|"
                    r"if you(?:'d| would)? (like|want|prefer)|shall i|should i (check|look))", re.I)
# "I did not check" hand-backs and invented worries about ids (rules 11 and 12); these count anywhere in the answer.
# The verbs cover check, verify, confirm, pull, look up / at / into, review, open, run, search, query, fetch, read, examine, inspect.
_VERB = (r"(check|verify|confirm|pull|look(?:ed)? (?:up|at|into|through|for)|looked|review|open|run|search|query|fetch|"
         r"read|examine|inspect|retrieve|load)(?:ed|ing)?")
_UNCHECKED = re.compile(
    rf"(\bi (did not|didn't|have not|haven't|could not|couldn't|was not able to|wasn't able to|never|did no|have yet to) (?:yet )?{_VERB}\b"
    rf"|\b(did not|didn't|not|without|never) (?:yet )?{_VERB} whether\b"
    rf"|\bwithout (?:checking|pulling|looking up|looking at|reviewing|verifying|confirming)\b"
    r"|whether (these|they|those|the two) (are|is|were) the same (person|candidate))", re.I)


def style_problems(answer):
    """List of problems found in the answer text (empty list = none found)."""
    problems = []
    for m in _INTERNAL_ID.finditer(answer):
        problems.append(f"internal id shown: {m.group(0)}")
    tail = answer.strip()[-600:]                         # offers belong at the end; an 'if you want' in the middle is rarer
    for m in _OFFER.finditer(tail):
        problems.append(f"closing offer: '{m.group(0)}'")
    for m in _UNCHECKED.finditer(answer):
        problems.append(f"unchecked claim: '{m.group(0)}'")
    return problems
