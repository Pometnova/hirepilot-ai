"""Phase 3: start backend/mcp_server.py as a subprocess over stdio and talk to it with the MCP client."""
import asyncio
import json
import subprocess
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend import config

EXPECTED_TOOLS = {"list_jobs", "get_job", "list_candidates_for_job", "get_candidate_profile",
                  "rank_candidates_for_job", "get_funnel", "list_tasks", "get_data_issues"}
SERVER = str(config.ROOT / "backend" / "mcp_server.py")


def run_session(fn):
    async def main():
        params = StdioServerParameters(command=sys.executable, args=["-I", SERVER], cwd=str(config.ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)
    return asyncio.run(main())


def call(session, name, args):
    async def go():
        res = await session.call_tool(name, args)
        return res, json.loads(res.content[0].text)
    return go()


def test_list_tools_returns_all_eight_with_descriptions_and_schemas():
    async def fn(s):
        return (await s.list_tools()).tools
    tools = run_session(fn)
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.description and len(t.description) > 40, t.name
        assert t.input_schema["type"] == "object"
    schema = next(t for t in tools if t.name == "get_funnel").input_schema
    assert schema["required"] == ["job_id"]


def test_call_list_tasks_overdue():
    async def fn(s):
        return await call(s, "list_tasks", {"state": "overdue"})
    res, body = run_session(fn)
    assert not res.is_error and body["ok"] and body["as_of"] == "2026-10-15"
    ids = {t["task_id"] for t in body["data"]["tasks"]}
    assert {"scorecard_pending:s-131", "offer_deadline:a-105"} <= ids
    assert all(t["source_file"] and t["source_id"] for t in body["data"]["tasks"])


def test_call_get_funnel():
    async def fn(s):
        return await call(s, "get_funnel", {"job_id": "j-backend"})
    res, body = run_session(fn)
    assert not res.is_error and body["ok"]
    assert [x["stage"] for x in body["data"]["stages"]][0] == "Application Review"
    assert body["data"]["stages"][0]["entered"] == 20


def test_call_with_bad_id_returns_structured_error_not_a_crash():
    async def fn(s):
        first = await call(s, "get_funnel", {"job_id": "j-nope"})
        second = await call(s, "list_jobs", {})              # the server is still alive afterwards
        return first, second
    (res, body), (_, jobs_body) = run_session(fn)
    assert body["ok"] is False and body["error"]["code"] == "unknown_job_id" and "j-backend" in body["error"]["valid_values"]
    assert jobs_body["ok"] and len(jobs_body["data"]) == 3


def test_call_rank_returns_two_separate_lists():
    async def fn(s):
        return await call(s, "rank_candidates_for_job", {"job_id": "j-backend"})
    _, body = run_session(fn)
    assert body["ok"] and "ranked" in body["data"] and "not_scored" in body["data"]
    assert len(body["data"]["ranked"]) == 3


def test_server_writes_nothing_to_stdout_by_itself():
    """stdout is the protocol channel. With no client input the server must print nothing there."""
    p = subprocess.run([sys.executable, "-I", SERVER], input=b"", capture_output=True, cwd=config.ROOT, timeout=60)
    assert p.stdout == b""
