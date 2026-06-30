# Contributing

Thanks for your interest in improving the Secure Credit Card Rewards Optimiser!
Contributions of all kinds are welcome — new cards, routing rules, bug fixes,
docs, and features.

> Using an AI coding tool (Claude Code, Gemini CLI, etc.)? See
> [AGENTS.md](AGENTS.md) — it's the single source of truth for project
> conventions, and `CLAUDE.md` / `GEMINI.md` import it automatically.

## Getting set up

Prerequisites: Python 3.9+ and [Ollama](https://ollama.com).

```bash
# Full first-time setup (venv + deps + pulls the Gemma model):
./setup_venv.sh

# Or just the Python environment (no model pull):
./scripts/setup-env.sh

source .adk_env/bin/activate
```

Run the app with `./run.sh` and open <http://localhost:8080>.

## Adding or changing a card (no code needed)

This optimiser is **config-driven**. To add a card, change a reward rate, add a
routing rule, or define a cap/threshold, edit **`config/cards.config`** only. The
schema and the available tracker types are documented in the README under
[Configure it for your own cards](README.md#configure-it-for-your-own-cards).

Please avoid adding card-specific `if` branches in Python — express the behaviour
as config (`value_back`, `tracker`, or a `decision_matrix` rule). If something
can't be expressed in config, that's a gap worth discussing in an issue first.

## Development workflow

1. Create a branch for your change.
2. Make the change (prefer config edits where possible).
3. Add or update tests for any logic change (`tests/`).
4. Run the checks below — all must pass.
5. Open a pull request with a clear description of what and why.

## Checks to run before a PR

```bash
source .adk_env/bin/activate
ruff check .                  # lint
black .                       # format (use `black --check .` to verify only)
python -m pytest tests/ -q    # fast, fully offline
```

## Coding conventions

- Python 3.9+, formatted with **black** (line length 88), linted with **ruff**
  (config in `pyproject.toml`).
- Tools exposed to the agent are plain, type-hinted functions with clear
  docstrings; keep them deterministic and JSON-serialisable.
- Don't break the [privacy invariants](AGENTS.md#privacy-invariants-do-not-break):
  local reasoning by default, web-search queries limited to merchant + card
  names, and no secrets committed.

## Reporting issues

Open a GitHub issue with steps to reproduce, what you expected, and what
happened. For routing/reward mistakes, include the transaction prompt and the
relevant snippet of your `config/cards.config`.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
