"""Offline tests for the ground-and-guard callback (optimizer/loop_guard.py).

The guard lets the model make NEW tool calls (compound/comparison flows work),
grounds it in the real result once routing has answered, and strips the tools
only on an identical-call loop or a per-turn budget overrun. No model / network.
"""

from google.adk.models import LlmRequest
from google.genai import types

from optimizer.loop_guard import (
    ground_and_break_tool_loops,
    _identical_call_counts,
    _primary_card,
)


def _call(name, **args):
    return types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
    )


def _result(name, response=None):
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    name=name, response=response or {}
                )
            )
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


def test_primary_card_extracted_from_routing_result():
    results = [
        ("find_cards_for_category", {"matches": [{"primary": "Tata Neu Infinity"}]})
    ]
    assert _primary_card(results) == "Tata Neu Infinity"
    assert _primary_card([("ddg_search", {"text": "..."})]) is None


def test_identical_call_counts_distinguishes_args():
    counts = _identical_call_counts(
        [
            _call("get_card_details", card_name="HDFC"),
            _call("get_card_details", card_name="HDFC"),  # identical
            _call("get_card_details", card_name="Amex"),  # different args
        ]
    )
    assert max(counts.values()) == 2
    assert len(counts) == 2


def test_no_tool_result_yet_is_a_noop():
    req = _request([types.Content(role="user", parts=[types.Part(text="which card?")])])
    n_before = len(req.contents)
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.contents) == n_before  # no note
    assert len(req.config.tools) == 1  # tools still offered


def test_spend_manager_alone_does_not_ground_or_strip():
    # Compound query: spend recorded first, routing not done yet -> let it proceed.
    req = _request(
        [
            _call("spend_manager", request="record Rs.9000 dining on HSBC Live+"),
            _result("spend_manager", {"result": "recorded"}),
        ]
    )
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.config.tools) == 1  # still available -> can now route
    assert _last_text(req) == ""  # no note appended yet


def test_after_routing_grounds_but_keeps_tools():
    # Routing done, no loop: hand over the winner but KEEP tools so the model may
    # still make a genuinely different call (per the "allow new tool calls" rule).
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Croma", amount=60000
            ),
            _result(
                "find_cards_for_category",
                {"matches": [{"primary": "Tata Neu Infinity"}]},
            ),
        ]
    )
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.config.tools) == 1  # NOT stripped -> new tool calls allowed
    text = _last_text(req)
    assert "THE WINNER IS" in text and "Tata Neu Infinity" in text
    assert req.config.max_output_tokens  # budget reserved


def test_compound_grounds_after_routing_with_the_swiggy_winner():
    req = _request(
        [
            _call("spend_manager", request="record"),
            _result("spend_manager", {"result": "recorded"}),
            _call("find_cards_for_category", merchant_or_category="Swiggy", amount=800),
            _result(
                "find_cards_for_category",
                {"matches": [{"primary": "HSBC Live+", "fallback": "Axis Rewards"}]},
            ),
        ]
    )
    ground_and_break_tool_loops(None, req)
    text = _last_text(req)
    assert "HSBC Live+" in text  # routed the Swiggy step, winner grounded
    assert len(req.config.tools) == 1  # still allowed a different call


def test_identical_repeat_strips_tools():
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Amazon", amount=4000
            ),
            _result(
                "find_cards_for_category",
                {"matches": [{"primary": "ICICI AmazonPay"}]},
            ),
            _call(
                "find_cards_for_category", merchant_or_category="Amazon", amount=4000
            ),
        ]
    )
    ground_and_break_tool_loops(None, req)
    assert req.config.tools == []  # loop -> tools stripped, must answer as text
    assert "stop" in _last_text(req).lower()


def test_web_search_result_caps_at_one_and_forces():
    # ddg_search loop: the model re-searches with a varied query (evading the
    # identical-call check). One search is enough -> force the answer after it.
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Croma", amount=200000
            ),
            _result(
                "find_cards_for_category",
                {"matches": [{"primary": "Tata Neu Infinity"}]},
            ),
            _call("ddg_search", query="MacBook Croma offer 2026"),
            _result("ddg_search", {"text": "some offers"}),
        ]
    )
    ground_and_break_tool_loops(None, req)
    assert req.config.tools == []  # search done -> tools stripped, must answer now
    assert "stop" in _last_text(req).lower()


def test_runaway_backstop_strips_tools():
    contents = []
    for i in range(6):  # 6 distinct calls -> hits _MAX_TOOL_CALLS_PER_TURN
        contents += [_call(f"tool_{i}"), _result(f"tool_{i}", {"n": i})]
    req = _request(contents)
    ground_and_break_tool_loops(None, req)
    assert req.config.tools == []


def test_disambiguation_result_asks_which_card():
    req = _request(
        [
            _call("find_matching_cards", card_name="axis"),
            _result(
                "find_matching_cards",
                {"ambiguous": True, "matches": ["Axis Rewards", "Axis RuPay"]},
            ),
        ]
    )
    ground_and_break_tool_loops(None, req)
    text = _last_text(req).lower()
    assert "which one" in text
    assert "axis rewards" in text and "axis rupay" in text
