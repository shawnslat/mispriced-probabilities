import time
from datetime import datetime

import requests

import config
from alerter import calculate_position_size, send_alert
from correlation import correlation_penalty
from database import init_db, log_opportunity, log_paper_trade
from ev_calculator import calculate_ev
from market_scorer import score_market
from portfolio_manager import get_open_positions, get_token
from probability import get_adjusted_probability

TOKEN = None
LAST_TOKEN_TIME = 0
TOKEN_EXPIRY = 3600

bankroll = config.INITIAL_BANKROLL
sim_positions = []


def refresh_token():
    global TOKEN, LAST_TOKEN_TIME
    if time.time() - LAST_TOKEN_TIME > TOKEN_EXPIRY or not TOKEN:
        TOKEN = get_token()
        LAST_TOKEN_TIME = time.time()
    return TOKEN


def normalize_price(price):
    if price is None:
        return 0.0
    return price / 100 if price > 1 else price


def fetch_markets():
    """Pull live markets from Kalshi."""
    refresh_token()
    url = f"{config.KALSHI_BASE_URL}/markets"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    params = {"status": "open", "limit": 1000}

    markets = []
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        markets.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break

    return markets


def filter_markets(markets):
    """Apply hard filters."""
    filtered = []

    for market in markets:
        if market.get("result_type") not in (None, "binary"):
            continue

        yes_price = normalize_price(market.get("yes_price", 0))
        if yes_price < config.MIN_PRICE:
            continue

        close_time = market.get("close_time")
        days_until = 0
        if close_time:
            try:
                days_until = (datetime.fromisoformat(close_time) - datetime.now()).days
            except ValueError:
                days_until = 0
        if days_until > 7:
            continue

        market["yes_price"] = yes_price
        filtered.append(market)

    return filtered


def simulate_trade(market, size_pct):
    """Simulate entering a position for paper trading."""
    global bankroll, sim_positions
    entry_price = 1 - market["yes_price"]
    position = {
        "market_id": market["ticker"],
        "size": size_pct * bankroll,
        "side": "NO",
        "entry_price": entry_price,
        "entry_time": time.time(),
        "category": market.get("category", "unknown"),
        "close_time": market.get("close_time"),
        "title": market.get("title", ""),
    }
    sim_positions.append(position)
    log_paper_trade(position)
    print(f"📈 Simulated trade: {market['title']} - Size: ${position['size']:.2f}")


def update_paper_pnl():
    """Stub: resolve closed positions and update bankroll."""
    return None


def scan_loop():
    """Main scanning loop."""
    init_db()
    print("🚀 Scanner started...")

    while True:
        try:
            markets = fetch_markets()
            filtered = filter_markets(markets)

            print(f"📊 Scanning {len(filtered)} markets...")

            token = refresh_token()
            open_positions = get_open_positions(token)

            for market in filtered:
                quality_score = score_market(market)

                if quality_score < config.MIN_MARKET_SCORE:
                    continue

                true_prob = get_adjusted_probability(market)
                market_price = market["yes_price"]

                ev = calculate_ev(market_price=market_price, true_prob=true_prob, side="NO")

                corr_penalty = correlation_penalty(open_positions + [market])
                if corr_penalty > config.MAX_CORRELATION:
                    continue

                if ev > config.MIN_EV:
                    size_pct = calculate_position_size(ev, quality_score, corr_penalty)
                    send_alert(market, quality_score, ev, true_prob, size_pct)
                    log_opportunity(market, quality_score, ev, true_prob, size_pct)
                    simulate_trade(market, size_pct)

            update_paper_pnl()
            time.sleep(config.SCAN_INTERVAL)

        except Exception as exc:
            print(f"❌ Error: {exc}")
            time.sleep(30)


if __name__ == "__main__":
    scan_loop()
