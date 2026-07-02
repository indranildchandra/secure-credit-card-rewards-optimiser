"""Offline unit tests for the deterministic routing/lookup tools.

No LLM and no network required — these validate that the decision matrix routes
each worked example to the right card.
"""

from tools.card_tools import (
    find_cards_for_category,
    find_matching_cards,
    get_card_details,
    list_all_cards,
    estimate_reward_value,
    estimate_net_cost,
    compare_cards_for_spend,
)


def _primary(query, amount=0.0):
    res = find_cards_for_category(query, amount)
    assert res["matches"], f"no match for {query!r} (amount={amount})"
    return res["matches"][0]["primary"]


def test_macbook_large_misc_routes_to_amex():
    assert _primary("MacBook Pro at Apple Store", 150000) == "Amex Platinum Travel"


def test_amazon_routes_to_icici():
    assert _primary("Amazon", 4000) == "ICICI AmazonPay"


def test_swiggy_routes_to_hsbc():
    assert _primary("Swiggy order", 500) == "HSBC Live+"


def test_grocery_routes_to_hsbc():
    assert _primary("grocery at supermarket", 1200) == "HSBC Live+"


def test_tata_ecosystem_routes_to_neu():
    assert _primary("Croma", 50000) == "Tata Neu Infinity"


def test_star_bazaar_routes_to_tata_star_sbi():
    assert _primary("Star Bazaar", 3000) == "Tata Star SBI Platinum"


def test_forex_routes_to_uni_goldx():
    assert _primary("international spend abroad", 20000) == "Uni GoldX"


def test_apparel_routes_to_axis_rewards():
    assert _primary("apparel at a fashion store", 5000) == "Axis Rewards"


def test_movies_route_to_uni_goldx():
    assert _primary("PVR movie tickets", 800) == "Uni GoldX"


def test_upi_low_band_routes_to_scapia_rupay():
    assert _primary("UPI payment to a merchant", 1000) == "Scapia RuPay"


def test_upi_high_band_routes_to_axis_rupay():
    assert _primary("UPI merchant payment", 3000) == "Axis RuPay"


def test_smartbuy_travel_routes_to_hdfc():
    assert _primary("hotel booking via SmartBuy", 25000) == "HDFC Regalia Gold"


def test_swiggy_fallback_present():
    res = find_cards_for_category("Swiggy", 700)
    top = res["matches"][0]
    assert top["primary"] == "HSBC Live+"
    assert top["fallback"] and "Axis Rewards" in top["fallback"]


def test_get_card_details_fuzzy():
    d = get_card_details("amex")
    assert d["name"] == "Amex Platinum Travel"
    assert "rewards" in d


def test_get_card_details_unknown():
    d = get_card_details("nonexistent card")
    assert "error" in d


def test_list_all_cards_count():
    cards = list_all_cards()
    assert len(cards) == 11
    assert all("name" in c and "when_to_use" in c for c in cards)


def test_estimate_reward_value_amazon():
    r = estimate_reward_value("ICICI AmazonPay", 10000, "amazon")
    assert r["rate_pct"] == 5.0
    assert r["approx_value_rupees"] == 500.0


def test_estimate_reward_value_base_rate():
    # Amazon card on a non-Amazon spend falls to its base rate (1%).
    r = estimate_reward_value("ICICI AmazonPay", 10000, "fuel")
    assert r["rate_pct"] == 1.0


def test_compare_cards_top_n_count_and_order():
    res = compare_cards_for_spend("amazon", 10000, top_n=3)
    assert len(res["top"]) == 3
    # ICICI AmazonPay (5% on Amazon) should top the ranking and be the primary.
    assert res["top"][0]["card"] == "ICICI AmazonPay"
    assert res["top"][0]["rank"] == 1
    assert res["matrix_primary"] == "ICICI AmazonPay"
    assert res["top"][0]["is_matrix_primary"] is True
    # Sorted by value descending.
    values = [r["approx_value_rupees"] for r in res["top"]]
    assert values == sorted(values, reverse=True)


def test_compare_cards_top_n_clamped():
    res = compare_cards_for_spend("dining", 2000, top_n=99)
    assert len(res["top"]) == 11  # clamped to the number of cards


def test_keyword_matching_is_word_boundary():
    # F2 regression: 'eat' must not match 'great', 'gold' must not match 'goldman'.
    assert find_cards_for_category("Great Clips salon", 800)["matches"] == []
    assert find_cards_for_category("goldman advisory", 5000)["matches"] == []


