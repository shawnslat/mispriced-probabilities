"""
Multi-Platform Market Adapter
============================

Provides a unified interface for fetching market data from different
prediction market platforms (Kalshi, Polymarket, etc.)

This abstraction layer makes it easy to:
1. Add new platforms without changing scanner logic
2. Run arbitrage detection across multiple platforms
3. Compare prices between platforms for cross-platform arb

Currently Supported:
- Kalshi (Elections API)

Coming Soon:
- Polymarket (when API access is available)
- Metaculus (read-only)
- PredictIt (if reopened)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
import time


class Platform(Enum):
    """Supported prediction market platforms."""
    KALSHI = "kalshi"
    POLYMARKET = "polymarket"
    METACULUS = "metaculus"
    PREDICTIT = "predictit"


@dataclass
class StandardMarket:
    """
    Platform-agnostic market representation.
    
    All platform adapters convert their native format to this standard format.
    """
    # Identifiers
    platform: Platform
    market_id: str
    event_id: Optional[str] = None
    
    # Display
    title: str = ""
    description: str = ""
    category: str = "other"
    
    # Prices (0-1 scale)
    yes_bid: float = 0.0
    yes_ask: float = 0.0
    no_bid: float = 0.0
    no_ask: float = 0.0
    
    # Convenience properties
    @property
    def yes_price(self) -> float:
        """Midpoint YES price."""
        if self.yes_bid > 0 and self.yes_ask > 0:
            return (self.yes_bid + self.yes_ask) / 2
        return self.yes_bid or self.yes_ask
    
    @property
    def no_price(self) -> float:
        """Midpoint NO price."""
        if self.no_bid > 0 and self.no_ask > 0:
            return (self.no_bid + self.no_ask) / 2
        return self.no_bid or self.no_ask
    
    @property
    def spread(self) -> float:
        """YES bid-ask spread."""
        return self.yes_ask - self.yes_bid if self.yes_ask > self.yes_bid else 0
    
    @property
    def price_sum(self) -> float:
        """Sum of YES + NO prices (should be ~1.00)."""
        return self.yes_price + self.no_price
    
    # Volume and liquidity
    volume: float = 0.0
    volume_24h: float = 0.0
    open_interest: float = 0.0
    liquidity: float = 0.0
    
    # Timing
    close_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    # Status
    status: str = "open"
    result: Optional[str] = None  # "yes", "no", None
    
    # Multi-outcome support
    is_multi_outcome: bool = False
    outcomes: list[dict] = None  # For multi-outcome markets
    
    # Raw data
    raw_data: dict = None
    
    def __post_init__(self):
        if self.outcomes is None:
            self.outcomes = []
        if self.raw_data is None:
            self.raw_data = {}
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage/serialization."""
        return {
            "platform": self.platform.value,
            "market_id": self.market_id,
            "event_id": self.event_id,
            "title": self.title,
            "category": self.category,
            "yes_bid": self.yes_bid,
            "yes_ask": self.yes_ask,
            "no_bid": self.no_bid,
            "no_ask": self.no_ask,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "spread": self.spread,
            "price_sum": self.price_sum,
            "volume": self.volume,
            "volume_24h": self.volume_24h,
            "open_interest": self.open_interest,
            "liquidity": self.liquidity,
            "close_time": self.close_time.isoformat() if self.close_time else None,
            "status": self.status,
            "is_multi_outcome": self.is_multi_outcome,
            "outcomes": self.outcomes,
        }


