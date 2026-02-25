# Seer - Prediction Market Arbitrage Scanner

**Multi-platform scanner that detects mispriced probabilities across Kalshi, Polymarket, and PredictIt.**

Finds risk-free arbitrage opportunities where prediction market prices don't add up correctly, sends real-time Telegram alerts, and tracks simulated P&L with paper trading.

Based on research from ["Unravelling the Probabilistic Forest" (arXiv:2508.03474)](https://arxiv.org/abs/2508.03474) which documented **$40M+** in arbitrage extracted from Polymarket alone.

---

## How It Works

In prediction markets, the YES prices across all outcomes of an event should sum to exactly 100%. When they don't, there's a guaranteed profit opportunity.

**Example:** If a market asks "Who wins the 2028 election?" with candidates priced at:
- Candidate A: 50¢
- Candidate B: 35¢
- Candidate C: 8¢
- **Total: 93¢** (should be 100¢)

Buy YES on all outcomes for 93¢. One **must** win and pay $1.00. Guaranteed 7¢ profit per dollar.

Seer scans thousands of markets every 60 seconds to find these mispricings.

---

## Features

- **Multi-Platform Scanning** — Kalshi (API), Polymarket (CLOB + Gamma API), PredictIt (read-only)
- **Arbitrage Detection** — Single-condition (YES+NO != $1), multi-outcome bracket, and 5-minute crypto markets
- **Real-Time Alerts** — Telegram notifications with edge size, days to resolution, and direct trade links
- **Paper Trading** — Simulated execution with P&L tracking, win rate, and bankroll management
- **Risk Management** — Kill switch (5% daily loss limit), position sizing, correlation checks, cooldown on re-entry
- **Live Dashboard** — Streamlit UI showing scanner status, portfolio metrics, arbitrage opportunities, and market health
- **WebSocket Support** — Optional real-time Polymarket orderbook updates (experimental)

---

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/shawnslat/mispriced-probabilities.git
cd mispriced-probabilities
pip3 install -r requirements.txt
```

### 2. Configure
```bash
cp config.example.py config.py
cp .env.example .env
```

Edit `config.py` with your Kalshi API key (get one at [kalshi.com/account/api](https://kalshi.com/account/api)) and place your `kalshi_private_key.pem` in the project root.

For Telegram alerts, create a bot via [@BotFather](https://t.me/BotFather) and add your bot token + chat ID.

### 3. Run
```bash
python3 seer.py
```

This starts the scanner, Telegram alerts, and the Streamlit dashboard at [http://localhost:8501](http://localhost:8501).

Or run components individually:
```bash
python3 scanner.py          # Scanner only
cd dashboard && streamlit run app.py  # Dashboard only
```

---

## Architecture

```
seer/
├── seer.py                 # Main launcher (scanner + dashboard)
├── config.example.py       # Configuration template (copy to config.py)
├── scanner.py              # Core scanning loop & paper trading
├── market_adapter.py       # Platform adapters (Kalshi, Polymarket, PredictIt)
├── polymarket_ws.py        # WebSocket client for real-time orderbook
├── arbitrage.py            # Arbitrage detection algorithms
├── portfolio_manager.py    # Kalshi API authentication (RSA signing)
├── risk_manager.py         # Kill switch & position limits
├── ev_calculator.py        # Expected value calculations
├── probability.py          # True probability estimation
├── market_scorer.py        # Market quality scoring (0-10)
├── correlation.py          # Position correlation checks
├── database.py             # SQLite persistence layer
├── alerter.py              # Alert formatting & position sizing
├── telegram_alerts.py      # Telegram bot notifications
├── reset_paper_trades.py   # Utility to reset paper trade data
│
└── dashboard/
    ├── app.py              # Streamlit main UI
    ├── platform_api.py     # Live API integration for dashboard
    ├── db.py               # Read-only database queries
    └── components/
        ├── tables.py       # Data tables & charts
        └── metrics.py      # Portfolio metric displays
```

---

## Configuration

### Operating Modes
| Mode | `WATCH_MODE` | `PAPER_TRADING_MODE` | Behavior |
|------|-------------|---------------------|----------|
| Watch | `True` | `True` | Alerts only, no simulated trades |
| Paper | `False` | `True` | Simulated trades with P&L tracking |
| Live | `False` | `False` | Real trades (not yet implemented) |

### Key Parameters
```python
# Arbitrage thresholds
ARB_MIN_PROFIT = 0.02       # 2% minimum edge to flag
ARB_MIN_NET_PROFIT = 0.005  # 0.5% after spread costs

# Position sizing
BASE_POSITION_SIZE = 0.02   # 2% of bankroll per trade
MAX_POSITION_SIZE = 0.05    # 5% max per trade
ARB_MAX_POSITION_DOLLARS = 500.0  # Hard dollar cap per arb

# Safety
DAILY_LOSS_LIMIT = 0.05     # 5% daily loss triggers kill switch
MAX_OPEN_POSITIONS = 50     # Max concurrent trades
ALERT_MAX_DAYS_TO_RESOLUTION = 30  # Only alert on near-term markets
```

### Telegram Alerts
Set environment variables or edit `config.py`:
```bash
export TELEGRAM_BOT_TOKEN="your_token_from_botfather"
export TELEGRAM_CHAT_ID="your_chat_id"
```

Alerts include: arbitrage opportunities, paper trade executions, trade resolutions (win/loss with P&L), hourly heartbeat, and daily summaries.

---

## Platforms

| Platform | Access | Trading | Notes |
|----------|--------|---------|-------|
| **Kalshi** | API (authenticated) | Paper | RSA-signed requests, full orderbook |
| **Polymarket** | CLOB + Gamma API | Paper | Free read access, CLOB for real-time prices |
| **PredictIt** | Public API | Alert only | 10% profit fee + 5% withdrawal fee makes arb harder |

Polymarket also supports 5-minute crypto prediction markets (BTC/ETH/SOL/XRP up/down) with tighter spreads and faster resolution.

---

## Database

SQLite database (`seer.db`) tracks all activity:

```sql
-- Check win rate
SELECT COUNT(*) as trades,
       SUM(CASE WHEN win=1 THEN 1 ELSE 0 END) as wins,
       ROUND(AVG(CASE WHEN win=1 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate
FROM paper_trades WHERE status='closed';

-- P&L by category
SELECT category, COUNT(*) as trades, ROUND(SUM(pnl), 2) as total_pnl
FROM paper_trades WHERE status='closed'
GROUP BY category ORDER BY total_pnl DESC;
```

---

## Roadmap

- [x] Kalshi API integration with RSA authentication
- [x] Multi-outcome bracket arbitrage detection
- [x] Polymarket integration (Gamma + CLOB API)
- [x] PredictIt integration
- [x] 5-minute crypto market scanning
- [x] Paper trading with P&L tracking
- [x] Telegram alerts with trade links
- [x] Streamlit dashboard
- [x] WebSocket real-time orderbook (experimental)
- [ ] Cross-market arbitrage (logical dependencies between markets)
- [ ] Backtesting module
- [ ] Live trading execution

---

## Disclaimers

- **Educational purposes only** — this is a research project
- **Not financial advice** — prediction markets carry real risk
- **Start with paper trading** — validate the strategy before risking capital
- **No guarantees** — arbitrage edges can close before execution

---

Good luck! 🔮
