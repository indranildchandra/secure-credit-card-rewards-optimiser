"""Ground-and-guard for weak local tool-calling models.

Two independent problems with small Ollama-served models (e.g. Gemma):

* they ignore the structured ``function_response`` and then hallucinate a card
  that isn't in the portfolio / routing result; and
* they can re-issue the SAME call forever (an infinite loop).

This ``before_model_callback`` handles both WITHOUT clipping legitimate work:

* it lets the model call any NEW tool it needs (a compound "record my spend, then
  which card?" runs ``spend_manager`` and then ``find_cards_for_category``; a
  comparison can look up two cards) — tools stay available;
* once a routing/disambiguation tool has answered it GROUNDS the model in the
  real result (as plain text, with the winner spelled out) so it answers from
  facts, not guesses — but still lets it make a different call if it truly needs
  one;
* it only STRIPS the tools (forcing a text answer) when the model repeats an
  IDENTICAL call (same tool + same args = a loop) or blows a per-turn budget.

Web search is opt-in (see the prompt): a normal "which card?" question never
calls it, so those answers are fast and fully offline.

Deterministic, no extra LLM call.
"""

import json

from google.genai import types

# Generous output budget so the answer never truncates mid-generation.
_ANSWER_TOKEN_BUDGET = 2048
# Same tool + same args this many times in a turn == a loop → force a text answer.
_IDENTICAL_CALL_THRESHOLD = 2
# Runaway backstop: force an answer after this many total tool calls in a turn.
_MAX_TOOL_CALLS_PER_TURN = 6
# Tools whose result means "we now have the recommendation / disambiguation", so
# it's time to ground the model toward answering (other tools may precede these).
_ROUTING_TOOLS = ("find_cards_for_category", "find_matching_cards")


def _recent_tool_results(contents, limit: int = 4) -> list:
    """The most-recent tool outputs (name, response) already in the turn."""
    results = []
    for content in contents or []:
        for part in getattr(content, "parts", None) or []:
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", None):
                results.append((fr.name, getattr(fr, "response", None)))
    return results[-limit:]


def _primary_card(results):
    """The routing primary card, if find_cards_for_category is among the results."""
    for name, resp in results:
        if name == "find_cards_for_category" and isinstance(resp, dict):
            matches = resp.get("matches") or []
            if matches and isinstance(matches[0], dict):
                primary = matches[0].get("primary")
                if primary:
                    return primary
    return None


def _canonical_args(function_call) -> str:
    """Stable string for a call's arguments so identical calls compare equal."""
    args = getattr(function_call, "args", None) or {}
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(args)


def _identical_call_counts(contents) -> dict:
    """Count function calls keyed by (tool name, canonical arguments)."""
    counts: dict = {}
    for content in contents or []:
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            name = getattr(fc, "name", None) if fc is not None else None
            if name:
                key = (name, _canonical_args(fc))
                counts[key] = counts.get(key, 0) + 1
    return counts


def _grounding_note(results, force: bool) -> str:
    """Instruction restating the tool outputs as plain text.

    ``force`` (a loop / budget was hit) → hard stop. Otherwise a soft nudge that
    hands over the winner and biases answering, while still permitting a NEW tool
    call if the model genuinely needs one.
    """
    primary = _primary_card(results)
    if force:
        head = (
            f"STOP — do not call any more tools. THE WINNER IS **{primary}**. "
            if primary
            else "STOP — do not call any more tools. "
        ) + (
            "Output ONLY the four fields now, starting with '**The Winner:**', "
            "using the facts below. Name ONLY a card that appears in these results "
            "— never invent a card. (If the user named a card that matches more "
            "than one result, ask which one instead.)"
        )
    elif primary:
        head = (
            f"You have the routing result. THE WINNER IS **{primary}**. Write the "
            "four-field answer NOW using the facts below — name ONLY a card that "
            "appears here, never invent one. Do NOT repeat a call you already "
            "made; only call a DIFFERENT tool if the user specifically needs it "
            "(e.g. they asked about current offers → web search)."
        )
    else:
        head = (
            "Use these tool results as FACTS — name ONLY a card that appears in "
            "them, never invent one. If the user named a card that matches more "
            "than one result, ask which one. If you have enough, answer now; only "
            "call a DIFFERENT tool if you truly need more, and NEVER repeat a call."
        )
    lines = [head, "", "Tool results this turn:"]
    for name, resp in results:
        try:
            rendered = json.dumps(resp, default=str)
        except (TypeError, ValueError):
            rendered = str(resp)
        lines.append(f"- {name} -> {rendered[:900]}")
    return "\n".join(lines)


def ground_and_break_tool_loops(callback_context, llm_request):
    """ADK before_model_callback: allow new tool calls, ground, break loops.

    Mutates ``llm_request`` in place and returns None (proceed). No-op while the
    model is still gathering (e.g. it recorded a spend but hasn't routed). Once a
    routing tool has answered it grounds the model toward the answer (tools stay
    available for a genuinely different call); it strips the tools only on an
    identical-call loop or a per-turn budget overrun.
    """
    contents = getattr(llm_request, "contents", None)
    results = _recent_tool_results(contents, limit=64)
    if not results:
        return None  # no tool output yet — let the model make its first tool call

    counts = _identical_call_counts(contents)
    total = sum(counts.values())
    repeated = max(counts.values()) if counts else 0
    force = repeated >= _IDENTICAL_CALL_THRESHOLD or total >= _MAX_TOOL_CALLS_PER_TURN
    routing_done = any(name in _ROUTING_TOOLS for name, _ in results)

    # Still gathering (no routing yet, not a loop) — let the model call its next
    # (different) tool without interference.
    if not force and not routing_done:
        return None

    config = getattr(llm_request, "config", None)
    if config is not None:
        if force:
            # A loop / runaway — remove tools so the next generation is text.
            config.tools = []
            if getattr(config, "tool_config", None) is not None:
                config.tool_config = None
        # Room to finish the four fields without truncating mid-generation.
        if not getattr(config, "max_output_tokens", None):
            config.max_output_tokens = _ANSWER_TOKEN_BUDGET

    note = types.Content(
        role="user", parts=[types.Part(text=_grounding_note(results[-4:], force))]
    )
    llm_request.contents = list(contents or []) + [note]
    return None
