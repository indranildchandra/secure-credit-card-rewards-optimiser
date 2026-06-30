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
Data reflects the matrix as of APRIL 2026; the optimiser performs a live web
search at query time to surface any newer offers or devaluations.
"""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "cards.config")

_VALID_TRACKER_TYPES = {
    "combined_monthly_cashback",
    "monthly_spend_threshold",
    "annual_spend_milestone",
}


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
        tr = card.get("tracker")
        if tr is not None and tr.get("type") not in _VALID_TRACKER_TYPES:
            problems.append(
                f"card '{name}': tracker.type must be one of "
                f"{sorted(_VALID_TRACKER_TYPES)}"
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
