"""Offline tests for grounding + loop-breaking (optimizer/loop_guard.py).

Builds real ADK LlmRequest objects with scripted function-call/response history
and asserts: nothing happens before any tool runs; once a tool HAS run the model
is grounded in the real result (so it can't hallucinate an off-portfolio card);
and an identical-repeat loop (or over-budget turn) also strips the tools. No
model / network involved.
"""

from google.adk.models import LlmRequest
from google.genai import types

from optimizer.loop_guard import (
    ground_and_break_tool_loops,
    _identical_call_counts,
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


def test_no_tool_result_yet_is_a_noop():
    # Before any tool has run there is nothing to ground — leave the request be.
    req = _request([types.Content(role="user", parts=[types.Part(text="which card?")])])
    n_before = len(req.contents)
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.contents) == n_before  # no note appended
    assert len(req.config.tools) == 1  # tools still offered


def test_single_call_grounds_but_keeps_tools():
    # One routing call + result, no loop: tools stay offered, but the model is
    # grounded in the real result so it cannot invent a card.
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
    assert len(req.config.tools) == 1  # NOT stripped (no loop)
    text = _last_text(req)
    assert "grounding" in text.lower()
    assert "Tata Neu Infinity" in text  # real result surfaced as readable text
    assert "do not call any more tools" not in text.lower()  # not forced final yet


def test_grounding_pins_winner_to_results():
    # The Croma bug: the model must be told the Winner MUST be one of these cards.
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Amazon", amount=4000
            ),
            _result(
                "find_cards_for_category",
                {"matches": [{"primary": "ICICI AmazonPay"}]},
            ),
        ]
    )
    ground_and_break_tool_loops(None, req)
    text = _last_text(req).lower()
    assert "must be" in text and "ICICI AmazonPay".lower() in text
    assert "do not invent" in text


def test_same_tool_different_args_is_allowed():
    # Legit multi-call: get_card_details for two cards -> different args -> tools
    # stay offered (grounding still applied).
    req = _request(
        [
            _call("get_card_details", card_name="HDFC Regalia Gold"),
            _result("get_card_details", {"name": "HDFC Regalia Gold"}),
            _call("get_card_details", card_name="Amex Platinum Travel"),
            _result("get_card_details", {"name": "Amex Platinum Travel"}),
        ]
    )
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.config.tools) == 1  # not clipped


def test_identical_repeat_breaks_and_grounds():
    # Identical repeated call -> loop -> strip tools AND force a final answer.
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
    assert ground_and_break_tool_loops(None, req) is None
    assert req.config.tools == []  # tools stripped -> must answer as text
    text = _last_text(req)
    assert "ICICI AmazonPay" in text
    assert "do not call any more tools" in text.lower()


def test_total_budget_backstop_breaks_runaway():
    # A pathological loop that varies its args still can't run forever.
    contents = []
    for i in range(10):
        contents += [_call(f"tool_{i}"), _result(f"tool_{i}", {"n": i})]
    req = _request(contents)
    assert ground_and_break_tool_loops(None, req) is None
    assert req.config.tools == []
