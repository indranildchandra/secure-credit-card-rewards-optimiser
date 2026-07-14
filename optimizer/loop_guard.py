"""Ground-and-finalise guard for weak local tool-calling models.

First-principles rationale: the routing is DETERMINISTIC — once
``find_cards_for_category`` returns, the winning card is already decided. A weak
model served via Ollama (e.g. Gemma) does not need to keep orchestrating after
that; asking it to (web-search, re-reason across more turns) is exactly what
makes it spiral, loop, hallucinate, or truncate mid-thought without ever emitting
the answer.

So this ``before_model_callback`` collapses the flow to **one tool call, then the
answer**. The instant ANY tool has returned, it:

  1. strips the tools so the next generation cannot start another tool/reason
     turn — it MUST produce text;
  2. re-states the tool outputs as plain text (weak models ignore the structured
     ``function_response``) and, when routing produced a primary card, hands that
     card to the model directly ("The Winner is X");
  3. raises the output-token budget so the four-field answer isn't truncated.

Deterministic, no extra LLM call. A capable model is unaffected — it would have
answered after one call anyway; this just guarantees a weak one does too.

Trade-off (intentional, for reliability): the always-on web-search "Live Update"
step is skipped — the answer relies on the local config, and the Live Update
field falls back to "No notable changes found". Reliability > freshness here.
"""

import json

from google.genai import types

# Generous output budget so the answer never truncates mid-generation.
_ANSWER_TOKEN_BUDGET = 2048


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
    """ADK before_model_callback: after the first tool result, force the answer.

    Mutates ``llm_request`` in place and returns None (proceed). No-op until a
    tool has run; after that it strips the tools, grounds the model in the real
    result (with the winner spelled out), and guarantees room for the answer.
    """
    contents = getattr(llm_request, "contents", None)
    results = _recent_tool_results(contents)
    if not results:
        return None  # no tool output yet — let the model make its one tool call

    config = getattr(llm_request, "config", None)
    if config is not None:
        # No more tool/reason turns — the next generation must be the answer.
        config.tools = []
        if getattr(config, "tool_config", None) is not None:
            config.tool_config = None
        # Room to finish the four fields without truncating mid-generation.
        if not getattr(config, "max_output_tokens", None):
            config.max_output_tokens = _ANSWER_TOKEN_BUDGET

    note = types.Content(role="user", parts=[types.Part(text=_grounding_note(results))])
    llm_request.contents = list(contents or []) + [note]
    return None
