def score_market(market):
    """
    Returns quality score 0-10

    Components:
    - Liquidity (25%)
    - Spread stability (25%)
    - Resolution clarity (20%)
    - Trader diversity (15%)
    - Historical behavior (15%)
    """
    # 1. Liquidity Score (0-10)
    volume = market.get("volume_24h", 0)
    liquidity_score = min(volume / 10000, 10)

    # 2. Spread Score (0-10)
    yes_bid = market.get("yes_bid", 0)
    yes_ask = market.get("yes_ask", 1)
    spread = max(yes_ask - yes_bid, 0)
    spread_score = max(10 - (spread * 100), 0)

    # 3. Resolution Clarity (0-10)
    title = market.get("title", "").lower()
    ambiguous_terms = ["might", "could", "possibly", "likely"]

    clarity_score = 5 if any(term in title for term in ambiguous_terms) else 10

    # 4. Trader Diversity (0-10)
    unique_traders = market.get("traders_count", 1)
    diversity_score = min(unique_traders / 50, 10)

    # 5. Historical Behavior (0-10)
    category = market.get("category", "unknown")
    historical_score = get_category_reliability(category)

    total_score = (
        liquidity_score * 0.25
        + spread_score * 0.25
        + clarity_score * 0.20
        + diversity_score * 0.15
        + historical_score * 0.15
    )

    return round(total_score, 2)


def get_category_reliability(category):
    """Returns reliability score for market category."""
    reliability_map = {
        "economics": 9.0,
        "weather": 9.5,
        "politics": 7.0,
        "sports": 8.0,
        "elections": 7.5,
        "unknown": 5.0,
    }

    return reliability_map.get(category, 5.0)
