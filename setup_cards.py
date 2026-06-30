#!/usr/bin/env python3
"""
Card onboarding CLI.

Run this to set up (or extend) your portfolio in config/cards.config by simply
talking to a local agent:

    python setup_cards.py

The agent reverse-prompts you for the cards you hold, researches each card's
current terms on the web in detail, and — with your confirmation — writes them
into config/cards.config (and adds routing rules). It runs on the same local
Gemma/Ollama model as the optimiser; only the web-search queries (card/merchant
names) leave your machine.

Requires Ollama running with the model from config/model.config (start it with
`ollama serve`, or just run ./run.sh once to pull the model).
"""

import asyncio
import os
import sys

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types
from dotenv import load_dotenv

from config import MODEL
from tools.duckduckgo_search import ddg_search
from tools.config_writer import (
    list_configured_cards,
    save_card,
    add_decision_rule,
)

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "config", "setup_cards_instruction.prompt"
)
with open(_PROMPT_PATH, encoding="utf-8") as _f:
    INSTRUCTION = _f.read()

APP_NAME = "card_setup"
USER_ID = "local"
SESSION_ID = "setup"

root_agent = Agent(
    name="card_setup",
    model=MODEL,
    description="Researches the user's credit cards and writes them into config/cards.config.",
    instruction=INSTRUCTION,
    tools=[ddg_search, list_configured_cards, save_card, add_decision_rule],
)


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


def main() -> None:
    print("Card Onboarding Assistant (local). Type 'exit' or Ctrl-C to finish.\n")
    runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    asyncio.run(
        runner.session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
        )
    )

    # Kick off the conversation so the agent greets and reverse-prompts.
    try:
        print("assistant>", _agent_reply(runner, "Hi — help me set up my cards."))
    except Exception as e:  # pragma: no cover - depends on a running Ollama
        print(f"\nCould not reach the model: {e}")
        print(
            "Make sure Ollama is running (`ollama serve`) with the model in "
            "config/model.config (run ./run.sh once to pull it)."
        )
        sys.exit(1)

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
        print("\nassistant>", _agent_reply(runner, user))


if __name__ == "__main__":
    main()
