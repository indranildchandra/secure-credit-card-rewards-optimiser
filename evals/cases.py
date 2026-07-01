"""Agent-level eval cases: a prompt and the card we expect to win.

These grade the *end-to-end* behaviour (prompt + routing + tools), which the
deterministic unit tests can't cover. Keep them aligned with the shipped
config/cards.config.
"""

EVAL_CASES = [
    {
        "prompt": "I am spending Rs.4,000 on Amazon. Which card?",
        "expect": "ICICI AmazonPay",
    },
    {"prompt": "I am spending Rs.500 on Swiggy. Which card?", "expect": "HSBC Live+"},
    {
        "prompt": "I am buying groceries for Rs.1,200. Which card?",
        "expect": "HSBC Live+",
    },
    {
        "prompt": "I am buying a TV at Croma for Rs.60,000. Which card?",
        "expect": "Tata Neu Infinity",
    },
    {
        "prompt": "I am spending Rs.1,50,000 on a MacBook Pro at an Apple Store. Which card?",
        "expect": "Amex Platinum Travel",
    },
    {
        "prompt": "I am making a Rs.3,000 UPI payment to a merchant. Which card?",
        "expect": "Axis RuPay",
    },
    {"prompt": "I am buying USD 500 of forex. Which card?", "expect": "Uni GoldX"},
    {
        "prompt": "I am buying apparel for Rs.5,000. Which card?",
        "expect": "Axis Rewards",
    },
]
