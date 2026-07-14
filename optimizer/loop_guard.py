"""Deterministic loop-breaker for weak local tool-calling models.

Small models served via Ollama (e.g. Gemma) sometimes fail to *register* a
tool's result and re-issue the SAME tool call on the next turn — re-planning
"from step 1" every time and never producing a final answer. That's an infinite
loop that would stall the agent (observed with ``find_cards_for_category``).

This ``before_model_callback`` watches the tool calls already made in the current
turn. Once a tool has been called more than once (a loop), or the turn exceeds a
total tool-call budget, it **strips the tools from the request** so the next
generation MUST be plain text, and appends a short instruction telling the model
to finalise from what it already has. Deterministic, no extra LLM call.

This is a robustness backstop, not a substitute for a capable model — a strong
model never trips it (it calls each tool once and answers).
"""

import json

from google.genai import types

# An IDENTICAL call (same tool + same arguments) repeated this many times is a
# loop: re-issuing it cannot return anything new. Calling the same tool with
# DIFFERENT arguments (e.g. get_card_details for two different cards) is a
# legitimate multi-call flow and is NOT restricted.
_IDENTICAL_CALL_THRESHOLD = 2
# Pure runaway backstop: an upper bound on total tool calls per turn, generous
# so it never clips a genuine multi-tool flow (compare several cards, check a
# cap, web-search) — it only stops a pathological loop that varies its args.
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


def _finalize_note(contents) -> str:
    """Build the loop-break instruction, INLINING the tool outputs as plain text.

    Small local models (Gemma via Ollama) often ignore the structured
    ``function_response`` messages and then claim "the tool outputs are not
    visible to me" — so they hallucinate. Re-stating the results as ordinary text
    (which those models read reliably) lets them answer from real data instead of
    guessing, and stops them inventing cards that aren't in the portfolio.
    """
    lines = [
        "STOP — do not call any more tools. You already ran the tools listed "
        "below and their outputs ARE available to you here. Do NOT say the "
        "outputs are missing and do NOT assume or invent anything. Write the "
        "final answer NOW in the four-field format (The Winner / The Reward / "
        "The Logic / The Live Update), naming ONLY a card that appears in these "
        "results.",
    ]
    results = _recent_tool_results(contents)
    if results:
        lines.append("")
        lines.append("Tool results already gathered this turn:")
        for name, resp in results:
            try:
                rendered = json.dumps(resp, default=str)
            except (TypeError, ValueError):
                rendered = str(resp)
            lines.append(f"- {name} -> {rendered[:900]}")
    return "\n".join(lines)


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


def break_tool_call_loops(callback_context, llm_request):
    """ADK before_model_callback: force finalisation when the model loops on tools.

    Mutates ``llm_request`` in place and returns None (proceed). Fires only when
    the model repeats an IDENTICAL call (same tool + same args) or blows the
    per-turn total budget — genuine multi-tool / different-args calls are allowed.
    """
    contents = getattr(llm_request, "contents", None)
    counts = _identical_call_counts(contents)
    if not counts:
        return None

    total = sum(counts.values())
    most_repeated = max(counts.values())
    if most_repeated < _IDENTICAL_CALL_THRESHOLD and total < _MAX_TOOL_CALLS_PER_TURN:
        return None

    # Loop / over-budget → remove the tools the model can see so it must answer
    # with text, and nudge it to produce the final answer.
    config = getattr(llm_request, "config", None)
    if config is not None:
        config.tools = []
        if getattr(config, "tool_config", None) is not None:
            config.tool_config = None

    note = types.Content(role="user", parts=[types.Part(text=_finalize_note(contents))])
    llm_request.contents = list(contents or []) + [note]
    return None
