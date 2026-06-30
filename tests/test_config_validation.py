"""Tests for the cards.config structural validator (fail-fast on bad config)."""

from data.cards import validate_config


def test_shipped_config_is_valid():
    # The real loaded config must validate (it loaded at import without raising).
    import data.cards as dc

    assert (
        validate_config({"cards": dc.CARDS, "decision_matrix": dc.DECISION_MATRIX})
        == []
    )


def test_missing_top_level_keys():
    problems = validate_config({})
    assert any("cards" in p for p in problems)
    assert any("decision_matrix" in p for p in problems)


def test_bad_value_back():
    problems = validate_config(
        {"cards": {"X": {"value_back": {"top_rate": "high"}}}, "decision_matrix": []}
    )
    assert any("value_back" in p for p in problems)


def test_bad_tracker_type():
    problems = validate_config(
        {"cards": {"X": {"tracker": {"type": "nope"}}}, "decision_matrix": []}
    )
    assert any("tracker.type" in p for p in problems)


def test_rule_unknown_primary():
    problems = validate_config(
        {
            "cards": {"X": {}},
            "decision_matrix": [
                {"category": "C", "keywords": ["c"], "primary": "Ghost"}
            ],
        }
    )
    assert any("not a known card" in p for p in problems)


def test_rule_missing_keywords():
    problems = validate_config(
        {"cards": {"X": {}}, "decision_matrix": [{"category": "C", "primary": "X"}]}
    )
    assert any("keywords" in p for p in problems)
