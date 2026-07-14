"""Agent-level (end-to-end) eval tests.

These run the REAL optimiser agent and call the live model, so they are SLOW and
network/model-bound. They are **opt-in**: the default ``pytest tests/`` suite
never runs them (it stays fast and fully offline even on a machine that happens
to have Ollama running). Enable them explicitly:

    RUN_LIVE_EVALS=1 python -m pytest tests/test_evals.py -q   # needs Ollama

or run the standalone report: ``python evals/run_evals.py``.
"""

import os

import pytest

from evals.cases import EVAL_CASES
from evals.harness import ollama_available, ask, winner_matches

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_EVALS"),
    reason=(
        "opt-in live-model evals (slow). Set RUN_LIVE_EVALS=1 with Ollama "
        "running, or run: python evals/run_evals.py"
    ),
)

# A representative subset for the automated gate (the full set lives in
# evals/cases.py and is runnable via evals/run_evals.py).
_SUBSET = EVAL_CASES[:4]


@pytest.mark.parametrize("case", _SUBSET, ids=[c["expect"] for c in _SUBSET])
def test_agent_picks_expected_card(case):
    # Opted in via RUN_LIVE_EVALS but Ollama isn't up — skip cleanly rather than
    # hang on a connection attempt.
    if not ollama_available():
        pytest.skip("RUN_LIVE_EVALS set but Ollama not reachable on :11434")
    answer = ask(case["prompt"])
    if not answer:
        pytest.skip("model returned no answer (not pulled / not ready)")
    assert winner_matches(
        answer, case["expect"]
    ), f"expected {case['expect']!r} in answer, got: {answer[:200]!r}"
