"""Shared test setup. The top bar of every page asks core.check_mcp() whether the MCP server starts. That check is free but
slow, so tests replace it with a fixed answer (one test in test_stage3.py calls the real function)."""
import pytest

from backend.agent import core


@pytest.fixture(autouse=True)
def fast_mcp_status(monkeypatch):
    from web import chat
    monkeypatch.setattr(core, "check_mcp", lambda: (True, 8))
    chat.mcp_status.clear()
    yield
    chat.mcp_status.clear()
