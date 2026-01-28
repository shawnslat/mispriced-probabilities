from datetime import datetime
from typing import Iterable


def _parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def correlation_penalty(positions: Iterable[dict]) -> float:
    """
    Compute max overlap across categories, times, news dependencies.
    Returns penalty 0-1 (higher = more correlated).
    """
    positions = list(positions)
    if len(positions) <= 1:
        return 0.0

    categories = [p.get("category", "unknown") for p in positions]
    category_overlap = (
        max(categories.count(c) / len(categories) for c in set(categories))
        if categories
        else 0
    )

    times = [_parse_time(p.get("close_time")) for p in positions]
    times = [t for t in times if t]
    time_overlap = 0
    if len(times) > 1:
        times = sorted(times)
        close_pairs = sum(
            1
            for i in range(1, len(times))
            if (times[i] - times[i - 1]).days <= 3
        )
        time_overlap = close_pairs / len(times)

    titles = [p.get("title", "").lower() for p in positions]
    token_sets = [set(t.split()) for t in titles if t]
    news_overlap = 0
    if token_sets:
        common_terms = set.intersection(*token_sets)
        news_overlap = min(len(common_terms) / 5, 1)

    return max(category_overlap, time_overlap, news_overlap)
