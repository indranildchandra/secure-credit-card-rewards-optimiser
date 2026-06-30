"""
Tools for writing to config/cards.config — used by the card-onboarding agent
(``scripts/setup_cards.py``) to persist researched cards and routing rules.

These read and write the JSON config file directly (atomically) rather than the
in-memory ``data.cards`` snapshot, so each call sees and saves the latest state.
They validate input and return clear messages so a small model can self-correct.
"""

import json
import os
import tempfile

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "cards.config")

_VALID_TRACKER_TYPES = {
    "combined_monthly_cashback",
    "monthly_spend_threshold",
    "annual_spend_milestone",
}


def _load() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(cfg: dict) -> None:
    # Atomic write: write to a temp file in the same dir, then replace.
    cfg_dir = os.path.dirname(os.path.abspath(_CONFIG_PATH))
    fd, tmp = tempfile.mkstemp(dir=cfg_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, _CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def list_configured_cards() -> dict:
    """List the cards currently saved in config/cards.config.

    Returns:
        dict with ``count`` and ``cards`` (list of names), so you can avoid
        duplicates and report progress while onboarding.
    """
    cfg = _load()
    names = list(cfg.get("cards", {}).keys())
    return {"count": len(names), "cards": names}


def save_card(card_json: str) -> str:
    """Create or update one card in config/cards.config.

    Args:
        card_json: A JSON object (as a string) for a single card. Required key:
            ``name``. Recommended keys (matching the config schema):
              - ``rewards``: list of human-readable reward lines
              - ``fees``, ``milestones``: optional human-readable strings
              - ``value_back``: {"top_rate": float, "top_keywords": [str],
                                 "base_rate": float}
              - ``tracker``: optional, one of the supported types
              - ``fee_waiver``: optional, {"annual_spend": int, "fee": str} or
                                {"lifetime_free": true}
              - ``aliases``: optional list of alternative names

            Example:
            {"name": "My Card", "rewards": ["2% on all spends"],
             "value_back": {"top_rate": 2.0, "top_keywords": [], "base_rate": 2.0},
             "fee_waiver": {"lifetime_free": true}}

    Returns:
        A confirmation string, or a validation error describing what to fix.
    """
    try:
        card = json.loads(card_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}. Pass a single JSON object for one card."
    if not isinstance(card, dict):
        return "Expected a JSON object for one card (got something else)."

    name = card.pop("name", None)
    if not name or not isinstance(name, str):
        return "Card is missing a string 'name' field."

    vb = card.get("value_back")
    if vb is not None:
        if not isinstance(vb, dict) or "top_rate" not in vb or "base_rate" not in vb:
            return (
                "value_back must be an object with numeric 'top_rate' and 'base_rate'."
            )
        vb.setdefault("top_keywords", [])

    tracker = card.get("tracker")
    if tracker is not None:
        ttype = tracker.get("type") if isinstance(tracker, dict) else None
        if ttype not in _VALID_TRACKER_TYPES:
            return (
                f"tracker.type must be one of {sorted(_VALID_TRACKER_TYPES)}; "
                f"got {ttype!r}."
            )

    cfg = _load()
    cfg.setdefault("cards", {})
    action = "Updated" if name in cfg["cards"] else "Added"
    cfg["cards"][name] = card
    _save(cfg)
    return f"{action} card '{name}' in config/cards.config."


def add_decision_rule(rule_json: str) -> str:
    """Add a routing rule to the decision matrix in config/cards.config.

    Args:
        rule_json: A JSON object (as a string) for one routing rule. Required:
            ``category`` (str), ``keywords`` (list of str), ``primary`` (str —
            an existing card name). Optional: ``strategy`` (str),
            ``fallback`` (str), ``min_amount`` (number), ``max_amount`` (number).

            Example:
            {"category": "Fuel", "keywords": ["fuel", "petrol", "diesel"],
             "primary": "My Card", "strategy": "1% surcharge waiver"}

    Returns:
        A confirmation string, or a validation error describing what to fix.
    """
    try:
        rule = json.loads(rule_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}. Pass a single JSON object for one rule."
    if not isinstance(rule, dict):
        return "Expected a JSON object for one routing rule."

    for req in ("category", "primary"):
        if not rule.get(req) or not isinstance(rule[req], str):
            return f"Rule is missing a string '{req}' field."
    if not isinstance(rule.get("keywords"), list) or not rule["keywords"]:
        return "Rule needs a non-empty 'keywords' list."

    cfg = _load()
    known = set(cfg.get("cards", {}).keys())
    if rule["primary"] not in known:
        return (
            f"primary '{rule['primary']}' is not a known card. Save the card first "
            f"with save_card, or check the name. Known: {sorted(known)}"
        )

    cfg.setdefault("decision_matrix", [])
    # Replace an existing rule with the same category, else append.
    replaced = False
    for i, existing in enumerate(cfg["decision_matrix"]):
        if existing.get("category", "").lower() == rule["category"].lower():
            cfg["decision_matrix"][i] = rule
            replaced = True
            break
    if not replaced:
        cfg["decision_matrix"].append(rule)
    _save(cfg)
    verb = "Replaced" if replaced else "Added"
    return f"{verb} routing rule '{rule['category']}' → {rule['primary']}."
