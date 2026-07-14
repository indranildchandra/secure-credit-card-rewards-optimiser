"""
Opt-in conversation-history compaction for very long sessions.

ADK replays the whole session's message history to the model on every turn, so a
very long single conversation can approach the context-window limit. This
`before_model_callback` keeps a sliding window of the most-recent turns and
replaces the older span with a short note that points the model back at durable
storage (spends/caps live in user-scoped state, retrievable via the tracker
tools) rather than the dropped dialogue.

It is deterministic (no extra LLM call) and OPT-IN: it does nothing unless the
env var ``OPTIMIZER_MAX_HISTORY_CONTENTS`` is set to a positive integer — the max
number of recent history items to keep. For a true LLM summary of the dropped
span, swap the note for a summarisation call; the wiring is the same.
"""

import os

from google.genai import types

_ENV_VAR = "OPTIMIZER_MAX_HISTORY_CONTENTS"

_SUMMARY_NOTE = (
    "[Earlier conversation omitted to stay within the context window. Durable "
    "facts (recorded spends, caps, milestones) are kept in storage — call "
    "get_spend_history / get_spend_summary / check_cap_status to recall them "
    "instead of relying on the omitted messages.]"
)


def _max_contents():
    """Configured window size, or None when compaction is disabled."""
    try:
        n = int(os.environ.get(_ENV_VAR, ""))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def trim_history_before_model(callback_context, llm_request):
    """ADK before_model_callback: shrink llm_request.contents to a sliding window.

    Returns None (proceed) — it mutates the request in place. No-op unless
    OPTIMIZER_MAX_HISTORY_CONTENTS is set and the history exceeds it.
    """
    limit = _max_contents()
    if not limit:
        return None
    contents = getattr(llm_request, "contents", None)
    if not contents or len(contents) <= limit:
        return None

    note = types.Content(role="user", parts=[types.Part(text=_SUMMARY_NOTE)])
    llm_request.contents = [note] + list(contents[-limit:])
    return None
