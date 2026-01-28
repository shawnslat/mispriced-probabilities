import requests

import config


def get_token():
    """Login and get access token."""
    url = f"{config.KALSHI_BASE_URL}/login"
    payload = {
        "email": config.KALSHI_EMAIL,
        "password": config.KALSHI_PASSWORD,
    }

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise ValueError("Login failed: missing token in response")
    return token


def get_open_positions(token):
    """Fetch current open positions from portfolio."""
    url = f"{config.KALSHI_BASE_URL}/portfolio/positions"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    positions = response.json().get("positions", [])

    return positions
