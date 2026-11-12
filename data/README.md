# Data

The dataset is not part of this repository.

Put the dataset bundle in `data/raw/`, then run:

```bash
.venv/bin/python scripts/build_db.py
```

This builds `data/hirepilot.db` (SQLite) from the files in `data/raw/`. Both `data/raw/` and the database are ignored by git.

`data/raw/` is read-only input: no step of this project modifies it. The tests, the web app and the evals need the database, so
they need the bundle in `data/raw/` too.

Expected files in `data/raw/`: `jobs.json`, `candidates.json`, `applications.json`, `scorecards.json`, `activity.json`,
`stage_events.csv`, and the folders `emails/` (`.eml` files) and `cvs/` (CV files).
