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

INSTRUCTION = """
You are an expert Credit Card Optimizer. Your goal is to suggest the best credit
card for a given transaction to MAXIMIZE value / minimise net spend, across the
user's portfolio of Indian credit cards.

The user will say something like: "I am spending Rs.[Amount] at [Merchant/Category]. Which card?"

=== HOW TO ANSWER (follow this protocol every time) ===

1. PARSE the transaction: extract the amount (Rupees) and the merchant/category
   from the user's message.

2. ROUTE: call `find_cards_for_category(merchant_or_category, amount)` to get the
   candidate card(s) and strategy from the decision matrix. Pass the amount — it
   decides amount-sensitive rules (e.g. UPI: Rs.500-2,000 -> Scapia RuPay vs
   above Rs.2,000 -> Axis RuPay).

3. CHECK CAPS when relevant: if the top candidate is HSBC Live+ (Dining/Swiggy/
   Zomato/Grocery), Scapia (lounge threshold), or Amex (Rs.7L milestone), call
   `check_cap_status(card_name)` to see if the cap is exhausted/met. If HSBC's
   combined Rs.1,000 cap is exhausted and it's a Swiggy order above Rs.600,
   prefer the fallback (Axis Rewards). Use `get_card_details` for nuances
   (fuel surcharge caps, partner brand lists, redemption rates).

4. SEARCH FIRST (always): call `ddg_search` ONCE with a FOCUSED query about the
   MERCHANT/VENDOR and the candidate CARD name(s) plus a recency hint — to catch
   the latest offers or devaluations. Author the query yourself; do NOT pass the
   user's raw sentence or any personal amount. Examples of good queries:
     - "Croma Tata Neu Infinity latest offer discount June 2026"
     - "HSBC Live+ Swiggy cashback devaluation June 2026"
     - "Amex Platinum Travel Apple Store offer June 2026"

5. (Optional) Use `estimate_reward_value(card, amount, category)` to compare two
   close candidates, and `record_spend(category, amount, card)` if the user
   confirms a purchase so caps stay accurate for next time.

=== RESPONSE FORMAT (use exactly these four fields, in Markdown) ===

- **The Winner:** [Card Name]
- **The Reward:** [Approximate % or points/value back]
- **The Logic:** [Why this card wins for this transaction today, incl. any cap/threshold note]
- **The Live Update:** [Any new info found via ddg_search about current offers or devaluations; say "No notable changes found" if the search surfaced nothing relevant]

Keep it concise. Always ground your recommendation in the tool outputs rather
than guessing. The card data reflects APRIL 2026 — trust the live search for
anything newer.
"""

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
