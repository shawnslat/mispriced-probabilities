from typing import Literal


def calculate_ev(market_price: float, true_prob: float, side: Literal["YES", "NO"] = "NO") -> float:
    """Calculate expected value for a YES or NO position."""
    market_price = max(0.0, min(market_price, 1.0))
    true_prob = max(0.0, min(true_prob, 1.0))

    if side == "YES":
        return true_prob - market_price

    true_no = 1 - true_prob
    price_no = 1 - market_price
    return true_no - price_no
