# Test Cases

Two layers of tests:

## 1. Automated (offline, no LLM) — `pytest`

```bash
cd adk_in_local
source .adk_env/bin/activate
python -m pytest tests/ -q
```

These validate the deterministic core — decision-matrix routing
(`test_card_tools.py`) and cap/threshold math (`test_spend_tracker.py`). No
network or model required.

## 2. End-to-end (manual, in the ADK Web UI)

```bash
cd adk_in_local
./run.sh           # boots Ollama + ADK Web UI on http://localhost:8080
```

Open the UI, select the **`optimizer`** agent, and run the prompts below. Each
should produce the four-field response (**The Winner / The Reward / The Logic /
The Live Update**) and you should see a `ddg_search` call whose query is about
the *merchant + card* (not your raw sentence).

| # | Prompt | Expected Winner |
|---|--------|-----------------|
| 1 | I am spending Rs.1,50,000 on a MacBook Pro at an Apple Store. Which card? | Amex Platinum Travel |
| 2 | I am spending Rs.500 on Swiggy. Which card? | HSBC Live+ |
| 3 | I am buying groceries for Rs.1,200. Which card? | HSBC Live+ |
| 4 | I am buying a TV at Croma for Rs.60,000. Which card? | Tata Neu Infinity |
| 5 | I am spending Rs.4,000 on Amazon. Which card? | ICICI AmazonPay |
| 6 | I am paying Rs.25,000 for a hotel via SmartBuy. Which card? | HDFC Regalia Gold |
| 7 | I am making a Rs.1,000 UPI payment to a kirana shop. Which card? | Scapia RuPay |
| 8 | I am making a Rs.3,000 UPI payment to a merchant. Which card? | Axis RuPay |
| 9 | I am buying USD 500 of forex. Which card? | Uni GoldX |
| 10 | I am buying apparel for Rs.5,000. Which card? | Axis Rewards |
| 11 | I am booking PVR movie tickets for Rs.800. Which card? | Uni GoldX |

### Cap-aware flow (exercises the spend tracker)

1. "I spent Rs.8,000 on dining and Rs.4,000 on groceries on HSBC Live+ this month." → agent records spends.
2. "I am ordering Swiggy for Rs.700. Which card?" → with the HSBC Rs.1,000 cap now exhausted and order > Rs.600, the agent should recommend the **Axis Rewards** fallback.
