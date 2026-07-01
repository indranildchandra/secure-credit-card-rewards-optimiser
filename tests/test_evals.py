"""Agent-level (end-to-end) eval tests.

These run the REAL optimiser agent, so they need a running Ollama with the
configured model. They are automatically skipped when Ollama isn't reachable
(e.g. in CI / the fast offline suite), and skipped per-case if the model returns
nothing. Run them locally after `./run.sh` has pulled the model.
"""

import pytest

from evals.cases import EVAL_CASES
from evals.harness import ollama_available, ask, winner_matches

pytestmark = pytest.mark.skipif(
    not ollama_available(), reason="Ollama not reachable — end-to-end evals skipped"
)

# A representative subset for the automated gate (the full set lives in
# evals/cases.py and is runnable via evals/run_evals.py).
_SUBSET = EVAL_CASES[:4]


@pytest.mark.parametrize("case", _SUBSET, ids=[c["expect"] for c in _SUBSET])
def test_agent_picks_expected_card(case):
    answer = ask(case["prompt"])
    if not answer:
        pytest.skip("model returned no answer (not pulled / not ready)")
    assert winner_matches(
        answer, case["expect"]
    ), f"expected {case['expect']!r} in answer, got: {answer[:200]!r}"
