# CLAUDE.md

This repository uses **[AGENTS.md](AGENTS.md)** as the single source of truth for
project context, conventions, and contribution rules. Please follow it.

@AGENTS.md

## Claude Code specifics

- A `SessionStart` hook (`.claude/hooks/session-start.sh`, registered in
  `.claude/settings.json`) bootstraps the environment in Claude Code on the web.
  It delegates to `scripts/setup-env.sh`, the same script every other tool uses.
- It runs only in remote (web) sessions; local sessions are skipped.
