"""Ground-and-finalise guard for weak local tool-calling models.

First-principles rationale: the routing is DETERMINISTIC — once
``find_cards_for_category`` returns, the winning card is already decided. A weak
model served via Ollama (e.g. Gemma) does not need to keep orchestrating after
that; asking it to (web-search, re-reason across more turns) is exactly what
makes it spiral, loop, hallucinate, or truncate mid-thought without ever emitting
the answer.

So this ``before_model_callback`` lets a query PROGRESS through the tools it
genuinely needs — e.g. a compound "record my spend, then which card?" runs
``spend_manager`` and *then* ``find_cards_for_category`` — and only forces the
final answer once a routing/disambiguation tool has actually answered (or a
per-turn budget is hit). At that point it:

  1. strips the tools so the next generation cannot start another tool/reason
     turn (e.g. the web-search spiral) — it MUST produce text;
  2. re-states the tool outputs as plain text (weak models ignore the structured
     ``function_response``) and, when routing produced a primary card, hands that
     card to the model directly ("The Winner is X");
  3. raises the output-token budget so the four-field answer isn't truncated.

Deterministic, no extra LLM call. A capable model is unaffected — it would have
answered after the routing call anyway; this just guarantees a weak one does too.

Trade-off (intentional, for reliability): the always-on web-search "Live Update"
step is skipped — the answer relies on the local config, and the Live Update
field falls back to "No notable changes found". Reliability > freshness here.
"""

import json

from google.genai import types

# Generous output budget so the answer never truncates mid-generation.
_ANSWER_TOKEN_BUDGET = 2048

# Tools whose result means "we now have the recommendation / disambiguation" —
# i.e. it is time to stop and answer. Everything else (e.g. spend_manager to
# record a spend) may legitimately precede routing in a compound query.
_ROUTING_TOOLS = ("find_cards_for_category", "find_matching_cards")

# Backstop: force an answer after this many tool results even without a routing
# tool, so a non-routing loop can't run forever.
_MAX_TOOL_CALLS_PER_TURN = 4


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


def _grounding_note(results) -> str:
    """Instruction that forces the final answer, handing the model the winner."""
    primary = _primary_card(results)
    if primary:
        head = (
            f"STOP — you already have the routing result. THE WINNER IS "
            f"**{primary}**. Do not think further and do not call any tools. "
            "Output ONLY the four fields now, starting with '**The Winner:**', "
            "based on the facts below. Name ONLY a card that appears in these "
            "results — never invent a card."
        )
    else:
        head = (
            "STOP — do not call any more tools. Respond NOW using ONLY the tool "
            "results below (if the user named a card that matches more than one "
            "result, ask which one they mean instead of guessing). Name ONLY a "
            "card that appears in these results — never invent a card."
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
    """ADK before_model_callback: let compound queries progress, then finalise.

    Mutates ``llm_request`` in place and returns None (proceed). No-op while the
    model is still legitimately gathering (e.g. it recorded a spend but hasn't
    routed yet). Once a routing/disambiguation tool has answered — or the per-turn
    budget is hit — it strips the tools, grounds the model in the real result
    (with the winner spelled out), and guarantees room for the answer.
    """
    contents = getattr(llm_request, "contents", None)
    results = _recent_tool_results(contents, limit=64)
    if not results:
        return None  # no tool output yet — let the model make its first tool call

    # Let a compound query keep gathering until a routing/disambiguation tool has
    # answered (or we hit the backstop). This is what lets "record my spend, then
    # which card?" call spend_manager AND then find_cards_for_category.
    routing_done = any(name in _ROUTING_TOOLS for name, _ in results)
    if not routing_done and len(results) < _MAX_TOOL_CALLS_PER_TURN:
        return None  # still gathering (not a loop) — keep the tools available

    config = getattr(llm_request, "config", None)
    if config is not None:
        # No more tool/reason turns — the next generation must be the answer.
        config.tools = []
        if getattr(config, "tool_config", None) is not None:
            config.tool_config = None
        # Room to finish the four fields without truncating mid-generation.
        if not getattr(config, "max_output_tokens", None):
            config.max_output_tokens = _ANSWER_TOKEN_BUDGET

    note = types.Content(
        role="user", parts=[types.Part(text=_grounding_note(results[-4:]))]
    )
    llm_request.contents = list(contents or []) + [note]
    return None
