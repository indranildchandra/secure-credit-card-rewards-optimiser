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


def _card(card: dict) -> dict:
    """Wrap a single card body in a minimal, otherwise-valid config."""
    return {"cards": {"X": card}, "decision_matrix": []}


def test_annual_spend_milestone_requires_target():
    # Missing target -> would default to 0 and report "milestone reached" on Rs.0.
    problems = validate_config(_card({"tracker": {"type": "annual_spend_milestone"}}))
    assert any("target" in p for p in problems)
    # A non-positive target is equally broken.
    problems = validate_config(
        _card({"tracker": {"type": "annual_spend_milestone", "target": 0}})
    )
    assert any("target" in p for p in problems)
    # A well-formed tracker passes.
    assert (
        validate_config(
            _card({"tracker": {"type": "annual_spend_milestone", "target": 700000}})
        )
        == []
    )


def test_monthly_spend_threshold_requires_threshold():
    problems = validate_config(_card({"tracker": {"type": "monthly_spend_threshold"}}))
    assert any("threshold" in p for p in problems)
    assert (
        validate_config(
            _card({"tracker": {"type": "monthly_spend_threshold", "threshold": 20000}})
        )
        == []
    )


def test_combined_monthly_cashback_requires_cap_rate_categories():
    # All three sub-fields missing -> three distinct problems.
    problems = validate_config(
        _card({"tracker": {"type": "combined_monthly_cashback"}})
    )
    assert any("cap_value" in p for p in problems)
    assert any("rate" in p for p in problems)
    assert any("categories" in p for p in problems)

    # rate out of the 0..1 fraction range is rejected.
    problems = validate_config(
        _card(
            {
                "tracker": {
                    "type": "combined_monthly_cashback",
                    "cap_value": 1000,
                    "rate": 10,
                    "categories": ["dining"],
                }
            }
        )
    )
    assert any("rate" in p for p in problems)

    # Empty categories list is rejected.
    problems = validate_config(
        _card(
            {
                "tracker": {
                    "type": "combined_monthly_cashback",
                    "cap_value": 1000,
                    "rate": 0.1,
                    "categories": [],
                }
            }
        )
    )
    assert any("categories" in p for p in problems)

    # A well-formed tracker passes.
    assert (
        validate_config(
            _card(
                {
                    "tracker": {
                        "type": "combined_monthly_cashback",
                        "cap_value": 1000,
                        "rate": 0.1,
                        "categories": ["dining", "grocery"],
                    }
                }
            )
        )
        == []
    )


def test_min_txn_must_be_number():
    problems = validate_config(_card({"min_txn": "2000"}))
    assert any("min_txn" in p for p in problems)
    assert validate_config(_card({"min_txn": 2000})) == []


def test_forex_markup_pct_must_be_number():
    problems = validate_config(_card({"forex_markup_pct": "0"}))
    assert any("forex_markup_pct" in p for p in problems)
    assert validate_config(_card({"forex_markup_pct": 0.0})) == []


def test_list_of_string_fields_reject_bare_string():
    for field in ("no_reward_categories", "aliases"):
        problems = validate_config(_card({field: "rent"}))
        assert any(field in p for p in problems)
        assert validate_config(_card({field: ["rent"]})) == []


def test_top_keywords_must_be_list_of_strings():
    problems = validate_config(
        _card(
            {
                "value_back": {
                    "top_rate": 5.0,
                    "base_rate": 1.0,
                    "top_keywords": "amazon",
                }
            }
        )
    )
    assert any("top_keywords" in p for p in problems)
    assert (
        validate_config(
            _card(
                {
                    "value_back": {
                        "top_rate": 5.0,
                        "base_rate": 1.0,
                        "top_keywords": ["amazon"],
                    }
                }
            )
        )
        == []
    )


def test_fee_waiver_annual_spend_must_be_number_when_present():
    problems = validate_config(_card({"fee_waiver": {"annual_spend": "1 Lakh"}}))
    assert any("annual_spend" in p for p in problems)
    # null (no spend-based waiver) and absence are both allowed.
    assert validate_config(_card({"fee_waiver": {"annual_spend": None}})) == []
    assert validate_config(_card({"fee_waiver": {"lifetime_free": True}})) == []
    assert validate_config(_card({"fee_waiver": {"annual_spend": 100000}})) == []


def test_real_shipped_config_file_validates():
    # Load config/cards.config straight from disk and validate its raw contents.
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "config", "cards.config")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert validate_config(raw) == []