def test_estimate_below_min_txn_earns_nothing():
    # F1 regression: Axis RuPay needs Rs.2,000 on UPI; below that it earns 0.
    low = estimate_reward_value("Axis RuPay", 1000, "upi")
    assert low["rate_pct"] == 0.0 and low["eligible"] is False
    high = estimate_reward_value("Axis RuPay", 3000, "upi")
    assert high["rate_pct"] > 0 and high["eligible"] is True


def test_estimate_excluded_category_earns_nothing():
    r = estimate_reward_value("Axis RuPay", 5000, "rent")
    assert r["rate_pct"] == 0.0 and r["eligible"] is False


def test_compare_ranks_ineligible_card_last():
    # A Rs.1,000 UPI spend: Axis RuPay (needs Rs.2,000) must not outrank earners.
    res = compare_cards_for_spend("upi", 1000, top_n=11)
    by_card = {r["card"]: r for r in res["top"]}
    assert by_card["Axis RuPay"]["approx_value_rupees"] == 0.0
    assert res["top"][0]["approx_value_rupees"] > 0  # the winner actually earns


def test_net_cost_domestic_is_price_minus_reward():
    # Amazon Rs.10,000 on ICICI (5%) -> net = 10000 - 500 = 9500, no forex.
    r = estimate_net_cost("ICICI AmazonPay", 10000, "amazon")
    assert r["reward_value"] == 500.0
    assert r["forex_markup"] == 0.0
    assert r["net_cost"] == 9500.0


def test_net_cost_international_applies_forex():
    # Uni GoldX has 0% forex; HDFC uses the 3.5% default. On a Rs.10,000 intl
    # spend Uni GoldX should have the lower net cost.
    uni = estimate_net_cost("Uni GoldX", 10000, "forex", is_international=True)
    hdfc = estimate_net_cost(
        "HDFC Regalia Gold", 10000, "shopping", is_international=True
    )
    assert uni["forex_markup"] == 0.0
    assert hdfc["forex_markup"] == 350.0
    assert uni["net_cost"] < hdfc["net_cost"]


def test_compare_includes_net_cost_and_orders_by_it():
    res = compare_cards_for_spend("amazon", 10000, top_n=3)
    assert "net_cost" in res["top"][0]
    nets = [r["net_cost"] for r in res["top"]]
    assert nets == sorted(nets)  # ascending net cost
    assert res["top"][0]["card"] == "ICICI AmazonPay"


class _FakeCtx:
    def __init__(self):
        self.state = {}


def test_compare_is_cap_aware_when_state_available():
    from tools.spend_tracker import record_spend

    ctx = _FakeCtx()
    # Exhaust the HSBC combined cap (Rs.12k eligible > Rs.10k).
    record_spend(ctx, "dining", 8000, "HSBC Live+")
    record_spend(ctx, "grocery", 4000, "HSBC Live+")
    res = compare_cards_for_spend("dining", 2000, top_n=11, tool_context=ctx)
    hsbc = next(r for r in res["top"] if r["card"] == "HSBC Live+")
    # Cap exhausted -> dining now earns base 1.5%, not 10%.
    assert hsbc["rate_pct"] == 1.5


# --- Disambiguation / reverse-prompting support ----------------------------


def test_find_matching_cards_issuer_is_ambiguous():
    # Portfolio holds two Axis cards -> "axis" must return both, flagged ambiguous
    # so the agent reverse-prompts instead of silently picking one.
    res = find_matching_cards("axis")
    assert res["ambiguous"] is True
    assert set(res["matches"]) == {"Axis Rewards", "Axis RuPay"}
    assert res["count"] == 2


def test_find_matching_cards_brand_is_ambiguous():
    res = find_matching_cards("scapia")
    assert res["ambiguous"] is True
    assert set(res["matches"]) == {"Scapia Visa", "Scapia RuPay"}


def test_find_matching_cards_exact_name_is_unambiguous():
    res = find_matching_cards("Axis Rewards")
    assert res["ambiguous"] is False
    assert res["matches"] == ["Axis Rewards"]


def test_find_matching_cards_alias_is_unambiguous():
    # An alias resolves to exactly one card.
    res = find_matching_cards("Citi Rewards")
    assert res["ambiguous"] is False
    assert res["matches"] == ["Axis Rewards"]


