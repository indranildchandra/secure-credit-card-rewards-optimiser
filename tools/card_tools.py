"""
Deterministic card-lookup tools for the optimiser agent.

These are plain Python functions (ADK exposes them as callable tools). They do
all the routing and arithmetic so the LLM only has to orchestrate and explain —
which keeps results reliable on small local models.

All functions return JSON-serialisable dicts/lists.
"""

import re
from typing import Optional

from data.cards import CARDS, CARD_ALIASES, DECISION_MATRIX


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Whole-word(s) match, so 'eat' does not match 'great' and 'gold' does not
    match 'goldman'. Multi-word keywords (e.g. 'food delivery') match as a unit."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _resolve_card_name(card_name: str) -> Optional[str]:
    """Map a possibly-fuzzy card name to its canonical key in CARDS.

    Matching is ordered from most to least precise to avoid loose mis-matches:
      1. exact alias (incl. canonical names);
      2. a known alias appearing in full inside the query
         (e.g. "use my hsbc live+ card" -> "HSBC Live+");
      3. a reasonably specific query (>= 4 chars) contained in an alias
         (e.g. "amex" -> "Amex Platinum Travel");
      4. all query tokens are tokens of a single card's canonical name.
    """
    if not card_name:
        return None
    key = card_name.strip().lower()

    # 1. exact match.
    if key in CARD_ALIASES:
        return CARD_ALIASES[key]

    # 2. a full alias appears inside the query.
    for alias, canonical in CARD_ALIASES.items():
        if alias in key:
            return canonical

    # 3. a specific-enough query is contained in an alias.
    if len(key) >= 4:
        for alias, canonical in CARD_ALIASES.items():
            if key in alias:
                return canonical

    # 4. whole-token overlap (every query token is a token of the card name).
    key_toks = set(key.split())
    for canonical in CARDS:
        if key_toks and key_toks <= set(canonical.lower().split()):
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
        hits = [kw for kw in rule["keywords"] if _keyword_in_text(kw, text)]
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
        dict with ``card``, ``amount``, ``rate_pct``, ``approx_value_rupees``,
        ``eligible`` and a ``basis`` explanation, or an ``error`` for unknown cards.
    """
    canonical = _resolve_card_name(card_name)
    if not canonical:
        return {"error": f"Unknown card: {card_name}"}

    card = CARDS[canonical]
    cat = (category or "").lower()

    # Eligibility first (config-driven): some cards earn NOTHING below a minimum
    # transaction value, or on excluded categories. Without this, a Rs.1,000 UPI
    # spend would wrongly score Axis RuPay (which needs Rs.2,000) as earning.
    min_txn = card.get("min_txn", 0)
    excluded = [c.lower() for c in card.get("no_reward_categories", [])]
    if min_txn and amount < min_txn:
        return {
            "card": canonical,
            "amount": amount,
            "rate_pct": 0.0,
            "approx_value_rupees": 0.0,
            "eligible": False,
            "basis": f"earns no rewards below the Rs.{min_txn:,.0f} minimum.",
        }
    if excluded and any(_keyword_in_text(x, cat) for x in excluded):
        return {
            "card": canonical,
            "amount": amount,
            "rate_pct": 0.0,
            "approx_value_rupees": 0.0,
            "eligible": False,
            "basis": "this category earns no rewards on this card.",
        }

    # Value-back rates come from the card's "value_back" block in cards.config:
    #   {top_rate, top_keywords, base_rate}
    # — the category top rate applies when the category matches a top keyword,
    # otherwise the base rate. Fully config-driven; no card names hardcoded here.
    vb = card.get("value_back", {})
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
        "eligible": True,
        "basis": ("category top rate" if matched_top else "base rate")
        + " — approximate; verify exact terms with get_card_details/ddg_search.",
    }


def compare_cards_for_spend(
    merchant_or_category: str, amount: float, top_n: int = 3, tool_context=None
) -> dict:
    """Rank the whole portfolio for a spend and return the top N cards by value.

    Use this for "show me the top 3 cards for this" style questions. Every card is
    scored with its configured value-back rate for the category (cards that earn
    nothing for this spend — below a minimum or an excluded category — score 0 and
    sink). When session state is available, a card whose bonus-category cap is
    already exhausted this month is scored at its base rate. The decision-matrix
    primary is flagged so you can call out routing nuances the raw value ranking
    doesn't capture.

    Args:
        merchant_or_category: Where/what the spend is (e.g. "Swiggy", "Amazon").
        amount: Transaction amount in Rupees.
        top_n: How many cards to return (default 3; clamped to 1..number of cards).

    Returns:
        dict with ``query``, ``amount``, ``matrix_primary`` (the matrix's pick),
        and ``top`` — a ranked list of
        {rank, card, rate_pct, approx_value_rupees, is_matrix_primary}.
    """
    matrix = find_cards_for_category(merchant_or_category, amount)
    primary = matrix["matches"][0]["primary"] if matrix["matches"] else None

    ranked = []
    for name in CARDS:
        ev = estimate_reward_value(name, amount, merchant_or_category)
        rate = ev["rate_pct"]
        value = ev["approx_value_rupees"]
        # Cap-aware down-ranking: if this card's combined cashback cap is already
        # exhausted, its bonus categories now earn only the base rate.
        if tool_context is not None and ev.get("eligible", True):
            from tools.spend_tracker import check_cap_status  # lazy: avoid cycle

            cap = check_cap_status(tool_context, name)
            if cap.get("exhausted"):
                base = CARDS[name].get("value_back", {}).get("base_rate", rate)
                if rate > base:
                    rate = base
                    value = round(amount * base / 100.0, 2)
        ranked.append(
            {
                "card": name,
                "rate_pct": rate,
                "approx_value_rupees": value,
                "is_matrix_primary": name == primary,
            }
        )
    # Sort by value, then keep the matrix primary ahead of ties.
    ranked.sort(
        key=lambda r: (r["approx_value_rupees"], r["is_matrix_primary"]), reverse=True
    )

    n = max(1, min(int(top_n) if top_n else 3, len(ranked)))
    top = []
    for i, row in enumerate(ranked[:n], 1):
        top.append({"rank": i, **row})

    return {
        "query": merchant_or_category,
        "amount": amount,
        "matrix_primary": primary,
        "top": top,
    }
