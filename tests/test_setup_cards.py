"""Offline smoke tests for the card-onboarding CLI (setup_cards.py).

These exercise the wiring and the --once / run_once plumbing WITHOUT calling the
model: the actual agent reply (which needs a running Ollama) is monkeypatched.
"""

from types import SimpleNamespace

import pytest

import setup_cards


def test_agent_wiring():
    assert setup_cards.root_agent.name == "card_setup"
    # ddg_search + the four config-writer tools (list/save/add_rule/remove).
    assert len(setup_cards.root_agent.tools) == 5
    # The confirm-before-write gate must be wired.
    assert setup_cards.root_agent.before_tool_callback is not None


def _ctx(user_text):
    return SimpleNamespace(
        user_content=SimpleNamespace(parts=[SimpleNamespace(text=user_text)])
    )


def test_is_affirmative_word_boundary():
    assert setup_cards._is_affirmative("yes, save it")
    assert setup_cards._is_affirmative("go ahead")
    assert setup_cards._is_affirmative("looks good to me")
    # 'yesterday' must NOT count as 'yes'.
    assert not setup_cards._is_affirmative("yesterday I spent 5000 at Croma")
    assert not setup_cards._is_affirmative("tell me about my HSBC card")


def test_is_affirmative_negation_aware():
    # F10 regression: a negated message must NOT count as confirmation, even
    # though it contains an affirmation token like "correct"/"approve"/"save".
    assert not setup_cards._is_affirmative("no, that's not correct")
    assert not setup_cards._is_affirmative("this is not ok, don't save it")
    assert not setup_cards._is_affirmative("do not approve this")
    assert not setup_cards._is_affirmative("wrong, cancel that")


def test_write_gate_blocks_without_confirmation():
    tool = SimpleNamespace(name="save_card")
    result = setup_cards.require_confirmation_before_write(
        tool, {"card_json": "{}"}, _ctx("research my HDFC card")
    )
    assert result is not None and result.get("blocked") is True


def test_write_gate_allows_with_confirmation():
    tool = SimpleNamespace(name="save_card")
    assert (
        setup_cards.require_confirmation_before_write(
            tool, {"card_json": "{}"}, _ctx("yes, save it please")
        )
        is None
    )


def test_write_gate_ignores_non_write_tools():
    tool = SimpleNamespace(name="ddg_search")
    assert (
        setup_cards.require_confirmation_before_write(
            tool, {"query": "x"}, _ctx("anything")
        )
        is None
    )


def test_build_runner_creates_session():
    # No model call — just constructs the runner and creates a session.
    runner = setup_cards.build_runner()
    assert runner is not None
    assert hasattr(runner, "session_service")


def test_run_once_plumbing(monkeypatch):
    monkeypatch.setattr(
        setup_cards, "_agent_reply", lambda runner, text: f"echo:{text}"
    )
    assert setup_cards.run_once("hello") == "echo:hello"


def test_main_once_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        setup_cards, "_agent_reply", lambda runner, text: f"echo:{text}"
    )
    setup_cards.main(["--once", "I have an Amazon Pay ICICI card"])
    out = capsys.readouterr().out
    assert "echo:I have an Amazon Pay ICICI card" in out


def test_run_once_empty_raises(monkeypatch):
    # No model running -> empty reply -> a clear, typed error (not a traceback).
    monkeypatch.setattr(setup_cards, "_agent_reply", lambda runner, text: "")
    with pytest.raises(setup_cards.ModelUnavailable):
        setup_cards.run_once("hello")


def test_main_once_empty_exits_gracefully(monkeypatch, capsys):
    monkeypatch.setattr(setup_cards, "_agent_reply", lambda runner, text: "")
    with pytest.raises(SystemExit) as exc:
        setup_cards.main(["--once", "hello"])
    assert exc.value.code == 1
    assert "Could not get a response" in capsys.readouterr().out
