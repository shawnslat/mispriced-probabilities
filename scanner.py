"""
Seer - Prediction Market Scanner
Main loop with error handling & paper trading resolution.
Supports Kalshi, Polymarket, and other prediction markets.
"""
import time
from datetime import datetime, timezone
from typing import Optional

import requests

import config
from alerter import calculate_position_size, send_alert
from telegram_alerts import send_arbitrage_alert, send_startup_alert, send_trade_alert
from correlation import correlation_penalty
from database import (
    get_open_paper_trades,
    init_db,
    log_metrics,
    log_opportunity,
    log_paper_trade,
    print_performance_report,
    update_paper_trade_result,
)
from ev_calculator import calculate_ev
from market_scorer import score_market
from portfolio_manager import get_market_result, get_open_positions, signed_request
from probability import get_adjusted_probability
from risk_manager import RiskManager


class SeerScanner:
    """Main scanner class with state management."""

    def __init__(self):
        self.bankroll = config.INITIAL_BANKROLL
        self.risk_manager = RiskManager(self.bankroll)
        self.sim_positions = []
        self.last_metrics_time = time.time()
        self.scan_count = 0
        self.error_count = 0

        # Track recently-resolved arb IDs to prevent re-entry compounding
        # Maps arb_id -> timestamp of resolution
        self._resolved_arb_cooldown: dict[str, float] = {}
        self._ARB_COOLDOWN_SECONDS = 3600  # 1 hour cooldown before re-entering same arb

        # Multi-platform adapters
        self.polymarket_adapter = None
        self.kalshi_adapter = None
        self.predictit_adapter = None
        self._init_adapters()

    def _init_adapters(self):
        """Initialize platform adapters."""
        try:
            from market_adapter import KalshiAdapter, PolymarketAdapter, PredictItAdapter

            self.kalshi_adapter = KalshiAdapter()
            if config.POLYMARKET_ENABLED:
                self.polymarket_adapter = PolymarketAdapter()
            if getattr(config, 'PREDICTIT_ENABLED', True):  # Enabled by default
                self.predictit_adapter = PredictItAdapter()
            print("✅ Multi-platform adapters initialized (Kalshi, Polymarket, PredictIt)")
        except Exception as e:
            print(f"⚠️ Adapter init failed: {e}")

    def normalize_price(self, price: Optional[float]) -> Optional[float]:
        """Normalize price to 0-1 range."""
        if price is None:
            return None

        try:
            normalized = float(price)
        except (TypeError, ValueError):
            return None

        if normalized > 1:
            normalized /= 100

        if normalized < 0 or normalized > 1:
            return None

        return normalized

    def _extract_yes_price(self, market: dict) -> Optional[float]:
        """Extract a usable YES price from market data."""
        yes_price = self.normalize_price(market.get("yes_price"))
        if yes_price is not None and 0 < yes_price < 1:
            return yes_price

        yes_bid = self.normalize_price(market.get("yes_bid"))
        yes_ask = self.normalize_price(market.get("yes_ask"))

        if yes_bid is not None and yes_ask is not None:
            if yes_ask >= yes_bid and yes_bid > 0:
                return (yes_bid + yes_ask) / 2
            return yes_bid if yes_bid > 0 else yes_ask

        if yes_bid is not None and yes_bid > 0:
            return yes_bid
        if yes_ask is not None and yes_ask > 0:
            return yes_ask

        return None

    def _has_open_position(self, market_id: str) -> bool:
        """Check if a market is already open in paper mode."""
        return any(p.get("market_id") == market_id for p in self.sim_positions)

    def _is_arb_on_cooldown(self, arb_id: str) -> bool:
        """Check if an arb opportunity was recently resolved (prevent re-entry loop)."""
        # Clean up expired cooldowns
        now = time.time()
        expired = [k for k, v in self._resolved_arb_cooldown.items()
                   if now - v > self._ARB_COOLDOWN_SECONDS]
        for k in expired:
            del self._resolved_arb_cooldown[k]

        return arb_id in self._resolved_arb_cooldown

    def _mark_arb_resolved(self, arb_id: str):
        """Mark an arb as recently resolved to prevent immediate re-entry."""
        self._resolved_arb_cooldown[arb_id] = time.time()

    def _normalize_close_time(self, close_time):
        """Normalize datetime/string close_time to UTC-aware datetime."""
        if not close_time:
            return None
        if isinstance(close_time, str):
            try:
                close_time = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return None
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        return close_time

    def _is_future_close(self, close_time) -> bool:
        """Return True if close_time is in the future."""
        normalized = self._normalize_close_time(close_time)
        return bool(normalized and normalized > datetime.now(timezone.utc))

    def fetch_markets_data(self):
        """Pull live markets from Kalshi with pagination."""
        markets = []
        cursor = None
        max_pages = 10
        page_count = 0

        while page_count < max_pages:
            params = {"status": "open", "limit": 1000}
            if cursor:
                params["cursor"] = cursor

            try:
                response = signed_request("GET", "/trade-api/v2/markets", params=params)
                response.raise_for_status()

                data = response.json()
                batch = data.get("markets", [])
                markets.extend(batch)

                cursor = data.get("cursor")
                page_count += 1

                if not cursor:
                    break

            except requests.Timeout:
                print("⚠️ Request timeout - retrying...")
                time.sleep(5)
                continue

            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    print("⚠️ Rate limited - waiting 60s...")
                    time.sleep(60)
                    continue
                raise

        return markets

    def filter_markets(self, markets):
        """Apply hard filters - look for mispriced markets on BOTH sides."""
        filtered = []

        for market in markets:
            # Only binary markets
            if market.get("result_type") not in (None, "binary"):
                continue

            yes_price = self._extract_yes_price(market)
            if yes_price is None or yes_price <= 0 or yes_price >= 1:
                continue

            # Buy NO when YES is expensive (>85%)
            # Buy YES when NO is expensive (YES <15%)
            min_threshold = 1 - config.MIN_PRICE  # 0.15
            max_threshold = config.MIN_PRICE  # 0.85

            if not (yes_price <= min_threshold or yes_price >= max_threshold):
                continue

            # Time filter
            close_time = market.get("close_time")
            days_until = 0
            if close_time:
                try:
                    close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                    days_until = (close_dt - datetime.now(timezone.utc)).days
                except (ValueError, AttributeError):
                    days_until = 0

            if days_until > config.MAX_DAYS_TO_CLOSE or days_until < 0:
                continue

            market["yes_price"] = yes_price
            filtered.append(market)

        return filtered

    def simulate_trade(self, market, size_pct, side):
        """Simulate entering a position for paper trading."""
        market_id = market["ticker"]
        if self._has_open_position(market_id):
            return False

        yes_price = market["yes_price"]

        # Calculate entry price based on side
        if side == "YES":
            entry_price = yes_price
        else:  # NO
            entry_price = 1 - yes_price

        position = {
            "market_id": market_id,
            "size": size_pct * self.bankroll,
            "side": side,
            "entry_price": max(entry_price, 0.01),
            "entry_time": time.time(),
            "category": market.get("category", "unknown"),
            "close_time": market.get("close_time"),
            "title": market.get("title", ""),
        }

        self.sim_positions.append(position)
        log_paper_trade(position)

        print(f"📈 Simulated trade: {market['title'][:60]}")
        print(f"   Side: {side} | Size: ${position['size']:.2f} | Entry: {entry_price:.3f}")
        return True

    def simulate_kalshi_arb_trade(self, opp):
        """Simulate one Kalshi multi-outcome arbitrage basket."""
        arb_id = f"KALSHI_ARB::{opp['event_key']}::{opp['strategy']}"
        if self._has_open_position(arb_id):
            return False
        if self._is_arb_on_cooldown(arb_id):
            return False

        profit_rate = max(opp["profit_per_100"] / 100.0, 0.0)
        min_profit = max(config.ARB_MIN_PROFIT, 0.0001)
        edge_mult = max(1.0, profit_rate / min_profit)
        proposed_size = min(config.BASE_POSITION_SIZE * edge_mult, config.MAX_POSITION_SIZE)
        proposed_size = max(proposed_size, config.MIN_POSITION_SIZE)

        valid, size_pct, reason = self.risk_manager.validate_position_size(
            proposed_size, self.bankroll, self.sim_positions
        )
        if not valid:
            print(f"⚠️ Kalshi arb rejected: {reason}")
            return False

        if size_pct != proposed_size:
            print(f"ℹ️ Kalshi arb adjusted: {reason}")

        close_time = opp.get("close_time")
        if not self._is_future_close(close_time):
            return False

        # Encode guaranteed arb return as a synthetic entry price so standard
        # binary settlement math can reuse it: r = 1/p - 1 => p = 1/(1+r).
        synthetic_entry_price = 1 / (1 + max(profit_rate, 0.001))

        # Absolute dollar cap to prevent compounding runaway
        max_dollars = getattr(config, 'ARB_MAX_POSITION_DOLLARS', 500.0)
        dollar_size = min(size_pct * self.bankroll, max_dollars)

        position = {
            "market_id": arb_id,
            "size": dollar_size,
            "side": "YES",
            "entry_price": synthetic_entry_price,
            "entry_time": time.time(),
            "category": "kalshi_arb",
            "close_time": close_time,
            "title": f"[KALSHI_ARB] {opp['title']}",
        }

        self.sim_positions.append(position)
        log_paper_trade(position)

        print(f"📈 Simulated KALSHI ARB: {opp['title'][:52]}...")
        print(
            f"   Strategy: {opp['strategy']} | Edge: {opp['profit_per_100']:.2f}%"
            f" | Size: ${position['size']:.2f}"
        )

        # Send Telegram trade execution alert
        try:
            from telegram_alerts import send_telegram_message
            msg = (
                f"📈 <b>PAPER TRADE EXECUTED</b>\n\n"
                f"<b>{opp['title'][:50]}...</b>\n"
                f"Platform: KALSHI\n"
                f"Strategy: {opp['strategy']}\n"
                f"Edge: {opp['profit_per_100']:.2f}%\n"
                f"Size: ${position['size']:.2f}\n"
                f"Bankroll: ${self.bankroll:,.2f}\n\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')}"
            )
            send_telegram_message(msg)
        except Exception:
            pass

        return True

    def simulate_polymarket_arb_trade(self, opp):
        """Simulate one Polymarket multi-outcome arbitrage basket."""
        arb_id = f"POLY_ARB::{opp['event_key']}::{opp['strategy']}"
        if self._has_open_position(arb_id):
            return False
        if self._is_arb_on_cooldown(arb_id):
            return False

        profit_rate = max(opp["profit_per_100"] / 100.0, 0.0)
        min_profit = max(config.ARB_MIN_PROFIT, 0.0001)
        edge_mult = max(1.0, profit_rate / min_profit)
        proposed_size = min(config.BASE_POSITION_SIZE * edge_mult, config.MAX_POSITION_SIZE)
        proposed_size = max(proposed_size, config.MIN_POSITION_SIZE)

        valid, size_pct, reason = self.risk_manager.validate_position_size(
            proposed_size, self.bankroll, self.sim_positions
        )
        if not valid:
            print(f"⚠️ Polymarket arb rejected: {reason}")
            return False

        if size_pct != proposed_size:
            print(f"ℹ️ Polymarket arb adjusted: {reason}")

        close_time = opp.get("close_time")
        if not self._is_future_close(close_time):
            return False

        # Encode guaranteed arb return as a synthetic entry price so standard
        # binary settlement math can reuse it: r = 1/p - 1 => p = 1/(1+r).
        synthetic_entry_price = 1 / (1 + max(profit_rate, 0.001))

        # Absolute dollar cap to prevent compounding runaway
        max_dollars = getattr(config, 'ARB_MAX_POSITION_DOLLARS', 500.0)
        dollar_size = min(size_pct * self.bankroll, max_dollars)

        position = {
            "market_id": arb_id,
            "size": dollar_size,
            "side": "YES",
            "entry_price": synthetic_entry_price,
            "entry_time": time.time(),
            "category": "polymarket_arb",
            "close_time": close_time,
            "title": f"[POLY_ARB] {opp['title']}",
        }

        self.sim_positions.append(position)
        log_paper_trade(position)

        print(f"📈 Simulated POLY ARB: {opp['title'][:52]}...")
        print(
            f"   Strategy: {opp['strategy']} | Edge: {opp['profit_per_100']:.2f}%"
            f" | Size: ${position['size']:.2f}"
        )

        # Send Telegram trade execution alert
        try:
            from telegram_alerts import send_telegram_message
            msg = (
                f"📈 <b>PAPER TRADE EXECUTED</b>\n\n"
                f"<b>{opp['title'][:50]}...</b>\n"
                f"Platform: POLYMARKET\n"
                f"Strategy: {opp['strategy']}\n"
                f"Edge: {opp['profit_per_100']:.2f}%\n"
                f"Size: ${position['size']:.2f}\n"
                f"Bankroll: ${self.bankroll:,.2f}\n\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')}"
            )
            send_telegram_message(msg)
        except Exception:
            pass

        return True

    def resolve_paper_trades(self):
        """Check for resolved markets and update P&L."""
        open_trades = get_open_paper_trades()

        if not open_trades:
            return

        resolved_count = 0

        for trade in open_trades:
            # Check if market should be closed
            close_time = trade.get("close_time")
            if not close_time:
                continue

            try:
                close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < close_dt:
                    continue  # Not closed yet
            except (ValueError, AttributeError):
                continue

            # Synthetic arb baskets are marked as guaranteed in paper mode.
            market_id = str(trade["market_id"])
            if market_id.startswith("POLY_ARB::") or market_id.startswith("KALSHI_ARB::"):
                result = {"result": "yes"}
            else:
                result = get_market_result(trade["market_id"])

            if result:
                # If we bought YES and result is "yes", we win (exit at 1.0)
                # If we bought NO and result is "no", we win (exit at 1.0)
                if trade["side"] == "YES":
                    exit_price = 1.0 if result["result"] == "yes" else 0.0
                else:  # NO
                    exit_price = 1.0 if result["result"] == "no" else 0.0

                update_result = update_paper_trade_result(
                    trade["market_id"], result["result"], exit_price
                )

                if update_result:
                    self.bankroll += update_result["pnl"]
                    resolved_count += 1

                    # Put this arb on cooldown to prevent re-entry compounding
                    self._mark_arb_resolved(market_id)

                    is_win = update_result["win"]
                    status = "✅ WIN" if is_win else "❌ LOSS"
                    print(f"{status} - {trade['title'][:60]}")
                    print(
                        f"   P&L: ${update_result['pnl']:+.2f}"
                        f" | New Bankroll: ${self.bankroll:.2f}"
                    )

                    # Send Telegram result alert
                    try:
                        from telegram_alerts import send_telegram_message
                        emoji = "✅" if is_win else "❌"
                        msg = (
                            f"{emoji} <b>PAPER TRADE {'WIN' if is_win else 'LOSS'}</b>\n\n"
                            f"<b>{trade['title'][:50]}...</b>\n"
                            f"P&L: <b>${update_result['pnl']:+.2f}</b>\n"
                            f"Bankroll: ${self.bankroll:,.2f}\n\n"
                            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')}"
                        )
                        send_telegram_message(msg)
                    except Exception:
                        pass

                    # Remove from sim positions
                    self.sim_positions = [
                        p for p in self.sim_positions if p["market_id"] != trade["market_id"]
                    ]

        if resolved_count > 0:
            print(f"\n💰 Resolved {resolved_count} position(s)")

    def scan_markets(self):
        """Execute one scan cycle."""
        try:
            # Check kill switch
            halt, reason = self.risk_manager.check_kill_switch(self.bankroll)
            if halt:
                print(f"🛑 Scanner halted: {reason}")
                print("⏸️ Waiting 1 hour before retry...")
                time.sleep(3600)
                return

            # Resolve any closed positions
            self.resolve_paper_trades()

            # Fetch and filter markets
            print(f"\n{'=' * 60}")
            print(f"🔍 Scan #{self.scan_count + 1} - {datetime.now().strftime('%H:%M:%S')}")

            markets = self.fetch_markets_data()
            filtered = self.filter_markets(markets)

            print(f"📊 Scanning {len(filtered)} markets (filtered from {len(markets)})")

            # Get current positions
            if config.PAPER_TRADING_MODE:
                open_positions = self.sim_positions
            else:
                open_positions = get_open_positions()

            # Check position limits
            can_trade, limit_reason = self.risk_manager.check_position_limits(open_positions)
            if not can_trade:
                print(f"⚠️ {limit_reason}")
                return

            # Scan for opportunities
            opportunities_found = 0

            for market in filtered:
                if self._has_open_position(market["ticker"]):
                    continue

                # Determine which side to trade
                yes_price = market["yes_price"]

                # Buy NO when YES is expensive (>85%)
                # Buy YES when NO is expensive (YES <15%)
                if yes_price >= config.MIN_PRICE:
                    side = "NO"
                else:
                    side = "YES"

                # Score market quality
                quality_score = score_market(market)
                if quality_score < config.MIN_MARKET_SCORE:
                    continue

                # Calculate true probability
                true_prob = get_adjusted_probability(market)

                # Calculate EV for the appropriate side
                ev = calculate_ev(market_price=yes_price, true_prob=true_prob, side=side)
                if ev <= config.MIN_EV:
                    continue

                # Check correlation
                corr_penalty = correlation_penalty(open_positions + [market])
                if corr_penalty > config.MAX_CORRELATION:
                    continue

                # Calculate position size
                size_pct = calculate_position_size(ev, quality_score, corr_penalty)

                # Validate position size
                valid, adjusted_size, size_reason = self.risk_manager.validate_position_size(
                    size_pct, self.bankroll, open_positions
                )
                if not valid:
                    print(f"⚠️ Position rejected: {size_reason}")
                    continue

                if adjusted_size != size_pct:
                    print(f"ℹ️ Position adjusted: {size_reason}")
                    size_pct = adjusted_size

                # Log and alert
                opportunities_found += 1
                send_alert(market, quality_score, ev, true_prob, size_pct * 100)
                log_opportunity(
                    market,
                    quality_score,
                    ev,
                    true_prob,
                    size_pct,
                    executed=not config.WATCH_MODE,
                )

                # Execute trade (paper or live)
                if config.WATCH_MODE:
                    print(f"⚠️ WATCH: {market['title'][:60]}")
                    print(f"   Side: {side} | EV: {ev * 100:+.2f}% | Score: {quality_score:.1f}")
                    print(f"   Price: {yes_price * 100:.1f}% | Suggested Size: {size_pct * 100:.1f}%")
                elif config.PAPER_TRADING_MODE:
                    if self.simulate_trade(market, size_pct, side):
                        open_positions = self.sim_positions
                # else: live trading (not implemented yet)

            if opportunities_found > 0:
                print(f"\n🎯 Found {opportunities_found} opportunity(ies)")
            else:
                print("✅ No edge detected - standing down (this is good!)")

            self.scan_count += 1
            self.error_count = 0  # Reset error counter on success

        except requests.HTTPError as e:
            self.error_count += 1
            print(f"❌ HTTP Error: {e}")
            print(f"   Status: {e.response.status_code}")

        except requests.ConnectionError:
            self.error_count += 1
            print("❌ Network error - check connection")

        except Exception as e:
            self.error_count += 1
            print(f"❌ Unexpected error: {e}")
            import traceback

            traceback.print_exc()

        # Emergency stop after repeated errors
        if self.error_count >= 5:
            print(f"\n{'=' * 60}")
            print("🛑 EMERGENCY STOP")
            print(f"Too many consecutive errors ({self.error_count})")
            print("Halting scanner for safety")
            print(f"{'=' * 60}\n")
            self.risk_manager.activate_kill_switch("Too many consecutive errors")

    def scan_kalshi_multi_outcome_arbitrage(self):
        """Scan Kalshi events for multi-outcome bracket arbitrage."""
        if not self.kalshi_adapter or not config.KALSHI_MULTI_ARB_ENABLED:
            return []

        try:
            events = self.kalshi_adapter.fetch_events(limit=100)
            opportunities = []

            for event in events:
                event_ticker = event.get("event_ticker")
                if not event_ticker:
                    continue

                markets = self.kalshi_adapter.fetch_markets_for_event(event_ticker)
                if len(markets) < config.ARB_MIN_OUTCOMES:
                    continue

                valid_markets = []
                close_times = []
                for market in markets:
                    yes_price = market.yes_price
                    if yes_price is None or yes_price <= 0 or yes_price >= 1:
                        continue
                    if yes_price < config.ARB_IGNORE_BELOW:
                        continue
                    valid_markets.append(market)
                    normalized_close = self._normalize_close_time(market.close_time)
                    if normalized_close and normalized_close > datetime.now(timezone.utc):
                        close_times.append(normalized_close)

                if len(valid_markets) < config.ARB_MIN_OUTCOMES or not close_times:
                    continue

                # === TIMING FILTER ===
                # Skip markets that resolve too far in the future
                earliest_close = min(close_times)
                if hasattr(config, 'ALERT_MAX_DAYS_TO_RESOLUTION') and config.ALERT_MAX_DAYS_TO_RESOLUTION > 0:
                    days_to_resolution = (earliest_close - datetime.now(timezone.utc)).days
                    if days_to_resolution > config.ALERT_MAX_DAYS_TO_RESOLUTION:
                        continue  # Skip - resolves too far out

                yes_sum = sum(m.yes_price for m in valid_markets)
                deviation = yes_sum - 1.0
                if abs(deviation) < config.ARB_MIN_PROFIT:
                    continue

                opportunities.append(
                    {
                        "platform": "kalshi",
                        "type": "multi_outcome",
                        "event_key": event_ticker,
                        "title": event.get("title", valid_markets[0].title),
                        "num_outcomes": len(valid_markets),
                        "yes_sum": yes_sum,
                        "deviation": deviation,
                        "strategy": "BUY_ALL_NO" if deviation > 0 else "BUY_ALL_YES",
                        "profit_per_100": abs(deviation) * 100,
                        "markets": valid_markets,
                        "close_time": min(close_times).isoformat(),
                    }
                )

            return sorted(opportunities, key=lambda x: -x["profit_per_100"])
        except Exception as e:
            print(f"⚠️ Kalshi multi-outcome scan error: {e}")
            return []

    def scan_polymarket_arbitrage(self):
        """Scan Polymarket for multi-outcome bracket arbitrage."""
        if not self.polymarket_adapter:
            return []

        from collections import defaultdict

        try:
            markets = self.polymarket_adapter.fetch_markets(limit=200)

            # Group by questionID base (removes last 2 hex chars = outcome index)
            events = defaultdict(list)
            for market in markets:
                qid = market.raw_data.get("questionID", "")
                if qid and len(qid) > 4:
                    events[qid[:-2]].append(market)

            opportunities = []
            for event_key, group in events.items():
                if len(group) < 2:
                    continue

                valid_group = []
                close_times = []
                for market in group:
                    if market.yes_price <= 0 or market.yes_price >= 1:
                        continue
                    normalized_close = self._normalize_close_time(market.close_time)
                    if normalized_close and normalized_close > datetime.now(timezone.utc):
                        close_times.append(normalized_close)
                    valid_group.append(market)

                if len(valid_group) < 2 or not close_times:
                    continue

                # === TIMING FILTER ===
                # Skip markets that resolve too far in the future
                earliest_close = min(close_times)
                if hasattr(config, 'ALERT_MAX_DAYS_TO_RESOLUTION') and config.ALERT_MAX_DAYS_TO_RESOLUTION > 0:
                    days_to_resolution = (earliest_close - datetime.now(timezone.utc)).days
                    if days_to_resolution > config.ALERT_MAX_DAYS_TO_RESOLUTION:
                        continue  # Skip - resolves too far out

                yes_sum = sum(m.yes_price for m in valid_group)
                deviation = yes_sum - 1.0

                # Significant arbitrage
                if abs(deviation) >= config.ARB_MIN_PROFIT:
                    opportunities.append(
                        {
                            "platform": "polymarket",
                            "type": "multi_outcome",
                            "event_key": event_key,
                            "title": valid_group[0].title,
                            "num_outcomes": len(valid_group),
                            "yes_sum": yes_sum,
                            "deviation": deviation,
                            "strategy": "BUY_ALL_NO" if deviation > 0 else "BUY_ALL_YES",
                            "profit_per_100": abs(deviation) * 100,
                            "markets": valid_group,
                            "close_time": min(close_times).isoformat(),
                        }
                    )

            return sorted(opportunities, key=lambda x: -x["profit_per_100"])

        except Exception as e:
            print(f"⚠️ Polymarket scan error: {e}")
            return []

    def scan_crypto_markets(self):
        """
        Scan Polymarket 5-minute crypto UP/DOWN markets.
        Looks for mispriced UP+DOWN pairs where sum ≠ 100%.
        """
        if not self.polymarket_adapter or not getattr(config, 'CRYPTO_MARKETS_ENABLED', False):
            return []

        try:
            markets = self.polymarket_adapter.fetch_crypto_markets(interval="5min")
            if not markets:
                return []

            # Group by underlying asset + time window
            from collections import defaultdict
            pairs = defaultdict(list)
            for m in markets:
                # Group by question stem (e.g. "BTC up or down 5min 19:00")
                title = m.title.lower()
                # Create grouping key from title
                key = m.event_id or title[:40]
                pairs[key].append(m)

            opportunities = []
            for key, group in pairs.items():
                if len(group) < 2:
                    continue

                yes_sum = sum(m.yes_price for m in group)
                deviation = yes_sum - 1.0

                if abs(deviation) >= 0.015:  # 1.5% min for crypto (tighter spreads)
                    opportunities.append({
                        "platform": "polymarket",
                        "type": "crypto_5min",
                        "event_key": key,
                        "title": group[0].title,
                        "num_outcomes": len(group),
                        "yes_sum": yes_sum,
                        "deviation": deviation,
                        "strategy": "BUY_ALL_NO" if deviation > 0 else "BUY_ALL_YES",
                        "profit_per_100": abs(deviation) * 100,
                        "markets": group,
                        "close_time": group[0].close_time.isoformat() if group[0].close_time else "",
                    })

            return sorted(opportunities, key=lambda x: -x["profit_per_100"])

        except Exception as e:
            print(f"⚠️ Crypto market scan error: {e}")
            return []

    def execute_polymarket_arbitrage(self, opportunities):
        """Paper-execute detected Polymarket arbitrage opportunities."""
        if config.WATCH_MODE or not config.PAPER_TRADING_MODE:
            return 0
        if not config.POLYMARKET_PAPER_ARB_EXECUTION:
            return 0

        available_slots = max(config.MAX_OPEN_POSITIONS - len(self.sim_positions), 0)
        if available_slots <= 0:
            return 0

        executed = 0
        for opp in opportunities[:available_slots]:
            if self.simulate_polymarket_arb_trade(opp):
                executed += 1

        return executed

    def scan_predictit_arbitrage(self):
        """Scan PredictIt for multi-outcome bracket arbitrage."""
        if not self.predictit_adapter:
            return []

        try:
            markets = self.predictit_adapter.fetch_multi_outcome_markets()
            opportunities = []

            for market in markets:
                contracts = market.get('contracts', [])

                if len(contracts) < 2:
                    continue

                valid_contracts = []
                close_times = []

                for contract in contracts:
                    # PredictIt prices are in cents (0-100), convert to 0-1
                    yes_price = contract.get('lastTradePrice', 0)
                    if yes_price is None:
                        yes_price = contract.get('bestBuyYesCost', 0)
                    if yes_price and yes_price > 1:
                        yes_price = yes_price / 100.0

                    if yes_price <= 0 or yes_price >= 1:
                        continue
                    if yes_price < config.ARB_IGNORE_BELOW:
                        continue

                    valid_contracts.append({
                        'name': contract.get('name', ''),
                        'yes_price': yes_price
                    })

                    end_date = contract.get('dateEnd')
                    if end_date:
                        normalized_close = self._normalize_close_time(end_date)
                        if normalized_close and normalized_close > datetime.now(timezone.utc):
                            close_times.append(normalized_close)

                if len(valid_contracts) < 2 or not close_times:
                    continue

                # === TIMING FILTER ===
                earliest_close = min(close_times)
                if hasattr(config, 'ALERT_MAX_DAYS_TO_RESOLUTION') and config.ALERT_MAX_DAYS_TO_RESOLUTION > 0:
                    days_to_resolution = (earliest_close - datetime.now(timezone.utc)).days
                    if days_to_resolution > config.ALERT_MAX_DAYS_TO_RESOLUTION:
                        continue

                yes_sum = sum(c['yes_price'] for c in valid_contracts)
                deviation = yes_sum - 1.0

                if abs(deviation) >= config.ARB_MIN_PROFIT:
                    opportunities.append({
                        "platform": "predictit",
                        "type": "multi_outcome",
                        "event_key": str(market.get('market_id', '')),
                        "title": market.get('name', 'Unknown'),
                        "num_outcomes": len(valid_contracts),
                        "yes_sum": yes_sum,
                        "deviation": deviation,
                        "strategy": "BUY_ALL_NO" if deviation > 0 else "BUY_ALL_YES",
                        "profit_per_100": abs(deviation) * 100,
                        "contracts": valid_contracts,
                        "close_time": earliest_close.isoformat(),
                    })

            return sorted(opportunities, key=lambda x: -x["profit_per_100"])

        except Exception as e:
            print(f"⚠️ PredictIt scan error: {e}")
            return []

    def execute_kalshi_arbitrage(self, opportunities):
        """Paper-execute detected Kalshi arbitrage opportunities."""
        if config.WATCH_MODE or not config.PAPER_TRADING_MODE:
            return 0
        if not config.KALSHI_PAPER_ARB_EXECUTION:
            return 0

        available_slots = max(config.MAX_OPEN_POSITIONS - len(self.sim_positions), 0)
        if available_slots <= 0:
            return 0

        executed = 0
        for opp in opportunities[:available_slots]:
            if self.simulate_kalshi_arb_trade(opp):
                executed += 1

        return executed

    def run(self):
        """Main scanner loop."""
        # Validate configuration
        if not config.validate_config():
            print("❌ Configuration validation failed - exiting")
            return

        # Initialize database
        init_db()
        self.sim_positions = [
            {
                "market_id": t["market_id"],
                "size": t["size"],
                "side": t.get("side", "NO"),
                "entry_price": t.get("entry_price", 0.5),
                "category": t.get("category", "unknown"),
                "close_time": t.get("close_time"),
                "title": t.get("title", ""),
            }
            for t in get_open_paper_trades()
        ]
        if self.sim_positions:
            print(f"♻️ Restored {len(self.sim_positions)} open paper position(s)")

        # Print startup info
        mode_str = (
            "👀 Watch Mode (Alerts Only)"
            if config.WATCH_MODE
            else ("📝 Paper Trading" if config.PAPER_TRADING_MODE else "💰 Live Trading")
        )
        print(f"\n{'=' * 60}")
        print("🔮 SEER STARTED")
        print(f"{'=' * 60}")
        print(f"Mode: {mode_str}")
        print(f"Starting Bankroll: ${self.bankroll:,.2f}")
        platforms = ["Kalshi"] + (["Polymarket"] if config.POLYMARKET_ENABLED else []) + (["PredictIt"] if self.predictit_adapter else [])
        print(f"Platforms: {' + '.join(platforms)}")
        print(f"Min EV: {config.MIN_EV * 100:.1f}% | Min Score: {config.MIN_MARKET_SCORE}")
        print(f"Max Days to Close: {config.MAX_DAYS_TO_CLOSE} days")
        print(f"Kill Switch: {config.DAILY_LOSS_LIMIT * 100:.1f}% daily loss limit")
        print(f"{'=' * 60}\n")

        # Send Telegram startup alert
        try:
            send_startup_alert()
            print("📱 Telegram alerts enabled")
        except Exception as e:
            print(f"⚠️ Telegram alerts unavailable: {e}")

        # Heartbeat tracking
        last_heartbeat = time.time()
        heartbeat_interval = 3600  # 1 hour
        total_opps_found = 0

        while True:
            try:
                # 1. Scan Kalshi for single-market edge
                self.scan_markets()

                # 2. Scan Kalshi for multi-outcome arbitrage
                kalshi_opps = self.scan_kalshi_multi_outcome_arbitrage()
                if kalshi_opps:
                    print(f"\n🎯 KALSHI MULTI-OUTCOME ARBITRAGE ({len(kalshi_opps)} opportunities):")
                    for opp in kalshi_opps[:5]:
                        print(f"   📍 {opp['title'][:45]}...")
                        print(f"      {opp['num_outcomes']} outcomes | YES sum: {opp['yes_sum']:.1%}")
                        print(f"      💰 {opp['strategy']}: ${opp['profit_per_100']:.2f} per $100")

                        # Send Telegram alert for high-edge opportunities (>3%)
                        if opp['profit_per_100'] >= 3.0:
                            try:
                                send_arbitrage_alert(opp)
                            except Exception as e:
                                print(f"   ⚠️ Telegram alert failed: {e}")

                    kalshi_executed = self.execute_kalshi_arbitrage(kalshi_opps)
                    if kalshi_executed > 0:
                        print(f"✅ Executed {kalshi_executed} Kalshi arb paper trade(s)")

                # 3. Optionally scan Polymarket
                if config.POLYMARKET_ENABLED:
                    poly_opps = self.scan_polymarket_arbitrage()
                    if poly_opps:
                        print(f"\n🎯 POLYMARKET ARBITRAGE FOUND ({len(poly_opps)} opportunities):")
                        for opp in poly_opps[:5]:
                            print(f"   📍 {opp['title'][:45]}...")
                            print(f"      {opp['num_outcomes']} outcomes | YES sum: {opp['yes_sum']:.1%}")
                            print(f"      💰 {opp['strategy']}: ${opp['profit_per_100']:.2f} per $100")

                            # Send Telegram alert for high-edge opportunities (>3%)
                            if opp['profit_per_100'] >= 3.0:
                                try:
                                    send_arbitrage_alert(opp)
                                except Exception as e:
                                    print(f"   ⚠️ Telegram alert failed: {e}")

                        poly_executed = self.execute_polymarket_arbitrage(poly_opps)
                        if poly_executed > 0:
                            print(f"✅ Executed {poly_executed} Polymarket arb paper trade(s)")

                # 4. Scan PredictIt
                if self.predictit_adapter:
                    predictit_opps = self.scan_predictit_arbitrage()
                    if predictit_opps:
                        print(f"\n🎯 PREDICTIT ARBITRAGE FOUND ({len(predictit_opps)} opportunities):")
                        for opp in predictit_opps[:5]:
                            print(f"   📍 {opp['title'][:45]}...")
                            print(f"      {opp['num_outcomes']} outcomes | YES sum: {opp['yes_sum']:.1%}")
                            print(f"      💰 {opp['strategy']}: ${opp['profit_per_100']:.2f} per $100")

                            # Send Telegram alert for high-edge opportunities (>3%)
                            if opp['profit_per_100'] >= 3.0:
                                try:
                                    send_arbitrage_alert(opp)
                                except Exception as e:
                                    print(f"   ⚠️ Telegram alert failed: {e}")
                        # Note: No auto-execution for PredictIt (no trading API)

                # 5. Scan Polymarket 5-min crypto markets
                crypto_opps = self.scan_crypto_markets()
                if crypto_opps:
                    print(f"\n⚡ CRYPTO 5-MIN OPPORTUNITIES ({len(crypto_opps)} found):")
                    for opp in crypto_opps[:3]:
                        print(f"   📍 {opp['title'][:45]}...")
                        print(f"      💰 {opp['strategy']}: ${opp['profit_per_100']:.2f} per $100")

                        if opp['profit_per_100'] >= 2.0:  # Lower threshold for fast crypto
                            try:
                                send_arbitrage_alert(opp)
                            except Exception as e:
                                print(f"   ⚠️ Telegram alert failed: {e}")

                # Track opportunities found this scan
                scan_opps = len(kalshi_opps) + len(poly_opps if 'poly_opps' in dir() else []) + len(predictit_opps if 'predictit_opps' in dir() else []) + len(crypto_opps)
                total_opps_found += scan_opps

                # Periodic reporting
                if time.time() - self.last_metrics_time > config.METRICS_INTERVAL:
                    self.risk_manager.print_risk_summary(self.bankroll, self.sim_positions)
                    print_performance_report()
                    log_metrics(
                        self.bankroll,
                        self.bankroll - self.risk_manager.daily_start_bankroll,
                        self.bankroll - self.risk_manager.starting_bankroll,
                        self.sim_positions,
                    )
                    self.last_metrics_time = time.time()

                # Hourly heartbeat to Telegram
                if time.time() - last_heartbeat > heartbeat_interval:
                    try:
                        from telegram_alerts import send_heartbeat
                        send_heartbeat(self.scan_count, total_opps_found)
                        print("💓 Heartbeat sent to Telegram")
                    except Exception as e:
                        print(f"⚠️ Heartbeat failed: {e}")
                    last_heartbeat = time.time()

                time.sleep(config.SCAN_INTERVAL)

            except KeyboardInterrupt:
                print(f"\n{'=' * 60}")
                print("⏹️ SCANNER STOPPED BY USER")
                print(f"{'=' * 60}")
                self.risk_manager.print_risk_summary(self.bankroll, self.sim_positions)
                print_performance_report()
                break


if __name__ == "__main__":
    scanner = SeerScanner()
    scanner.run()
