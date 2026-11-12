"""HirePilot MCP server: a thin wrapper. All logic is in backend/services/.

Run (stdio):   .venv/bin/python -I backend/mcp_server.py
stdout is the MCP protocol channel: nothing may print there. Logs go to stderr (counts only).
Every tool returns {"ok": true, "as_of", "data", "notes"} or {"ok": false, "error": {...}}.
"""
import sys
from pathlib import Path

if __package__ in (None, ""):                          # -I removes the project folder from sys.path; add it back
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from backend import config  # noqa: E402
from backend.services import candidates, funnel, issues, jobs, ranking, tasks  # noqa: E402
from backend.services.common import log  # noqa: E402

server = MCPServer(
    "hirepilot",
    instructions=("Recruiting data for Quillfeather Labs, as of the export date 2026-10-15 (not today). "
                  "Every result has ok=true with data, or ok=false with an error that lists valid values. "
                  "Numbers are computed in Python; explain them, do not recompute them. "
                  "'No feedback yet' on a scorecard is not negative feedback."))


def _tool(description=None):
    """Register a tool. The description is the docstring with the indentation removed (or an explicit text)."""
    def register(fn):
        return server.tool(description=description or " ".join(fn.__doc__.split()))(fn)
    return register


def _log(tool, result):
    data = result.get("data") or {}
    size = next((len(v) for v in data.values() if isinstance(v, list)), 0) if isinstance(data, dict) else len(data)
    log.info("tool=%s ok=%s items=%s", tool, result["ok"], size)      # counts only, no candidate records
    return result


@_tool()
def list_jobs() -> dict:
    """List all jobs: id, title, department, status, open date, and how long each has been open
    (days_open and months_open, counted to the export date 2026-10-15), plus application counts by status.
    Start here to find job ids (j-backend, j-csm, j-designer)."""
    return _log("list_jobs", jobs.list_jobs())


@_tool()
def get_job(job_id: str) -> dict:
    """Get one job: its stages in hiring order and the stage-name aliases. The source data has NO role
    requirements, so 'requirements' is null; never invent any. job_id example: 'j-backend'."""
    return _log("get_job", jobs.get_job(job_id))


@_tool()
def list_candidates_for_job(job_id: str, status: str | None = None) -> dict:
    """List the applications for a job with candidate id, name, current stage and status.
    Optional status filter: 'active', 'rejected', 'withdrawn' or 'hired'. Notes list any stage conflicts
    between applications.json and the stage events."""
    return _log("list_candidates_for_job", jobs.list_candidates_for_job(job_id, status))


@_tool()
def get_candidate_profile(candidate_id: str) -> dict:
    """Everything known about one candidate (id like 'c-101'): contacts, applications, stage events,
    scorecards (each 'submitted' or 'no_feedback_yet'; no feedback is NOT negative), notes, a CV excerpt,
    linked emails with link method and confidence, and data issues. Every record has source_file and source_id."""
    return _log("get_candidate_profile", candidates.get_candidate_profile(candidate_id))


_RANK_DESCRIPTION = (
    "Rank candidates for a job with a fixed formula computed in Python: score = 100 * "
    f"({config.RANK_WEIGHT_FEEDBACK:.2f} * interview feedback + {config.RANK_WEIGHT_PROGRESS:.2f} * stage progress). "
    "Returns two separate lists: 'ranked' (has submitted feedback; shows score, each part of the score, the evidence and "
    "the candidate's open tasks) and 'not_scored' (no feedback yet; NOT a low score). By default only active applications "
    "are ranked; include_statuses can add 'rejected', 'withdrawn', 'hired'. The ranking measures interview feedback and "
    "progress only, NOT fit to the role, because the data has no role requirements.")


@_tool(_RANK_DESCRIPTION)
def rank_candidates_for_job(job_id: str, top_n: int = 3, include_statuses: list[str] | None = None) -> dict:
    return _log("rank_candidates_for_job", ranking.rank_candidates_for_job(job_id, top_n, include_statuses))


@_tool()
def get_funnel(job_id: str) -> dict:
    """Hiring funnel for a job, per stage in order: entered, moved on, rejected, withdrew, hired, still in
    stage, conversion rates, rejection reasons and median days in stage. 'notes' lists data conflicts
    (for example a-114 and a-116) instead of hiding them. Use it to see where candidates are lost."""
    return _log("get_funnel", funnel.get_funnel(job_id))


_TASKS_DESCRIPTION = (
    "List tasks (offer deadlines, scorecards not submitted, candidate emails with no reply, new applications not reviewed). "
    "state: 'overdue', 'due_today', 'pending' (future or no due date) or 'all' (all open tasks). Dates are judged against "
    "the export date 2026-10-15. Each task says which rule sets its due date: 'data' (explicit), 'assumption' (our "
    f"{config.SCORECARD_OVERDUE_DAYS}-day scorecard / {config.EMAIL_UNANSWERED_DAYS}-day email rule) or 'none'. "
    "A task with no due date is 'pending_no_due_date' and is never overdue. Optional job_id filter.")


@_tool(_TASKS_DESCRIPTION)
def list_tasks(state: str = "all", job_id: str | None = None, include_closed: bool = False) -> dict:
    return _log("list_tasks", tasks.list_tasks(state, job_id, include_closed))


@_tool()
def get_data_issues(entity_id: str | None = None) -> dict:
    """List data problems found when loading the export (conflicts, inferred dates, merged duplicate people).
    Optional entity_id: a job (j-...), candidate (c-...), person (p-...), application (a-...), scorecard (s-...)
    or email file name. Without it, returns all issues."""
    return _log("get_data_issues", issues.get_data_issues(entity_id))


if __name__ == "__main__":
    server.run("stdio")
