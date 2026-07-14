"""Offline tests for the tool-call loop-breaker (optimizer/loop_guard.py).

Builds real ADK LlmRequest objects with scripted function-call history and
asserts the callback (a) leaves a healthy single-call turn untouched and (b)
strips the tools + nudges a final answer once the model repeats a tool call.
No model / network involved.
"""

from google.adk.models import LlmRequest
from google.genai import types

from optimizer.loop_guard import break_tool_call_loops, _tool_call_counts


def _call(name):
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))],
    )


def _result(name):
    return types.Content(
        role="user",
        parts=[
            types.Part(function_response=types.FunctionResponse(name=name, response={}))
        ],
    )


def _request(contents):
    req = LlmRequest()
    req.config.tools = [types.Tool()]  # pretend the tools are offered
    req.contents = list(contents)
    return req


def _last_text(req):
    return " ".join(
        p.text or "" for p in (req.contents[-1].parts or []) if getattr(p, "text", None)
    )


def test_counts_helper():
    assert _tool_call_counts([_call("x"), _call("x"), _call("y")]) == {"x": 2, "y": 1}


def test_single_tool_call_is_left_alone():
    # The healthy path: one routing call + its result -> guard must NOT fire.
    req = _request(
        [_call("find_cards_for_category"), _result("find_cards_for_category")]
    )
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools and len(req.config.tools) == 1  # tools still offered
    assert "do not call any more tools" not in _last_text(req).lower()


def test_two_distinct_tools_is_left_alone():
    # find_cards + one web search = two DIFFERENT tools, each once -> fine.
    req = _request(
        [
            _call("find_cards_for_category"),
            _result("find_cards_for_category"),
            _call("ddg_search"),
            _result("ddg_search"),
        ]
    )
    assert break_tool_call_loops(None, req) is None
    assert len(req.config.tools) == 1


def test_repeated_same_tool_breaks_the_loop():
    # The bug: the model calls find_cards_for_category a second time -> loop.
    req = _request(
        [
            _call("find_cards_for_category"),
            _result("find_cards_for_category"),
            _call("find_cards_for_category"),  # repeat -> loop detected
        ]
    )
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools == []  # tools stripped -> model must answer as text
    assert "do not call any more tools" in _last_text(req).lower()


def test_total_budget_breaks_the_loop():
    # Five distinct tool calls in one turn (alternating loop) exceeds the budget.
    contents = []
    for name in ("a", "b", "c", "d", "e"):
        contents += [_call(name), _result(name)]
    req = _request(contents)
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools == []
