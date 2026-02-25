"""
Platform API - Live market data and arbitrage scanning.

This module provides the dashboard with:
1. Live market prices and trending markets
2. Arbitrage opportunity scanning
3. Account balance and positions
4. Market health metrics

Supports Kalshi and Polymarket.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path to import from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialize flags
KALSHI_API_AVAILABLE = False
POLYMARKET_API_AVAILABLE = False

try:
    from portfolio_manager import get_account_balance, signed_request
    from arbitrage import ArbitrageDetector, ArbitrageOpportunity, ArbitrageType
    from market_adapter import KalshiAdapter, PolymarketAdapter, StandardMarket
    import config
    KALSHI_API_AVAILABLE = True
except Exception as e:
    print(f"Warning: Kalshi API not available: {e}")

# Try to initialize Polymarket (doesn't require auth for reading)
try:
    from market_adapter import PolymarketAdapter
    import config
    if config.POLYMARKET_ENABLED:
        POLYMARKET_API_AVAILABLE = True
except Exception as e:
    print(f"Warning: Polymarket API not available: {e}")

# Initialize adapters
_kalshi_adapter = None
_polymarket_adapter = None

if KALSHI_API_AVAILABLE:
    try:
        _kalshi_adapter = KalshiAdapter()
    except Exception as e:
        print(f"Warning: Could not initialize Kalshi adapter: {e}")
        KALSHI_API_AVAILABLE = False

if POLYMARKET_API_AVAILABLE:
    try:
        _polymarket_adapter = PolymarketAdapter()
    except Exception as e:
        print(f"Warning: Could not initialize Polymarket adapter: {e}")
        POLYMARKET_API_AVAILABLE = False

# Initialize arbitrage detector
_arb_detector = None
if KALSHI_API_AVAILABLE or POLYMARKET_API_AVAILABLE:
    try:
        _arb_detector = ArbitrageDetector(
            min_profit_threshold=config.ARB_MIN_PROFIT if KALSHI_API_AVAILABLE else 0.02,
            min_net_profit=config.ARB_MIN_NET_PROFIT if KALSHI_API_AVAILABLE else 0.005,
            platform="multi"
        )
    except:
        pass


def is_api_available() -> bool:
    """Check if any platform API is properly configured."""
    return KALSHI_API_AVAILABLE or POLYMARKET_API_AVAILABLE


def is_kalshi_available() -> bool:
    """Check if Kalshi API is available."""
    return KALSHI_API_AVAILABLE


def is_polymarket_available() -> bool:
    """Check if Polymarket API is available."""
    return POLYMARKET_API_AVAILABLE


def get_live_balance() -> Optional[float]:
    """Get current Kalshi account balance."""
    if not KALSHI_API_AVAILABLE:
        return None
    try:
        return get_account_balance()
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return None


def get_live_market_price(market_ticker: str) -> Optional[dict]:
    """
    Get current market price and details.
    
    Returns:
        dict with keys: yes_price, no_price, volume, liquidity, status
    """
    if not KALSHI_API_AVAILABLE or not _kalshi_adapter:
        return None
    
    try:
        market = _kalshi_adapter.fetch_market_details(market_ticker)
        if not market:
            return None
        
        return {
            'yes_bid': market.yes_bid,
            'no_bid': market.no_bid,
            'yes_ask': market.yes_ask,
            'no_ask': market.no_ask,
            # Legacy compatibility
            'yes_price': market.yes_price,
            'no_price': market.no_price,
            'volume': market.volume,
            'open_interest': market.open_interest,
            'liquidity': market.liquidity,
            'status': market.status,
            'close_time': market.close_time.isoformat() if market.close_time else None,
            'spread': market.spread,
            'price_sum': market.price_sum,
        }
    except Exception as e:
        print(f"Error fetching market {market_ticker}: {e}")
        return None


def get_trending_markets(limit: int = 10) -> list[dict]:
    """
    Get trending markets sorted by volume from all available platforms.

    Returns:
        List of market dicts with title, ticker, prices, volume, platform
    """
    all_markets = []

    # Fetch from Kalshi
    if KALSHI_API_AVAILABLE and _kalshi_adapter:
        try:
            markets = _kalshi_adapter.fetch_markets(limit=limit * 2)
            all_markets.extend(markets)
        except Exception as e:
            print(f"Error fetching Kalshi markets: {e}")

    # Fetch from Polymarket
    if POLYMARKET_API_AVAILABLE and _polymarket_adapter:
        try:
            markets = _polymarket_adapter.fetch_markets(limit=limit * 2)
            all_markets.extend(markets)
        except Exception as e:
            print(f"Error fetching Polymarket markets: {e}")

    if not all_markets:
        return []

    # Sort by volume
    all_markets.sort(key=lambda m: m.volume, reverse=True)

    return [
        {
            'title': m.title,
            'ticker': m.market_id,
            'yes_price': m.yes_price,
            'no_price': m.no_price,
            'yes_bid': m.yes_bid,
            'yes_ask': m.yes_ask,
            'no_bid': m.no_bid,
            'no_ask': m.no_ask,
            'volume': m.volume,
            'open_interest': m.open_interest,
            'category': m.category,
            'close_time': m.close_time.isoformat() if m.close_time else None,
            'spread': m.spread,
            'price_sum': m.price_sum,
            'platform': m.platform.value,
        }
        for m in all_markets[:limit]
    ]


def scan_arbitrage_opportunities(limit: int = 50) -> list[ArbitrageOpportunity]:
    """
    Scan all active markets for arbitrage opportunities across all platforms.

    Checks:
    1. Single condition: YES + NO should = $1.00
    2. Multi-outcome events: All YES prices should sum to $1.00

    Returns:
        List of ArbitrageOpportunity objects sorted by profit potential
    """
    if not _arb_detector:
        return []

    if not config.ARB_SCAN_ENABLED:
        return []

    opportunities = []
    seen_markets = set()

    # Scan Kalshi
    if KALSHI_API_AVAILABLE and _kalshi_adapter:
        try:
            kalshi_opps = _scan_kalshi_arbitrage(seen_markets)
            opportunities.extend(kalshi_opps)
        except Exception as e:
            print(f"Error scanning Kalshi: {e}")

    # Scan Polymarket
    if POLYMARKET_API_AVAILABLE and _polymarket_adapter:
        try:
            poly_opps = _scan_polymarket_arbitrage(seen_markets)
            opportunities.extend(poly_opps)
        except Exception as e:
            print(f"Error scanning Polymarket: {e}")

    # Sort by profit potential (descending)
    opportunities.sort(key=lambda x: x.profit_per_dollar, reverse=True)

    return opportunities[:limit]


def _scan_kalshi_arbitrage(seen_markets: set) -> list[ArbitrageOpportunity]:
    """Scan Kalshi markets for arbitrage."""
    opportunities = []

    try:
        events = _kalshi_adapter.fetch_events(limit=100)

        for event in events:
            event_ticker = event.get('event_ticker')
            if not event_ticker:
                continue

            markets = _kalshi_adapter.fetch_markets_for_event(event_ticker)
            if not markets:
                continue

            # Single-condition checks
            if config.ARB_SINGLE_CONDITION:
                for market in markets:
                    if market.market_id in seen_markets:
                        continue
                    seen_markets.add(market.market_id)

                    if market.yes_bid == 0 or market.no_bid == 0:
                        continue

                    opp = _arb_detector.check_single_condition(
                        market_id=market.market_id,
                        market_title=f"[Kalshi] {market.title}",
                        yes_bid=market.yes_bid,
                        no_bid=market.no_bid,
                        yes_ask=market.yes_ask,
                        no_ask=market.no_ask,
                        liquidity=market.liquidity,
                    )

                    if opp and opp.is_profitable_after_spread:
                        opp.platform = "kalshi"
                        opportunities.append(opp)

            # Multi-outcome checks
            if config.ARB_MULTI_OUTCOME and len(markets) >= config.ARB_MIN_OUTCOMES:
                outcomes = [
                    {"name": m.title, "yes_bid": m.yes_bid, "yes_ask": m.yes_ask, "liquidity": m.liquidity}
                    for m in markets if m.yes_bid >= config.ARB_IGNORE_BELOW
                ]

                if len(outcomes) >= config.ARB_MIN_OUTCOMES:
                    opp = _arb_detector.check_multi_outcome(
                        market_id=event_ticker,
                        market_title=f"[Kalshi] {event.get('title', 'Unknown')}",
                        outcomes=outcomes,
                        min_probability_threshold=config.ARB_IGNORE_BELOW,
                    )
                    if opp and opp.is_profitable_after_spread:
                        opp.platform = "kalshi"
                        opportunities.append(opp)

    except Exception as e:
        print(f"Error in Kalshi arb scan: {e}")

    return opportunities


def _scan_polymarket_arbitrage(seen_markets: set) -> list[ArbitrageOpportunity]:
    """Scan Polymarket markets for arbitrage."""
    opportunities = []

    try:
        # Fetch markets from Polymarket
        markets = _polymarket_adapter.fetch_markets(limit=100)

        # Create a Polymarket-specific detector
        poly_detector = ArbitrageDetector(
            min_profit_threshold=config.ARB_MIN_PROFIT,
            min_net_profit=config.ARB_MIN_NET_PROFIT,
            platform="polymarket"
        )

        for market in markets:
            market_key = f"poly_{market.market_id}"
            if market_key in seen_markets:
                continue
            seen_markets.add(market_key)

            # Skip if no prices
            if market.yes_bid == 0 and market.yes_ask == 0:
                continue

            # Single-condition check
            opp = poly_detector.check_single_condition(
                market_id=market.market_id,
                market_title=f"[Polymarket] {market.title}",
                yes_bid=market.yes_bid,
                no_bid=market.no_bid,
                yes_ask=market.yes_ask,
                no_ask=market.no_ask,
                liquidity=market.liquidity,
            )

            if opp and opp.is_profitable_after_spread:
                opp.platform = "polymarket"
                opportunities.append(opp)

    except Exception as e:
        print(f"Error in Polymarket arb scan: {e}")

    return opportunities


def get_market_efficiency_metrics() -> dict:
    """
    Calculate overall market efficiency metrics across all platforms.

    Returns:
        Dict with efficiency score, average price sum deviation, etc.
    """
    all_markets = []

    # Fetch from Kalshi
    if KALSHI_API_AVAILABLE and _kalshi_adapter:
        try:
            markets = _kalshi_adapter.fetch_markets(limit=30)
            all_markets.extend(markets)
        except Exception as e:
            print(f"Error fetching Kalshi for efficiency: {e}")

    # Fetch from Polymarket
    if POLYMARKET_API_AVAILABLE and _polymarket_adapter:
        try:
            markets = _polymarket_adapter.fetch_markets(limit=30)
            all_markets.extend(markets)
        except Exception as e:
            print(f"Error fetching Polymarket for efficiency: {e}")

    if not all_markets:
        return {}

    try:
        price_sums = []
        spreads = []

        for m in all_markets:
            if m.yes_bid > 0 and m.no_bid > 0:
                price_sums.append(m.price_sum)
            if m.spread > 0:
                spreads.append(m.spread)

        if not price_sums:
            return {}

        avg_sum = sum(price_sums) / len(price_sums)
        deviation = abs(1.0 - avg_sum)

        # Efficiency score: 100% = perfectly efficient
        efficiency = max(0, (1 - deviation * 10)) * 100

        return {
            'efficiency_score': efficiency,
            'avg_price_sum': avg_sum,
            'deviation': deviation,
            'avg_spread': sum(spreads) / len(spreads) if spreads else 0,
            'markets_analyzed': len(price_sums),
            'markets_with_deviation': sum(1 for p in price_sums if abs(1.0 - p) > 0.02),
            'platforms': ['kalshi' if KALSHI_API_AVAILABLE else None, 'polymarket' if POLYMARKET_API_AVAILABLE else None],
        }

    except Exception as e:
        print(f"Error calculating efficiency: {e}")
        return {}


def get_open_positions() -> list[dict]:
    """Get current open positions from Kalshi account."""
    if not KALSHI_API_AVAILABLE:
        return []
    
    try:
        response = signed_request('GET', '/trade-api/v2/portfolio/positions')
        if response.status_code != 200:
            return []
        
        return response.json().get('positions', [])
    except Exception as e:
        print(f"Error fetching positions: {e}")
        return []


def get_arb_summary() -> dict:
    """
    Get a summary of current arbitrage opportunities.
    
    Returns:
        Dict with counts and totals by type
    """
    opportunities = scan_arbitrage_opportunities(limit=100)
    
    if not opportunities:
        return {
            'total_count': 0,
            'risk_free_count': 0,
            'total_potential_profit': 0,
            'avg_profit_pct': 0,
            'by_type': {},
        }
    
    by_type = {}
    for opp in opportunities:
        type_name = opp.arb_type.value
        if type_name not in by_type:
            by_type[type_name] = {'count': 0, 'total_profit': 0}
        by_type[type_name]['count'] += 1
        by_type[type_name]['total_profit'] += opp.max_profit
    
    return {
        'total_count': len(opportunities),
        'risk_free_count': sum(1 for o in opportunities if o.is_risk_free),
        'total_potential_profit': sum(o.max_profit for o in opportunities),
        'avg_profit_pct': sum(o.profit_percent for o in opportunities) / len(opportunities),
        'by_type': by_type,
    }


def get_market_spread(market_ticker: str) -> Optional[dict]:
    """
    Calculate bid-ask spread for a market.
    """
    price_data = get_live_market_price(market_ticker)
    if not price_data:
        return None
    
    yes_spread = price_data['yes_ask'] - price_data['yes_bid']
    no_spread = price_data['no_ask'] - price_data['no_bid']
    
    return {
        'yes_spread': yes_spread,
        'no_spread': no_spread,
        'yes_spread_pct': yes_spread / price_data['yes_bid'] if price_data['yes_bid'] > 0 else 0,
        'no_spread_pct': no_spread / price_data['no_bid'] if price_data['no_bid'] > 0 else 0,
        'effective_cost': (yes_spread + no_spread) / 2,
        'effective_cost_pct': (yes_spread + no_spread) / 2 * 100,
    }
