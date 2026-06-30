"""Offline unit tests for the deterministic routing/lookup tools.

No LLM and no network required — these validate that the decision matrix routes
each worked example to the right card.
"""

from tools.card_tools import (
    find_cards_for_category,
    get_card_details,
    list_all_cards,
    estimate_reward_value,
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
