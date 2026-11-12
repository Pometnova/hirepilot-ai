"""Collects data_issues rows during the build; written to the database at the end."""
from .normalize import insert


class Issues:
    def __init__(self):
        self.rows = []

    def add(self, issue_type, severity, source_file, source_id, reason, handling,
            problem_id=None, related_source_id=None, value_source=None, value_used=None):
        self.rows.append(dict(
            problem_id=problem_id, issue_type=issue_type, severity=severity,
            source_file=source_file, source_id=source_id, related_source_id=related_source_id,
            value_source=value_source, value_used=value_used, reason=reason, handling=handling))

    def write(self, con):
        for row in self.rows:
            insert(con, "data_issues", row)