def test_find_matching_cards_single_issuer_not_ambiguous():
    # Only one HDFC card in the default portfolio -> unambiguous.
    res = find_matching_cards("hdfc")
    assert res["ambiguous"] is False
    assert res["matches"] == ["HDFC Regalia Gold"]


def test_find_matching_cards_unknown_returns_empty():
    res = find_matching_cards("totally fake card")
    assert res["matches"] == []
    assert res["ambiguous"] is False


def test_find_matching_cards_scales_via_config():
    # Config-driven: add a second HDFC card purely as data and "hdfc" becomes
    # ambiguous with no code change (proves it scales to the user's real wallet).
    from data.cards import CARDS, CARD_ALIASES

    CARDS["HDFC Millennia"] = {"value_back": {"top_rate": 5.0, "base_rate": 1.0}}
    CARD_ALIASES["hdfc millennia"] = "HDFC Millennia"
    try:
        res = find_matching_cards("hdfc")
        assert res["ambiguous"] is True
        assert set(res["matches"]) == {"HDFC Regalia Gold", "HDFC Millennia"}
    finally:
        CARDS.pop("HDFC Millennia", None)
        CARD_ALIASES.pop("hdfc millennia", None)


# --- Ambiguity gate on the name-taking tools --------------------------------


def test_resolve_card_or_ambiguity_contract():
    from tools.card_tools import resolve_card_or_ambiguity

    canonical, amb = resolve_card_or_ambiguity("amex")
    assert canonical == "Amex Platinum Travel" and amb is None
    canonical, amb = resolve_card_or_ambiguity("axis")
    assert canonical is None and amb and amb["ambiguous"] is True
    assert set(amb["matches"]) == {"Axis Rewards", "Axis RuPay"}
    canonical, amb = resolve_card_or_ambiguity("totally fake card")
    assert canonical is None and amb is None


def test_get_card_details_ambiguous_issuer():
    # Two Axis cards -> "axis" must signal ambiguity, not silently pick one.
    d = get_card_details("axis")
    assert d.get("ambiguous") is True
    assert set(d["matches"]) == {"Axis Rewards", "Axis RuPay"}


def test_estimate_reward_value_ambiguous_issuer():
    r = estimate_reward_value("scapia", 5000, "travel")
    assert r.get("ambiguous") is True
    assert set(r["matches"]) == {"Scapia Visa", "Scapia RuPay"}


def test_estimate_net_cost_ambiguous_issuer():
    r = estimate_net_cost("axis", 5000, "shopping")
    assert r.get("ambiguous") is True
    assert set(r["matches"]) == {"Axis Rewards", "Axis RuPay"}


# --- Value-based routing (not keyword length) -------------------------------


def test_macbook_at_croma_routes_by_value_not_keyword_length():
    # "croma" (5 chars) is shorter than "macbook" (7), so the old length-based
    # score wrongly picked Amex (large-misc). Croma is a Tata brand at 10% value,
    # so value ranking must pick Tata Neu Infinity — and it must AGREE with the
    # value ranking from compare_cards_for_spend.
    assert _primary("MacBook at Croma", 150000) == "Tata Neu Infinity"
    res = compare_cards_for_spend("MacBook at Croma", 150000, top_n=1)
    assert res["top"][0]["card"] == "Tata Neu Infinity"


def test_find_cards_amount_unknown_flags_upi_tiers():
    # No amount -> both UPI tiers match and we can't value-rank; the note must
    # surface the amount-dependence rather than silently picking a tier.
    res = find_cards_for_category("UPI merchant payment", 0)
    assert res["matches"]
    assert "amount" in res["note"].lower()


# --- Cap-aware blended valuation --------------------------------------------


def test_compare_blended_partial_cap():
    from tools.spend_tracker import record_spend

    ctx = _FakeCtx()
    # HSBC combined cap: Rs.1,000/month @10% -> Rs.10,000 eligible-spend ceiling.
    # Rs.8,000 dining already spent -> Rs.2,000 of headroom left.
    record_spend(ctx, "dining", 8000, "HSBC Live+")
    # A Rs.5,000 dining spend: Rs.2,000 @10% + Rs.3,000 @1.5% = 200 + 45 = 245.
    res = compare_cards_for_spend("dining", 5000, top_n=11, tool_context=ctx)
    hsbc = next(r for r in res["top"] if r["card"] == "HSBC Live+")
    assert hsbc["approx_value_rupees"] == 245.0
    assert hsbc["rate_pct"] == 4.9  # blended effective rate 245/5000


