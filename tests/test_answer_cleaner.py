"""Offline tests for the answer cleaner (optimizer/answer_cleaner.py).

Verifies the after_model_callback trims a reasoning preamble down to the
four-field answer, drops commentary attached to a tool call, and leaves a
genuine non-answer reply (a disambiguation question) untouched.
"""

from google.adk.models import LlmResponse
from google.genai import types

from optimizer.answer_cleaner import clean_final_answer, _answer_start


def _resp(*parts):
    return LlmResponse(content=types.Content(role="model", parts=list(parts)))


def _text(resp):
    return " ".join(
        p.text or "" for p in (resp.content.parts or []) if getattr(p, "text", None)
    )


def test_answer_start_finds_the_winner_with_and_without_bold():
    assert _answer_start("blah blah The Winner: X") == len("blah blah ")
    t = "reasoning... **The Winner:** X"
    assert t[_answer_start(t) :].startswith("**The Winner")  # bold marker kept
    assert _answer_start("no answer here") == -1


def test_trims_reasoning_preamble_to_the_answer():
    text = (
        "The user wants a recommendation. 1. Parse... 2. Route... I must now "
        "generate the output.**The Winner:** ICICI AmazonPay\n"
        "**The Reward:** 5% cashback\n**The Logic:** best for Amazon\n"
        "**The Live Update:** No notable changes found"
    )
    resp = _resp(types.Part(text=text))
    clean_final_answer(None, resp)
    out = _text(resp)
    assert out.startswith("**The Winner:**")
    assert "The user wants" not in out  # reasoning dropped
    assert "ICICI AmazonPay" in out


def test_drops_commentary_attached_to_a_tool_call():
    resp = _resp(
        types.Part(text="I will call find_cards_for_category now to route this."),
        types.Part(
            function_call=types.FunctionCall(name="find_cards_for_category", args={})
        ),
    )
    clean_final_answer(None, resp)
    # commentary text gone, but the function call is preserved.
    assert _text(resp).strip() == ""
    assert any(
        getattr(p, "function_call", None) is not None for p in resp.content.parts
    )


def test_leaves_disambiguation_question_untouched():
    q = "You hold two Axis cards. Which did you mean: Axis Rewards or Axis RuPay?"
    resp = _resp(types.Part(text=q))
    clean_final_answer(None, resp)
    assert _text(resp) == q  # no 'The Winner' + no tool call -> left as-is


def test_already_clean_answer_is_unchanged():
    clean = "**The Winner:** Tata Neu Infinity\n**The Reward:** 10%"
    resp = _resp(types.Part(text=clean))
    clean_final_answer(None, resp)
    assert _text(resp) == clean
