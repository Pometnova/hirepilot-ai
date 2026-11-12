-- HirePilot AI schema (Phase 2). Built by scripts/build_db.py from data/raw/.
-- Every table keeps source_file + source_id (where the row came from).
-- Missing values are NULL, never '' and never a guess.
-- Times: ISO 8601 with the New York offset (e.g. 2026-10-07T10:15:00-04:00).
-- Date-only fields stay plain dates (YYYY-MM-DD). Dates are compared in Python, not as text in SQL.

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  department TEXT,
  opened_at TEXT,                       -- plain date
  status TEXT,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE job_stages (
  job_id TEXT NOT NULL REFERENCES jobs(id),
  position INTEGER NOT NULL,
  stage TEXT NOT NULL,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  PRIMARY KEY (job_id, position),
  UNIQUE (job_id, stage)
);

CREATE TABLE stage_aliases (            -- 'Phone Screen' -> 'Recruiter Call'
  alias TEXT PRIMARY KEY,
  stage TEXT NOT NULL,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE persons (                  -- one row per real person
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE candidates (               -- one row per candidate id in the source (both duplicates kept)
  id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL REFERENCES persons(id),
  name TEXT NOT NULL,
  location TEXT,
  created_at TEXT,                      -- plain date
  person_link_method TEXT NOT NULL,
  person_link_confidence TEXT CHECK (person_link_confidence IN ('high','medium','low')),
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE candidate_contacts (       -- emails and phones
  id INTEGER PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  kind TEXT NOT NULL CHECK (kind IN ('email','phone')),
  value TEXT NOT NULL,
  value_norm TEXT NOT NULL,             -- for matching only
  source TEXT NOT NULL CHECK (source IN ('candidates.json','cv_text','email_exact_name')),
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  UNIQUE (candidate_id, kind, value)
);

CREATE TABLE applications (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  job_id_source TEXT NOT NULL,          -- as in applications.json
  job_id_effective TEXT NOT NULL REFERENCES jobs(id),
  job_title_source TEXT,
  applied_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','rejected','withdrawn','hired')),
  current_stage_source TEXT,            -- as in applications.json
  current_stage_from_events TEXT,       -- last stage after sorting events; NULL if no events
  rejected_at TEXT,                     -- for 'withdrawn' this is the withdrawal date (audit P16)
  rejection_reason TEXT,
  source_channel TEXT,
  offer_deadline TEXT,                  -- plain date
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE stage_events (
  id INTEGER PRIMARY KEY,               -- CSV line number (line 1 = header)
  application_id TEXT NOT NULL REFERENCES applications(id),
  from_stage_raw TEXT,
  to_stage_raw TEXT NOT NULL,
  from_stage TEXT,                      -- after alias mapping
  to_stage TEXT NOT NULL,
  changed_at TEXT,                      -- NULL when the source has no date
  changed_at_raw TEXT,
  date_parse_rule TEXT CHECK (date_parse_rule IN ('iso','ddmm_24h','mmdd_ampm')),
  changed_by TEXT,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (changed_at IS NULL OR date_parse_rule IS NOT NULL)
);

CREATE TABLE scorecards (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id),
  interview TEXT,
  interview_key TEXT NOT NULL,          -- application_id|interview (groups several interviewers)
  interviewer TEXT,
  interview_at TEXT,
  submitted_at TEXT,
  text TEXT,
  feedback_status TEXT NOT NULL CHECK (feedback_status IN ('submitted','no_feedback_yet')),
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (
    (feedback_status = 'no_feedback_yet' AND text IS NULL AND submitted_at IS NULL) OR
    (feedback_status = 'submitted' AND text IS NOT NULL AND submitted_at IS NOT NULL)
  )
);

CREATE TABLE scorecard_scores (         -- one row per 'Label: n/d' found in the text
  id INTEGER PRIMARY KEY,
  scorecard_id TEXT NOT NULL REFERENCES scorecards(id),
  label TEXT NOT NULL,
  value REAL NOT NULL,
  scale INTEGER NOT NULL CHECK (scale > 0),
  normalized REAL NOT NULL CHECK (normalized >= 0 AND normalized <= 1),   -- value / scale
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (value >= 0 AND value <= scale)
);

CREATE TABLE activity_notes (
  id INTEGER PRIMARY KEY,               -- zero-based list index in activity.json
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  person_id TEXT NOT NULL REFERENCES persons(id),
  author TEXT,
  created_at TEXT,
  body TEXT,
  source_file TEXT NOT NULL, source_id TEXT NOT NULL
);

CREATE TABLE cvs (
  filename TEXT PRIMARY KEY,
  format TEXT NOT NULL CHECK (format IN ('pdf','docx','txt')),
  text TEXT,
  extract_status TEXT NOT NULL CHECK (extract_status IN ('ok','empty','failed')),
  extract_error TEXT,
  candidate_id TEXT REFERENCES candidates(id),   -- NULL for 'shared' and unresolved CVs
  person_id TEXT REFERENCES persons(id),
  link_method TEXT,
  link_confidence TEXT CHECK (link_confidence IN ('high','medium','low')),
  link_status TEXT NOT NULL CHECK (link_status IN ('linked','corrected','shared','ambiguous','unlinked')),
  source_candidate_id TEXT,             -- what candidates.json says (for corrected / shared CVs)
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (link_status NOT IN ('linked','corrected') OR candidate_id IS NOT NULL),
  CHECK (NOT (link_status IN ('linked','corrected') AND link_method LIKE '%fuzzy%'))
);

CREATE TABLE emails (
  file TEXT PRIMARY KEY,
  message_id TEXT NOT NULL UNIQUE,
  in_reply_to TEXT,                     -- may point to a message that is not in the mailbox
  thread_id TEXT NOT NULL,              -- message_id of the thread root
  sent_at TEXT NOT NULL,
  sent_at_raw TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('outbound','inbound')),
  sender TEXT,
  recipient TEXT,
  counterparty_address TEXT,            -- the non-staff side: recipient if staff sent, else sender
  counterparty_name TEXT,
  subject TEXT,
  body TEXT,
  candidate_id TEXT REFERENCES candidates(id),
  person_id TEXT REFERENCES persons(id),
  candidate_options TEXT,               -- candidate ids when link_status = 'ambiguous'
  link_method TEXT CHECK (link_method IN ('exact_email','normalized_email','cv_email','exact_name','fuzzy_name')),
  link_confidence TEXT CHECK (link_confidence IN ('high','medium','low')),
  link_status TEXT NOT NULL CHECK (link_status IN ('linked','ambiguous','unlinked')),
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (NOT (link_status = 'linked' AND link_method = 'fuzzy_name')),
  CHECK ((link_status = 'linked' AND candidate_id IS NOT NULL) OR (link_status <> 'linked' AND candidate_id IS NULL))
);

CREATE TABLE tasks (                    -- stores every item, open and closed. NO 'overdue' column.
  id TEXT PRIMARY KEY,                  -- task_type:source_id
  task_type TEXT NOT NULL CHECK (task_type IN
    ('offer_deadline','scorecard_pending','email_unanswered','application_unreviewed')),
  application_id TEXT REFERENCES applications(id),
  candidate_id TEXT REFERENCES candidates(id),
  person_id TEXT REFERENCES persons(id),
  due_date TEXT,                        -- plain date, NULL when the source has no due date
  due_basis TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open','done','closed')),
  closed_at TEXT,                       -- NULL when the data does not say
  closed_by TEXT,                       -- '<file>#<id>' of the record that closed it
  close_method TEXT CHECK (close_method IN ('status_field','same_thread')),
  close_confidence TEXT CHECK (close_confidence IN ('high','medium','low')),
  source_file TEXT NOT NULL, source_id TEXT NOT NULL,
  CHECK (
    (status = 'open' AND closed_at IS NULL AND closed_by IS NULL AND close_method IS NULL AND close_confidence IS NULL) OR
    (status <> 'open' AND closed_by IS NOT NULL AND close_method IS NOT NULL AND close_confidence IS NOT NULL)
  )
);

CREATE TABLE data_issues (              -- the ONLY place problems are recorded
  id INTEGER PRIMARY KEY,
  problem_id TEXT,                      -- 'P01'.. from DATA_AUDIT.md, NULL for new findings
  issue_type TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('High','Medium','Low')),
  source_file TEXT,
  source_id TEXT,
  related_source_id TEXT,
  value_source TEXT,                    -- the value in the raw data
  value_used TEXT,                      -- the value we stored / used
  reason TEXT NOT NULL,
  handling TEXT NOT NULL CHECK (handling IN ('normalized','recorded','left'))
);

CREATE TABLE build_meta (               -- no source columns: describes the build itself
  key TEXT PRIMARY KEY,
  value TEXT
);