def test_estimate_net_cost_is_cap_aware_when_context_given():
    from tools.spend_tracker import record_spend

    ctx = _FakeCtx()
    record_spend(ctx, "dining", 8000, "HSBC Live+")  # Rs.2,000 headroom left
    r = estimate_net_cost("HSBC Live+", 5000, "dining", tool_context=ctx)
    assert r["reward_value"] == 245.0  # blended, not the full 10%
    # Without context the estimate stays un-capped (schema/behaviour unchanged).
    r2 = estimate_net_cost("HSBC Live+", 5000, "dining")
    assert r2["reward_value"] == 500.0


# --- Word-boundary top-rate matching ----------------------------------------


def test_top_rate_uses_word_boundary_not_substring():
    # 'titan' is a Tata-Neu top keyword; 'titanium' must NOT trigger the top rate.
    r = estimate_reward_value("Tata Neu Infinity", 5000, "titanium supplier")
    assert r["rate_pct"] == 1.5  # base rate, not the 10% top rate
    r2 = estimate_reward_value("Tata Neu Infinity", 5000, "Titan watch")
    assert r2["rate_pct"] == 10.0  # a real Titan spend does earn the top rate


# --- Missing value_back is honest, not fabricated 1% ------------------------


def test_estimate_reward_value_missing_value_back_is_honest():
    from data.cards import CARDS, CARD_ALIASES

    CARDS["No VB Card"] = {}
    CARD_ALIASES["no vb card"] = "No VB Card"
    try:
        r = estimate_reward_value("No VB Card", 10000, "shopping")
        assert r["rate_pct"] == 0.0
        assert r["approx_value_rupees"] == 0.0
        assert r["eligible"] is False
        assert r.get("reward_unknown") is True
        # In a comparison it must not be ranked as if it earns 1%: it sinks last.
        res = compare_cards_for_spend("shopping", 10000, top_n=99)
        row = next(x for x in res["top"] if x["card"] == "No VB Card")
        assert row["approx_value_rupees"] == 0.0
        assert row["reward_unknown"] is True
        assert res["top"][-1]["card"] == "No VB Card"
    finally:
        CARDS.pop("No VB Card", None)
        CARD_ALIASES.pop("no vb card", None)


# --- Assumed-forex visibility -----------------------------------------------


def test_forex_assumed_flag_when_field_missing():
    # HDFC omits forex_markup_pct -> the 3.5% default is ASSUMED (flagged).
    hdfc = estimate_net_cost(
        "HDFC Regalia Gold", 10000, "shopping", is_international=True
    )
    assert hdfc["forex_markup"] == 350.0
    assert hdfc["forex_assumed"] is True
    # Uni GoldX declares 0% forex explicitly -> not an assumption.
    uni = estimate_net_cost("Uni GoldX", 10000, "forex", is_international=True)
    assert uni["forex_assumed"] is False
    # Domestic spend -> no forex assumption in play.
    dom = estimate_net_cost("HDFC Regalia Gold", 10000, "shopping")
    assert dom["forex_assumed"] is False


# --- Config keyword-collision regressions (deferred config pass) ------------


def test_generic_premium_no_longer_hijacks_forex_card():
    # "premium" removed from the Forex/Gold rule: a subscription must not route
    # to Uni GoldX just because it says "Premium".
    assert find_cards_for_category("Netflix Premium subscription", 649)["matches"] == []


def test_generic_gold_no_longer_matches_unrelated_merchants():
    # bare "gold" removed -> "Gold's Gym" no longer routes to the gold card.
    assert find_cards_for_category("Gold's Gym membership", 2000)["matches"] == []


def test_specific_gold_purchase_still_routes_to_uni_goldx():
    assert _primary("gold jewellery purchase", 50000) == "Uni GoldX"


def test_generic_booking_no_longer_routes_to_hdfc():
    # "booking" removed -> a bus booking must not hit the SmartBuy travel rule.
    assert find_cards_for_category("bus booking", 800)["matches"] == []


def test_hotel_smartbuy_still_routes_to_hdfc():
    # Removing "booking" must not break the legitimate travel route.
    assert _primary("hotel via SmartBuy", 25000) == "HDFC Regalia Gold"


def test_iphone_now_routes_to_electronics():
    # "iphone" keyword added -> a flagship phone is no longer unrouted.
    assert _primary("buying an iphone", 80000) == "Amex Platinum Travel"
