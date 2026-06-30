# secure-credit-card-rewards-optimiser

A privacy-first credit card rewards strategist for Indian cards, powered entirely
by a locally hosted LLM (via Ollama). Ask *"I am spending Rs.X at [merchant].
Which card?"* and it recommends the card that minimises your net spend — all
reasoning happens on-device, with only a focused offer/devaluation web-search
reaching the internet.

The interface is the stock **Google ADK Web UI** — there is no custom frontend.

## Get started

Everything lives in [`adk_in_local/`](adk_in_local/). See its
[README](adk_in_local/README.md) for setup and usage. In short:

```bash
cd adk_in_local
chmod +x setup_venv.sh run.sh
./setup_venv.sh     # virtualenv + deps + pulls the local Ollama model
./run.sh            # boots Ollama + ADK Web UI at http://localhost:8080
```

Then open <http://localhost:8080> and pick the **`optimizer`** agent.

Inspired by the [ADK crash-course codelab](https://github.com/indranildchandra/adk-crash-course-codelab).
