# Data Audit — Quillfeather Labs recruiting export (Phase 1)

Export date (REFERENCE_DATE): **2026-10-15**. Times in the data are New York local time.
Every number below comes from a script in `scripts/audit/`. Re-run all of them with:

```
sh scripts/audit/run_all.sh
```

Raw data checksum (all 285 files in `data/raw/`, sha256 of the sorted per-file hashes):
`e440f9bf0563336b181bdc05c83f5dd2a586f126a83695fae67b970022aa571b`
(measured before and after the audit; unchanged).

**References.** Candidate IDs (`c-…`) are the main reference. Application IDs are `a-…`,
scorecards `s-…`. Email files are named by file name. CSV rows are named by CSV line number
(line 1 = header). Script that produced each number is in brackets, e.g. [01].

| Script | Topic |
|---|---|
| `01_structure.py` | counts, links, duplicates, status and stage conflicts |
| `02_dates.py` | date formats, time zones, future dates |
| `03_cvs.py` | CV → candidate linking |
| `04_emails.py` | email → candidate linking, threads |
| `05_tasks_and_funnel.py` | Q3 task sources, stage dwell, Q2 evidence |
| `06_email_vs_status.py` | emails vs application status, CSV order |
| `07_scorecard_scales.py` | score formats, empty cards, wrong-name card |

**Severity.** High = changes an answer to Q1/Q2/Q3. Medium = less certain, may change an answer.
Low = cosmetic.

### Decisions made after Phase 1 review (author)

1. **P04** — link `RosaDelgado_Resume_2026.pdf` to **c-108**. Keep the source value (c-112) in the
   data as a recorded conflict.
2. **P06** — a-113 gets `job_id_effective = j-backend`. Keep the source value (`j-designer`).
3. **Thresholds** — a scorecard is overdue after **2 days**; an inbound email is unanswered after
   **3 days**. Both go in `backend/config.py` next to `REFERENCE_DATE`
   (`SCORECARD_OVERDUE_DAYS = 2`, `EMAIL_UNANSWERED_DAYS = 3`).
4. **Schema** — ~~no `derived_tasks` table~~ (**changed at the start of Phase 2, see decision 6**).
   Problems are recorded **only** in the `data_issues` table; there are no `flags` columns.
5. **P01** — a-399 is a real CSM rejection. Funnels count per role.

### Decisions made at the start of Phase 2 (author)

6. **A `tasks` table now exists** (this replaces the "no tasks table" part of decision 4).
   *Why:* the services should only filter and compare. They should not rebuild the task list
   from four raw sources on every question. *Rules:* the loader stores **every** item, open and
   closed (`status` = `open | done | closed`, plus `closed_at`, `closed_by`, `close_method`,
   `close_confidence`). It does **not** filter by `REFERENCE_DATE`. There is **no `overdue` column**:
   overdue is calculated later in `backend/services/`.
7. **Times are stored as ISO 8601 with the New York offset** (e.g. `2026-10-07T10:15:00-04:00`).
   This replaces the "no offset" part of rule 5.2. *Why:* an offset makes each value
   unambiguous; the offset comes from the `America/New_York` time zone rules, not from a fixed
   `-04:00` (every date in this export falls in daylight time, so all are `-04:00`).
8. **Date-only fields stay plain dates** (`jobs.opened_at`, `candidates.created_at`,
   `applications.offer_deadline`, `tasks.due_date`). *Why:* they have no time of day, and adding
   `T00:00` would invent data.
9. **Overdue rule.** `overdue` means `due_date < REFERENCE_DATE`. A task due **on** `REFERENCE_DATE`
   is "due today", not overdue (example: s-315, due 2026-10-15). *Why:* a task is late only after its
   due day has ended. Dates are compared **in Python** (`date` objects), never as text in SQL.
   *Why:* ISO strings with different offsets, and plain dates mixed with timestamps, do not
   compare correctly as text.
10. **Email tasks close only on the same thread and the same person.** A later staff message
    closes an inbound-email task only if it is on the same thread **and** goes to the same
    `person_id`. Same subject alone does not close it: the task stays open and a `data_issues`
    row is written. *Why:* a subject is reused across candidates and across threads.
11. **Applications with no stage events** (9): each gets a `data_issues` row. A task is created
    only for the 3 active ones (class H below, "pending only, no due date"). No tasks are created
    for the 6 rejected ones, because no audit source defines a task for them.

---

## 1. Overview

### Files and counts

| File | Format | Records | What it holds |
|---|---|---|---|
| `jobs.json` | JSON list | 3 | `id, title, department, opened_at, status, stages[]` |
| `candidates.json` | JSON list | 45 | `id, name, emails[], phones[], location, created_at, attachments[]` |
| `applications.json` | JSON list | 45 | `id, candidate_id, job_id, job_title, applied_at, status, current_stage, rejected_at, rejection_reason, source, offer_deadline` |
| `stage_events.csv` | CSV | 89 rows | `application_id, from_stage, to_stage, changed_at, changed_by` |
| `scorecards.json` | JSON list | 80 | `id, application_id, interview, interviewer, interview_at, submitted_at, text` |
| `activity.json` | JSON list | 16 | `candidate_id, author, created_at, body` (no id field; referenced here by zero-based list index) |
| `emails/` | `.eml`, text/plain | 235 | 154 sent by staff (all from one person, Priya Raman), 81 inbound |
| `cvs/` | PDF / DOCX / TXT | 43 | all text can be extracted |

