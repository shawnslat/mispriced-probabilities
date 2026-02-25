"""
Analyze Kalshi Markets - See what's actually available
"""
from portfolio_manager import signed_request
from datetime import datetime

print("Fetching markets...\n")

response = signed_request(
    'GET',
    '/trade-api/v2/markets',
    params={"status": "open", "limit": 100}
)

markets = response.json().get('markets', [])

print(f"Found {len(markets)} markets (first 100)\n")
print("=" * 80)

# Analyze price distribution
price_ranges = {
    "0-50%": 0,
    "50-70%": 0,
    "70-85%": 0,
    "85-95%": 0,
    "95-100%": 0
}

time_ranges = {
    "< 1 day": 0,
    "1-7 days": 0,
    "7-30 days": 0,
    "> 30 days": 0,
}

for market in markets:
    # Check price
    yes_price = market.get('yes_price', 0)
    if yes_price > 1:
        yes_price = yes_price / 100
    
    if yes_price < 0.5:
        price_ranges["0-50%"] += 1
    elif yes_price < 0.7:
        price_ranges["50-70%"] += 1
    elif yes_price < 0.85:
        price_ranges["70-85%"] += 1
    elif yes_price < 0.95:
        price_ranges["85-95%"] += 1
    else:
        price_ranges["95-100%"] += 1
    
    # Check time
    close_time = market.get('close_time')
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            days = (close_dt - datetime.now()).days
            
            if days < 1:
                time_ranges["< 1 day"] += 1
            elif days <= 7:
                time_ranges["1-7 days"] += 1
            elif days <= 30:
                time_ranges["7-30 days"] += 1
            else:
                time_ranges["> 30 days"] += 1
        except:
            pass

print("PRICE DISTRIBUTION:")
for range_name, count in price_ranges.items():
    pct = (count / len(markets)) * 100
    bar = "█" * int(pct / 2)
    print(f"  {range_name:12} {count:3d} ({pct:5.1f}%) {bar}")

print("\nTIME TO CLOSE:")
for range_name, count in time_ranges.items():
    pct = (count / len(markets)) * 100
    bar = "█" * int(pct / 2)
    print(f"  {range_name:12} {count:3d} ({pct:5.1f}%) {bar}")

print("\n" + "=" * 80)
print("MARKETS THAT MEET CURRENT CRITERIA (>85%, closes in 7 days):")
print("=" * 80)

matching = 0
for market in markets:
    yes_price = market.get('yes_price', 0)
    if yes_price > 1:
        yes_price = yes_price / 100
    
    close_time = market.get('close_time')
    if close_time:
        try:
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            days = (close_dt - datetime.now()).days
            
            if yes_price >= 0.85 and 0 <= days <= 7:
                matching += 1
                print(f"\n{matching}. {market.get('title', 'Unknown')[:70]}")
                print(f"   YES: {yes_price*100:.1f}% | Closes in {days} days")
                print(f"   Ticker: {market.get('ticker')}")
        except:
            pass

if matching == 0:
    print("\n❌ NO MARKETS match criteria (>85% YES, closes in 0-7 days)")
    print("\n💡 RECOMMENDATIONS:")
    print("   1. Lower MIN_PRICE to 0.75 (75%) to find more opportunities")
    print("   2. Extend time window to 14 or 30 days")
    print("   3. Or both")
else:
    print(f"\n✅ Found {matching} markets that match criteria")
