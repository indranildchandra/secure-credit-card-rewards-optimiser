#!/usr/bin/env python3
"""
Card onboarding CLI.

Set up (or extend) your portfolio in config/cards.config by talking to a local
agent. Easiest via the shell wrapper:

    ./scripts/setup_cards.sh                 # interactive
    ./scripts/setup_cards.sh --once "TEXT"   # one-shot (scriptable, no TTY needed)

or directly:

    python scripts/setup_cards.py [--once "TEXT"]

The agent reverse-prompts you for the cards you hold, researches each card's
current terms on the web in detail, and — with your confirmation — writes them
into config/cards.config (and adds routing rules). It runs on the same local
Gemma/Ollama model as the optimiser; only the web-search queries (card/merchant
names) leave your machine.

Requires Ollama running with the model from config/model.config (start it with
`ollama serve`, or just run ./run.sh once to pull the model).
"""

import argparse
import asyncio
import os
import re
import sys

# This script lives in scripts/; put the repo root on sys.path so `config`,
# `tools`, etc. import correctly no matter the working directory.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from google.adk.agents import Agent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from config import MODEL  # noqa: E402
from tools.web_search import build_web_search_tool  # noqa: E402
from tools.config_writer import (  # noqa: E402
    list_configured_cards,
    save_card,
    add_decision_rule,
    remove_card,
)

load_dotenv(os.path.join(_ROOT, ".env"))

_PROMPT_PATH = os.path.join(_ROOT, "config", "setup_cards_instruction.prompt")
with open(_PROMPT_PATH, encoding="utf-8") as _f:
    INSTRUCTION = _f.read()

APP_NAME = "card_setup"
USER_ID = "local"
SESSION_ID = "setup"

# --- Write gate (code-level enforcement of the confirm-before-write rule) ---
# The config-writing tools are only allowed to run when the USER's most recent
# message contains an explicit affirmation. This defends against prompt-injection
# from web-search results: even if a poisoned page tells the model to save, the
# write is blocked unless the actual user just confirmed it.
_WRITE_TOOLS = {"save_card", "add_decision_rule", "remove_card"}
_AFFIRM_WORDS = {
    "yes",
    "yeah",
    "yep",
    "confirm",
    "confirmed",
    "approve",
    "approved",
    "ok",
    "okay",
    "correct",
    "proceed",
    "perfect",
    "sure",
    "save",
    "add",
    "update",
    "remove",
    "delete",
}
_AFFIRM_PHRASES = (
    "go ahead",
    "do it",
    "looks good",
    "sounds good",
    "that's right",
    "thats right",
    "go for it",
)
# Any of these in the user's message vetoes the affirmation (so "no, that's not
# correct" or "don't approve" never counts as a yes).
_NEGATION_WORDS = {
    "no",
    "nope",
    "nah",
    "not",
    "don't",
    "dont",
    "do n't",
    "never",
    "cancel",
    "stop",
    "wait",
    "hold",
    "incorrect",
    "wrong",
}


def _is_affirmative(text: str) -> bool:
    """True only if the text contains an explicit confirmation AND no negation.

    Word-boundary safe ('yesterday' is not 'yes'); negation-aware ('no, that's
    not correct' is NOT a yes even though it contains 'correct'). Biased toward
    blocking: if a confirmation is ambiguous, return False and let the agent ask
    again."""
    t = (text or "").lower()
    words = set(re.findall(r"[a-z']+", t))
    if words & _NEGATION_WORDS:
        return False
    if any(p in t for p in _AFFIRM_PHRASES):
        return True
    return bool(words & _AFFIRM_WORDS)


def _latest_user_text(tool_context) -> str:
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return " ".join(p.text or "" for p in parts if getattr(p, "text", None))


def require_confirmation_before_write(tool, args, tool_context):
    """ADK before_tool_callback: block save_card/add_decision_rule unless the
    user's latest message explicitly confirms. Returning a dict skips the tool."""
    if getattr(tool, "name", "") not in _WRITE_TOOLS:
        return None
    if _is_affirmative(_latest_user_text(tool_context)):
        return None
    return {
        "blocked": True,
        "reason": (
            "Write blocked: the user has not explicitly confirmed this in their "
            "latest message. Show the proposed JSON and ask them to confirm "
            "(e.g. 'yes, save it') before calling this tool again."
        ),
    }


root_agent = Agent(
    name="card_setup",
    model=MODEL,
    description="Researches the user's credit cards and writes them into config/cards.config.",
    instruction=INSTRUCTION,
    tools=[
        build_web_search_tool(),
        list_configured_cards,
        save_card,
        add_decision_rule,
        remove_card,
    ],
    before_tool_callback=require_confirmation_before_write,
)


def build_runner() -> InMemoryRunner:
    """Build a runner with its session created. No model call happens here."""
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    asyncio.run(
        runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
        )
    )
    return runner


def _agent_reply(runner: InMemoryRunner, text: str) -> str:
    """Send one user message and return the agent's final text response."""
    message = types.Content(role="user", parts=[types.Part(text=text)])
    chunks = []
    for event in runner.run(
        user_id=USER_ID, session_id=SESSION_ID, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            chunks.append("".join(p.text or "" for p in event.content.parts))
    return "\n".join(c for c in chunks if c).strip()


class ModelUnavailable(RuntimeError):
    """Raised when the agent produced no response (typically Ollama not running)."""


def run_once(text: str) -> str:
    """Send a single message to a fresh session and return the reply.

    Useful for scripting/testing the onboarding flow without an interactive TTY:
        python scripts/setup_cards.py --once "I have an Amazon Pay ICICI card"

    Raises ModelUnavailable if the agent produced no response.
    """
    reply = _agent_reply(build_runner(), text)
    if not reply:
        raise ModelUnavailable("no response from the model")
    return reply


def _model_unreachable(detail: str = "") -> None:
    suffix = f" ({detail})" if detail else ""
    print(f"\nCould not get a response from the local model{suffix}.")
    print(
        "Make sure Ollama is running (`ollama serve`) with the model in "
        "config/model.config (run ./run.sh once to pull it)."
    )
    sys.exit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Onboard your credit cards into config/cards.config by chatting."
    )
    parser.add_argument(
        "--once",
        metavar="TEXT",
        help="Send a single message, print the reply, and exit (no interactive TTY).",
    )
    args = parser.parse_args(argv)

    if args.once is not None:
        try:
            print(run_once(args.once))
        except ModelUnavailable as e:  # pragma: no cover - needs a running Ollama
            _model_unreachable(str(e))
        return

    print("Card Onboarding Assistant (local). Type 'exit' or Ctrl-C to finish.\n")
    runner = build_runner()

    # Kick off the conversation so the agent greets and reverse-prompts. If the
    # very first call yields nothing, the model isn't reachable — bail clearly.
    greeting = _agent_reply(runner, "Hi — help me set up my cards.")
    if not greeting:  # pragma: no cover - needs a running Ollama
        _model_unreachable()
    print("assistant>", greeting)

    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDone. Restart ./run.sh to load your updated cards.")
            break
        if not user:
            continue
        if user.lower() in {"exit", "quit", "q"}:
            print("Done. Restart ./run.sh to load your updated cards.")
            break
        reply = _agent_reply(runner, user)
        print("\nassistant>", reply or "(no response — is Ollama still running?)")


if __name__ == "__main__":
    main()