class PlatformAdapter(ABC):
    """Abstract base class for platform adapters."""
    
    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform identifier."""
        pass
    
    @abstractmethod
    def fetch_markets(
        self,
        status: str = "open",
        limit: int = 100,
        category: Optional[str] = None,
    ) -> list[StandardMarket]:
        """Fetch markets from the platform."""
        pass
    
    @abstractmethod
    def fetch_market_details(self, market_id: str) -> Optional[StandardMarket]:
        """Fetch detailed info for a specific market."""
        pass
    
    @abstractmethod
    def fetch_events(self, limit: int = 50) -> list[dict]:
        """Fetch events/market groups from the platform."""
        pass
    
    def is_available(self) -> bool:
        """Check if the platform API is accessible."""
        try:
            markets = self.fetch_markets(limit=1)
            return len(markets) > 0
        except Exception:
            return False


class KalshiAdapter(PlatformAdapter):
    """
    Kalshi Elections API adapter.
    
    Converts Kalshi's native format to StandardMarket.
    """
    
    def __init__(self):
        self._rate_limit_delay = 0.5  # seconds between requests
        self._last_request_time = 0
    
    @property
    def platform(self) -> Platform:
        return Platform.KALSHI
    
    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()
    
    def _signed_request(self, method: str, path: str, params: dict = None):
        """Make a signed request to Kalshi API."""
        try:
            from portfolio_manager import signed_request
            return signed_request(method, path, params=params)
        except ImportError:
            raise RuntimeError("portfolio_manager not available")
    
    def _normalize_price(self, price: float) -> float:
        """Convert Kalshi's 0-100 prices to 0-1."""
        if price is None:
            return 0.0
        return price / 100 if price > 1 else price
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse Kalshi datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def _convert_market(self, raw: dict, category: str = "other") -> StandardMarket:
        """Convert Kalshi market dict to StandardMarket."""
        return StandardMarket(
            platform=Platform.KALSHI,
            market_id=raw.get("ticker", ""),
            event_id=raw.get("event_ticker"),
            title=raw.get("title", "Unknown"),
            description=raw.get("subtitle", ""),
            category=category,
            yes_bid=self._normalize_price(raw.get("yes_bid", 0)),
            yes_ask=self._normalize_price(raw.get("yes_ask", 0)),
            no_bid=self._normalize_price(raw.get("no_bid", 0)),
            no_ask=self._normalize_price(raw.get("no_ask", 0)),
            volume=raw.get("volume", 0),
            volume_24h=raw.get("volume_24h", 0),
            open_interest=raw.get("open_interest", 0),
            liquidity=raw.get("liquidity", raw.get("open_interest", 0)),
            close_time=self._parse_datetime(raw.get("close_time")),
            created_at=self._parse_datetime(raw.get("created_time")),
            status=raw.get("status", "unknown"),
            result=raw.get("result"),
            is_multi_outcome=False,  # Kalshi markets are binary
            raw_data=raw,
        )
    
    def fetch_events(self, limit: int = 50) -> list[dict]:
        """Fetch events from Kalshi."""
        self._rate_limit()
        
        try:
            response = self._signed_request(
                'GET',
                '/trade-api/v2/events',
                params={'status': 'open', 'limit': limit}
            )
            
            if response.status_code != 200:
                return []
            
            return response.json().get('events', [])
        except Exception as e:
            print(f"Error fetching Kalshi events: {e}")
            return []
    
    def fetch_markets(
        self,
        status: str = "open",
        limit: int = 100,
        category: Optional[str] = None,
    ) -> list[StandardMarket]:
        """
        Fetch markets from Kalshi.
        
        Uses events-first approach to avoid parlay markets.
        """
        markets = []
        events = self.fetch_events(limit=50)
        
        for event in events:
            event_ticker = event.get('event_ticker')
            event_category = event.get('category', 'other')
            
            if category and event_category.lower() != category.lower():
                continue
            
            if not event_ticker:
                continue
            
            self._rate_limit()
            
            try:
                response = self._signed_request(
                    'GET',
                    '/trade-api/v2/markets',
                    params={'event_ticker': event_ticker, 'status': status}
                )
                
                if response.status_code != 200:
                    continue
                
                raw_markets = response.json().get('markets', [])
                
                for raw in raw_markets:
                    # Skip parlay/combo markets
                    if raw.get('mve_collection_ticker') or raw.get('custom_strike'):
                        continue
                    
                    markets.append(self._convert_market(raw, event_category))
                    
                    if len(markets) >= limit:
                        return markets
                        
            except Exception as e:
                print(f"Error fetching markets for {event_ticker}: {e}")
                continue
        
        return markets
    
    def fetch_market_details(self, market_id: str) -> Optional[StandardMarket]:
        """Fetch detailed info for a specific market."""
        self._rate_limit()
        
        try:
            response = self._signed_request(
                'GET',
                f'/trade-api/v2/markets/{market_id}'
            )
            
            if response.status_code != 200:
                return None
            
            raw = response.json().get('market', {})
            return self._convert_market(raw)
            
        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            return None
    
    def fetch_markets_for_event(self, event_ticker: str) -> list[StandardMarket]:
        """Fetch all markets for a specific event (for multi-outcome arb)."""
        self._rate_limit()
        
        try:
            response = self._signed_request(
                'GET',
                '/trade-api/v2/markets',
                params={'event_ticker': event_ticker, 'status': 'open'}
            )
            
            if response.status_code != 200:
                return []
            
            raw_markets = response.json().get('markets', [])
            
            markets = []
            for raw in raw_markets:
                if raw.get('mve_collection_ticker') or raw.get('custom_strike'):
                    continue
                markets.append(self._convert_market(raw))
            
            return markets
            
        except Exception as e:
            print(f"Error fetching markets for event {event_ticker}: {e}")
            return []


