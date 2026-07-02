"""
Deterministic card-lookup tools for the optimiser agent.

These are plain Python functions (ADK exposes them as callable tools). They do
all the routing and arithmetic so the LLM only has to orchestrate and explain —
which keeps results reliable on small local models.

All functions return JSON-serialisable dicts/lists.
"""

import logging
import re
from typing import Optional

from google.adk.tools import ToolContext

from data.cards import CARDS, CARD_ALIASES, DECISION_MATRIX

logger = logging.getLogger("optimizer.card_tools")

# Default international markup (%) for cards that don't override it in config.
_DEFAULT_FOREX_MARKUP_PCT = 3.5


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


def _all_matching_card_names(card_name: str) -> list:
    """Every canonical card a fuzzy reference could mean (for disambiguation).

    Same precision tiers as ``_resolve_card_name`` but COLLECTS every card at the
    first tier that produces a match, instead of silently returning the first.
    An exact name/alias is unambiguous (one element); an issuer/brand-only query
    like "axis", "scapia" or "hdfc" returns every card the user holds under it,
    so the caller can ask which one they mean before acting.
    """
    if not card_name:
        return []
    key = card_name.strip().lower()

    # 1. exact name/alias -> unambiguous.
    if key in CARD_ALIASES:
        return [CARD_ALIASES[key]]

    def _collect(predicate) -> list:
        out = []
        for alias, canonical in CARD_ALIASES.items():
            if predicate(alias) and canonical not in out:
                out.append(canonical)
        return out

    # 2. a full alias appears inside the query (e.g. "my axis rewards card").
    found = _collect(lambda alias: alias in key)
    # 3. a specific-enough query (>=4 chars) is contained in an alias
    #    (e.g. "axis" is inside BOTH "axis rewards" and "axis rupay").
    if not found and len(key) >= 4:
        found = _collect(lambda alias: key in alias)
    # 4. whole-token overlap (every query token is a token of a card name).
    if not found:
        key_toks = set(key.split())
        found = [c for c in CARDS if key_toks and key_toks <= set(c.lower().split())]
    return sorted(found)


def resolve_card_or_ambiguity(card_name: str):
    """Resolve a fuzzy card reference, signalling ambiguity instead of silently
    picking the first match. Returns (canonical, None) for a unique match;
    (None, ambiguity_dict) when it matches >1 card; (None, None) when it matches
    none (caller emits its own 'unknown card' error)."""
    matches = _all_matching_card_names(card_name)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, {
            "ambiguous": True,
            "query": card_name,
            "matches": matches,
            "message": (
                f"You hold more than one card matching '{card_name}'. "
                "Which did you mean: " + ", ".join(matches) + "?"
            ),
        }
    return None, None


