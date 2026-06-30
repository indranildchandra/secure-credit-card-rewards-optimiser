# GEMINI.md

This repository uses **[AGENTS.md](AGENTS.md)** as the single source of truth for
project context, conventions, and contribution rules. Please follow it.

@AGENTS.md

## Gemini CLI specifics

- A `SessionStart` hook (`.gemini/hooks/session-start.sh`, registered in
  `.gemini/settings.json`) bootstraps the environment on session start. It
  delegates to `scripts/setup-env.sh`, the same script every other tool uses.
- Use a Gemma 4 tag in `config/model.config` — the optimiser requires tool
  calling, which the Gemma 4 generation supports on Ollama.
