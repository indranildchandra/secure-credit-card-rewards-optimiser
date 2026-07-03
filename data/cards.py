"""
Credit card knowledge base loader.

The actual card data lives in ``config/cards.config`` (JSON) so it can be edited
and maintained without touching any Python. This module loads that config and
exposes three structures used by the deterministic tools:

* ``CARDS``           — the "Full Card Reference": each card's rewards, fees and
                        milestones (human-readable), plus two machine-readable
                        blocks the tools consume: ``value_back`` (top/base reward
                        rates) and an optional ``tracker`` (cap/threshold spec).
* ``DECISION_MATRIX`` — the "Which Card?" routing table: ordered category rules
                        mapping a merchant/category (+ optional amount band) to a
                        primary card and strategy, with fallbacks where relevant.
* ``CARD_ALIASES``    — lowercased name/alias -> canonical card name (for fuzzy
                        lookup); derived from ``CARDS``.

To add or edit a card or routing rule, edit ``config/cards.config`` only.
Data was refreshed JULY 2026 against current issuer terms; the optimiser also
performs a live web search at query time to surface any newer offers/devaluations.
"""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "cards.config")

_VALID_TRACKER_TYPES = {
    "combined_monthly_cashback",
    "monthly_spend_threshold",
    "annual_spend_milestone",
}


def _is_number(x) -> bool:
    """True for a real numeric value (ints/floats), excluding bools."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_str_list(x) -> bool:
    """True for a list whose every element is a string (empty list allowed)."""
    return isinstance(x, list) and all(isinstance(item, str) for item in x)


def validate_config(data: dict) -> list:
    """Return a list of human-readable problems with a cards.config structure.

    Empty list == valid. Used to fail fast (with a clear message) on a malformed
    config instead of a confusing crash deep inside a tool at query time.
    """
    problems = []
    cards = data.get("cards")
    matrix = data.get("decision_matrix")
    if not isinstance(cards, dict):
        problems.append("top-level 'cards' must be an object")
        cards = {}
    if not isinstance(matrix, list):
        problems.append("top-level 'decision_matrix' must be a list")
        matrix = []

    for name, card in (cards.items() if isinstance(cards, dict) else []):
        if not isinstance(card, dict):
            problems.append(f"card '{name}' must be an object")
            continue
        vb = card.get("value_back")
        if vb is not None:
            if not isinstance(vb, dict) or not all(
                isinstance(vb.get(k), (int, float)) for k in ("top_rate", "base_rate")
            ):
                problems.append(
                    f"card '{name}': value_back needs numeric top_rate and base_rate"
                )
            elif vb.get("top_keywords") is not None and not _is_str_list(
                vb.get("top_keywords")
            ):
                problems.append(
                    f"card '{name}': value_back.top_keywords must be a list of strings"
                )
        tr = card.get("tracker")
        if tr is not None:
            ttype = tr.get("type") if isinstance(tr, dict) else None
            if ttype not in _VALID_TRACKER_TYPES:
                problems.append(
                    f"card '{name}': tracker.type must be one of "
                    f"{sorted(_VALID_TRACKER_TYPES)}"
                )
            elif ttype == "annual_spend_milestone":
                target = tr.get("target")
                if not (_is_number(target) and target > 0):
                    problems.append(
                        f"card '{name}': tracker '{ttype}' needs a positive numeric "
                        "'target'"
                    )
            elif ttype == "monthly_spend_threshold":
                threshold = tr.get("threshold")
                if not (_is_number(threshold) and threshold > 0):
                    problems.append(
                        f"card '{name}': tracker '{ttype}' needs a positive numeric "
                        "'threshold'"
                    )
            elif ttype == "combined_monthly_cashback":
                cap_value = tr.get("cap_value")
                if not (_is_number(cap_value) and cap_value > 0):
                    problems.append(
                        f"card '{name}': tracker '{ttype}' needs a positive numeric "
                        "'cap_value'"
                    )
                rate = tr.get("rate")
                if not (_is_number(rate) and 0 < rate <= 1):
                    problems.append(
                        f"card '{name}': tracker '{ttype}' needs a numeric 'rate' "
                        "as a fraction between 0 and 1"
                    )
                if not (_is_str_list(tr.get("categories")) and tr.get("categories")):
                    problems.append(
                        f"card '{name}': tracker '{ttype}' needs a non-empty "
                        "'categories' list of strings"
                    )

        min_txn = card.get("min_txn")
        if min_txn is not None and not _is_number(min_txn):
            problems.append(f"card '{name}': min_txn must be a number")

        forex = card.get("forex_markup_pct")
        if forex is not None and not _is_number(forex):
            problems.append(f"card '{name}': forex_markup_pct must be a number")

        for field in ("no_reward_categories", "aliases"):
            value = card.get(field)
            if value is not None and not _is_str_list(value):
                problems.append(f"card '{name}': {field} must be a list of strings")

        fw = card.get("fee_waiver")
        if isinstance(fw, dict):
            annual_spend = fw.get("annual_spend")
            if annual_spend is not None and not _is_number(annual_spend):
                problems.append(
                    f"card '{name}': fee_waiver.annual_spend must be a number "
                    "when present"
                )

    for i, rule in enumerate(matrix):
        if not isinstance(rule, dict):
            problems.append(f"decision_matrix[{i}] must be an object")
            continue
        if not rule.get("category") or not isinstance(rule.get("category"), str):
            problems.append(f"decision_matrix[{i}] needs a string 'category'")
        if not isinstance(rule.get("keywords"), list) or not rule.get("keywords"):
            problems.append(f"decision_matrix[{i}] needs a non-empty 'keywords' list")
        primary = rule.get("primary")
        if primary not in cards:
            problems.append(
                f"decision_matrix[{i}] primary '{primary}' is not a known card"
            )
    return problems


with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _data = json.load(_f)

_problems = validate_config(_data)
if _problems:
    raise ValueError("Invalid config/cards.config:\n- " + "\n- ".join(_problems))

CARDS = _data["cards"]
DECISION_MATRIX = _data["decision_matrix"]

# Convenience: lowercased name -> canonical name (incl. aliases) for fuzzy lookup.
CARD_ALIASES = {}
for _canonical, _card in CARDS.items():
    CARD_ALIASES[_canonical.lower()] = _canonical
    for _alias in _card.get("aliases", []):
        CARD_ALIASES[_alias.lower()] = _canonical
