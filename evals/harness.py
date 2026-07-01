"""
Agent-level eval harness — runs the real optimiser agent end-to-end and grades
its card choice. Requires a running Ollama (the model from config/model.config);
these are NOT part of the fast offline unit suite.

Grading is deterministic by default (does the expected card appear in the
answer's "Winner"?). An optional LLM judge (``--judge``, uses JUDGE_MODEL from
model.config) can add a qualitative score for nuanced cases.
"""

import asyncio
import os
import socket

from google.genai import types


def ollama_available(host: str = "localhost", port: int = 11434) -> bool:
    """True if something is listening on the Ollama port."""
    base = os.environ.get("OLLAMA_API_BASE", "")
    if base:
        host = base.split("//")[-1].split(":")[0] or host
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _build_runner():
    # Imported lazily so importing this module never triggers model setup.
    from optimizer import root_agent
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=root_agent, app_name="optimizer_eval")
    asyncio.run(
        runner.session_service.create_session(
            app_name="optimizer_eval", user_id="eval", session_id="eval"
        )
    )
    return runner


def ask(prompt: str) -> str:
    """Run one prompt through a FRESH optimiser session and return the answer."""
    runner = _build_runner()
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    chunks = []
    for event in runner.run(user_id="eval", session_id="eval", new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            chunks.append("".join(p.text or "" for p in event.content.parts))
    return "\n".join(c for c in chunks if c).strip()


def winner_matches(answer: str, expected: str) -> bool:
    """Deterministic grade: the expected card name appears in the answer."""
    return expected.lower() in (answer or "").lower()


def run_all(cases) -> list:
    """Run every case; return [{prompt, expect, answer, passed}]."""
    results = []
    for c in cases:
        answer = ask(c["prompt"])
        results.append(
            {
                "prompt": c["prompt"],
                "expect": c["expect"],
                "answer": answer,
                "passed": winner_matches(answer, c["expect"]),
            }
        )
    return results
