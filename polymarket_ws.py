#!/usr/bin/env python3
"""
Polymarket WebSocket Client
============================

Real-time orderbook and price updates via WebSocket.
Much faster than polling - sub-second price detection.

Endpoints:
- wss://ws-subscriptions-clob.polymarket.com/ws/market  (orderbook changes)
- wss://ws-live-data.polymarket.com  (low-latency crypto feeds)

Usage:
    ws = PolymarketWebSocket(on_price_update=my_callback)
    ws.subscribe_market(token_id)
    ws.start()  # Runs in background thread
"""

import json
import threading
import time
from datetime import datetime
from typing import Callable, Optional

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


class PolymarketWebSocket:
    """
    WebSocket client for real-time Polymarket data.

    Subscribes to orderbook updates and triggers callbacks
    when prices change - much faster than polling Gamma API.
    """

    CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    RTDS_WS_URL = "wss://ws-live-data.polymarket.com"

    def __init__(
        self,
        on_price_update: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ):
        """
        Args:
            on_price_update: Called with (token_id, best_bid, best_ask) on price changes
            on_trade: Called with (token_id, price, size, side) on trades
            on_error: Called with (error_msg) on connection errors
        """
        if not HAS_WEBSOCKET:
            raise ImportError(
                "websocket-client required. Install: pip install websocket-client"
            )

        self.on_price_update = on_price_update or self._default_price_handler
        self.on_trade = on_trade
        self.on_error = on_error or self._default_error_handler

        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._subscribed_tokens: set[str] = set()

        # Price tracking
        self.latest_prices: dict[str, dict] = {}
        self.last_update_time: dict[str, float] = {}

        # Stats
        self.messages_received = 0
        self.price_updates = 0
        self.connected_since: Optional[datetime] = None

    def _default_price_handler(self, token_id: str, best_bid: float, best_ask: float):
        """Default price update handler (just logs)."""
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        print(f"📊 {token_id[:8]}... bid={best_bid:.4f} ask={best_ask:.4f} mid={mid:.4f}")

    def _default_error_handler(self, error_msg: str):
        """Default error handler."""
        print(f"⚠️ WS Error: {error_msg}")

    def _on_open(self, ws):
        """Called when WebSocket connection is established."""
        self.connected_since = datetime.now()
        print(f"🔌 Polymarket WebSocket connected")

        # Subscribe to all tracked tokens
        for token_id in self._subscribed_tokens:
            self._send_subscribe(token_id)

    def _on_message(self, ws, message):
        """Process incoming WebSocket message."""
        self.messages_received += 1

        try:
            data = json.loads(message)
            msg_type = data.get('type', data.get('event', ''))

            if msg_type in ('book', 'book_update', 'price_change'):
                self._handle_book_update(data)
            elif msg_type in ('trade', 'last_trade_price'):
                self._handle_trade(data)
            elif msg_type == 'subscribed':
                asset_id = data.get('asset_id', 'unknown')
                print(f"  ✅ Subscribed to {asset_id[:12]}...")

        except json.JSONDecodeError:
            pass
        except Exception as e:
            self.on_error(f"Message processing error: {e}")

    def _handle_book_update(self, data: dict):
        """Handle orderbook/price update message."""
        token_id = data.get('asset_id', data.get('token_id', ''))
        if not token_id:
            return

        # Extract best bid/ask
        best_bid = 0
        best_ask = 0

        bids = data.get('bids', [])
        asks = data.get('asks', [])

        if bids:
            best_bid = float(bids[0].get('price', 0)) if isinstance(bids[0], dict) else float(bids[0])
        if asks:
            best_ask = float(asks[0].get('price', 0)) if isinstance(asks[0], dict) else float(asks[0])

        # Also check for direct price fields
        if best_bid == 0:
            best_bid = float(data.get('best_bid', 0) or 0)
        if best_ask == 0:
            best_ask = float(data.get('best_ask', 0) or 0)

        if best_bid > 0 or best_ask > 0:
            self.latest_prices[token_id] = {
                'best_bid': best_bid,
                'best_ask': best_ask,
                'midpoint': (best_bid + best_ask) / 2 if best_bid and best_ask else 0,
                'timestamp': time.time(),
            }
            self.last_update_time[token_id] = time.time()
            self.price_updates += 1

            # Trigger callback
            self.on_price_update(token_id, best_bid, best_ask)

    def _handle_trade(self, data: dict):
        """Handle trade execution message."""
        if self.on_trade:
            token_id = data.get('asset_id', data.get('token_id', ''))
            price = float(data.get('price', 0))
            size = float(data.get('size', data.get('amount', 0)))
            side = data.get('side', 'unknown')
            self.on_trade(token_id, price, size, side)

    def _on_error(self, ws, error):
        """Handle WebSocket error."""
        self.on_error(str(error))

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        print(f"🔌 WebSocket disconnected (code={close_status_code})")
        self.connected_since = None

        # Auto-reconnect if still running
        if self._running:
            print("🔄 Reconnecting in 5s...")
            time.sleep(5)
            self._connect()

    def _send_subscribe(self, token_id: str):
        """Send subscription message for a token."""
        if self._ws:
            msg = json.dumps({
                "type": "subscribe",
                "channel": "market",
                "assets_id": token_id,
            })
            try:
                self._ws.send(msg)
            except Exception as e:
                self.on_error(f"Subscribe failed: {e}")

    def subscribe_market(self, token_id: str):
        """Subscribe to real-time updates for a market token."""
        self._subscribed_tokens.add(token_id)
        if self._ws and self._running:
            self._send_subscribe(token_id)

    def subscribe_markets(self, token_ids: list[str]):
        """Subscribe to multiple market tokens."""
        for token_id in token_ids:
            self.subscribe_market(token_id)

    def unsubscribe_market(self, token_id: str):
        """Unsubscribe from a market token."""
        self._subscribed_tokens.discard(token_id)
        if self._ws and self._running:
            msg = json.dumps({
                "type": "unsubscribe",
                "channel": "market",
                "assets_id": token_id,
            })
            try:
                self._ws.send(msg)
            except Exception:
                pass

    def _connect(self):
        """Create and connect WebSocket."""
        self._ws = websocket.WebSocketApp(
            self.CLOB_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_interval=30, ping_timeout=10)

    def start(self):
        """Start WebSocket connection in background thread."""
        if self._running:
            print("⚠️ WebSocket already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()
        print(f"🚀 Polymarket WebSocket starting (tracking {len(self._subscribed_tokens)} tokens)")

    def stop(self):
        """Stop WebSocket connection."""
        self._running = False
        if self._ws:
            self._ws.close()
        print("⏹️ Polymarket WebSocket stopped")

    def get_price(self, token_id: str) -> Optional[dict]:
        """Get latest cached price for a token."""
        return self.latest_prices.get(token_id)

    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            'connected': self.connected_since is not None,
            'connected_since': self.connected_since.isoformat() if self.connected_since else None,
            'subscribed_tokens': len(self._subscribed_tokens),
            'messages_received': self.messages_received,
            'price_updates': self.price_updates,
            'latest_prices': len(self.latest_prices),
        }

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.connected_since is not None and self._running


# Convenience function
def create_price_monitor(token_ids: list[str], callback: Callable = None) -> PolymarketWebSocket:
    """
    Quick-start a price monitor for given tokens.

    Usage:
        monitor = create_price_monitor(["0xabc...", "0xdef..."])
        monitor.start()
        # ... later ...
        price = monitor.get_price("0xabc...")
    """
    ws = PolymarketWebSocket(on_price_update=callback)
    ws.subscribe_markets(token_ids)
    return ws


if __name__ == "__main__":
    print("=" * 50)
    print("Polymarket WebSocket Test")
    print("=" * 50)

    if not HAS_WEBSOCKET:
        print("❌ websocket-client not installed")
        print("   Install: pip install websocket-client")
    else:
        def on_update(token_id, bid, ask):
            print(f"  💰 {token_id[:12]}... | bid={bid:.4f} | ask={ask:.4f}")

        ws = PolymarketWebSocket(on_price_update=on_update)
        print("✅ WebSocket client ready")
        print("   Call ws.subscribe_market(token_id) then ws.start()")
