"""Offline tests for the tool-call loop-breaker (optimizer/loop_guard.py).

Builds real ADK LlmRequest objects with scripted function-call history and
asserts the callback (a) leaves a healthy single-call turn untouched and (b)
strips the tools + nudges a final answer once the model repeats a tool call.
No model / network involved.
"""

from google.adk.models import LlmRequest
from google.genai import types

from optimizer.loop_guard import break_tool_call_loops, _identical_call_counts


def _call(name, **args):
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
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


def test_identical_call_counts_distinguishes_args():
    counts = _identical_call_counts(
        [
            _call("get_card_details", card_name="HDFC"),
            _call("get_card_details", card_name="HDFC"),  # identical
            _call("get_card_details", card_name="Amex"),  # different args
        ]
    )
    assert max(counts.values()) == 2  # the two identical HDFC calls
    assert len(counts) == 2  # HDFC and Amex are distinct keys


def test_single_tool_call_is_left_alone():
    # The healthy path: one routing call + its result -> guard must NOT fire.
    req = _request(
        [_call("find_cards_for_category"), _result("find_cards_for_category")]
    )
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools and len(req.config.tools) == 1  # tools still offered
    assert "do not repeat a tool call" not in _last_text(req).lower()


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


def test_same_tool_different_args_is_allowed():
    # Legit multi-call: comparing two cards -> get_card_details twice with
    # DIFFERENT args must NOT be treated as a loop.
    req = _request(
        [
            _call("get_card_details", card_name="HDFC Regalia Gold"),
            _result("get_card_details"),
            _call("get_card_details", card_name="Amex Platinum Travel"),
            _result("get_card_details"),
        ]
    )
    assert break_tool_call_loops(None, req) is None
    assert len(req.config.tools) == 1  # tools still offered — not clipped


def test_identical_repeat_breaks_the_loop():
    # The bug: find_cards_for_category re-issued with the SAME args -> loop.
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Amazon", amount=4000
            ),
            _result("find_cards_for_category"),
            _call(
                "find_cards_for_category", merchant_or_category="Amazon", amount=4000
            ),
        ]
    )
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools == []  # tools stripped -> model must answer as text
    assert "do not repeat a tool call" in _last_text(req).lower()


def test_total_budget_backstop_breaks_runaway():
    # A pathological loop that varies its args still can't run forever.
    contents = []
    for i in range(10):
        contents += [_call(f"tool_{i}"), _result(f"tool_{i}")]
    req = _request(contents)
    assert break_tool_call_loops(None, req) is None
    assert req.config.tools == []
