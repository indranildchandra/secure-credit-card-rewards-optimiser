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
from .context_window import trim_history_before_model
from tools.web_search import build_web_search_tool
from tools.card_tools import (
    find_cards_for_category,
    get_card_details,
    list_all_cards,
    estimate_reward_value,
    estimate_net_cost,
    compare_cards_for_spend,
)
from tools.spend_tracker import (
    record_spend,
    get_spend_summary,
    get_spend_history,
    check_cap_status,
    check_fee_waiver_status,
    assess_card_value,
)

# Single source of truth: project root .env covers all modules.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Web-search tool — Google Search grounding on Gemini, DuckDuckGo on Ollama.
web_search_tool = build_web_search_tool()

# The system instruction lives in a plain-text file under config/ so it can be
# maintained and evolved without touching Python.
_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "system_instruction.prompt"
)
with open(_PROMPT_PATH, encoding="utf-8") as _f:
    INSTRUCTION = _f.read()

root_agent = Agent(
    name="optimizer",
    model=MODEL,
    description="Recommends the best credit card for a given transaction to maximise rewards (local/offline).",
    instruction=INSTRUCTION,
    tools=[
        find_cards_for_category,
        compare_cards_for_spend,
        get_card_details,
        list_all_cards,
        estimate_reward_value,
        estimate_net_cost,
        check_cap_status,
        check_fee_waiver_status,
        assess_card_value,
        record_spend,
        get_spend_summary,
        get_spend_history,
        web_search_tool,
    ],
    before_model_callback=trim_history_before_model,
)

print(" Credit Card Optimiser agent ready.")
