"""
Secure Credit Card Rewards Optimiser — root agent.

Given a transaction ("I am spending Rs.X at <merchant>"), recommends the card
that minimises net spend / maximises value. Card knowledge lives in structured
data (data/cards.py) and is queried through deterministic tools, so the small
local model only has to orchestrate and explain.

Runs on a local Ollama model by default (config.py) — transaction reasoning
never leaves the machine. A live web-search step (ddg_search) checks for the
latest offers/devaluations using a model-authored, merchant+card-focused query.
"""

import os

from google.adk.agents import Agent
from dotenv import load_dotenv

from config import MODEL
from tools.duckduckgo_search import ddg_search
from tools.card_tools import (
    find_cards_for_category,
    get_card_details,
    list_all_cards,
    estimate_reward_value,
)
from tools.spend_tracker import record_spend, get_spend_summary, check_cap_status

# Single source of truth: project root .env covers all modules.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# The system instruction lives in a plain-text file next to this module so it can
# be maintained and evolved without touching Python.
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "system_instruction.prompt")
with open(_PROMPT_PATH, encoding="utf-8") as _f:
    INSTRUCTION = _f.read()

root_agent = Agent(
    name="optimizer",
    model=MODEL,
    description="Recommends the best credit card for a given transaction to maximise rewards (local/offline).",
    instruction=INSTRUCTION,
    tools=[
        find_cards_for_category,
        get_card_details,
        list_all_cards,
        estimate_reward_value,
        check_cap_status,
        record_spend,
        get_spend_summary,
        ddg_search,
    ],
)

print(" Credit Card Optimiser agent ready.")
