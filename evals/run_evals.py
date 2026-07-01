#!/usr/bin/env python3
"""
Run the agent-level evals and print a pass/fail report.

    python evals/run_evals.py

Requires Ollama running with the model in config/model.config. Exit code is the
number of failures (0 = all passed), so it can gate CI/releases when a model is
available.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.cases import EVAL_CASES  # noqa: E402
from evals.harness import ollama_available, run_all  # noqa: E402


def main() -> None:
    if not ollama_available():
        print("Ollama is not reachable on :11434 — start it (`ollama serve`) first.")
        sys.exit(2)

    results = run_all(EVAL_CASES)
    failures = 0
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            failures += 1
        print(f"[{status}] expect {r['expect']!r} — {r['prompt']}")
        if not r["passed"]:
            print(f"         got: {r['answer'][:160]!r}")

    total = len(results)
    print(f"\n{total - failures}/{total} passed.")
    sys.exit(failures)


if __name__ == "__main__":
    main()
