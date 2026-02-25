#!/usr/bin/env python3
"""
Seer Telegram Alerts
Sends notifications when arbitrage opportunities are detected.
"""

import requests
from datetime import datetime
from typing import Optional

# Telegram Bot Configuration
# Set via environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import os
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "your_bot_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "your_chat_id")

# Alert cooldown tracking (prevent spam)
_alert_history: dict[str, float] = {}
COOLDOWN_SECONDS = 900  # 15 minutes


def _get_opportunity_key(opportunity: dict) -> str:
    """Generate unique key for an opportunity."""
    return f"{opportunity.get('platform', '')}:{opportunity.get('title', '')[:30]}"


def _check_cooldown(key: str) -> bool:
    """Check if we should send alert (not in cooldown)."""
    import time
    last_alert = _alert_history.get(key, 0)
    if time.time() - last_alert < COOLDOWN_SECONDS:
        return False  # Still in cooldown
    _alert_history[key] = time.time()
    return True


def send_telegram_message(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram alert failed: {e}")
        return False


def send_arbitrage_alert(opportunity: dict, force: bool = False) -> bool:
    """Send an arbitrage opportunity alert (with cooldown)."""
    from dateutil import parser as date_parser

    # Check cooldown unless forced
    key = _get_opportunity_key(opportunity)
    if not force and not _check_cooldown(key):
        return False  # Skipped due to cooldown

    platform = opportunity.get('platform', 'Unknown').upper()
    title = opportunity.get('title', 'Unknown Market')[:50]
    num_outcomes = opportunity.get('num_outcomes', 0)
    yes_sum = opportunity.get('yes_sum', 0)
    deviation = opportunity.get('deviation', 0)
    strategy = opportunity.get('strategy', 'UNKNOWN')
    profit = opportunity.get('profit_per_100', 0)
    close_time = opportunity.get('close_time', '')

    # Calculate days to resolution
    days_to_resolution = "?"
    if close_time:
        try:
            close_dt = date_parser.parse(close_time)
            if close_dt.tzinfo is None:
                from datetime import timezone
                close_dt = close_dt.replace(tzinfo=timezone.utc)
            days_to_resolution = (close_dt - datetime.now(close_dt.tzinfo)).days
        except:
            pass

    # Emoji based on profit potential
    if profit >= 5:
        emoji = "🔥"
    elif profit >= 3:
        emoji = "🎯"
    else:
        emoji = "📊"

    # Platform links
    platform_links = {
        "KALSHI": "https://kalshi.com/markets",
        "POLYMARKET": "https://polymarket.com",
        "PREDICTIT": "https://www.predictit.org/markets",
    }
    trade_link = platform_links.get(platform, "")

    message = f"""
{emoji} <b>SEER ARBITRAGE ALERT</b>

<b>📍 {title}...</b>
Platform: {platform}
Outcomes: {num_outcomes}
YES Sum: {yes_sum:.1%} ({deviation:+.1%})

<b>💰 Strategy: {strategy}</b>
<b>Edge: ${profit:.2f} per $100</b>
<b>📅 Resolves: {days_to_resolution} days</b>

🔗 <a href="{trade_link}">Trade on {platform}</a>

⏰ {datetime.now().strftime('%H:%M:%S')}
"""

    return send_telegram_message(message.strip())


def send_trade_alert(trade: dict, is_win: bool = True) -> bool:
    """Send a trade execution/resolution alert."""

    title = trade.get('title', 'Unknown')[:40]
    pnl = trade.get('pnl', 0)
    bankroll = trade.get('bankroll', 0)

    emoji = "✅" if is_win else "❌"
    status = "WIN" if is_win else "LOSS"

    message = f"""
{emoji} <b>TRADE {status}</b>

{title}...
P&L: <b>${pnl:+.2f}</b>
Bankroll: ${bankroll:,.2f}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""

    return send_telegram_message(message.strip())


def send_startup_alert() -> bool:
    """Send alert when scanner starts."""
    message = """
🔮 <b>SEER SCANNER STARTED</b>

Monitoring:
• Kalshi (API connected)
• Polymarket (read-only)
• PredictIt (read-only)

Alerts enabled for arbitrage opportunities.

⏰ {time}
""".format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    return send_telegram_message(message.strip())


def send_heartbeat(scan_count: int, opps_found: int) -> bool:
    """Send periodic heartbeat to confirm scanner is running."""
    message = f"""
💓 <b>SEER HEARTBEAT</b>

Scanner active and running
Scans completed: {scan_count}
Opportunities found: {opps_found}

⏰ {datetime.now().strftime('%H:%M:%S')}
"""
    return send_telegram_message(message.strip())


def send_daily_summary(stats: dict) -> bool:
    """Send daily performance summary."""

    trades = stats.get('trades', 0)
    wins = stats.get('wins', 0)
    pnl = stats.get('pnl', 0)
    bankroll = stats.get('bankroll', 0)
    win_rate = (wins / trades * 100) if trades > 0 else 0

    message = f"""
📈 <b>SEER DAILY SUMMARY</b>

Trades: {trades}
Win Rate: {win_rate:.1f}%
Daily P&L: <b>${pnl:+,.2f}</b>
Bankroll: ${bankroll:,.2f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    return send_telegram_message(message.strip())


# Quick test
if __name__ == "__main__":
    print("Testing Telegram alerts...")

    success = send_telegram_message("🔮 <b>Seer Alert Test</b>\n\nIf you see this, alerts are working!")

    if success:
        print("✅ Telegram alert sent successfully!")
    else:
        print("❌ Failed to send Telegram alert")
