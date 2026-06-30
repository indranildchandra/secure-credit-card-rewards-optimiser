"""
Deterministic card-lookup tools for the optimiser agent.

These are plain Python functions (ADK exposes them as callable tools). They do
all the routing and arithmetic so the LLM only has to orchestrate and explain —
which keeps results reliable on small local models.

All functions return JSON-serialisable dicts/lists.
"""

from typing import Optional

from data.cards import CARDS, CARD_ALIASES, DECISION_MATRIX


def _resolve_card_name(card_name: str) -> Optional[str]:
    """Map a possibly-fuzzy card name to its canonical key in CARDS."""
    if not card_name:
        return None
    key = card_name.strip().lower()
    if key in CARD_ALIASES:
        return CARD_ALIASES[key]
    # Substring / token match as a fallback (e.g. "amex" -> "Amex Platinum Travel").
    for alias, canonical in CARD_ALIASES.items():
        if key in alias or alias in key:
            return canonical
    for canonical in CARDS:
        toks = canonical.lower().split()
        if any(t in key for t in toks):
            return canonical
    return None


def find_cards_for_category(merchant_or_category: str, amount: float = 0.0) -> dict:
    """Find the best card(s) for a transaction from the decision matrix.

    Match the merchant/category text against the routing rules and (when the
    amount matters, e.g. UPI tiers) the transaction amount. Returns the primary
    recommendation, its strategy, any fallback, and other candidate matches.

    Args:
        merchant_or_category: Where/what the spend is, e.g. "Swiggy", "Croma",
            "UPI to a kirana store", "MacBook at Apple Store", "forex".
        amount: Transaction amount in Rupees (optional; 0 if unknown). Used to
            pick the correct band for amount-sensitive rules like UPI.

    Returns:
        dict with keys: ``query``, ``amount``, ``matches`` (ranked list of
        {category, primary, strategy, fallback}), and ``note``. If nothing
        matches, ``matches`` is empty and the note suggests the catch-all card.
    """
    text = (merchant_or_category or "").lower()
    matches = []
    for rule in DECISION_MATRIX:
        # Amount band filter.
        if amount:
            if amount < rule.get("min_amount", 0):
                continue
            if rule.get("max_amount") is not None and amount >= rule["max_amount"]:
                continue
        # Keyword match + a simple score (number of keyword hits, longer = stronger).
        hits = [kw for kw in rule["keywords"] if kw in text]
        if not hits:
            continue
        score = sum(len(kw) for kw in hits)
        matches.append(
            (
                score,
                {
                    "category": rule["category"],
                    "primary": rule["primary"],
                    "strategy": rule["strategy"],
                    "fallback": rule.get("fallback"),
                },
            )
        )

    matches.sort(key=lambda m: m[0], reverse=True)
    ranked = [m[1] for m in matches]

    note = ""
    if not ranked:
        note = (
            "No specific category matched. For large miscellaneous spends, "
            "consider 'Amex Platinum Travel' (milestone strategy)."
        )
    return {
        "query": merchant_or_category,
        "amount": amount,
        "matches": ranked,
        "note": note,
    }


def get_card_details(card_name: str) -> dict:
    """Return the full reference for a single card (rewards, caps, fees, etc.).

    Args:
        card_name: Card name (fuzzy/alias accepted, e.g. "amex", "hsbc live+").

    Returns:
        The card's reference dict plus its canonical ``name``, or an ``error``
        if the card is unknown.
    """
    canonical = _resolve_card_name(card_name)
    if not canonical:
        return {
            "error": f"Unknown card: {card_name}",
            "known_cards": list(CARDS.keys()),
        }
    return {"name": canonical, **CARDS[canonical]}


def list_all_cards() -> list:
    """List every card in the portfolio with a one-line 'when to use'.

    Returns:
        List of {name, when_to_use} dicts.
    """
    return [
        {"name": name, "when_to_use": data.get("when_to_use", "")}
        for name, data in CARDS.items()
    ]


def estimate_reward_value(card_name: str, amount: float, category: str = "") -> dict:
    """Estimate the approximate value-back for a spend on a given card.

    Uses a coarse value-back rate per card/category so the model doesn't have to
    do the arithmetic itself. This is an APPROXIMATION for ranking — exact RP
    conversion depends on redemption route (see get_card_details).

    Args:
        card_name: Card to evaluate (fuzzy/alias accepted).
        amount: Transaction amount in Rupees.
        category: Optional merchant/category hint to pick the right rate.

    Returns:
        dict with ``card``, ``amount``, ``rate_pct``, ``approx_value_rupees``
        and a ``basis`` explanation, or an ``error`` for unknown cards.
    """
    canonical = _resolve_card_name(card_name)
    if not canonical:
        return {"error": f"Unknown card: {card_name}"}

    cat = (category or "").lower()
    # Value-back rates come from the card's "value_back" block in cards.config:
    #   {top_rate, top_keywords, base_rate}
    # — the category top rate applies when the category matches a top keyword,
    # otherwise the base rate. Fully config-driven; no card names hardcoded here.
    vb = CARDS[canonical].get("value_back", {})
    top = vb.get("top_rate", 1.0)
    top_kw = vb.get("top_keywords", [])
    base = vb.get("base_rate", top)
    matched_top = any(kw.lower() in cat for kw in top_kw) if top_kw else (top == base)
    rate = top if matched_top else base
    value = round(amount * rate / 100.0, 2)
    return {
        "card": canonical,
        "amount": amount,
        "rate_pct": rate,
        "approx_value_rupees": value,
        "basis": ("category top rate" if matched_top else "base rate")
        + " — approximate; verify exact terms with get_card_details/ddg_search.",
    }
