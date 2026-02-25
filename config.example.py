# Seer - Prediction Market Scanner
# =================================
# Copy this file to config.py and fill in your credentials
#   cp config.example.py config.py

import os
from pathlib import Path

# Get the directory where config.py lives (project root)
_PROJECT_ROOT = Path(__file__).parent.resolve()

# ==============================================
# KALSHI CREDENTIALS (Required)
# ==============================================
# Get your API key at https://kalshi.com/account/api
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "your_kalshi_api_key_id")
KALSHI_PRIVATE_KEY_PATH = str(_PROJECT_ROOT / "kalshi_private_key.pem")
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# ==============================================
# POLYMARKET SETTINGS
# ==============================================
# Reading market data is FREE and doesn't require API key
# API key is only needed for placing trades
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", None)
POLYMARKET_ENABLED = True
POLYMARKET_TRADING_ENABLED = POLYMARKET_API_KEY is not None
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"

# ==============================================
# SCANNING PARAMETERS
# ==============================================
SCAN_INTERVAL = 60  # seconds between scans
MIN_MARKET_SCORE = 6.0  # Lower for learning (raise to 7.5 for real money)
MIN_EV = 0.008  # 0.8% for learning (raise to 1.5% for real money)
MIN_PRICE = 0.85  # Buy NO when YES > 85%, buy YES when YES < 15%
MAX_DAYS_TO_CLOSE = 30  # Maximum days until market closes

# ==============================================
# ARBITRAGE DETECTION SETTINGS
# ==============================================
# Based on "Unravelling the Probabilistic Forest" (arXiv:2508.03474)

ARB_MIN_PROFIT = 0.02  # 2% minimum profit to flag
ARB_MIN_NET_PROFIT = 0.005  # 0.5% after transaction costs
ARB_SCAN_ENABLED = True

# Types of arbitrage to scan for
ARB_SINGLE_CONDITION = True  # YES + NO != $1.00
ARB_MULTI_OUTCOME = True     # Sum of all YES != $1.00
ARB_CROSS_MARKET = False     # Logically related markets (experimental)

# Multi-outcome settings
ARB_MIN_OUTCOMES = 2         # Minimum outcomes for multi-arb
ARB_IGNORE_BELOW = 0.02      # Ignore outcomes with <2% probability

# ==============================================
# POSITION SIZING
# ==============================================
BASE_POSITION_SIZE = 0.02  # 2% of bankroll base
MAX_POSITION_SIZE = 0.05   # 5% absolute max
MIN_POSITION_SIZE = 0.005  # 0.5% minimum

# Arbitrage-specific sizing (can be more aggressive since risk-free)
ARB_MAX_POSITION_SIZE = 0.20  # 20% max for risk-free arb
ARB_KELLY_FRACTION = 0.5      # 50% Kelly for arb (vs 25% for EV)
ARB_MAX_POSITION_DOLLARS = 500.0  # Absolute dollar cap per arb trade

# ==============================================
# RISK LIMITS - CRITICAL SAFETY CONTROLS
# ==============================================
MAX_CORRELATION = 0.4  # Max correlation between positions
MAX_OPEN_POSITIONS = 50  # Max concurrent trades
DAILY_LOSS_LIMIT = 0.05  # 5% max daily loss (KILL SWITCH)
MAX_POSITION_VALUE = 0.20  # 20% max in single position

# Kill switch state (DO NOT MODIFY - set by system)
KILL_SWITCH_ACTIVE = False
KILL_SWITCH_REASON = None

# ==============================================
# TOKEN MANAGEMENT
# ==============================================
TOKEN_REFRESH_INTERVAL = 3300  # 55 minutes (tokens expire at 60)
TOKEN_MAX_RETRIES = 3

# ==============================================
# TELEGRAM ALERTS (Optional)
# ==============================================
# Create a bot via @BotFather on Telegram, then get your chat ID
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "your_bot_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "your_chat_id")
TELEGRAM_ENABLED = TELEGRAM_BOT_TOKEN != "your_bot_token"

# Alert settings
ALERT_ON_ARB = True         # Alert for arbitrage opportunities
ALERT_ON_EV = True          # Alert for EV opportunities
ALERT_MIN_PROFIT = 0.03     # Minimum profit to trigger alert (3%)

# ==============================================
# TRADING MODE
# ==============================================
INITIAL_BANKROLL = 5000.0  # Reference for sizing calculations
PAPER_TRADING_MODE = True  # Keep True until ready for live
WATCH_MODE = True  # True = alerts only, False = paper trading

