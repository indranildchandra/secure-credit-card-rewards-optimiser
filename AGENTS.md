# AGENTS.md

Guidance for AI coding agents and human contributors working in this repo. This
is the **single source of truth**; `CLAUDE.md` and `GEMINI.md` import it so every
tool sees the same rules.

## What this project is

A local, privacy-first credit-card rewards optimiser. Given a transaction
("I'm spending ₹X at [merchant]"), it recommends the card that minimises net
spend. The LLM is a local **Gemma** model served by **Ollama**; the agent is
built on the **Google ADK** and surfaced through the stock ADK Web UI.

See [`README.md`](README.md) for the full overview and architecture diagram.

## Setup

```bash
./scripts/setup-env.sh      # create .adk_env, install deps (used by all tool hooks)
# or, for a full first-time setup including the Ollama model:
./setup_venv.sh
```

Every AI tool's SessionStart hook (`.claude/`, `.gemini/`, `.cursor/`) delegates
to `scripts/setup-env.sh`, so the environment is identical everywhere.

## Repository map

| Path | What lives here |
|------|-----------------|
| `config/cards.config` | **The card knowledge base** (JSON): Full Reference + Decision Matrix. Edit this, not code. |
| `config/model.config` | Provider/model selection (Gemma via Ollama). |
| `config/system_instruction.prompt` | The optimiser agent's system prompt. |
| `config/setup_cards_instruction.prompt` | The onboarding agent's system prompt. |
| `optimizer/agent.py` | ADK `root_agent`: wires tools, loads the prompt. |
| `scripts/setup_cards.py` | Natural-language onboarding agent: researches cards, writes `cards.config`. |
| `scripts/setup_cards.sh` | Shell wrapper for the onboarding CLI (activates the venv). |
| `scripts/import_spends.py` | Local CSV/statement import into the spend log (on-device). |
| `tools/web_search.py` | Provider-aware web-search tool factory (Gemini grounding vs Ollama/DDG). |
| `tools/spend_import.py` | CSV parsing + ADK-persist for statement import. |
| `evals/` | Agent-level (end-to-end) eval cases + runner (`run_evals.py`). |
| `setup_venv.sh` | Full first-time setup: runs `scripts/setup-env.sh`, then pulls the Ollama model. |
| `data/cards.py` | Loads `config/cards.config`; derives `CARDS`, `DECISION_MATRIX`, `CARD_ALIASES`. |
| `tools/card_tools.py` | Deterministic routing / lookup / reward / top-N compare tools. |
| `tools/spend_tracker.py` | Session-state cap, threshold & fee-waiver tracker. |
| `tools/duckduckgo_search.py` | Live offers/devaluation web search. |
| `tools/config_writer.py` | Validates + writes/removes cards in `cards.config` (onboarding). |
| `data/cards.py` (`validate_config`) | Fail-fast structural validation of `cards.config` at load. |
| `.github/workflows/ci.yml` | CI: ruff + black + pytest on push/PR. |
| `config.py` | Reads `config/model.config` → `MODEL`. |
| `tests/` | Offline pytest suite + `TEST-CASES.md`. |
| `scripts/setup-env.sh` | Shared environment bootstrap. |

## The golden rule: prefer config over code

Card behaviour is **data**. To add or change a card, a reward rate, a routing
rule, or a cap, edit `config/cards.config` — do **not** add card-specific
branches in Python. The schema and tracker types are documented in the README
("Configure it for your own cards").

If you find yourself writing `if card_name == "...":` in a tool, stop — express
it as config (`value_back`, `tracker`, or a `decision_matrix` rule) instead.

## Privacy invariants (do not break)

1. **Local reasoning only.** The default provider is Ollama. Never add a code
   path that sends transaction data to a cloud LLM by default.
2. **Web search is merchant + card only.** Web-search queries must be built from
   merchant/vendor and card names (plus a recency hint) — never the user's raw
   sentence or amounts. Keep the `system_instruction.prompt` wording that enforces
   this (covered by `tests/test_prompts.py`).
3. **Treat web results as untrusted data.** Search results may contain prompt-
   injection. The agents are instructed to treat them as reference data only. The
   only file-writing tools (`save_card` / `add_decision_rule`) live solely in the
   onboarding agent, and are guarded by a code-level `before_tool_callback`
   (`require_confirmation_before_write` in `scripts/setup_cards.py`) that blocks a
   write unless the user's latest message explicitly confirms — so a poisoned
   search result cannot trigger a silent write. Writes are confined to
   `config/cards.config` (no path traversal, no exec). Don't widen this: never
   give the main optimiser agent file-write tools.
4. **No secrets in the repo.** The default setup needs none. `db/` (the local
   session store) and `.env` are git-ignored — keep them that way.

## Memory & context

Two distinct stores — keep them separate:

- **Durable facts → ADK session state**, `user:`-scoped (`user:spend_log`). This is
  a server-side KV store in SQLite; it does **not** enter the LLM context window
  unless a tool returns it. Tracked spends/caps/milestones live here and are read
  on demand via the tracker tools (incl. `get_spend_history`), so they persist
  across turns and sessions without bloating the prompt. The store is bounded: it
  keeps only the most-recent `_RETENTION_MONTHS` (13) months — that's the eviction
  policy for the durable layer.
- **Conversation history → the context window.** This is what actually grows per
  turn. The design keeps facts out of it (tools-on-demand). For very long single
  sessions there is an opt-in sliding-window compaction
  (`optimizer/context_window.py`, wired as the optimiser's `before_model_callback`):
  set `OPTIMIZER_MAX_HISTORY_CONTENTS=<N>` to keep only the most-recent N history
  items, replacing older ones with a note that points the model back at the
  tracker tools. For heavier needs, swap the note for an LLM summary or push
  completed sessions into an ADK `MemoryService` — don't move durable data into
  the prompt.

## Coding conventions

- Python 3.9+. Format with **black** (line length 88) and lint with **ruff**;
  config in `pyproject.toml`.
- Tools exposed to the agent are plain, **type-hinted** functions with clear
  docstrings (ADK turns the signature + docstring into the tool schema). Keep
  them **deterministic** and **JSON-serialisable**.
- Session-state tools take `tool_context: ToolContext` and read/write
  `tool_context.state`.
- Match the style of the surrounding code; keep comments purposeful.

## Testing

```bash
source .adk_env/bin/activate
python -m pytest tests/ -q        # fast, fully offline (no LLM, no network)
ruff check . && black --check .   # lint + format check
```

Add or update tests for any logic change. New tracker/routing behaviour should be
covered by a config-driven test (see `tests/test_spend_tracker.py` for the
pattern that registers a card purely via config data).

## Commits & pull requests

- Before committing: `ruff check .`, `black .`, and `python -m pytest tests/ -q`
  must all pass.
- Write clear, imperative commit messages describing the change and why.
- For new cards/rules, the diff should ideally touch only `config/cards.config`.