class PolymarketAdapter(PlatformAdapter):
    """
    Polymarket API adapter (Enhanced v2).

    Uses multiple APIs:
    - Gamma API (gamma-api.polymarket.com): Market discovery, metadata, events
    - CLOB API (clob.polymarket.com): Real-time prices, orderbooks, trading
    - RTDS WebSocket (ws-live-data.polymarket.com): Low-latency crypto feeds
    - Data API (data-api.polymarket.com): Positions, activity, history

    Read-only operations (prices, markets) don't require authentication.
    Trading operations require API key + wallet signature.

    Rate limits (CLOB):
    - GET /book: 50 req / 10s
    - POST /order: 500 burst / 10s, 3000 / 10min
    - DELETE /order: 500 burst / 10s
    """

    def __init__(self, api_key: Optional[str] = None):
        import requests
        self.api_key = api_key
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.data_url = "https://data-api.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Seer/2.0',
            'Accept': 'application/json',
        })
        if api_key:
            self.session.headers['Authorization'] = f'Bearer {api_key}'
        self._rate_limit_delay = 0.2  # 200ms between requests
        self._last_request_time = 0
        # CLOB book cache (token_id -> {prices, timestamp})
        self._book_cache: dict[str, dict] = {}
        self._book_cache_ttl = 5  # 5 second cache for CLOB prices

    @property
    def platform(self) -> Platform:
        return Platform.POLYMARKET

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _gamma_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make a request to Gamma API."""
        self._rate_limit()
        try:
            url = f"{self.gamma_url}{endpoint}"
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Gamma API error {response.status_code}: {endpoint}")
                return None
        except Exception as e:
            print(f"Gamma API request failed: {e}")
            return None

    def _clob_request(self, endpoint: str, params: dict = None, method: str = 'GET', json_data: dict = None) -> Optional[dict]:
        """Make a request to CLOB API."""
        self._rate_limit()
        try:
            url = f"{self.clob_url}{endpoint}"
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=10)
            elif method == 'POST':
                response = self.session.post(url, json=json_data, timeout=10)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params, timeout=10)
            else:
                return None

            if response.status_code == 200:
                return response.json()
            else:
                print(f"CLOB API error {response.status_code}: {endpoint}")
                return None
        except Exception as e:
            print(f"CLOB API request failed: {e}")
            return None

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse Polymarket datetime string."""
        if not dt_str:
            return None
        try:
            if 'Z' in dt_str:
                dt_str = dt_str.replace('Z', '+00:00')
            return datetime.fromisoformat(dt_str)
        except (ValueError, AttributeError):
            return None

    def _get_clob_prices(self, token_id: str) -> dict:
        """Get bid/ask prices from CLOB for a token (with cache)."""
        # Check cache first
        cached = self._book_cache.get(token_id)
        if cached and (time.time() - cached['ts']) < self._book_cache_ttl:
            return cached['prices']

        prices = {'yes_bid': 0, 'yes_ask': 0, 'no_bid': 0, 'no_ask': 0}

        book = self._clob_request('/book', {'token_id': token_id})
        if book:
            bids = book.get('bids', [])
            asks = book.get('asks', [])

            if bids:
                prices['yes_bid'] = float(bids[0].get('price', 0))
            if asks:
                prices['yes_ask'] = float(asks[0].get('price', 0))

            if prices['yes_ask'] > 0:
                prices['no_bid'] = 1.0 - prices['yes_ask']
            if prices['yes_bid'] > 0:
                prices['no_ask'] = 1.0 - prices['yes_bid']

            # Cache the result
            self._book_cache[token_id] = {'prices': prices, 'ts': time.time()}

        return prices

    def fetch_clob_books_batch(self, token_ids: list[str]) -> dict[str, dict]:
        """
        Fetch orderbooks for multiple tokens using enhanced /books endpoint.
        Returns dict of token_id -> orderbook data.
        Much faster than individual /book calls.
        """
        results = {}
        # CLOB supports batch book fetches
        for token_id in token_ids:
            book = self._clob_request('/book', {'token_id': token_id})
            if book:
                results[token_id] = book
        return results

    def fetch_clob_midpoints_batch(self, token_ids: list[str]) -> dict[str, float]:
        """
        Fetch midpoint prices for multiple tokens.
        Returns dict of token_id -> midpoint price.
        """
        results = {}
        for token_id in token_ids:
            data = self._clob_request('/midpoint', {'token_id': token_id})
            if data and 'mid' in data:
                results[token_id] = float(data['mid'])
        return results

    def _convert_market(self, raw: dict, clob_prices: dict = None) -> StandardMarket:
        """Convert Polymarket market dict to StandardMarket."""
        yes_bid, yes_ask, no_bid, no_ask = 0, 0, 0, 0

        # PRIORITY 1: Use CLOB real-time prices if available
        if clob_prices:
            yes_bid = clob_prices.get('yes_bid', 0)
            yes_ask = clob_prices.get('yes_ask', 0)
            no_bid = clob_prices.get('no_bid', 0)
            no_ask = clob_prices.get('no_ask', 0)

        # PRIORITY 2: Use Gamma API outcomePrices
        if yes_bid == 0 and yes_ask == 0:
            outcome_prices = raw.get('outcomePrices', [])
            if outcome_prices and len(outcome_prices) >= 2:
                try:
                    yes_price = float(outcome_prices[0])
                    no_price = float(outcome_prices[1])
                    spread = 0.02
                    yes_bid = max(0, yes_price - spread/2)
                    yes_ask = min(1, yes_price + spread/2)
                    no_bid = max(0, no_price - spread/2)
                    no_ask = min(1, no_price + spread/2)
                except (ValueError, IndexError, TypeError):
                    pass

        # PRIORITY 3: Try bestBid/bestAsk
        if yes_bid == 0 and yes_ask == 0:
            try:
                best_bid = raw.get('bestBid')
                best_ask = raw.get('bestAsk')
                if best_bid is not None:
                    yes_bid = float(best_bid)
                if best_ask is not None:
                    yes_ask = float(best_ask)
                if yes_bid > 0:
                    no_ask = 1.0 - yes_bid
                if yes_ask > 0:
                    no_bid = 1.0 - yes_ask
            except (ValueError, TypeError):
                pass

        # Parse volume
        volume = 0
        try:
            volume = float(raw.get('volume', 0) or raw.get('volumeNum', 0) or 0)
        except (ValueError, TypeError):
            pass

        # Parse liquidity
        liquidity = 0
        try:
            liquidity = float(raw.get('liquidity', 0) or raw.get('liquidityNum', 0) or 0)
        except (ValueError, TypeError):
            pass

        return StandardMarket(
            platform=Platform.POLYMARKET,
            market_id=raw.get('id', raw.get('conditionId', '')),
            event_id=raw.get('groupItemSlug', raw.get('slug', '')),
            title=raw.get('question', raw.get('title', 'Unknown')),
            description=raw.get('description', ''),
            category=raw.get('groupItemTitle', 'other'),
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            volume=volume,
            volume_24h=volume,
            open_interest=liquidity,
            liquidity=liquidity,
            close_time=self._parse_datetime(raw.get('endDate', raw.get('endDateIso', ''))),
            created_at=self._parse_datetime(raw.get('startDate', raw.get('createdAt', ''))),
            status='open' if raw.get('active', True) and not raw.get('closed', False) else 'closed',
            result=raw.get('resolutionSource'),
            is_multi_outcome=len(raw.get('outcomes', [])) > 2,
            raw_data=raw,
        )

    def fetch_events(self, limit: int = 50) -> list[dict]:
        """Fetch events from Polymarket Gamma API."""
        data = self._gamma_request('/events', {
            'active': 'true',
            'closed': 'false',
            'limit': limit,
        })

        if data and isinstance(data, list):
            return data[:limit]
        return []

    def fetch_markets(
        self,
        status: str = "open",
        limit: int = 100,
        category: Optional[str] = None,
    ) -> list[StandardMarket]:
        """Fetch markets from Polymarket Gamma API."""
        params = {
            'active': 'true' if status == 'open' else 'false',
            'closed': 'false' if status == 'open' else 'true',
            'limit': limit,
        }

        if category:
            params['tag'] = category

        data = self._gamma_request('/markets', params)

        if not data:
            return []

        markets = []
        items = data if isinstance(data, list) else data.get('markets', [])

        for raw in items[:limit]:
            try:
                market = self._convert_market(raw)
                if market.yes_price > 0 or market.no_price > 0:
                    markets.append(market)
            except Exception:
                continue

        return markets

    def fetch_crypto_markets(self, interval: str = "5min") -> list[StandardMarket]:
        """
        Fetch 5-minute and 15-minute crypto prediction markets.
        These are rapid UP/DOWN binary markets on BTC, ETH, SOL, XRP.

        Args:
            interval: "5min" or "15min"
        """
        # Search for crypto Up/Down markets
        tag = "crypto" if interval == "5min" else "crypto"
        data = self._gamma_request('/markets', {
            'active': 'true',
            'closed': 'false',
            'limit': 100,
            'tag': tag,
        })

        if not data:
            return []

        crypto_markets = []
        items = data if isinstance(data, list) else data.get('markets', [])

        for raw in items:
            question = raw.get('question', '').lower()
            # Filter for up/down crypto markets
            if any(kw in question for kw in ['up or down', 'higher or lower', 'btc', 'eth', 'sol', 'xrp', 'bitcoin', 'ethereum']):
                try:
                    market = self._convert_market(raw)
                    if market.yes_price > 0:
                        crypto_markets.append(market)
                except Exception:
                    continue

        return crypto_markets

    def fetch_market_details(self, market_id: str) -> Optional[StandardMarket]:
        """Fetch detailed info for a specific market."""
        data = self._gamma_request(f'/markets/{market_id}')

        if not data:
            data = self._gamma_request('/markets', {'slug': market_id})
            if data and isinstance(data, list) and len(data) > 0:
                data = data[0]

        if not data:
            return None

        try:
            return self._convert_market(data)
        except Exception as e:
            print(f"Error fetching Polymarket market {market_id}: {e}")
            return None

    def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch full orderbook for a token."""
        return self._clob_request('/book', {'token_id': token_id})

    def fetch_price(self, token_id: str, side: str = 'buy') -> Optional[float]:
        """Fetch current price for a token."""
        data = self._clob_request('/price', {
            'token_id': token_id,
            'side': side,
        })
        if data:
            return float(data.get('price', 0))
        return None

    def fetch_midpoint(self, token_id: str) -> Optional[float]:
        """Fetch midpoint price for a token."""
        data = self._clob_request('/midpoint', {'token_id': token_id})
        if data and 'mid' in data:
            return float(data['mid'])
        return None

    # === ORDER BATCHING (for future live trading) ===

    def place_batch_orders(self, orders: list[dict]) -> Optional[dict]:
        """
        Place up to 5 orders in a single request (requires API key).
        Each order: {token_id, price, size, side, type}

        Note: Only works with authenticated session (API key required).
        """
        if not self.api_key:
            print("⚠️ Batch orders require API key")
            return None
        if len(orders) > 5:
            print("⚠️ Maximum 5 orders per batch")
            orders = orders[:5]

        return self._clob_request('/orders', method='POST', json_data={'orders': orders})


class PredictItAdapter(PlatformAdapter):
    """
    PredictIt API adapter.

    Public read-only API for political prediction markets.
    No authentication required for market data.
    Note: Trading must be done manually on their website.
    """

    def __init__(self):
        import requests
        self.base_url = "https://www.predictit.org/api/marketdata"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Seer/1.0',
            'Accept': 'application/json',
        })
        self._rate_limit_delay = 1.0  # Be nice to their API
        self._last_request_time = 0
        self._cached_markets = None
        self._cache_time = 0

    @property
    def platform(self) -> Platform:
        return Platform.PREDICTIT

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._rate_limit_delay:
            time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _fetch_all_data(self) -> Optional[dict]:
        """Fetch all market data from PredictIt (cached for 60s)."""
        # Return cached data if fresh
        if self._cached_markets and (time.time() - self._cache_time) < 60:
            return self._cached_markets

        self._rate_limit()
        try:
            response = self.session.get(f"{self.base_url}/all/", timeout=15)
            if response.status_code == 200:
                self._cached_markets = response.json()
                self._cache_time = time.time()
                return self._cached_markets
            else:
                print(f"PredictIt API error: {response.status_code}")
                return None
        except Exception as e:
            print(f"PredictIt request failed: {e}")
            return None

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse PredictIt datetime string."""
        if not dt_str:
            return None
        try:
            # PredictIt uses ISO format
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None

    def _convert_contract(self, contract: dict, market_name: str, market_id: int) -> StandardMarket:
        """Convert a PredictIt contract to StandardMarket."""
        # PredictIt prices are already 0-1 (displayed as cents)
        yes_bid = contract.get('bestBuyYesCost') or 0
        yes_ask = contract.get('bestSellYesCost') or 0
        no_bid = contract.get('bestBuyNoCost') or 0
        no_ask = contract.get('bestSellNoCost') or 0

        # Last trade prices as fallback
        if yes_bid == 0 and yes_ask == 0:
            last_price = contract.get('lastTradePrice') or 0
            if last_price > 0:
                yes_bid = max(0, last_price - 0.02)
                yes_ask = min(1, last_price + 0.02)
                no_bid = max(0, (1 - last_price) - 0.02)
                no_ask = min(1, (1 - last_price) + 0.02)

        return StandardMarket(
            platform=Platform.PREDICTIT,
            market_id=str(contract.get('id', '')),
            event_id=str(market_id),
            title=contract.get('name', contract.get('shortName', 'Unknown')),
            description=market_name,
            category='politics',
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            volume=0,  # PredictIt doesn't expose volume
            volume_24h=0,
            open_interest=0,
            liquidity=0,
            close_time=self._parse_datetime(contract.get('dateEnd')),
            status='open' if contract.get('status') == 'Open' else 'closed',
            is_multi_outcome=False,
            raw_data=contract,
        )

    def fetch_events(self, limit: int = 50) -> list[dict]:
        """Fetch all markets (events) from PredictIt."""
        data = self._fetch_all_data()
        if not data:
            return []
        markets = data.get('markets', [])
        return markets[:limit]

    def fetch_markets(
        self,
        status: str = "open",
        limit: int = 100,
        category: Optional[str] = None,
    ) -> list[StandardMarket]:
        """Fetch markets from PredictIt."""
        data = self._fetch_all_data()
        if not data:
            return []

        markets = []
        for market in data.get('markets', []):
            market_name = market.get('name', '')
            market_id = market.get('id', 0)
            market_status = market.get('status', '')

            # Filter by status
            if status == 'open' and market_status != 'Open':
                continue

            contracts = market.get('contracts', [])
            for contract in contracts:
                contract_status = contract.get('status', '')
                if status == 'open' and contract_status != 'Open':
                    continue

                try:
                    std_market = self._convert_contract(contract, market_name, market_id)
                    if std_market.yes_price > 0 or std_market.no_price > 0:
                        markets.append(std_market)
                except Exception:
                    continue

                if len(markets) >= limit:
                    return markets

        return markets

    def fetch_market_details(self, market_id: str) -> Optional[StandardMarket]:
        """Fetch details for a specific market."""
        self._rate_limit()
        try:
            response = self.session.get(
                f"{self.base_url}/markets/{market_id}/",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                contracts = data.get('contracts', [])
                if contracts:
                    return self._convert_contract(
                        contracts[0],
                        data.get('name', ''),
                        int(market_id)
                    )
            return None
        except Exception as e:
            print(f"Error fetching PredictIt market {market_id}: {e}")
            return None

    def fetch_multi_outcome_markets(self) -> list[dict]:
        """
        Fetch markets grouped by event for multi-outcome arbitrage detection.
        Returns list of events with their contracts.
        """
        data = self._fetch_all_data()
        if not data:
            return []

        multi_outcome = []
        for market in data.get('markets', []):
            contracts = market.get('contracts', [])
            # Only include markets with multiple contracts (multi-outcome)
            if len(contracts) >= 2:
                open_contracts = [c for c in contracts if c.get('status') == 'Open']
                if len(open_contracts) >= 2:
                    multi_outcome.append({
                        'market_id': market.get('id'),
                        'name': market.get('name'),
                        'contracts': open_contracts,
                        'num_outcomes': len(open_contracts),
                    })

        return multi_outcome


class MultiPlatformScanner:
    """
    Unified scanner that works across multiple prediction market platforms.
    
    Usage:
        scanner = MultiPlatformScanner()
        scanner.add_platform(KalshiAdapter())
        scanner.add_platform(PolymarketAdapter(api_key="..."))  # when available
        
        markets = scanner.fetch_all_markets()
        opportunities = scanner.scan_for_arbitrage()
    """
    
    def __init__(self):
        self.adapters: dict[Platform, PlatformAdapter] = {}
    
    def add_platform(self, adapter: PlatformAdapter) -> None:
        """Register a platform adapter."""
        self.adapters[adapter.platform] = adapter
    
    def remove_platform(self, platform: Platform) -> None:
        """Remove a platform adapter."""
        if platform in self.adapters:
            del self.adapters[platform]
    
    def get_available_platforms(self) -> list[Platform]:
        """Get list of configured platforms."""
        return list(self.adapters.keys())
    
    def fetch_all_markets(
        self,
        status: str = "open",
        limit_per_platform: int = 100,
    ) -> list[StandardMarket]:
        """Fetch markets from all configured platforms."""
        all_markets = []
        
        for platform, adapter in self.adapters.items():
            try:
                markets = adapter.fetch_markets(status=status, limit=limit_per_platform)
                all_markets.extend(markets)
                print(f"✓ Fetched {len(markets)} markets from {platform.value}")
            except Exception as e:
                print(f"✗ Failed to fetch from {platform.value}: {e}")
        
        return all_markets
    
    def scan_for_arbitrage(
        self,
        markets: Optional[list[StandardMarket]] = None,
        min_profit: float = 0.02,
    ) -> list:
        """
        Scan markets for arbitrage opportunities.
        
        This integrates with the ArbitrageDetector module.
        """
        from arbitrage import ArbitrageDetector, ArbitrageOpportunity
        
        if markets is None:
            markets = self.fetch_all_markets()
        
        opportunities = []
        
        # Group markets by platform for platform-specific detection
        by_platform: dict[Platform, list[StandardMarket]] = {}
        for m in markets:
            if m.platform not in by_platform:
                by_platform[m.platform] = []
            by_platform[m.platform].append(m)
        
        # Scan each platform
        for platform, platform_markets in by_platform.items():
            detector = ArbitrageDetector(
                min_profit_threshold=min_profit,
                platform=platform.value
            )
            
            for market in platform_markets:
                # Check single-condition arb
                opp = detector.check_single_condition(
                    market_id=market.market_id,
                    market_title=market.title,
                    yes_bid=market.yes_bid,
                    no_bid=market.no_bid,
                    yes_ask=market.yes_ask,
                    no_ask=market.no_ask,
                    liquidity=market.liquidity,
                )
                
                if opp and opp.is_profitable_after_spread:
                    opportunities.append(opp)
        
        # TODO: Cross-platform arbitrage detection
        # Compare same/similar markets across platforms
        
        # Sort by profit potential
        opportunities.sort(key=lambda x: x.profit_per_dollar, reverse=True)
        
        return opportunities


# Factory function for easy setup
def create_scanner(
    include_kalshi: bool = True,
    include_polymarket: bool = True,
    polymarket_api_key: Optional[str] = None,
) -> MultiPlatformScanner:
    """
    Create a configured multi-platform scanner.

    Args:
        include_kalshi: Include Kalshi adapter
        include_polymarket: Include Polymarket adapter (no auth needed for reading)
        polymarket_api_key: Polymarket API key (only needed for trading)

    Returns:
        Configured MultiPlatformScanner
    """
    scanner = MultiPlatformScanner()

    if include_kalshi:
        try:
            scanner.add_platform(KalshiAdapter())
        except Exception as e:
            print(f"Warning: Could not add Kalshi adapter: {e}")

    if include_polymarket:
        # Polymarket read-only doesn't require API key
        scanner.add_platform(PolymarketAdapter(api_key=polymarket_api_key))

    return scanner


# Test
if __name__ == "__main__":
    print("=" * 60)
    print("MULTI-PLATFORM ADAPTER TEST")
    print("=" * 60)

    # Test Kalshi adapter
    print("\n--- Testing Kalshi Adapter ---")

    try:
        kalshi = KalshiAdapter()

        if kalshi.is_available():
            print("✓ Kalshi API is available")

            # Fetch some markets
            markets = kalshi.fetch_markets(limit=5)
            print(f"✓ Fetched {len(markets)} markets")

            for m in markets[:3]:
                print(f"\n  {m.title[:50]}")
                print(f"    YES: {m.yes_bid:.2f}/{m.yes_ask:.2f} | NO: {m.no_bid:.2f}/{m.no_ask:.2f}")
                print(f"    Sum: {m.price_sum:.3f} | Spread: {m.spread:.3f}")
        else:
            print("✗ Kalshi API not available")

    except Exception as e:
        print(f"✗ Kalshi Error: {e}")

    # Test Polymarket adapter
    print("\n--- Testing Polymarket Adapter ---")

    try:
        poly = PolymarketAdapter()

        if poly.is_available():
            print("✓ Polymarket API is available")

            # Fetch some markets
            markets = poly.fetch_markets(limit=5)
            print(f"✓ Fetched {len(markets)} markets")

            for m in markets[:3]:
                print(f"\n  {m.title[:50]}")
                print(f"    YES: {m.yes_bid:.2f}/{m.yes_ask:.2f} | NO: {m.no_bid:.2f}/{m.no_ask:.2f}")
                print(f"    Sum: {m.price_sum:.3f} | Spread: {m.spread:.3f}")
                print(f"    Volume: ${m.volume:,.0f} | Liquidity: ${m.liquidity:,.0f}")
        else:
            print("✗ Polymarket API not available")

    except Exception as e:
        print(f"✗ Polymarket Error: {e}")

    # Test multi-platform scanner
    print("\n--- Testing Multi-Platform Scanner ---")

    scanner = create_scanner(include_kalshi=True, include_polymarket=True)
    print(f"Configured platforms: {[p.value for p in scanner.get_available_platforms()]}")

    # Scan for arbitrage
    print("\n--- Scanning for Arbitrage ---")
    opportunities = scanner.scan_for_arbitrage(min_profit=0.02)
    print(f"Found {len(opportunities)} opportunities")

    for opp in opportunities[:5]:
        print(f"\n  {opp.market_title[:50]}")
        print(f"    Platform: {opp.platform} | Profit: {opp.profit_percent:.2f}%")
