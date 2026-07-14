"""Offline tests for the ground-and-finalise guard (optimizer/loop_guard.py).

The guard collapses the weak-model flow to "one tool call, then the answer":
before any tool runs it does nothing; once ANY tool has returned it strips the
tools (so the next generation must be text), grounds the model in the real
result, spells out the winner, and reserves output-token budget. No model /
network involved.
"""

from google.adk.models import LlmRequest
from google.genai import types

from optimizer.loop_guard import (
    ground_and_break_tool_loops,
    _primary_card,
    _ANSWER_TOKEN_BUDGET,
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


def test_no_tool_result_yet_is_a_noop():
    # Before any tool has run there is nothing to ground — leave the request be.
    req = _request([types.Content(role="user", parts=[types.Part(text="which card?")])])
    n_before = len(req.contents)
    assert ground_and_break_tool_loops(None, req) is None
    assert len(req.contents) == n_before  # no note appended
    assert len(req.config.tools) == 1  # tools still offered for the first call


def test_after_routing_forces_answer_with_the_winner():
    # The Croma case: find_cards returned Tata Neu Infinity. The guard must strip
    # tools (no web-search/extra turn to spiral into) and hand the winner over.
    req = _request(
        [
            _call(
                "find_cards_for_category", merchant_or_category="Croma", amount=60000
            ),
            _result(
                "find_cards_for_category",
                {
                    "matches": [
                        {
                            "primary": "Tata Neu Infinity",
                            "fallback": "Tata Star SBI Platinum",
                        }
                    ]
                },
            ),
        ]
    )
    assert ground_and_break_tool_loops(None, req) is None
    assert req.config.tools == []  # tools stripped -> next gen must be the answer
    assert req.config.max_output_tokens == _ANSWER_TOKEN_BUDGET  # room to finish
    text = _last_text(req)
    assert "THE WINNER IS" in text
    assert "Tata Neu Infinity" in text  # winner handed to the model
    assert "never invent" in text.lower()


def test_ambiguous_result_asks_instead_of_inventing():
    # A disambiguation tool result (no routing primary) -> instruction to ASK, not
    # to fabricate a winner.
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
    assert "ask which one" in text
    assert "axis rewards" in text and "axis rupay" in text


def test_does_not_override_an_existing_token_budget():
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
    req.config.max_output_tokens = 512  # caller already set a budget
    ground_and_break_tool_loops(None, req)
    assert req.config.max_output_tokens == 512  # respected, not clobbered
