"""Offline wiring tests for the optimiser agent (no model call)."""

import optimizer
from optimizer.agent import web_search_tool


def test_optimizer_tool_count():
    # 6 card tools (find/compare/details/list/reward/net_cost) + 6 spend/cap/ROI/
    # recall tools + 1 web-search tool.
    assert len(optimizer.root_agent.tools) == 13


def test_new_tools_wired():
    names = {getattr(t, "__name__", "") for t in optimizer.root_agent.tools}
    assert {"estimate_net_cost", "assess_card_value"} <= names


def test_web_search_tool_is_ddg_on_ollama():
    # Default config is ollama -> the DuckDuckGo function tool (not google_search).
    assert getattr(web_search_tool, "__name__", "") == "ddg_search"


def test_recall_tool_is_wired():
    names = {getattr(t, "__name__", "") for t in optimizer.root_agent.tools}
    assert "get_spend_history" in names
