"""
Portfolio Manager V2 - Kalshi Request Signing (No Token)
"""
import time
import base64
import requests
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import config


class KalshiAuth:
    """Handles Kalshi API request signing."""
    
    def __init__(self):
        self.private_key = self._load_private_key()
        self.key_id = config.KALSHI_API_KEY_ID
        
    def _load_private_key(self):
        """Load RSA private key from file."""
        try:
            with open(config.KALSHI_PRIVATE_KEY_PATH, 'rb') as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            print("✓ Private key loaded successfully")
            return private_key
        except FileNotFoundError:
            raise ValueError(f"Private key file not found: {config.KALSHI_PRIVATE_KEY_PATH}")
        except Exception as e:
            raise ValueError(f"Error loading private key: {e}")
    
    def sign_request(self, method, path):
        """
        Create signed headers for a Kalshi API request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path WITHOUT query parameters (e.g., '/trade-api/v2/markets')
        
        Returns:
            dict: Headers with signature
        """
        # Get current timestamp in milliseconds
        timestamp = str(int(time.time() * 1000))
        
        # Strip query parameters from path
        path_without_query = path.split('?')[0]
        
        # Create message: timestamp + method + path
        message = f"{timestamp}{method}{path_without_query}"
        
        # Sign with PSS padding
        signature = self.private_key.sign(
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Encode to base64
        sig_b64 = base64.b64encode(signature).decode('utf-8')
        
        # Return headers
        return {
            'KALSHI-ACCESS-KEY': self.key_id,
            'KALSHI-ACCESS-SIGNATURE': sig_b64,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }


# Global auth instance
_kalshi_auth = KalshiAuth()


def signed_request(method, path, **kwargs):
    """
    Make a signed request to Kalshi API.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API path (e.g., '/trade-api/v2/markets')
        **kwargs: Additional arguments for requests (params, json, etc.)
    
    Returns:
        requests.Response
    """
    # Generate signed headers
    headers = _kalshi_auth.sign_request(method, path)
    
    # Merge with any additional headers
    if 'headers' in kwargs:
        headers.update(kwargs['headers'])
        del kwargs['headers']
    
    # Build full URL
    url = config.KALSHI_BASE_URL + path.replace('/trade-api/v2', '')
    
    # Make request
    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=kwargs.pop('timeout', 10),
        **kwargs
    )
    
    return response


def get_open_positions():
    """
    Fetch current open positions from portfolio.
    
    Returns:
        list: Current positions
    """
    try:
        response = signed_request('GET', '/trade-api/v2/portfolio/positions')
        response.raise_for_status()
        
        data = response.json()
        positions = data.get('positions', [])
        
        return positions
        
    except requests.HTTPError as e:
        print(f"❌ Error fetching positions: {e}")
        print(f"   Status: {e.response.status_code}")
        print(f"   Response: {e.response.text[:200]}")
        return []
    
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return []


def get_market_result(market_id):
    """
    Get the result of a closed market.
    
    Args:
        market_id: Market ticker/ID
        
    Returns:
        dict: Market result data or None if not resolved
    """
    try:
        response = signed_request('GET', f'/trade-api/v2/markets/{market_id}')
        response.raise_for_status()
        
        data = response.json()
        market = data.get('market', {})
        
        # Check if market is resolved
        status = market.get('status')
        result = market.get('result')
        
        if status == 'closed' and result:
            return {
                "market_id": market_id,
                "result": result,  # "yes" or "no"
                "close_time": market.get('close_time'),
            }
        
        return None
        
    except Exception as e:
        print(f"⚠️ Error fetching market result for {market_id}: {e}")
        return None


def get_account_balance():
    """
    Get current account balance.
    
    Returns:
        float: Account balance in dollars
    """
    try:
        response = signed_request('GET', '/trade-api/v2/portfolio/balance')
        response.raise_for_status()
        
        data = response.json()
        balance = data.get('balance', 0)
        
        # Kalshi returns balance in cents
        return balance / 100.0
        
    except Exception as e:
        print(f"⚠️ Error fetching balance: {e}")
        return None


def fetch_markets(params=None):
    """
    Fetch markets from Kalshi.
    
    Args:
        params: Optional query parameters dict
        
    Returns:
        list: Markets data
    """
    try:
        response = signed_request(
            'GET',
            '/trade-api/v2/markets',
            params=params or {}
        )
        response.raise_for_status()
        
        data = response.json()
        return data.get('markets', [])
        
    except Exception as e:
        print(f"❌ Error fetching markets: {e}")
        import traceback
        traceback.print_exc()
        return []
