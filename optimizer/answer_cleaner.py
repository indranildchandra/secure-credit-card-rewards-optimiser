"""Strip the model's reasoning so the UI shows only the final answer.

Weak local models (Gemma via Ollama) narrate their reasoning as plain text
before emitting the four-field answer, and attach commentary to their tool
calls — both surface as noisy "thought" blocks in the ADK Web UI. Prompt
instructions don't reliably stop it (the model even says "I must not explain my
process" and then does). So we trim it deterministically in an
``after_model_callback``:

* a response whose text contains the four-field answer is trimmed to start at
  "The Winner" (the reasoning preamble is dropped);
* commentary text attached to a tool call is dropped (the tool call is kept);
* a genuine non-answer reply (e.g. a "which card did you mean?" disambiguation
  question) is left untouched;
* explicit model "thought" parts are cleared.

Deterministic, no extra LLM call.
"""


def _answer_start(text: str) -> int:
    """Index where the four-field answer begins, or -1 if there is none."""
    idx = text.lower().find("the winner")
    if idx == -1:
        return -1
    # Include a leading markdown bold marker ("**The Winner") if present.
    if idx >= 2 and text[idx - 2 : idx] == "**":
        return idx - 2
    return idx


def clean_final_answer(callback_context, llm_response):
    """ADK after_model_callback: trim reasoning so only the answer is shown.

    Mutates ``llm_response`` in place and returns it. No-op for responses that
    are already clean or that carry no four-field answer.
    """
    content = getattr(llm_response, "content", None)
    if content is None:
        return llm_response
    parts = getattr(content, "parts", None) or []
    has_tool_call = any(getattr(p, "function_call", None) is not None for p in parts)

    for part in parts:
        if getattr(part, "thought", False):  # explicit thought part → drop text
            part.text = ""
            continue
        text = getattr(part, "text", None)
        if not text:
            continue
        start = _answer_start(text)
        if start > 0:
            part.text = text[start:].lstrip()  # drop the reasoning preamble
        elif start == -1 and has_tool_call:
            part.text = ""  # pre-tool commentary → hide, keep the function_call
    return llm_response
