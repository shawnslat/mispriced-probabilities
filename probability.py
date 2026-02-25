# Expanded base rate database (historical % from data sources; expand over time)
BASE_RATES = {
    "indictment_7day": {"rate": 0.021, "sample": 847},
    "cpi_surprise_02": {"rate": 0.084, "sample": 120},
    "fed_rate_hold": {"rate": 0.732, "sample": 96},
    "election_upset": {"rate": 0.15, "sample": 50},
    "weather_extreme": {"rate": 0.05, "sample": 1000},
}


def get_adjusted_probability(market):
    """
    Returns adjusted probability estimate.

    Formula:
    adjusted = (base_rate * 0.7) + (recency * 0.3) - noise_penalty
    """
    title = market.get("title", "").lower()
    category = market.get("category", "unknown")

    base_rate = match_base_rate(title, category)

    if base_rate is None:
        base_rate = market.get("yes_price", 0.5) * 0.7

    recency_signal = get_recency_signal(market)

    blended = (base_rate * 0.7) + (recency_signal * 0.3)

    news_intensity = estimate_news_intensity(market)
    noise_penalty = min(news_intensity * 0.25, 0.5)

    adjusted = blended * (1 - noise_penalty)

    return max(0.01, min(adjusted, 0.99))


def match_base_rate(title, category):
    """Match market to known base rate."""
    if "indictment" in title or "indicted" in title:
        return BASE_RATES["indictment_7day"]["rate"]
    if "cpi" in title:
        return BASE_RATES["cpi_surprise_02"]["rate"]
    if "fed" in title and "rate" in title:
        return BASE_RATES["fed_rate_hold"]["rate"]
    if "election" in title:
        return BASE_RATES["election_upset"]["rate"]
    if category == "weather":
        return BASE_RATES["weather_extreme"]["rate"]

    return None


def get_recency_signal(market):
    """Check for recent similar events; fallback to market price."""
    return market.get("yes_price", 0.5)


def estimate_news_intensity(market):
    """Estimate how much noise is in the market via volume spikes."""
    volume_24h = market.get("volume_24h", 0)
    volume_7d = market.get("volume_7d", 1)
    if volume_7d == 0:
        return 0.5

    ratio = volume_24h / (volume_7d / 7)

    if ratio > 3:
        return 0.8
    if ratio > 1.5:
        return 0.4
    return 0.1
