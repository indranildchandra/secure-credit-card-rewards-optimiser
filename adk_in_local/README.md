# Secure Credit Card Rewards Optimiser (local / offline)

A privacy-first credit-card rewards strategist for an Indian card portfolio.
Ask *"I am spending Rs.X at [merchant]. Which card?"* and it tells you which card
minimises net spend — running entirely on a **local model via Ollama**, so your
transaction reasoning never leaves your machine.

The interface is the **stock ADK Web UI** — no custom frontend to build or trust.

Inspired by the [ADK crash-course codelab](https://github.com/indranildchandra/adk-crash-course-codelab).

## Why "secure"?

- The LLM runs **locally via Ollama** — amounts, merchants and your card mix are
  reasoned about on-device. Nothing is sent to a cloud LLM.
- The only outbound traffic is a focused **web-search step** for the latest
  offers/devaluations. The model authors that query around the *merchant + card
  names* (e.g. `"Croma Tata Neu Infinity latest offer June 2026"`) — never your
  raw sentence or amount.

## How it works

```
optimizer/        ADK agent (root_agent) — orchestrates tools, formats the answer
data/cards.py     Knowledge base: Full Card Reference + Decision Matrix (Apr 2026)
tools/
  card_tools.py        find_cards_for_category, get_card_details,
                       list_all_cards, estimate_reward_value   (deterministic)
  spend_tracker.py     record_spend, get_spend_summary, check_cap_status
                       (ADK session state → SQLite; tracks HSBC/Scapia/Amex caps)
  duckduckgo_search.py ddg_search — live offers/devaluation check
config.py         Reads model.config → MODEL (Ollama/Gemini), no code changes
model.config      Provider/model selection (default: ollama / gemma4:e2b)
run.sh            Boots Ollama + `adk web .` on :8080 with persistent sessions
setup_venv.sh     Creates .adk_env, installs deps, pulls the Ollama model
tests/            Offline pytest suite + manual TEST-CASES.md
```

The agent does the heavy lifting through **deterministic tools** rather than
stuffing the whole rulebook into the prompt — which keeps results reliable even
on small local models like `gemma4:e2b`.

## Quick start

Prerequisites: Python 3.9+ and [Ollama](https://ollama.com).

```bash
cd adk_in_local
chmod +x setup_venv.sh run.sh
./setup_venv.sh                 # venv + deps + pulls the model from model.config
./run.sh                        # boots Ollama + ADK Web UI
```

Open <http://localhost:8080>, pick the **`optimizer`** agent, and ask:

> I am spending Rs.1,50,000 on a MacBook Pro at an Apple Store. Which card?

You'll get:

- **The Winner** — the recommended card
- **The Reward** — approximate % / value back
- **The Logic** — why it wins (including any cap/threshold note)
- **The Live Update** — anything new found via web search

`./run.sh --clean` wipes the session DB (resets the cap/spend tracker).

## Switching models

Edit `model.config`. Default is local/offline:

```
MODEL_PROVIDER=ollama
MODEL_NAME=gemma4:e2b
```

Use any tool-calling Ollama model (`qwen2.5:7b`, `llama3.1:8b`, `mistral:7b`,
`gemma4`). To use Gemini instead, switch `MODEL_PROVIDER=gemini`,
`MODEL_NAME=gemini-2.5-flash`, and set `GOOGLE_API_KEY` in `.env` (note: this is
no longer offline).

## Testing

```bash
source .adk_env/bin/activate
python -m pytest tests/ -q      # deterministic, offline
```

See [`tests/TEST-CASES.md`](tests/TEST-CASES.md) for the end-to-end prompts.

## Notes

- Card data reflects the user's **April 2026** matrix; the live search surfaces
  newer changes at query time.
- "UniCard" in the movie rule maps to **Uni GoldX** (the card carrying the 50%
  PVR/INOX benefit).
