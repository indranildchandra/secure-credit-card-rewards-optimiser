"""Offline wiring tests for the optimiser agent (no model call)."""

import optimizer
from optimizer.agent import web_search_tool


def test_optimizer_tool_count():
    # 5 card tools + 5 spend/cap/recall tools + 1 web-search tool.
    assert len(optimizer.root_agent.tools) == 11


def test_web_search_tool_is_ddg_on_ollama():
    # Default config is ollama -> the DuckDuckGo function tool (not google_search).
    assert getattr(web_search_tool, "__name__", "") == "ddg_search"


def test_recall_tool_is_wired():
    names = {getattr(t, "__name__", "") for t in optimizer.root_agent.tools}
    assert "get_spend_history" in names
