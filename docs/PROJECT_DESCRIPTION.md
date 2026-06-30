# Detailed Project Description

## What problem does your solution solve?

People who hold many credit cards face a small but constant optimisation problem
at the point of every purchase: **which card minimises the net cost of *this*
transaction right now?** The answer depends on a tangle of variables — per-
category reward rates, monthly cashback caps, UPI routing quirks, annual-fee
waiver thresholds, milestone math, partner-brand lists, and frequent, unannounced
devaluations.

Existing tools don't serve this moment well:

- **Expense-tracker apps** optimise for dashboards, budgeting and bill reminders;
  the "which card should I swipe?" question gets buried.
- The good ones sit **behind a paywall**, or require **full email / SMS access**
  to parse statements — a serious privacy trade-off for financial data.
- A custom LLM "assistant" solves the reasoning, but sending every transaction
  (merchant, amount, your exact card portfolio) to a **cloud LLM** re-introduces
  the same privacy problem.

**Our solution** is a local, privacy-first credit-card rewards optimiser. You ask,
in plain language, *"I'm spending ₹X at [merchant] — which card?"* and it returns
a clear recommendation — **the winning card, the approximate reward, the reasoning,
and any live offer/devaluation** — computed **entirely on your own machine**. It
also tracks cap usage, fee-waiver progress and milestones across sessions, ranks
the top-N cards for a spend, and onboards your portfolio through a natural-language
interview that researches each card's current terms for you. Card knowledge is
pure configuration, so anyone can adapt it to their own cards without writing code.

Key properties:

- **Private by construction** — transaction reasoning runs on a local model; your
  amounts and card mix never reach a cloud LLM. The only outbound traffic is a
  focused web search built from *merchant + card names* (never your raw sentence
  or amount).
- **Reliable on small models** — all routing and arithmetic happen in
  deterministic Python tools, so even a compact local model gives consistent,
  trustworthy answers.
- **Bring-your-own-cards** — the entire knowledge base (reward rates, caps,
  routing rules, fee waivers) lives in a single JSON config.

## How does it utilise Google AI technologies?

The solution is built end-to-end on Google's AI stack:

### 1. Gemma (Google's open model family) — the local reasoning engine
The agent's language model is **Gemma**, run locally via Ollama (default
`gemma4` family, which supports tool calling). Gemma performs the natural-language
understanding (parsing the transaction), tool orchestration, the offer-search
query authoring, and the final explanation — all on-device. Running an *open*
Google model locally is precisely what makes the "secure / offline" guarantee
possible: high-quality reasoning without sending data to any hosted service.

### 2. Google Agent Development Kit (ADK) — the agent framework
The whole application is an **ADK** agent:

- **`Agent` + function tools** — the optimiser is an ADK `Agent` wired to plain,
  type-hinted Python functions. ADK turns each function's signature and docstring
  into a tool schema automatically, which is how the small model reliably calls
  `find_cards_for_category`, `compare_cards_for_spend`, `check_cap_status`,
  `check_fee_waiver_status`, `estimate_reward_value`, and the web search.
- **Session state** — the spend/cap/fee-waiver tracker reads and writes
  `ToolContext.state`, which ADK persists (SQLite) across turns and restarts.
- **ADK Web UI** — the entire user interface is the **stock ADK Web UI**; there is
  no custom frontend to build or trust. ADK's `InMemoryRunner` also powers the
  natural-language onboarding CLI.
- **Provider abstraction** — ADK's model layer lets the same agent run on Gemma
  via Ollama *or* on Gemini with a one-line config change.

### 3. Gemini + Google Search grounding — optional cloud path
For users who don't need the offline guarantee, the same agent runs on **Gemini**
(`gemini-2.5-flash`) by switching one config value, and in that mode it uses
**Google Search grounding** for the live offer/devaluation check instead of the
local DuckDuckGo tool. This demonstrates the portability ADK provides across
Google's local (Gemma) and hosted (Gemini) models.

### Architecture in one line
A **Gemma** model (via Ollama) orchestrates a set of deterministic tools, exposed
and run through **Google ADK** and its Web UI, with all card knowledge as
config — delivering cloud-quality rewards advice with on-device privacy.
