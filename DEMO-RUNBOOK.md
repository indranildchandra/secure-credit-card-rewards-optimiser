# Demo Runbook — Secure Credit Card Rewards Optimiser

A stage script for a live demo (e.g. Google I/O Connect India). Everything runs
**locally** — that's the story. Total runtime: ~5–7 minutes.

> The exact card each query returns is **deterministic** (routing is code, not the
> LLM), so the *winner* below is what you'll get. The model only phrases the
> answer and does the live web-search "Live Update" line.

---

## 0. Before you go on stage (~10 min prior, on good wifi)

```bash
./scripts/demo-preflight.sh
```
This verifies Ollama, pulls `gemma4:e4b`, runs the offline suite, and **pre-warms
the model** (so your first on-stage query is instant, not a cold load). It prints
the first-query latency and a sample answer — glance at it before you walk up.

Then start the app and leave the browser open on the agent:
```bash
./run.sh            # boots Ollama + the ADK Web UI on http://localhost:8080
```
Open <http://localhost:8080>, select the **`optimizer`** agent. Zoom the browser
to ~150% so the back row can read it.

**Have ready as a safety net:** a terminal with `MODEL_PROVIDER=gemini` +
`GOOGLE_API_KEY` in `.env` (one-line switch in `config/model.config`) in case the
local model misbehaves. See §"If something breaks".

---

## 1. The hook (say this first, ~30s)

> "I hold about a dozen credit cards. Every single purchase is a tiny
> optimisation problem — which card earns the most *right now*? The apps that
> solve this want full access to my email and SMS to read my statements. So I
> built one that answers the question **entirely on my laptop** — a local Gemma
> model via Ollama, Google's ADK. My transaction data never leaves this machine.
> Watch."

---

## 2. The core flow (type these verbatim, in order)

Each returns a four-field answer: **Winner / Reward / Logic / Live Update**.

| # | Type this | Winner you'll get | What to say while it thinks |
|---|-----------|-------------------|-----------------------------|
| 1 | `I'm spending Rs.4,000 on Amazon. Which card?` | **ICICI AmazonPay** (5%) | "Simple one to start — it knows the Amazon co-brand card." |
| 2 | `I'm buying a TV at Croma for Rs.60,000. Which card?` | **Tata Neu Infinity** (10%) | "Croma is a Tata brand — it knows the *ecosystem*, 10% back, not just generic cashback." |
| 3 | `I'm spending Rs.1,50,000 on a MacBook at an Apple Store. Which card?` | **Amex Platinum Travel** | "Big-ticket, no bonus category — so it plays the ₹7-lakh annual milestone instead. That's strategy, not a lookup." |

**Beat 4 — the "true net cost" wow (international):**

| # | Type this | Winner | Say |
|---|-----------|--------|-----|
| 4 | `I'm spending Rs.1,00,000 on a trip abroad. Which card?` | **Uni GoldX** | "Here's the difference between % back and *net cost*. Most cards add a ~3.5% forex markup — ₹3,500 on this spend. Uni GoldX has **zero** forex markup, so its true net cost is ~₹3,500 lower. It optimises **net spend**, not headline rewards." |

---

## 3. The two "only-because-it's-smart" beats

**Beat 5 — reverse-prompting / it refuses to guess (safety story):**

> Type: `Use my Axis card for this.`

The agent **asks which Axis card you mean** (Axis Rewards vs Axis RuPay) instead
of guessing.

> Say: "I hold two Axis cards. A naive tool silently picks one — and might record
> a spend against the wrong card. This one **stops and asks**. When money's
> involved, guessing is a bug."

**Beat 6 — the live web check (grounding story):**

Point at the **Live Update** line on any answer above.

> Say: "That last line is a live web search — merchant and card names only, never
> my amount — checking for the latest offer or devaluation. Card terms change
> constantly; the local model reasons, the web keeps it current. And notice:
> only *'Croma Tata Neu offer 2026'* left the machine. Never the ₹60,000."

---

## 4. Optional advanced beat (only if the model's been reliable in rehearsal)

**Cap-aware memory** — multi-turn, so slightly riskier on a small model:

1. `I spent Rs.9,000 on dining and Rs.3,000 on groceries this month on my HSBC Live+.`
2. `I'm ordering Rs.800 on Swiggy. Which card?`

The agent should note HSBC's shared ₹1,000/month 10% cap is exhausted and steer
you to the fallback. If the model doesn't call the tracker cleanly, **skip it** —
don't fight it live. (You can pre-seed spends with
`python scripts/import_spends.py --csv demo.csv` before the talk to make cap
state deterministic.)

---

## 5. The close (~20s)

> "Deterministic tools for the math, a local model for the reasoning, live web
> for freshness — and my financial data never left this laptop. It's ~170 tests,
> config-driven so anyone can drop in their own cards without touching code, and
> it runs on the stock ADK Web UI. Thank you."

---

## If something breaks

- **Model gives a weird / wrong answer:** don't argue with it live — say "the
  routing is deterministic; the model just phrases it" and re-type the query
  once. The *winner* is computed by code, so a re-run is stable.
- **First query hangs (cold model):** you skipped the pre-warm — ask a throwaway
  query first, keep talking.
- **"Live Update" is slow / says 'no live data':** that's the **5-second
  bounded** web search timing out on venue wifi — it degrades gracefully and the
  recommendation still stands. Narrate it: "offline-first — if the web's flaky it
  just says 'no live data' and still answers."
- **Local model is clearly unreliable:** switch to the cloud fallback — in
  `config/model.config` set `MODEL_PROVIDER=gemini`, `MODEL_NAME=gemini-2.5-flash`,
  put `GOOGLE_API_KEY=…` in `.env`, restart `./run.sh`. Same agent, same tools,
  rock-solid tool-calling. (Trade-off: not offline — acknowledge that if asked.)

## Cheat-sheet (queries only)

```
I'm spending Rs.4,000 on Amazon. Which card?
I'm buying a TV at Croma for Rs.60,000. Which card?
I'm spending Rs.1,50,000 on a MacBook at an Apple Store. Which card?
I'm spending Rs.1,00,000 on a trip abroad. Which card?
Use my Axis card for this.
```
Expected winners: ICICI AmazonPay · Tata Neu Infinity · Amex Platinum Travel ·
Uni GoldX · (asks which Axis card).
