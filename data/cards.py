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

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _data = json.load(_f)

CARDS = _data["cards"]
DECISION_MATRIX = _data["decision_matrix"]

# Convenience: lowercased name -> canonical name (incl. aliases) for fuzzy lookup.
CARD_ALIASES = {}
for _canonical, _card in CARDS.items():
    CARD_ALIASES[_canonical.lower()] = _canonical
    for _alias in _card.get("aliases", []):
        CARD_ALIASES[_alias.lower()] = _canonical