Jobs: `j-backend` Senior Backend Engineer (opened 2026-06-10, 127 days = 4.2 months open on the
reference date), `j-csm` Customer Success Manager (94 days), `j-designer` Product Designer (73 days).
[05]

### How the files link

```
jobs.id ──────────< applications.job_id
candidates.id ────< applications.candidate_id   (every candidate has exactly 1 application)
applications.id ──< stage_events.application_id
applications.id ──< scorecards.application_id
candidates.id ────< activity.candidate_id       (by candidate, not by application)
candidates.attachments[].filename ── cvs/<filename>      (44 references, 43 files)
emails/ ── NO key. Linked only by address / name (see 4.4). Not linked in the data.
```

All JSON/CSV id links resolve: no application points to a missing candidate or job, no event,
scorecard or note points to a missing application or candidate. [01]
Stage events are not in date order and not in application order. [06]
Applications with no stage events: 9 (all at the first stage, so this is expected). [01]

---

## 2. Problems found

Format: **ID — title** · Source · Impact · Severity · Evidence.

### High

**P01 — One person stored as two candidates (c-105 and c-121).**
Source: `candidates.json` c-105, c-121 (same name, same phone `+1 347-555-0115`, same email once
`+jobs` is removed, same CV file `Jonah_Whitfield_Resume.docx`). Applications: a-399
(c-105, CSM, rejected 2026-07-29) and a-105 (c-121, backend, active, at Offer).
Effects: 14 emails use `jonah.whitfield@example.net` and link to c-105, but the Offer emails
(`20260928-1600-m-1023.eml` … `20261013-0950-m-1026.eml`) are about a-105, which belongs to c-121.
Activity notes at `activity.json` index 1 (2026-08-03) and index 2 (2026-10-13, "Offer deadline
passed yesterday") sit on c-105 but describe the backend process and the a-105 offer. [01, 04]
Impact: Q1 (one person appears twice; feedback split), Q2 (a-399 is a real CSM rejection, so each
role funnel counts it once; the same person may appear in two role funnels but must be one person
in any total across roles), Q3 (the overdue offer is on c-121, its notes are on c-105). **High.**

**P02 — `jobs.json` has no role requirements.**
Source: `jobs.json`, all 3 jobs. Fields are only id, title, department, opened_at, status, stages.
No skills, seniority, must-haves, location, salary, or headcount.
Impact: **Q1.** "Top 3 for a role" cannot be ranked against a requirement list. The only role
evidence is the job title, scorecard text, rejection reasons, and the emails that describe a role.
The ranking will rest on scorecards, stage progress and CV text, and must say so. Also, an email
(2026-10-05 to c-307) says two CSMs are being hired; headcount is not in the data. **High.**

**P03 — There is no tasks file.**
Source: README lists no tasks. Q3 must be derived (see section 3.3 for each source). **High.**

**P04 — CV attached to the wrong candidate (c-112 vs c-108).**
Source: `candidates.json` c-112 (Kwame Asante) lists `RosaDelgado_Resume_2026.pdf`. The CV text
is Rosa Delgado's, her email in the CV (`rosa.delgado@example.com`) is c-108's. c-108 has no
attachment. [03]
Impact: Q1 — both are backend candidates in the later stages (a-108 Onsite, a-112 Take-Home).
The wrong CV would give each the other's evidence. **High.**

**P05 — Stage history disagrees with `applications.json`.** [01]
- a-114 (c-114, active): app says `Technical Screen`; events show `→ Take-Home` (line 19,
  2026-09-21) and scorecard s-131 (Take-Home, 2026-10-06) exists. The app stage looks stale.
- a-116 (c-116, rejected at Take-Home): events line 2 (`Technical Screen → Take-Home`) is dated
  2026-07-08, before `applied_at` 2026-07-13, and before the earlier stages. Sorted by date, the
  "last" event is Technical Screen, which conflicts with the app stage. The date looks wrong
  (hypothesis only: day and month swapped, i.e. 2026-08-07). Not proven.
- a-302, a-304 (CSM): events use `Phone Screen`, which is not in the CSM stage list. It is
  almost certainly `Recruiter Call` (alias). 6 event rows use it (lines 9, 10, 20, 25, 56, 79).
- **Resolution (Phase 5 review, author): the stage chain decides, dates do not.** `current_stage_from_events` is the
  end of the `from -> to` chain, not the last event by date. a-116's events form a straight chain
  (Application Review -> Recruiter Call -> Technical Screen -> Take-Home), so it ends at **Take-Home**. That agrees with
  `applications.json`, with the rejection reason ("Take-home: no tests…") and with scorecard s-136 (Take-Home,
  2026-08-19). The old date rule put it at Technical Screen and counted a Take-Home rejection as a Technical Screen
  rejection. a-114 is unchanged (chain and dates both say Take-Home; `applications.json` is stale, so its
  `stage_conflict` row stays). Rules: (1) if the events are not one straight line (loop, branch, missing step), fall
  back to date order and write a `stage_chain_not_linear` row (none occur: all 36 applications with events are
  straight); (2) when the chain and the dates disagree, write a Medium `stage_resolved_by_chain` row (handling
  `normalized`, both values kept); (3) event dates are never changed (line 2 keeps its `suspect_date` row; the day/month
  swap stays a guess); (4) rejection text is evidence in the issue row only, never used by code to place an application.
Impact: Q2 (where candidates are lost and how long they wait), Q3 (stalled applications). **High.**

**P06 — Application a-113 has the wrong job (or wrong title).**
Source: `applications.json` a-113 (c-113): `job_id = j-designer` but `job_title = Senior Backend
Engineer`; its events (lines 53, 76) and scorecards (s-127, s-128) use backend stages
(Recruiter Call, Technical Screen), which `j-designer` does not have, and the rejection reason is
about "database fundamentals and concurrency". The evidence says backend. [01]
Impact: Q1 (a backend candidate inside the designer list), Q2 (designer funnel gets 1 extra
application and the backend funnel loses 1). By `job_id` the counts are backend 19, designer 14,
csm 12; by title they are backend 20, designer 13, csm 12. **High.**

**P07 — Mixed date formats in `stage_events.csv`.**
Source: lines 3, 21, 26, 27, 49, 53, 66, 87 use slash dates (the other 80 rows use
`YYYY-MM-DD HH:MM`). Line 59 (a-104, `Recruiter Call → Technical Screen`) has no date at all.
No JSON field has a date format problem. No timezone markers anywhere in JSON/CSV. [02]
The slash dates are ambiguous. Rule inferred from the data: **24-hour time → DD/MM/YYYY**
(3 rows: lines 3, 21, 26), **12-hour AM/PM → MM/DD/YYYY** (5 rows: lines 27, 49, 53, 66, 87).
All 8 then fall after `applied_at` and before the reference date; the other reading breaks
that for 5 of them. Line 53 (`08/13/2026`) can only be MM/DD. This is an inference, not stated
in the data. Impact: Q2 (time in stage, order of stages). **High**, with Medium confidence in
the rule.

**P08 — Scores are on different scales and live inside free text.**
Source: `scorecards.json` text. 75 cards have text: 60 use `/5`, 14 use `/10`, 1 (s-126) mixes
both. Labels vary (Overall, Technical, Communication, Ownership, Empathy, Craft, Collaboration);
there is no structured score field. [07]
Impact: Q1. Averaging raw numbers without scale handling would rank `/10` cards wrongly. **High.**

**P09 — Empty scorecards: 5 interviews with no feedback yet.**
Source: s-131 (a-114, c-114), s-208 and s-209 (a-203, c-203), s-211 (a-204, c-204), s-315
(a-308, c-308). `submitted_at` and `text` are both empty; all are for active applications. [05]
Per project rule: empty = "no feedback yet", never negative.
Impact: Q1 (do not score as zero), Q3 (pending scorecards). **High.**

**P10 — Application a-201 is "rejected" at the Offer stage, with no reason, and has a future
offer deadline.**
Source: `applications.json` a-201 (c-201): status rejected, `rejected_at` 2026-10-09,
`rejection_reason` empty (the only rejected application without one), `offer_deadline`
2026-10-20 (5 days after the reference date). Emails show the offer was sent 2026-10-06
(`20261006-1530…`) and the candidate asked about the start date on 2026-10-07; no email after
that. [01, 05]
Impact: Q1 (is the strongest designer still a candidate?), Q3 (is an offer pending?). The data
cannot say whether the candidate declined or the record is wrong. **High.**

### Medium

**P11 — Same name, different people (c-110 and c-210 are both "Maya Chen").**
Different phone, city, email, CV, job (backend vs designer). Not duplicates. Any link by name
alone is ambiguous: 2 CVs (`MayaChen-backend-resume.txt`, `MayaChen_ProductDesign_CV.pdf`) match
both names; resolved only by the attachment reference and the email/phone in the CV text. [01, 03]
Impact: Q1/Q3 if linking by name. **Medium.**

**P12 — Scorecard s-207 text names the wrong person.**
`scorecards.json` s-207 is attached to a-203 (c-203, Theo Lindqvist, Design Exercise) but the
text starts "Rafael." Rafael Mendoza (c-201) already has his own Design Exercise card (s-202).
[01] Impact: Q1. **Medium** (may be a typo by the interviewer).

**P13 — Several interviewers per interview.**
7 application/interview pairs have 2 cards (Onsite or Panel): a-105, a-108, a-110, a-117, a-201,
a-203, a-213. Not an error; cards ≠ interviews. Impact: Q1 (do not count one interview twice).
**Medium.**

**P14 — Missing contact data.**
c-309 has no email in `candidates.json` (the CV shows `sana.qureshi@example.org`, and 7 emails
use it). c-108 has no CV. c-121 has no email that matches exactly (only a `+jobs` variant).
c-306 uses a second address (`hcastellano.home@example.net`, 4 emails) that is not in the record.
[03, 04] Impact: Q3 (unanswered emails), Q1 (CV evidence). **Medium.**

**P15 — Email linking is mostly exact, but some links are weaker.**
235 of 235 emails link to a candidate: 210 by exact address (high), 14 by exact address but
belonging to the c-105/c-121 person (P01), 4 by exact name only (medium; c-306), 7 by an address
found in the CV (medium; c-309). None link by fuzzy name. None are unlinked. [04]
`20260916-1605-m-3055.eml` replies to `m-3051`, which is not in the mailbox. **Medium.**

**P16 — Withdrawn applications store their reason in the `rejection_*` fields.**
All 8 withdrawn (a-103, a-106, a-109, a-115, a-118, a-211, a-212, a-305) have `rejected_at` and
`rejection_reason` filled. Impact: Q2 if "rejected" is counted by looking at `rejected_at`
(withdrawals would be counted as company rejections). Three withdrawals blame the wait for
take-home feedback (a-106, a-109, a-118). **Medium.**

**P17 — Activity notes are free text and have no due dates.**
16 notes, 4 contain a date phrase ("Oct 12", "10/13", "Tuesday", "July 1"). [05] Impact: Q3.
**Medium.**

### Low

**P18 — Naming and format variation.** CV file names follow no pattern; CV headings use
capitals ("HANA SATO"); phone numbers are formatted as `+1 xxx-xxx-xxxx` only; one id (a-399)
breaks the a-1xx numbering. Candidate emails are mixed case (`Jonah.Whitfield+jobs@…`). **Low.**

**P19 — Time zone.** The 235 email `Date:` headers all have offset −0400 (New York daylight time,
correct for dates before 2026-11-01). JSON/CSV dates have no offset. No date is after
2026-10-15. [02] **Low.**

### Checked and found clean
- IDs unique; all links resolve; no candidate has 2 applications; no duplicate event rows. [01]
- No date after the reference date; no scorecard submitted before its interview; no event after a
  rejection. [01, 02]
- Emails vs status: 0 contradictions by simple keyword check (limited, see L5). [06]
- Email `Date:` offsets all consistent with New York time. [02]

---

## 3. What we will handle, and how

### 3.1 Handle in Phase 2 (data layer)

| Problem | How |
|---|---|
| P01 duplicate person | Add `person_id`. c-105 and c-121 share one person with method `same_phone+same_email_normalized+same_cv`, confidence high. **Do not delete either record.** Keep both candidate ids, point activity and emails to the person, and add a `data_issues` row (P01). |
| P04 wrong CV | Store the link `RosaDelgado_Resume_2026.pdf → c-108`, method `exact_name+email_in_cv`, confidence high, keeping the source value `c-112` (`source_candidate_id`) and a `data_issues` row (P04). **Approved.** |
| P05 stage conflicts | Store `current_stage_source` (as in applications.json) and `current_stage_from_events`. Record a `data_issues` row for a-114 (`stage_conflict`) and a-116 (`stage_resolved_by_chain`) (P05). The current stage is the end of the stage chain; dates only order events in time. Map `Phone Screen → Recruiter Call` (alias table). |
| P06 a-113 | Keep `job_id_source = j-designer`. Set `job_id_effective = j-backend`, based on title, stages, events and reason, and add a `data_issues` row (P06). **Approved.** |
| P07 dates | Store raw text, parsed local time, and `date_parse_rule`. Parse by the AM/PM rule. Line 59 and a-116 line 2 get a `data_issues` row (`missing` / `suspect`); do not guess. |
| P08 scores | Extract each `Label: n/d` into a score table with `scale` and `n/d` (0–1). Keep the label. Cards with no number have no score. |
| P09 empty scorecards | `submitted = false`, no scores, `feedback_status = no_feedback_yet`. |
| P10 a-201 | Keep as in source (`rejected`), add a `data_issues` row (P10). Do not decide. |
| P01 funnels | a-399 stays a real CSM rejection. Funnels count per role (one application = one funnel entry). |
| P11 same name | Always link by id, never by name alone. |
| P13 | Keep one row per card; add `interview_key = application + interview` for grouping. |
| P14, P15 | Store email link method and confidence on every email. Add extra known addresses as `candidate_email_aliases` with their source (`cv_text`, `email_exact_name`). |
| P16 | Keep `status` as in the source. Do not call withdrawn "rejected". |

### 3.2 What the data cannot give us (Q1)
Because `jobs.json` has no requirements (P02), Phase 2 stores no requirement table. For Q1 the
agent must use: scorecard scores and text, stage reached, CV text, and the role title, and it
must tell the user that no written requirements exist.

### 3.3 Q3: how "tasks" are derived (there is no tasks file)

All dates relative to **2026-10-15**. From Phase 2 the `tasks` table is built by the loader
(`backend/ingest/build_tasks.py`) from the sources A, B, C and H below. It stores open **and**
closed items, with a plain-date `due_date`, and **never** an "overdue" flag. `backend/services/`
reads it and decides pending / overdue against `REFERENCE_DATE` (rule: `due_date < REFERENCE_DATE`;
due on that day = "due today"). Sources D, E, F, G and I are **not** stored as tasks.
Thresholds are the author's decisions (not in the data) and live in `backend/config.py`:
`SCORECARD_OVERDUE_DAYS = 2`, `EMAIL_UNANSWERED_DAYS = 3`.

What the `tasks` table holds (Phase 2 result):

| `task_type` | One row per | `due_date` | open | done | closed |
|---|---|---|---|---|---|
| `offer_deadline` (A) | application with an `offer_deadline` | the deadline | active (a-105) | hired (a-306) | rejected / withdrawn (a-201) |
| `scorecard_pending` (B) | scorecard | interview date + 2 days | unsubmitted, application active (5) | submitted (75) | unsubmitted, application not active (0) |
| `email_unanswered` (C) | inbound email | date received + 3 days | no later staff reply on the same thread (2) | later staff message, same thread and same person (79) | not used |
| `application_unreviewed` (H) | active application with no stage events | `NULL` (a `data_issues` row each) | 3 | not used | not used |

`close_method` is `status_field` (the application or scorecard status says so) or `same_thread`
(email). For `same_thread`, confidence is `high` when the staff message replies directly to the
email (77 rows) and `medium` when it is later on the same thread (2 rows: `…m-2044.eml`,
`…m-3038.eml`). `closed_at` is `NULL` only for the hired offer (a-306), because the data has no date for it.

**Q3 scope decision ("core only", author).**

| Class | Sources | How Q3 treats them |
|---|---|---|
| **Tasks** (pending / overdue) | A offer deadlines, B unsubmitted scorecards, C inbound emails with no staff reply | These are the only items called "pending" or "overdue" |
| **Pending only, no due date** | H new applications not yet reviewed | Listed as pending. Never "overdue", because the data has no due date |
| **"At risk" list** | E stalled applications | Shown with *days since last change*. Never labeled overdue |
| **Context only, not tasks** | D activity notes, F threads waiting on a candidate, G dates mentioned in email text, I rejection with no notice email | Shown to the LLM as supporting context. Never counted or listed as tasks |

| Source | Pending | Overdue | Evidence | Result on 2026-10-15 |
|---|---|---|---|---|
| **A. Offer deadline** (`applications.offer_deadline`) | `status=active`, stage Offer, deadline ≥ ref date | `status=active`, deadline < ref date | Explicit date. Strongest. | a-105 (c-121): **overdue 3 days** (also in activity index 2 and `20261013-0950-m-1026.eml`). a-306: hired, closed. a-201: rejected, so a conflict (P10), not a task. |
| **B. Unsubmitted scorecard** (`submitted_at` empty) | Interview held ≤ ref date, active application, card unsubmitted | Unsubmitted more than **2 days** after `interview_at` (decided; for comparison, submitted cards took median 2.5 h, max 31.5 h, n=75) | Explicit interview date; no due date in data | Overdue: s-131 (a-114, 8.4 d), s-211 (a-204, 7.6 d). Pending: s-315 (a-308, 1.4 d), s-208 and s-209 (a-203, 0.4 d). |
| **C. Inbound email with no staff reply** | Candidate wrote last, no later staff message in the thread | No staff reply more than **3 days** after the inbound email (decided; for comparison, staff replies took median 4.3 h, p90 167 h, max 338 h, n=77) | Explicit timestamps; threshold decided | `…m-1067.eml` (c-112, take-home feedback, 7.6 d) and `…m-3073.eml` (c-309, next-steps timing, 7.6 d). Two older ones (`…m-2044.eml`, `…m-3038.eml`) have a later staff message on the same subject, so probably answered; not counted. |
| **D. Follow-ups in activity notes** — *context only* | Needs reading the text | Cannot be computed | Free text, no due dates | Not computed. Example: activity index 15 (c-308, role play booked 10/13) matches s-315. Use only as supporting context. |
| **E. Stalled applications** (derived from stage events) — *"at risk", not a task* | `status=active` | **Never labeled overdue.** List by days since the last recorded change; no threshold decided | Derived. Weak. | Longest: a-110 (34 d, Onsite), a-307 (31 d), a-112 (30 d), a-114 (24 d), a-309 (23 d). |

Not in the table above, by the scope decision: **H** new applications not yet reviewed (a-120, a-206,
a-311) are *pending only*, with no due date. **F** outbound emails that wait for a candidate (e.g.
the offer to c-201), **G** dates mentioned in email text, and **I** a rejection with no notice email
are *context only*. Counts and rules for H, F, G and I are in `docs/COMPLETENESS_CHECK.md` section 5.

### 3.4 Q2 evidence the data does support
- `j-backend` has been open **127 days (4.2 months)**. [05]
- Backend applications that end at Take-Home: 4 withdrawn, 1 rejected, 1 active. Three withdrawal
  reasons blame waiting for take-home review (a-106, a-109, a-118). [05]
- Time spent in a stage, after the sort and alias fixes (n is small): Take-Home median 22 days
  (n=4), Design Exercise 17 days (n=4), Application Review 2.5 days (n=36). [05]
- These numbers depend on the date rule in P07 and on the a-113 decision in P06.

---

## 4. What we will leave, and why

| Item | Why we leave it |
|---|---|
| Fixing `a-116` event date (line 2) | Day/month swap is only a guess. Record in `data_issues`, don't edit. |
| Line 59 missing date (a-104) | Cannot be recovered from the data. The order is still known from the chain. |
| a-201 true status | Not in the data. Show the conflict to the user. |
| s-207 who the card is about | Cannot tell typo from misfiled card. Keep on a-203, record in `data_issues`. |
| Activity note tasks (source D) | Free text; reading it is the LLM's job, not Python's. |
| Inferring role requirements from CVs and scorecards | Would be inventing data. |
| Merging same-name people (Maya Chen) | They are different people. |
| Fuzzy name matching for CVs and emails | None needed; would only create "ambiguous". |
| Name casing, phone and filename style (P18) | Cosmetic. |
| Deleting any record | Raw data is read-only and we keep source ids. |

---

## 5. Normalization rules

1. **Ids** are kept exactly as in the source (`c-…`, `a-…`, `s-…`, `j-…`). Each table keeps
   `source_file` and `source_id` (CSV: line number; activity: list index; email: file name).
2. **Dates** (changed in Phase 2, decisions 7–9) are stored as ISO 8601 **with the New York offset**
   (`YYYY-MM-DDTHH:MM:SS-04:00`). Stage events also keep the raw text (`changed_at_raw`) and the
   rule used (`date_parse_rule`). How each format is handled:

   | Raw format | Stored as |
   |---|---|
   | JSON `YYYY-MM-DDTHH:MM:SS` | ISO + offset |
   | CSV `YYYY-MM-DD HH:MM` (80 rows) | ISO + offset, rule `iso` |
   | CSV `DD/MM/YYYY HH:MM` 24-hour (3 rows) | ISO + offset, rule `ddmm_24h` (inferred, P07) |
   | CSV `MM/DD/YYYY H:MM AM/PM` (5 rows) | ISO + offset, rule `mmdd_ampm` (inferred, P07) |
   | `YYYY-MM-DD` (date only) | plain date, no offset, no time invented |
   | Email `Date:` header (−0400) | converted to New York time, ISO + offset |
   | empty (CSV line 59, 5 scorecards' `submitted_at`) | `NULL` |
   | anything else | the build stops with an error; nothing is guessed |

   Never use today's date; use REFERENCE_DATE. **Overdue** = `due_date < REFERENCE_DATE`; due on
   that day = "due today". Dates are compared in Python, never as text in SQL.
3. **Stage names**: `Phone Screen → Recruiter Call`. Other stage names are used as in
   `jobs.json`. Order of stages = order in the job's `stages[]`. Raw name is kept.
4. **Status**: `active | rejected | withdrawn | hired` as in the source. Withdrawn ≠ rejected.
   An application is "open" only if `active`.
5. **Emails (addresses)**: lowercase, strip `+tag`, for matching only. Keep the original.
6. **Phones**: digits only, for matching only.
7. **Names**: lowercase letters only, for matching only. Never link by name alone when two
   candidates share it.
8. **Email counterparty**: sender is company staff if the domain is `quillfeather.example.com`.
   Then the candidate is the recipient. Otherwise it is the sender.
9. **Link order**: CV: attachment reference, then exact name. Email: exact address, then
   normalized address, then address in the candidate's CV, then exact name. Fuzzy matches are
   `ambiguous` and never `linked`. Every link stores `method` and `confidence`.
10. **Scorecards**: empty text and `submitted_at` = `NULL` → "no feedback yet". Score =
    `Label: n/d`; store `n`, `d`, and `n/d`. No score → no row.
11. **Threads**: group by `In-Reply-To`; the thread root is the first message.
12. **Issues** (never silent fixes): every changed or doubtful value gets a row in `data_issues`
    with the problem id (P01 …), the source, and how it was handled. There are no `flags`
    columns on other tables. Original source values are kept in `*_source` / `*_raw` columns.

---

## 6. Proposed SQLite schema

Plain SQL, for review in Phase 2. `src_*` columns keep the source reference.

> **Status: implemented in `backend/db/schema.sql` (Phase 2).** The SQL below is the Phase 1
> proposal and is kept for history. Where they differ, `schema.sql` is right. Differences:
> - `src_file` / `src_id` / `src_row` / `src_index` are called `source_file` / `source_id` on every table.
> - New table `tasks` (decision 6) and new table `build_meta` (reference date, thresholds, raw checksum).
> - `cvs`: added `person_id`, `format`, `extract_status`, `extract_error`; `link_status` also allows `corrected`.
> - `emails`: added `sent_at_raw`, `counterparty_address`, `counterparty_name`, `candidate_options`.
> - `candidate_contacts.source` allows `email_exact_name`; `UNIQUE (candidate_id, kind, value)`.
> - `data_issues`: `description` is split into `issue_type`, `related_source_id`, `value_source`,
>   `value_used`, `reason`.
> - `scorecards`, `emails`, `cvs`, `tasks` have `CHECK` constraints that make an impossible state
>   (a fuzzy "linked" email, a submitted card without text, a closed task without `closed_by`) fail.

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY, title TEXT, department TEXT, opened_at TEXT, status TEXT
);
CREATE TABLE job_stages (
  job_id TEXT REFERENCES jobs(id), position INTEGER, stage TEXT,
  PRIMARY KEY (job_id, position)
);
CREATE TABLE stage_aliases (alias TEXT PRIMARY KEY, stage TEXT);   -- 'Phone Screen' -> 'Recruiter Call'

CREATE TABLE persons (id TEXT PRIMARY KEY, display_name TEXT);       -- one row per real person
CREATE TABLE candidates (
  id TEXT PRIMARY KEY, person_id TEXT REFERENCES persons(id),
  name TEXT, location TEXT, created_at TEXT,
  person_link_method TEXT, person_link_confidence TEXT,
  src_file TEXT, src_id TEXT
);
CREATE TABLE candidate_contacts (                                    -- emails and phones
  candidate_id TEXT REFERENCES candidates(id), kind TEXT,            -- 'email' | 'phone'
  value TEXT, value_norm TEXT, source TEXT                           -- 'candidates.json' | 'cv_text' | 'email_header'
);

CREATE TABLE applications (
  id TEXT PRIMARY KEY, candidate_id TEXT REFERENCES candidates(id),
  job_id_source TEXT, job_id_effective TEXT REFERENCES jobs(id), job_title_source TEXT,
  applied_at TEXT, status TEXT, current_stage_source TEXT, current_stage_from_events TEXT,
  rejected_at TEXT, rejection_reason TEXT, source_channel TEXT, offer_deadline TEXT,
  src_file TEXT, src_id TEXT
);
CREATE TABLE stage_events (
  id INTEGER PRIMARY KEY, application_id TEXT REFERENCES applications(id),
  from_stage_raw TEXT, to_stage_raw TEXT, from_stage TEXT, to_stage TEXT,
  changed_at TEXT, changed_at_raw TEXT, date_parse_rule TEXT,        -- 'iso' | 'ddmm_24h' | 'mmdd_ampm' | NULL
  changed_by TEXT, src_file TEXT, src_row INTEGER
);

CREATE TABLE scorecards (
  id TEXT PRIMARY KEY, application_id TEXT REFERENCES applications(id),
  interview TEXT, interview_key TEXT, interviewer TEXT,
  interview_at TEXT, submitted_at TEXT, text TEXT,
  feedback_status TEXT,                                              -- 'submitted' | 'no_feedback_yet'
  src_file TEXT, src_id TEXT
);
CREATE TABLE scorecard_scores (
  scorecard_id TEXT REFERENCES scorecards(id), label TEXT,
  value REAL, scale INTEGER, normalized REAL                         -- value/scale, 0..1
);

CREATE TABLE activity_notes (
  id INTEGER PRIMARY KEY, candidate_id TEXT REFERENCES candidates(id),
  person_id TEXT REFERENCES persons(id), author TEXT, created_at TEXT, body TEXT,
  src_file TEXT, src_index INTEGER
);

CREATE TABLE cvs (
  filename TEXT PRIMARY KEY, text TEXT, format TEXT,
  candidate_id TEXT REFERENCES candidates(id),
  link_method TEXT, link_confidence TEXT, link_status TEXT,          -- linked|conflict|ambiguous|shared
  source_candidate_id TEXT                                           -- who candidates.json says (for conflicts)
);

CREATE TABLE emails (
  file TEXT PRIMARY KEY, message_id TEXT, in_reply_to TEXT, thread_id TEXT,
  sent_at TEXT, direction TEXT,                                      -- 'outbound' | 'inbound'
  sender TEXT, recipient TEXT, subject TEXT, body TEXT,
  candidate_id TEXT, person_id TEXT,
  link_method TEXT, link_confidence TEXT, link_status TEXT          -- linked|ambiguous|unlinked
);

CREATE TABLE data_issues (                                           -- the ONLY place issues are recorded
  id INTEGER PRIMARY KEY, problem_id TEXT, severity TEXT,            -- 'P01'.., 'High'|'Medium'|'Low'
  src_file TEXT, src_id TEXT, description TEXT, handling TEXT        -- 'normalized'|'recorded'|'left'
);

-- (Phase 1 proposal said: no tasks table. Changed in Phase 2, decision 6: the `tasks` table exists,
-- stores open and closed items with due_date + status, and never stores "overdue".
-- Stalled applications (class E) are still computed in backend/services/ at query time.)
```

---

## 7. Known limitations

- **L1.** No role requirements (P02): Q1 answers must say they come from scorecards, stages and
  CV text, not from a requirement list.
- **L2.** "Overdue" for scorecards (2 days) and unanswered emails (3 days) uses thresholds the
  author chose; the data has no due dates for them. Only offer deadlines are explicit. Stalled
  applications have no threshold. Change the values in `backend/config.py`.
- **L3.** The slash-date rule (P07) is inferred from 8 rows. If it is wrong for a row, that
  application's stage durations are wrong. The rule is stored per row.
- **L4.** Small samples: stage-dwell medians use 1–4 cases for later stages. Do not present them
  as precise.
- **L5.** The email-vs-status check uses simple keywords and can miss contradictions. Emails
  were not read one by one; only the latest ~35 were read for Q3 context.
- **L6.** Scores are read from text with a regex (`Label: n/d`). A card that phrases a score
  differently would be missed; the script found a score in all 75 cards with text, but the regex
  was not checked against every card by eye.
- **L7.** The audit does not judge CV or scorecard content quality, only structure and links.
- **L8.** After the chain rule (P05), one `current_stage` conflict is stored (a-114, where `applications.json` is
  stale) and one chain resolution (a-116). a-302 and a-304 only use the `Phone Screen` alias. All other applications
  agree with `applications.json`. The chain rule assumes each application moves along one straight line; a loop or
  branch would fall back to date order and be flagged.
- **L9.** Fictional dataset: the checks fit this export; other exports need the scripts re-run.

## 8. Assumptions (not in the data)

These values are **our choices**. The raw data has no due date for the first two, and no weights for the last two. Every
"overdue" answer that depends on them must say so.

| Name | Value | Used for | Why this value | If it is wrong |
|---|---|---|---|---|
| `SCORECARD_OVERDUE_DAYS` | 2 | `scorecard_pending` task: due date = interview date + 2 days | Submitted scorecards took a median of 2.5 h and at most 31.5 h (n=75), so 2 days is generous | s-131 (due 2026-10-08) and s-211 may be "pending" instead of overdue with a larger value |
| `EMAIL_UNANSWERED_DAYS` | 3 | `email_unanswered` task: due date = date received + 3 days | Staff replies took a median of 4.3 h, p90 167 h (n=77) | Fewer or more unanswered emails |

| `RANK_WEIGHT_FEEDBACK` | 0.70 | Ranking: share of the score from interview scorecards | Scorecards are the only direct quality signal in the data | A different top 3 is possible; the tool returns each part of the score |
| `RANK_WEIGHT_PROGRESS` | 0.30 | Ranking: share of the score from how far the candidate got in the stages | Progress also reflects process speed, so it is a weaker signal | Same as above |

- **Single source.** All four values live **only** in `backend/config.py`. Code, tests and audit scripts
  import them. Nothing else may hard-code them.
- **Stored with the task.** `tasks.due_basis` says which rule set each due date: an explicit date
  from the data (`applications.offer_deadline`), one of the two assumptions above, or `none` (no due
  date). `build_meta` also records the values used for each build.
- **Not an assumption:** the offer deadline is explicit data. The overdue rule itself
  (`due_date < REFERENCE_DATE`, decision 9) is a design decision, not a threshold.

## 9. Limitations added in Phase 3

- **L10.** `jobs.json` has no role requirements (P02). Ranking uses interview feedback and stage
  progress only. It does **not** measure fit to the role. Say this in every ranking answer.
- **L11.** A candidate with no submitted scorecard is "not scored" (no feedback yet). That is not a
  negative result. The `not_scored` list is separate from the ranked list.
- **L12.** One scorecard is "thin" evidence. Scores come from 1-4 interviews per candidate.

## 10. Manual review decisions

- **s-103 (Phase 4 review, author).** Scorecard s-103 (Recruiter Call, 2026-08-07, attached to a-105) mentions "the CSM
  process". The person also has a CSM application (a-399, rejected 2026-07-29). Checked against dates and stages: the
  interview date is inside a-105's Recruiter Call window (08-05 to 08-10), and a-399 already has its own cards (s-108,
  s-109). Decision: **keep it on a-105 and flag only**. A `data_issues` row (`scorecard_mentions_other_application`,
  **Low**, handling `recorded`, no P-number) records it; it appears in `get_data_issues` for s-103, a-105 and a-399.
  It does not change any score: a-105 scores 100.0 with or without it. Source: `loader`, `REVIEWED_SCORECARD_FLAGS`.
- **a-116 stage (Phase 5 review, author).** Use the chain rule described under P05 (`stage_resolved_by_chain` row).
  This amends the earlier decision "count a-114 and a-116 at the stage from sorted events": a-114 is unchanged; a-116 is
  now counted at Take-Home. j-backend funnel after the change: Technical Screen moved on 11, rejected 2; Take-Home
  entered 11, rejected 1, withdrew 4, still in stage 2. Source: `backend/ingest/load_core.py` (`_chain_end`).
- **a-201 status (Phase 6 review, author).** P10 says a-201 (Rafael Mendoza, c-201, Product Designer) is `rejected` at Offer
  on 2026-10-09 with no reason and an offer deadline of 2026-10-20. The emails add evidence: `20261006-1530-m-2007.eml`
  (staff, offer sent), `20261007-0940-m-2008.eml` (Rafael: "Thank you, this is wonderful news", asks only about the start
  date) and `20261007-1115-m-2009.eml` (Priya: "Three weeks' notice is completely fine ... Just let me know with your
  decision"). Rafael never declines, and both sides were waiting for his decision. No email after 2026-10-07 explains the
  rejection. Reading: the `rejected` status is **likely a data error**, and the offer deadline (2026-10-20) has **not passed**
  (5 days after the reference date). Recommended action for the recruiter: contact Rafael before 2026-10-20 to confirm.
  Decision: **no change to the stored status** (the data cannot prove it; the author's reading is a judgement). No new
  `data_issues` row: P10 already covers it. `get_candidate_profile` now returns the email text so the agent can weigh it.
