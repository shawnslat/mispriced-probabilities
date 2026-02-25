"""
Detailed Market Analysis - See actual market data
"""
from portfolio_manager import signed_request
from datetime import datetime
import json

print("Fetching first 20 markets...\n")

response = signed_request(
    'GET',
    '/trade-api/v2/markets',
    params={"status": "open", "limit": 20}
)

markets = response.json().get('markets', [])

print(f"Found {len(markets)} markets\n")
print("=" * 100)

for i, market in enumerate(markets[:10], 1):
    print(f"\n{i}. {market.get('title', 'Unknown')[:80]}")
    print(f"   Ticker: {market.get('ticker')}")
    
    # Show all price-related fields
    yes_price = market.get('yes_price')
    no_price = market.get('no_price')
    yes_bid = market.get('yes_bid')
    yes_ask = market.get('yes_ask')
    no_bid = market.get('no_bid')
    no_ask = market.get('no_ask')
    
    print(f"   YES Price: {yes_price} | NO Price: {no_price}")
    print(f"   YES Bid/Ask: {yes_bid}/{yes_ask} | NO Bid/Ask: {no_bid}/{no_ask}")
    
    # Show close time
    close_time = market.get('close_time')
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            days = (close_dt - datetime.now()).days
            print(f"   Closes in: {days} days ({close_time[:10]})")
        except:
            print(f"   Close time: {close_time}")
    
    # Show volume/liquidity
    volume = market.get('volume', 0)
    open_interest = market.get('open_interest', 0)
    print(f"   Volume: {volume:,} | Open Interest: {open_interest:,}")
    
    # Show status and type
    status = market.get('status')
    result_type = market.get('result_type')
    print(f"   Status: {status} | Type: {result_type}")

print("\n" + "=" * 100)
print("\n🔍 CHECKING IF HIGH-PROBABILITY MARKETS EXIST...")
print("=" * 100)

# Fetch more markets to find high-probability ones
response = signed_request(
    'GET',
    '/trade-api/v2/markets',
    params={"status": "open", "limit": 1000}
)

all_markets = response.json().get('markets', [])
print(f"\nAnalyzing {len(all_markets)} markets...")

high_prob_count = 0
for market in all_markets:
    yes_price = market.get('yes_price', 0)
    
    # Normalize to 0-1
    if yes_price > 1:
        yes_price = yes_price / 100
    
    if yes_price >= 0.70:
        high_prob_count += 1
        if high_prob_count <= 5:  # Show first 5
            print(f"\n{high_prob_count}. {market.get('title', 'Unknown')[:70]}")
            print(f"   YES: {yes_price*100:.1f}% | Ticker: {market.get('ticker')}")
            
            close_time = market.get('close_time')
            if close_time:
                try:
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    days = (close_dt - datetime.now()).days
                    print(f"   Closes in: {days} days")
                except:
                    pass

if high_prob_count == 0:
    print("\n❌ NO MARKETS found with YES > 70%")
    print("\n📊 This suggests Kalshi currently has mostly:")
    print("   • Competitive/uncertain events (close to 50/50)")
    print("   • Early-stage events (not yet resolved)")
    print("   • Markets without clear favorites")
    print("\n💡 The arbitrage strategy works best when:")
    print("   • Major events are near resolution (high certainty)")
    print("   • Clear favorites exist but are slightly overpriced")
    print("   • Market has high liquidity")
else:
    print(f"\n✅ Found {high_prob_count} markets with YES >= 70%")
    print(f"   ({(high_prob_count/len(all_markets))*100:.1f}% of all markets)")
