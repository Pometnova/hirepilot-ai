#!/bin/sh
# Re-run every Phase 1 audit script. Read-only on data/raw/.
# Usage (from the project root):  sh scripts/audit/run_all.sh
set -e
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
for s in 01_structure 02_dates 03_cvs 04_emails 05_tasks_and_funnel 06_email_vs_status 07_scorecard_scales 08_completeness; do
  echo
  echo "################ $s ################"
  $PY -I "scripts/audit/$s.py"
done
echo
echo "################ raw data checksum (should match the value in docs/DATA_AUDIT.md) ################"
find data/raw -type f -exec shasum -a 256 {} + | sort -k2 | shasum -a 256
