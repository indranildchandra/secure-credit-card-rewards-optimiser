"""Offline wiring tests for the optimiser agent + spend sub-agent (no model call)."""

import optimizer
from optimizer.agent import web_search_tool
from optimizer.spend_agent import spend_agent


def _tool_names(agent):
    names = set()
    for t in agent.tools:
        names.add(getattr(t, "__name__", None) or getattr(t, "name", ""))
    return names


def test_root_is_thin_router():
    # 6 hot card/value tools + spend_manager sub-agent + web-search = 8.
    assert len(optimizer.root_agent.tools) == 8
    names = _tool_names(optimizer.root_agent)
    assert "estimate_net_cost" in names
    assert "spend_manager" in names  # the AgentTool wrapping the sub-agent
    # Spend tools live in the sub-agent now, not on the root.
    assert "get_spend_history" not in names
    assert "assess_card_value" not in names


def test_spend_subagent_owns_the_spend_tools():
    names = _tool_names(spend_agent)
    assert {
        "record_spend",
        "get_spend_summary",
        "get_spend_history",
        "check_cap_status",
        "check_fee_waiver_status",
        "assess_card_value",
    } <= names
    assert len(spend_agent.tools) == 6


def test_web_search_tool_is_ddg_on_ollama():
    # Default config is ollama -> the DuckDuckGo function tool (not google_search).
    assert getattr(web_search_tool, "__name__", "") == "ddg_search"