# Paper execution - simulates arb trades and tracks P&L
POLYMARKET_PAPER_ARB_EXECUTION = True
KALSHI_MULTI_ARB_ENABLED = True
KALSHI_PAPER_ARB_EXECUTION = True

# ==============================================
# ALERT THRESHOLDS
# ==============================================
ALERT_MIN_EDGE_PCT = 3.0  # Only alert if edge >= 3%
ALERT_COOLDOWN_SECONDS = 900  # 15 min cooldown per opportunity

# ==============================================
# DATABASE
# ==============================================
DB_PATH = str(_PROJECT_ROOT / "seer.db")

# ==============================================
# LOGGING
# ==============================================
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = "seer.log"
CONSOLE_OUTPUT = True

# ==============================================
# PERFORMANCE TRACKING
# ==============================================
TRACK_METRICS = True
METRICS_INTERVAL = 3600  # Log metrics every hour


def validate_config() -> bool:
    """Validate critical configuration settings."""
    errors = []

    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "your_kalshi_api_key_id":
        errors.append("KALSHI_API_KEY_ID is not set")

    key_path = Path(KALSHI_PRIVATE_KEY_PATH)
    if not key_path.exists():
        errors.append(f"Private key not found at: {KALSHI_PRIVATE_KEY_PATH}")

    if DAILY_LOSS_LIMIT <= 0 or DAILY_LOSS_LIMIT > 0.5:
        errors.append(f"DAILY_LOSS_LIMIT should be 0-50%, got {DAILY_LOSS_LIMIT*100}%")

    if MAX_POSITION_SIZE > 0.2:
        errors.append(f"MAX_POSITION_SIZE is dangerously high: {MAX_POSITION_SIZE*100}%")

    if ARB_SCAN_ENABLED:
        if ARB_MIN_PROFIT <= 0:
            errors.append("ARB_MIN_PROFIT must be positive")
        if ARB_MIN_NET_PROFIT >= ARB_MIN_PROFIT:
            errors.append("ARB_MIN_NET_PROFIT should be less than ARB_MIN_PROFIT")

    if errors:
        print("❌ Configuration Errors:")
        for e in errors:
            print(f"   - {e}")
        return False

    return True


def get_config_summary() -> dict:
    """Get a summary of current configuration."""
    return {
        "mode": "watch" if WATCH_MODE else ("paper" if PAPER_TRADING_MODE else "live"),
        "bankroll": INITIAL_BANKROLL,
        "min_ev": f"{MIN_EV*100:.1f}%",
        "min_score": MIN_MARKET_SCORE,
        "arb_enabled": ARB_SCAN_ENABLED,
        "arb_min_profit": f"{ARB_MIN_PROFIT*100:.1f}%",
        "daily_loss_limit": f"{DAILY_LOSS_LIMIT*100:.1f}%",
        "max_position": f"{MAX_POSITION_SIZE*100:.1f}%",
        "platforms": ["kalshi"] + (["polymarket"] if POLYMARKET_ENABLED else []),
    }


if __name__ == "__main__":
    print("Seer Configuration")
    print("=" * 40)

    if validate_config():
        print("✓ Configuration valid")

        summary = get_config_summary()
        for k, v in summary.items():
            print(f"  {k}: {v}")
    else:
        print("✗ Configuration has errors")

# === TIMING FILTER ===
ALERT_MAX_DAYS_TO_RESOLUTION = 30  # Only alert on markets resolving within N days (0 = disabled)

# ==============================================
# PREDICTIT SETTINGS
# ==============================================
PREDICTIT_ENABLED = True  # PredictIt read-only scanning

# ==============================================
# CRYPTO 5-MIN MARKETS (Polymarket)
# ==============================================
CRYPTO_MARKETS_ENABLED = True  # Scan 5-min BTC/ETH/SOL/XRP up/down markets
CRYPTO_MIN_EDGE = 0.015  # 1.5% min edge (tighter spreads, faster resolution)
CRYPTO_ALERT_COOLDOWN = 300  # 5 min cooldown for crypto alerts (faster markets)

# ==============================================
# WEBSOCKET SETTINGS
# ==============================================
WS_ENABLED = False  # Enable WebSocket for real-time updates (requires websocket-client)
WS_AUTO_SUBSCRIBE = True  # Auto-subscribe to markets found during scanning
WS_RECONNECT_DELAY = 5  # Seconds before reconnecting on disconnect

# ==============================================
# POLYMARKET CLOB SETTINGS
# ==============================================
CLOB_BOOK_CACHE_TTL = 5  # Seconds to cache CLOB book data
CLOB_USE_MIDPOINT = True  # Use /midpoint endpoint for faster price checks
CLOB_BATCH_SIZE = 5  # Max orders per batch (Polymarket limit)
