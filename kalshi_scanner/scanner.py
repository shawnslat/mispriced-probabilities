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
TOKEN_EXPIRY = 3300

bankroll = config.INITIAL_BANKROLL
sim_positions = []


def refresh_token():
    """Refresh the API token with basic retry handling."""
    global TOKEN, LAST_TOKEN_TIME
    try:
        if time.time() - LAST_TOKEN_TIME > TOKEN_EXPIRY or not TOKEN:
            TOKEN = get_token()
            LAST_TOKEN_TIME = time.time()
            print(f"✓ Token refreshed at {datetime.now()}")
        return TOKEN
    except Exception as exc:
        print(f"❌ Token refresh failed: {exc}")
        time.sleep(10)
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
    """Resolve closed paper positions and update bankroll."""
    global bankroll, sim_positions
    if not sim_positions:
        return

    refresh_token()
    markets = fetch_markets()
    market_lookup = {market.get("ticker"): market for market in markets}

    resolved_positions = []
    for position in sim_positions:
        market = market_lookup.get(position["market_id"])
        if not market:
            continue

        close_time = position.get("close_time")
        close_dt = None
        if close_time:
            try:
                close_dt = datetime.fromisoformat(close_time)
            except ValueError:
                close_dt = None

        market_status = market.get("status")
        if close_dt and datetime.now() < close_dt and market_status not in ("closed", "resolved"):
            continue

        result = market.get("result") or market.get("resolution") or market.get("outcome")
        if result is None:
            continue

        result_normalized = str(result).lower()
        wins_no = result_normalized in ("no", "false", "0")
        wins_yes = result_normalized in ("yes", "true", "1")
        if not (wins_no or wins_yes):
            continue

        entry_price = position["entry_price"]
        payout = 1.0 if wins_no else 0.0
        position["exit_price"] = payout
        position["pnl"] = (payout - entry_price) * position["size"]
        resolved_positions.append(position)

    if resolved_positions:
        for position in resolved_positions:
            bankroll += position["pnl"]
            log_paper_trade(position)
            print(
                f"💰 Position resolved: {position['market_id']} | "
                f"PnL: ${position['pnl']:.2f}"
            )

        sim_positions = [pos for pos in sim_positions if pos not in resolved_positions]


def check_kill_switch():
    """Monitor losses and stop if threshold hit."""
    starting_balance = config.INITIAL_BANKROLL
    current_loss = (starting_balance - bankroll) / starting_balance

    if current_loss > config.MAX_DAILY_LOSS:
        print(f"🛑 KILL SWITCH ACTIVATED - Loss: {current_loss * 100:.1f}%")
        config.KILL_SWITCH_ACTIVE = True
        return True
    return False


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
            if check_kill_switch():
                print("⏸️ Scanner paused due to loss limit")
                time.sleep(3600)
                continue
            time.sleep(config.SCAN_INTERVAL)

        except requests.HTTPError as exc:
            response = exc.response
            status_code = response.status_code if response else None
            if status_code == 401:
                print("❌ Auth failed - refreshing token")
                TOKEN = None
                time.sleep(5)
            elif status_code == 429:
                print("⏸️ Rate limited - waiting 60s")
                time.sleep(60)
            else:
                print(f"❌ HTTP Error: {exc}")
                time.sleep(30)
        except requests.ConnectionError:
            print("❌ Network error - retrying in 30s")
            time.sleep(30)
        except Exception as exc:
            print(f"❌ Unexpected error: {exc}")
            import traceback

            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    scan_loop()
