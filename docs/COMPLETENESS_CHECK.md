# Completeness Check (before Phase 2)

Goal: prove that no record is silently lost and that Phase 2 will see the full dataset.
Produced by `scripts/audit/08_completeness.py` (part of `sh scripts/audit/run_all.sh`).
It reuses the linking rules of `03_cvs.py` and `04_emails.py`; it adds no new linking logic.
Read-only. `data/raw/` checksum before and after: `e440f9bf0563336b181bdc05c83f5dd2a586f126a83695fae67b970022aa571b` (unchanged).
REFERENCE_DATE = 2026-10-15. Thresholds: scorecard overdue after 2 days, email unanswered after 3 days.

## Summary

| source | raw | read | failed | linked | not linked | ambiguous |
|---|---:|---:|---:|---:|---:|---:|
| jobs.json | 3 | 3 | 0 | n/a | n/a | n/a |
| candidates.json | 45 | 45 | 0 | n/a | n/a | n/a |
| applications.json | 45 | 45 | 0 | 45 | 0 | 0 |
| stage_events.csv | 89 | 89 | 0 | 89 | 0 | 0 |
| scorecards.json | 80 | 80 | 0 | 80 | 0 | 0 |
| activity.json | 16 | 16 | 0 | 16 | 0 | 0 |
| emails/ | 235 | 235 | 0 | 221 | 0 | 14 |
| cvs/ | 43 | 43 | 0 | 43 | 0 | 0 |

`jobs` and `candidates` are the link targets, so linking does not apply to them.
Files under `data/raw/`: 285 = 7 top-level + 235 emails + 43 CVs. No hidden or unexpected files.

## 1. Record counts

How the numbers were made:
- **raw**: an independent count. JSON: number of records found by a text pattern (`"id":`, or
  `"body":` for activity, which has no id). CSV: physical lines minus the header. Emails and CVs:
  files in the folder.
- **read**: records the audit scripts handled (`json.load`, pandas rows, parsed `.eml`, extracted CV text).
- **failed**: a record missing a required key, a CSV row with the wrong column count, a file
  that could not be parsed or extracted.

Result: **raw = read + failed for all 8 sources, no gap.**
- CSV: 89 lines after the header = 89 rows by the `csv` module = 89 pandas rows; no row has a wrong column count.
- Dates: every non-empty date field parses. One field is empty: `stage_events.csv` line 59 (a-104),
  which stays NULL (it is a missing value, not a failed record).
- "Failed" is 0 everywhere. No file name needs a reason.

## 2. Linking

Rule: linked + not linked + ambiguous = total. "Ambiguous" is used only when we cannot tell who a
record belongs to.

| source | method | linked | not linked | ambiguous |
|---|---|---:|---:|---:|
| applications | ID: `candidate_id` and `job_id` both resolve | 45 | 0 | 0 |
| stage_events | ID: `application_id` | 89 | 0 | 0 |
| scorecards | ID: `application_id` | 80 | 0 | 0 |
| activity | ID: `candidate_id` | 16 | 0 | 0 |
| emails | address, then name, then CV address | 221 | 0 | 14 |
| cvs | attachment reference, then exact name | 43 | 0 | 0 |

Notes:
- applications: a-113 resolves by ID but its job conflicts (P06). Linked by ID; the job is corrected
  in Phase 2 (`job_id_effective = j-backend`).
- activity: linked by candidate ID. Two notes on c-105 describe the a-105 offer (P01); the ID link is
  still correct, the person-level link fixes it.
