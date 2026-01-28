import requests

import config


def send_alert(market, score, ev, true_prob, size_pct):
    """Send formatted alert to Telegram."""
    message = f"""
🚨 **OPPORTUNITY DETECTED**

Market: {market['title']}
Category: {market.get('category', 'unknown')}

📊 **Analysis**
Quality Score: {score}/10
Expected Value: +{ev * 100:.2f}%
Market Price: {market['yes_price'] * 100:.1f}%
True Probability: {true_prob * 100:.1f}%
Edge: {(market['yes_price'] - true_prob) * 100:.1f}%

💰 **Recommendation**
Side: BUY NO
Size: {size_pct:.2f}% of bankroll

⏰ Expires: {market.get('close_time', 'Unknown')}

🔗 [Trade on Kalshi](https://kalshi.com/markets/{market['ticker']})
"""

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as exc:
        print(f"❌ Alert failed: {exc}")


def calculate_position_size(ev, score, corr_penalty):
    """Dynamic sizing based on EV, quality, and correlation."""
    if score >= 9:
        confidence = 1.0
    elif score >= 8:
        confidence = 0.7
    else:
        confidence = 0.5

    corr_mult = max(1 - (corr_penalty / config.MAX_CORRELATION), 0.3)

    size = config.BASE_POSITION_SIZE * confidence * corr_mult
    return min(size, config.MAX_POSITION_SIZE)
