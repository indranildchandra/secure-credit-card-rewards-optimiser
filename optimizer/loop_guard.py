"""Grounding + loop-breaking for weak local tool-calling models.

Small models served via Ollama (e.g. Gemma) frequently ignore the structured
``function_response`` messages ADK feeds back after a tool runs. Two failure
modes follow:

* they re-issue the SAME tool call every turn (an infinite loop), or
* they answer once but WITHOUT the tool's output — hallucinating a card that is
  neither in the portfolio nor in the routing result (observed: the tool
  returned "Tata Neu Infinity" and the model still named an invented card).

This ``before_model_callback`` fixes both. On every model call *after a tool has
run*, it re-states the tool outputs as plain text (which these models read
reliably) with an explicit instruction that the recommended card MUST come from
those results — so the model can't ignore them or invent a card. If it also
detects a loop (an identical call repeated) or a blown per-turn budget, it strips
the tools so the next generation must be a final text answer.

Deterministic, no extra LLM call. A capable model is unaffected: grounding only
restates what it already retrieved, and it never trips the loop-break.
"""

import json

from google.genai import types

# An IDENTICAL call (same tool + same arguments) repeated this many times is a
# loop. Calling the same tool with DIFFERENT arguments (e.g. get_card_details for
# two cards) is a legitimate multi-call flow and is NOT restricted.
_IDENTICAL_CALL_THRESHOLD = 2
# Pure runaway backstop on total tool calls per turn — generous so it never
# clips a genuine multi-tool flow, only a pathological args-varying loop.
_MAX_TOOL_CALLS_PER_TURN = 10


def _recent_tool_results(contents, limit: int = 4) -> list:
    """The most-recent tool outputs (name, response) already in the turn."""
    results = []
    for content in contents or []:
        for part in getattr(content, "parts", None) or []:
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", None):
                results.append((fr.name, getattr(fr, "response", None)))
    return results[-limit:]


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


def _grounding_note(results, force_final: bool) -> str:
    """Plain-text restatement of the tool outputs + a hard grounding constraint.

    Weak models ignore the structured function_response and hallucinate; stating
    the results as ordinary text they read reliably — and pinning the Winner to
    those results — stops the invention of off-portfolio cards.
    """
    lines = [
        "GROUNDING — the tool results below are FACTS you already retrieved. The "
        "card you name as **The Winner** MUST be one of the cards that appears in "
        "these results (its `primary`, or a named `fallback`). Do NOT invent, "
        "guess, or name any card that is not in these results.",
        "",
        "Tool results this turn:",
    ]
    for name, resp in results:
        try:
            rendered = json.dumps(resp, default=str)
        except (TypeError, ValueError):
            rendered = str(resp)
        lines.append(f"- {name} -> {rendered[:900]}")
    if force_final:
        lines.append("")
        lines.append(
            "You have enough information. Do NOT call any more tools — write the "
            "four-field answer NOW."
        )
    return "\n".join(lines)


def ground_and_break_tool_loops(callback_context, llm_request):
    """ADK before_model_callback: ground the model in tool results, break loops.

    Mutates ``llm_request`` in place and returns None (proceed). No-op until a
    tool has actually run; after that it always appends a plain-text grounding
    note, and additionally strips the tools when a loop / over-budget is detected.
    """
    contents = getattr(llm_request, "contents", None)
    results = _recent_tool_results(contents)
    if not results:
        return None  # no tool output yet — let the model call tools normally

    counts = _identical_call_counts(contents)
    total = sum(counts.values())
    most_repeated = max(counts.values()) if counts else 0
    looping = (
        most_repeated >= _IDENTICAL_CALL_THRESHOLD or total >= _MAX_TOOL_CALLS_PER_TURN
    )

    if looping:
        # Remove the tools the model can see so it must answer with text.
        config = getattr(llm_request, "config", None)
        if config is not None:
            config.tools = []
            if getattr(config, "tool_config", None) is not None:
                config.tool_config = None

    note = types.Content(
        role="user", parts=[types.Part(text=_grounding_note(results, looping))]
    )
    llm_request.contents = list(contents or []) + [note]
    return None