- **emails, 221 linked**: 210 exact address (high), 4 exact name (medium, c-306's second address),
  7 address found in the CV (medium, c-309).
- **emails, 14 ambiguous**: all use `jonah.whitfield@example.net`, which matches both c-105 and
  c-121. They are ambiguous at candidate level and resolved at person level (c-105 and c-121 share the
  normalized email **and** phone, so they are one person, P01). The script finds exactly one such
  group: `[c-105, c-121]`. No other email is ambiguous.

### CVs: sub-statuses (all 43 are linked)

| status | count | meaning |
|---|---:|---|
| linked | 39 | attachment reference and exact name agree on one candidate |
| linked_samename | 2 | the two Maya Chen CVs (c-110, c-210): the attachment decides, email/phone in the CV agrees |
| shared (one person) | 1 | `Jonah_Whitfield_Resume.docx`, referenced by c-105 and c-121, who are one person (P01) |
| linked (corrected) | 1 | `RosaDelgado_Resume_2026.pdf` → **c-108** (P04 decision). `conflict_with_source = c-112` |

Record name: in the Phase 2 schema the source value is stored in `cvs.source_candidate_id` and a
`data_issues` row; there is no flags column.

### Why 44 CV references but 43 files

`candidates.json` has 44 attachment references and **43 distinct filenames**. The difference is
exactly one: `Jonah_Whitfield_Resume.docx` is referenced by both c-105 and c-121 (the same person).
Every referenced file exists on disk, and every file on disk is referenced. After the P04
correction, the only candidate without a CV is **c-112** (before the correction it was c-108).

## 3. Emails

- **Total 235 = outbound 154 + inbound 81 + other 0.** "Other" (staff to staff only) is 0.
- Outbound: all 154 are from one sender, `priya.raman@quillfeather.example.com`.
- Inbound: 81 emails from `example.com` (29), `example.net` (27), `example.org` (25).
  **All 81 match a candidate; 0 do not.** There are no agencies, referrers or unknown senders in the
  mailbox. Methods: 72 exact address, 4 exact address on the c-105/c-121 person, 2 exact name, 3 CV address.
- Threads: 89. 87 end with an outbound message, 15 of those are single-message threads
  (applicant acknowledgements and rejections that need no reply).
  One reply (`20260916-1605-m-3055.eml`) points to a message (`m-3051`) that is not in the mailbox.

### Outbound staff emails with no candidate reply

- 154 outbound emails: **104** have a later inbound email from the same person (any thread);
  **50** do not.
- **7 people** received an outbound email and never wrote back: c-101, c-107, c-207, c-208 (all
  rejected at Application Review, so a reply was not expected) and c-120, c-205, c-206 (active; the
  emails are dated 2026-10-05 to 2026-10-14).
- The 50 are mostly acknowledgements, rejections, confirmations and withdrawal acknowledgements.
  A script cannot tell "needs a reply" from "does not". **This matters for Q2 only a little:**
  silence after a rejection is normal; silence from active candidates (c-120, c-205, c-206) is
  recent (1–10 days) and cannot yet be called a loss. The stronger Q2 evidence is elsewhere
  (take-home waits, section 3.4 of `DATA_AUDIT.md`). Nothing is built for this.

## 4. Exclusions, NULLs and what Phase 2 will not use

Nothing is deleted or dropped: **0 raw records are removed.** Doubtful values are kept and
recorded in `data_issues`.

| # | Item | Treatment | Reason |
|---|---|---|---|
| a | `stage_events.csv` line 59 (a-104) has no date | `changed_at = NULL` | Cannot be recovered; order is still known from the chain |
| b | line 2 (a-116) is dated before `applied_at` | kept, `data_issues` row (P05) | The correction is a guess |
| c | `Phone Screen` in 6 event rows | mapped to `Recruiter Call`; raw name kept | Alias, only in the CSM job |
| d | 8 slash-date rows | parsed by the AM/PM rule; raw text kept | Rule is inferred (P07) |
| e | 5 empty scorecards (s-131, s-208, s-209, s-211, s-315) | no scores; `no_feedback_yet` | Empty ≠ negative |
| f | s-207 text names a different person | kept on a-203, `data_issues` row | Typo vs misfiled is unknown |
| g | a-113 `job_id = j-designer` | stored as `job_id_source`; `j-backend` used in funnels | P06 decision |
| h | `RosaDelgado_Resume_2026.pdf` attached to c-112 | source kept in `source_candidate_id`; CV used for c-108 | P04 decision |
| i | 8 withdrawn applications | not counted as rejected | They hold a reason in `rejection_*` fields |
| j | `offer_deadline` on a-201 (rejected) and a-306 (hired) | not turned into tasks | Not open offers (a-201 conflict, P10) |
| k | 16 activity notes | kept as context, no tasks computed | Free text, no due dates |
| l | 2 inbound emails with a later staff message on the same subject (`20260814-1230-m-2044.eml`, `20260825-1640-m-3038.eml`) | not counted as unanswered | Probably answered |
| m | `20260916-1605-m-3055.eml` parent `m-3051` missing | kept; thread root = itself | Message not in mailbox |
| n | a-399 (c-105) | kept as a real CSM rejection; funnels count per role | P01 decision |
| o | Requirements for roles | not stored | `jobs.json` has none (P02) |

## 5. Q3 task sources

Computed at query time in `backend/services/` (no tasks table). "Explicit" = the date is in the
data; "inferred" = we chose the rule or threshold.

**Q3 scope decision ("core only", author).**

| Class | Sources | How Q3 treats them |
|---|---|---|
| **Tasks** (pending / overdue) | A offer deadlines, B unsubmitted scorecards, C inbound emails with no staff reply | These are the only items called "pending" or "overdue" |
| **Pending only, no due date** | H new applications not yet reviewed | Listed as pending. Never "overdue", because the data has no due date |
| **"At risk" list** | E stalled applications | Shown with *days since last change*. Never labeled overdue |
| **Context only, not tasks** | D activity notes, F threads waiting on a candidate, G dates mentioned in email text, I rejection with no notice email | Shown to the LLM as supporting context. Never counted or listed as tasks |

| Source | Count | Rule | Due date | Result on 2026-10-15 |
|---|---:|---|---|---|
| A. Offer deadline — *task* | 3 records | `status=active` and deadline < ref → overdue; ≥ ref → pending | **Explicit** | overdue: a-105 (3 d). Pending: none. Not a task: a-201 (rejected), a-306 (hired) |
| B. Unsubmitted scorecard — *task* | 5 | unsubmitted > 2 days after `interview_at` → overdue | Interview date explicit; **due inferred** (2 d) | overdue: s-131, s-211. Pending: s-208, s-209, s-315 |
| C. Inbound email, no staff reply — *task* | 4 | no reply and age > 3 days, and no later staff message on the same subject → unanswered | **Inferred** (3 d) | unanswered: `20261007-1015-m-1067.eml` (c-112), `20261007-1015-m-3073.eml` (c-309), both 7.6 d. **Between 3 and 7 days: none.** Probably answered: 2 |
| D. Activity notes — *context only* | 16 notes, 4 with a date phrase | not computed | Not structured | Context for the LLM only |
| E. Stalled applications — *at risk, never overdue* | 17 active | days since the last recorded stage change; no threshold decided | Inferred | Longest waits listed in `05_tasks_and_funnel.py` |
| F. Waiting on candidate — *context only* | 37 threads | thread ends with an outbound message and the candidate has an active application | Inferred | Not a recruiter task. Context for Q2. Includes old threads, so it overcounts |
| G. Dates mentioned in email text — *context only* | 2 | email body mentions a date after 2026-10-15 | Explicit, in free text | `20261006-1530-m-2007.eml` ("October 20", offer reply for a-201), `20261008-1525-m-1101.eml` ("October 16", intro call) |
| H. New applications not yet reviewed — *pending only, no due date* | 3 | active, no stage events | No due date; inferred | a-120, a-206, a-311 |
| I. Rejection with no notice email — *context only* | 1 | rejected, and no staff email to the person on/after `rejected_at − 1 day` | Inferred, low confidence | a-201 (also has no reason; supports the P10 doubt) |
| J. Future interviews in scorecards | 0 | `interview_at` > ref | n/a | none |

Under the scope decision, only A, B and C produce "pending" or "overdue" items; H is pending only; E is an
"at risk" list; D, F, G and I are context. The counts above do not change.

Limits of this section:
- Source G uses a simple pattern (`October N`, `10/N`) and misses phrases like "the 16th", so it is a
  lower bound.
- Source F counts every thread that ends outbound, including old ones. It is context, not a task list.
- Source C depends on `In-Reply-To` plus a same-subject check. An email answered by phone or in a
  different thread would still show as unanswered.

## Result

- No record is lost: all 8 sources reconcile (raw = read + failed, 0 failed).
- Every record that can link does link (0 not linked). The only ambiguity is 14 emails to one person
  stored under two candidate IDs (P01), resolved at person level.
- Phase 2 can load the full dataset: 3 jobs, 45 candidates, 45 applications, 89 stage events,
  80 scorecards, 16 notes, 235 emails, 43 CVs.

Not verified: the checks cover structure and links, not the truth of the content. The inferred date
rule (P07), the two thresholds and the person link for c-105/c-121 are judgments, not facts in the data.
