# Kalshi Credentials (get from your account)
KALSHI_EMAIL = "your_email@domain.com"
KALSHI_PASSWORD = "your_secure_password"
KALSHI_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"

# Scanning parameters
SCAN_INTERVAL = 60  # seconds
MIN_MARKET_SCORE = 7.5
MIN_EV = 0.015  # 1.5% minimum edge
MIN_PRICE = 0.85  # Only "NO" on high-prob events

# Position sizing
BASE_POSITION_SIZE = 0.02  # 2% of bankroll
MAX_POSITION_SIZE = 0.05   # 5% max

# Risk limits
MAX_CORRELATION = 0.4
MAX_OPEN_POSITIONS = 50
DAILY_LOSS_LIMIT = 0.03  # 3% of bankroll

# Telegram
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"

# Paper trading
INITIAL_BANKROLL = 5000.0  # Simulated starting capital
