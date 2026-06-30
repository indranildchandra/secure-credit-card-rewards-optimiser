# Secure Credit Card Rewards Optimiser

A privacy-first credit-card rewards strategist for **your own** card portfolio.
Ask **"I am spending Rs.X at [merchant]. Which card?"** and it tells you which
card minimises net spend — running entirely on a **local Gemma model via
Ollama**, so your transaction reasoning never leaves your machine.

Describe your cards once in [`data/cards.config`](data/cards.config) (see
[Configure it for your own cards](#configure-it-for-your-own-cards)) — no code
changes. The interface is the stock **Google ADK Web UI**, so there is no custom
frontend to build or trust.

## Why "secure"?

- The LLM runs **locally via Ollama** — amounts, merchants and your card mix are
  reasoned about on-device. Nothing is sent to a cloud LLM.
- The only outbound traffic is a focused **web-search step** for the latest
  offers/devaluations. The model authors that query around the *merchant + card
  names* (e.g. `"Croma Tata Neu Infinity latest offer June 2026"`) — never your
  raw sentence or amount.
- The session database (your tracked spends/caps) is stored locally in `db/` and
  is git-ignored.

## Quick start

Prerequisites: Python 3.9+ and [Ollama](https://ollama.com).

```bash
chmod +x setup_venv.sh run.sh
./setup_venv.sh        # creates .adk_env, installs deps, pulls the Ollama model
./run.sh               # boots Ollama + ADK Web UI
```

Open <http://localhost:8080>, pick the **`optimizer`** agent, and ask:

> I am spending Rs.1,50,000 on a MacBook Pro at an Apple Store. Which card?

You'll get a four-field answer:

- **The Winner** — the recommended card
- **The Reward** — approximate % / value back
- **The Logic** — why it wins (including any cap/threshold note)
- **The Live Update** — anything new found via web search

`./run.sh --clean` wipes the session DB (resets the cap/spend tracker).

## Project layout

```
optimizer/
  agent.py                 ADK root_agent — orchestrates tools, formats the answer
  system_instruction.prompt  the agent's system prompt (edit to evolve behaviour)
data/
  cards.py                 loads the knowledge base from cards.config
  cards.config             JSON: Full Card Reference + Decision Matrix (edit this)
tools/
  card_tools.py            deterministic routing / lookup / reward-estimate tools
  spend_tracker.py         session-state cap & threshold tracker
  duckduckgo_search.py     live offers/devaluation web search
config.py                  reads model.config -> MODEL (Ollama/Gemini)
model.config               provider/model selection (default: ollama / gemma4:e2b)
run.sh                     boots Ollama + `adk web .` on :8080, persistent sessions
setup_venv.sh              creates .adk_env, installs deps, pulls the model
db/                        local SQLite session store (git-ignored)
tests/                     offline pytest suite + manual TEST-CASES.md
```

The agent does the heavy lifting through **deterministic tools** rather than
stuffing the whole rulebook into the prompt — which keeps results reliable even
on small local models like `gemma4:e2b`.

## Tools and their methods

The agent is wired with the following tools (all are plain Python functions ADK
exposes as callable tools).

### `tools/card_tools.py` — deterministic routing & lookup
| Method | Signature | What it does |
|--------|-----------|--------------|
| `find_cards_for_category` | `(merchant_or_category: str, amount: float = 0.0) -> dict` | Matches the merchant/category text (and amount band) against the Decision Matrix; returns ranked `{primary, strategy, fallback}` candidates. |
| `get_card_details` | `(card_name: str) -> dict` | Returns the full reference for one card (rewards, caps, milestones, fees); fuzzy/alias name match. |
| `list_all_cards` | `() -> list` | Lists every card with a one-line "when to use". |
| `estimate_reward_value` | `(card_name: str, amount: float, category: str = "") -> dict` | Approximate ₹/% value-back for a spend, so the model doesn't do the arithmetic itself. |

### `tools/spend_tracker.py` — session-state cap & threshold tracking
Persisted to the SQLite session store (survives across turns/restarts).
| Method | Signature | What it does |
|--------|-----------|--------------|
| `record_spend` | `(tool_context, category: str, amount: float, card: str = "") -> str` | Records a spend for the current month (by category and by card). |
| `get_spend_summary` | `(tool_context) -> dict` | Returns this month's totals by category and by card. |
| `check_cap_status` | `(tool_context, card_name: str) -> dict` | Reports remaining headroom: HSBC Rs.1,000 combined monthly cashback cap, Scapia Rs.20,000 monthly lounge threshold, Amex Rs.7 Lakh annual milestone. |

### `tools/duckduckgo_search.py` — live web search
| Method | Signature | What it does |
|--------|-----------|--------------|
| `ddg_search` | `(query: str) -> str` | Free DuckDuckGo search for the latest offers/devaluations. The model authors a focused *merchant + card* query — no API key, no raw transaction text leaves the machine. |

## Configure it for your own cards

This is a generic optimiser — **bring your own portfolio by editing
`data/cards.config`**; no Python changes needed. The shipped config is just an
example set of cards. Each card has:

```jsonc
"My Card Name": {
  "rewards": ["human-readable reward lines, shown in answers"],
  "fees": "…", "milestones": "…",        // optional, human-readable
  "value_back": {                         // machine-readable reward rate
    "top_rate": 5.0,                      // % back in the bonus category
    "top_keywords": ["amazon"],           // categories that earn top_rate
    "base_rate": 1.0                      // % back on everything else
  },
  "tracker": {                            // OPTIONAL — enables cap/threshold tracking
    "type": "combined_monthly_cashback",  // one of the 3 types below
    "categories": ["dining", "grocery"],
    "rate": 0.10,
    "cap_value": 1000,
    "label": "combined monthly cashback"
  }
}
```

**Routing** lives under `decision_matrix` — ordered rules mapping merchant/
category `keywords` (and optional `min_amount`/`max_amount` bands) to a `primary`
card, `strategy`, and optional `fallback`.

**Tracker types** (declare a `tracker` block on any card to enable it):

| `type` | Fields | Tracks |
|--------|--------|--------|
| `combined_monthly_cashback` | `categories`, `rate`, `cap_value` | A cashback cap shared across categories in a month. |
| `monthly_spend_threshold` | `threshold`, `counts_cards` (optional) | A monthly spend target (optionally summing several cards). |
| `annual_spend_milestone` | `target` | Year-to-date spend toward an annual milestone. |

Other knobs:
- **Agent behaviour** — edit `optimizer/system_instruction.prompt`.
- **Model** — edit `model.config` (see below).

## Model (Gemma via Ollama)

This project targets Google's **Gemma** family running locally on Ollama. The
optimiser **requires tool calling**, which the **Gemma 4** generation supports on
Ollama (earlier Gemma generations do not, so they won't work). Set your tag in
`model.config`:

```
MODEL_PROVIDER=ollama
MODEL_NAME=gemma4:e2b
OLLAMA_API_BASE=http://localhost:11434
```

| Model tag | Approx size | Notes |
|-----------|-------------|-------|
| `gemma4:e2b` | ~7.2GB | Efficient; good for 16GB RAM machines (default). |
| `gemma4:e4b` | ~9.6GB | Higher quality; needs 16GB+ RAM. |
| `gemma4`     | —       | Alias for the current Gemma 4 default tag. |
| `gemma4:27b` | ~17GB   | Best quality; needs a large-VRAM GPU. |

## Testing

```bash
source .adk_env/bin/activate
python -m pytest tests/ -q        # deterministic, offline
```

See [`tests/TEST-CASES.md`](tests/TEST-CASES.md) for the full set of end-to-end
prompts (core routing, UPI boundaries, nuance checks, and cap-aware flows).

## Linting & formatting

[ruff](https://docs.astral.sh/ruff/) (linter) and
[black](https://black.readthedocs.io/) (formatter) are installed with the
dependencies (config in `pyproject.toml`):

```bash
source .adk_env/bin/activate
ruff check .       # lint
black .            # format (or `black --check .` to verify only)
```

## Notes

- The card data is just an example portfolio — replace it with your own in
  `data/cards.config`. Reward programs change often, so keep it current; the live
  web search helps surface recent offers/devaluations at query time.