def find_matching_cards(card_name: str) -> dict:
    """List every portfolio card a loosely-named reference could mean.

    Use this to DISAMBIGUATE before acting on a card the user named loosely. If
    they say only an issuer/brand ("Axis", "HDFC", "Scapia") and hold more than
    one such card, this returns all of them so you can ask which they mean rather
    than guessing.

    Args:
        card_name: The user's card reference, possibly ambiguous (e.g. "axis").

    Returns:
        dict with ``query``, ``matches`` (canonical card names), ``count`` and
        ``ambiguous`` (True when more than one card matches — ask the user which
        one before proceeding). ``matches`` is empty for an unknown reference.
    """
    matches = _all_matching_card_names(card_name)
    return {
        "query": card_name,
        "matches": matches,
        "count": len(matches),
        "ambiguous": len(matches) > 1,
    }


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
    candidates = []
    for idx, rule in enumerate(DECISION_MATRIX):
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
        candidates.append(
            {
                "idx": idx,
                "rule": rule,
                "kw_score": sum(len(kw) for kw in hits),
                "entry": {
                    "category": rule["category"],
                    "primary": rule["primary"],
                    "strategy": rule["strategy"],
                    "fallback": rule.get("fallback"),
                },
            }
        )

    # Rank by reward VALUE (not keyword length) so, e.g., "MacBook at Croma" routes
    # to the 10% Tata brand rule over the 2% large-misc rule — and so this pick
    # agrees with compare_cards_for_spend's value ranking. When the amount is
    # unknown we can't value-rank, so we fall back to keyword score + config order.
    if amount:
        for c in candidates:
            ev = estimate_reward_value(
                c["rule"]["primary"], amount, merchant_or_category
            )
            c["value"] = ev.get("approx_value_rupees", 0.0)
        candidates.sort(key=lambda c: (-c["value"], -c["kw_score"], c["idx"]))
    else:
        candidates.sort(key=lambda c: (-c["kw_score"], c["idx"]))
    ranked = [c["entry"] for c in candidates]

    note = ""
    if not ranked:
        note = (
            "No specific category matched. For large miscellaneous spends, "
            "consider 'Amex Platinum Travel' (milestone strategy)."
        )
    elif not amount:
        banded = [
            c
            for c in candidates
            if c["rule"].get("min_amount") or c["rule"].get("max_amount") is not None
        ]
        if len(banded) > 1:
            note = (
                "Amount unknown and this category has amount-dependent tiers "
                "(e.g. UPI) — the best card depends on the amount; ask the user. "
                "Ranked by keyword match only."
            )
        else:
            note = (
                "Amount unknown — ranked by keyword match only; this pick is "
                "amount-independent."
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
    canonical, _amb = resolve_card_or_ambiguity(card_name)
    if _amb:
        return _amb
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
    canonical, _amb = resolve_card_or_ambiguity(card_name)
    if _amb:
        return _amb
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
    # A card with NO value_back block has an UNKNOWN reward rate — be honest about
    # it (rate 0, flagged) rather than fabricating a 1% rate.
    vb = card.get("value_back")
    if not vb:
        return {
            "card": canonical,
            "amount": amount,
            "rate_pct": 0.0,
            "approx_value_rupees": 0.0,
            "eligible": False,
            "reward_unknown": True,
            "basis": "no value_back configured — reward rate unknown.",
        }
    top = vb.get("top_rate", 1.0)
    top_kw = vb.get("top_keywords", [])
    base = vb.get("base_rate", top)
    matched_top = (
        any(_keyword_in_text(kw.lower(), cat) for kw in top_kw)
        if top_kw
        else (top == base)
    )
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


def _apply_cap_to_reward(card_name: str, amount: float, ev: dict, tool_context):
    """Adjust an eligibility-aware reward estimate ``ev`` for a card's combined-
    cashback cap read from session state. Returns ``(rate_pct, value_rupees)``.

    Cards without a ``combined_monthly_cashback`` tracker, spends already at the
    base rate, or a missing ``tool_context`` are returned unchanged. When the cap
    is fully exhausted the spend earns the base rate. When it is PARTIALLY used
    (headroom remains but is smaller than this spend's eligible amount) the spend
    is valued at a BLENDED rate: the portion within the remaining eligible-spend
    headroom at the top rate, the remainder at the base rate.
    """
    rate = ev["rate_pct"]
    value = ev["approx_value_rupees"]
    if tool_context is None or not ev.get("eligible", True):
        return rate, value
    base = CARDS[card_name].get("value_back", {}).get("base_rate", rate)
    tracker = CARDS[card_name].get("tracker") or {}
    if tracker.get("type") != "combined_monthly_cashback" or rate <= base:
        return rate, value

    from tools.spend_tracker import check_cap_status  # lazy: avoid import cycle

    cap = check_cap_status(tool_context, card_name)
    if cap.get("exhausted"):
        return base, round(amount * base / 100.0, 2)

    tr_rate = tracker.get("rate", 0.0)
    cap_value = tracker.get("cap_value", 0)
    # Ceiling of eligible spend that still earns the top rate = cap / rate.
    ceiling = cap_value / tr_rate if tr_rate else 0.0
    eligible_spent = cap.get("eligible_spend_this_month", 0.0)
    headroom = max(ceiling - eligible_spent, 0.0)
    if headroom >= amount:
        return rate, value  # whole spend still fits under the cap at the top rate

    blended = round(headroom * rate / 100.0 + (amount - headroom) * base / 100.0, 2)
    blended_rate = round(blended / amount * 100.0, 2) if amount else rate
    return blended_rate, blended


def estimate_net_cost(
    card_name: str,
    amount: float,
    category: str = "",
    is_international: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Estimate the TRUE net cost of a transaction on a card: what it really costs
    you after rewards and forex markup.

        net_cost = price − reward_value + forex_markup

    This is the honest "minimise net spend" number for a single transaction.
    (Annual fees are not amortised per transaction — track those with
    check_fee_waiver_status / assess_card_value.) Reward value is eligibility-
    aware, so a card that earns nothing here contributes no reward.

    Args:
        card_name: Card to evaluate (fuzzy/alias accepted).
        amount: Transaction price in Rupees.
        category: Merchant/category hint (picks the right reward rate).
        is_international: If True, apply the card's forex markup to the price.

    Returns:
        dict with ``card``, ``amount``, ``reward_value``, ``forex_markup``,
        ``net_cost``, ``effective_rate_pct`` and ``eligible`` (or ``error``).
    """
    canonical, _amb = resolve_card_or_ambiguity(card_name)
    if _amb:
        return _amb
    if not canonical:
        return {"error": f"Unknown card: {card_name}"}

    rv = estimate_reward_value(canonical, amount, category)
    # Cap-aware reward when session state is provided (optional — existing callers
    # pass no context and see the un-capped estimate, so the schema is unaffected).
    _rate, reward = _apply_cap_to_reward(canonical, amount, rv, tool_context)
    # Forex: a missing forex_markup_pct falls back to the default, but flag that the
    # assumption was made so it's visible rather than silent.
    forex_assumed = is_international and "forex_markup_pct" not in CARDS[canonical]
    markup_pct = (
        CARDS[canonical].get("forex_markup_pct", _DEFAULT_FOREX_MARKUP_PCT)
        if is_international
        else 0.0
    )
    forex = round(amount * markup_pct / 100.0, 2)
    net = round(amount - reward + forex, 2)
    eff = round((reward - forex) / amount * 100.0, 2) if amount else 0.0
    return {
        "card": canonical,
        "amount": amount,
        "reward_value": reward,
        "forex_markup": forex,
        "forex_assumed": forex_assumed,
        "net_cost": net,
        "effective_rate_pct": eff,
        "eligible": rv.get("eligible", True),
        "reward_unknown": rv.get("reward_unknown", False),
    }


def compare_cards_for_spend(
    merchant_or_category: str,
    amount: float,
    top_n: int = 3,
    is_international: bool = False,
    tool_context: Optional[ToolContext] = None,
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
        and ``top`` — a ranked list of {rank, card, rate_pct, approx_value_rupees,
        net_cost, is_matrix_primary}, ordered by lowest net cost.
    """
    matrix = find_cards_for_category(merchant_or_category, amount)
    primary = matrix["matches"][0]["primary"] if matrix["matches"] else None

    forex_default = _DEFAULT_FOREX_MARKUP_PCT
    ranked = []
    for name in CARDS:
        ev = estimate_reward_value(name, amount, merchant_or_category)
        # Cap-aware valuation: an exhausted combined-cashback cap drops the bonus
        # category to its base rate; a PARTIALLY-used cap blends top + base rates
        # across the remaining eligible-spend headroom.
        rate, value = _apply_cap_to_reward(name, amount, ev, tool_context)
        forex_assumed = is_international and "forex_markup_pct" not in CARDS[name]
        markup_pct = (
            CARDS[name].get("forex_markup_pct", forex_default)
            if is_international
            else 0.0
        )
        forex = round(amount * markup_pct / 100.0, 2)
        net_cost = round(amount - value + forex, 2)
        ranked.append(
            {
                "card": name,
                "rate_pct": rate,
                "approx_value_rupees": value,
                "net_cost": net_cost,
                "forex_assumed": forex_assumed,
                "reward_unknown": ev.get("reward_unknown", False),
                "is_matrix_primary": name == primary,
            }
        )
    # Minimise net spend: lowest net cost wins; matrix primary breaks ties.
    ranked.sort(key=lambda r: (r["net_cost"], not r["is_matrix_primary"]))

    n = max(1, min(int(top_n) if top_n else 3, len(ranked)))
    top = [{"rank": i, **row} for i, row in enumerate(ranked[:n], 1)]

    logger.debug(
        "compare_cards_for_spend: query=%r amount=%s intl=%s -> winner=%s",
        merchant_or_category,
        amount,
        is_international,
        top[0]["card"] if top else None,
    )
    return {
        "query": merchant_or_category,
        "amount": amount,
        "matrix_primary": primary,
        "top": top,
    }
