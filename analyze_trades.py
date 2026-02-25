#!/usr/bin/env python3
"""
Comprehensive trade analysis script.
Calculates profitability, PnL, position tracking, and trading behavior insights.
"""

import json
import sys
from datetime import datetime
from collections import defaultdict


def load_trades(filename="trades.json"):
    """Load trades from JSON file."""
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File {filename} not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {filename}: {e}", file=sys.stderr)
        sys.exit(1)


def analyze_trades(trades):
    """Perform comprehensive trade analysis."""

    # Sort by timestamp
    trades.sort(key=lambda x: x["timestamp"])

    # Initialize tracking variables
    up_buys = []
    up_sells = []
    down_buys = []
    down_sells = []

    up_shares_bought = 0
    up_shares_sold = 0
    up_cost_basis = 0
    up_proceeds = 0

    down_shares_bought = 0
    down_shares_sold = 0
    down_cost_basis = 0
    down_proceeds = 0

    # Track positions over time
    up_position = 0
    down_position = 0
    up_avg_price = 0
    down_avg_price = 0
    up_total_cost = 0
    down_total_cost = 0

    profitability_timeline = []

    # Process each trade
    for trade in trades:
        timestamp = trade["timestamp"]
        dt = datetime.fromtimestamp(timestamp)
        side = trade["side"]
        outcome = trade["outcome"]
        size = trade["size"]
        price = trade["price"]
        value = size * price

        if outcome == "Up":
            if side == "BUY":
                up_buys.append(trade)
                up_shares_bought += size
                up_cost_basis += value
                up_total_cost += value
                up_position += size
                # Update average price (weighted average)
                if up_position > 0:
                    up_avg_price = up_total_cost / up_position
            else:  # SELL
                up_sells.append(trade)
                up_shares_sold += size
                up_proceeds += value
                up_position -= size
                # Update average price if position remains
                if up_position > 0:
                    up_total_cost -= (size * up_avg_price)
                    up_avg_price = up_total_cost / up_position if up_position > 0 else 0
                else:
                    up_total_cost = 0
                    up_avg_price = 0
        else:  # Down
            if side == "BUY":
                down_buys.append(trade)
                down_shares_bought += size
                down_cost_basis += value
                down_total_cost += value
                down_position += size
                # Update average price (weighted average)
                if down_position > 0:
                    down_avg_price = down_total_cost / down_position
            else:  # SELL
                down_sells.append(trade)
                down_shares_sold += size
                down_proceeds += value
                down_position -= size
                # Update average price if position remains
                if down_position > 0:
                    down_total_cost -= (size * down_avg_price)
                    down_avg_price = down_total_cost / down_position if down_position > 0 else 0
                else:
                    down_total_cost = 0
                    down_avg_price = 0

        # Calculate profitability: avg(YES) + avg(NO) < $1 means profitable
        # Only calculate if trader has positions in BOTH sides (hedging strategy)
        if up_position > 0 and down_position > 0:
            total_avg_price = up_avg_price + down_avg_price
            is_profitable = total_avg_price < 1.0
        elif up_position > 0 or down_position > 0:
            # Only one side - can't determine profitability using this metric
            total_avg_price = (up_avg_price if up_position > 0 else 0) + (down_avg_price if down_position > 0 else 0)
            is_profitable = None  # Not applicable for single-sided positions
        else:
            total_avg_price = 0
            is_profitable = None

        profitability_timeline.append({
            "timestamp": timestamp,
            "datetime": dt,
            "up_avg_price": up_avg_price,
            "down_avg_price": down_avg_price,
            "total_avg_price": total_avg_price,
            "is_profitable": is_profitable,
            "up_position": up_position,
            "down_position": down_position
        })

    # Calculate final positions
    up_final_position = up_shares_bought - up_shares_sold
    down_final_position = down_shares_bought - down_shares_sold

    # Calculate PnL
    # Realized PnL from sells
    up_realized_pnl = up_proceeds - (up_shares_sold * (up_cost_basis / up_shares_bought if up_shares_bought > 0 else 0))
    down_realized_pnl = down_proceeds - (down_shares_sold * (down_cost_basis / down_shares_bought if down_shares_bought > 0 else 0))

    # Unrealized PnL (if we assume final positions are worth $1 each if profitable)
    # This is simplified - in reality, you'd need current market prices
    up_unrealized_pnl = 0  # Would need current market price
    down_unrealized_pnl = 0  # Would need current market price

    total_realized_pnl = up_realized_pnl + down_realized_pnl

    # Analyze profitability intervals
    profitable_intervals = []
    unprofitable_intervals = []
    current_state = None
    interval_start = None

    for entry in profitability_timeline:
        if entry["is_profitable"] is None:
            continue

        if current_state != entry["is_profitable"]:
            if current_state is not None and interval_start is not None:
                # Close previous interval
                if current_state:
                    profitable_intervals.append({
                        "start": interval_start,
                        "end": profitability_timeline[profitability_timeline.index(entry) - 1]["datetime"]
                    })
                else:
                    unprofitable_intervals.append({
                        "start": interval_start,
                        "end": profitability_timeline[profitability_timeline.index(entry) - 1]["datetime"]
                    })

            current_state = entry["is_profitable"]
            interval_start = entry["datetime"]

    # Close final interval
    if current_state is not None and interval_start is not None:
        if current_state:
            profitable_intervals.append({
                "start": interval_start,
                "end": profitability_timeline[-1]["datetime"]
            })
        else:
            unprofitable_intervals.append({
                "start": interval_start,
                "end": profitability_timeline[-1]["datetime"]
            })

    # Find first profitable and first unprofitable moments
    first_profitable = None
    first_unprofitable = None

    for entry in profitability_timeline:
        if entry["is_profitable"] is True and first_profitable is None:
            first_profitable = entry["datetime"]
        if entry["is_profitable"] is False and first_unprofitable is None:
            first_unprofitable = entry["datetime"]

    # Additional behavioral insights
    # Trade frequency analysis
    trade_times = [datetime.fromtimestamp(t["timestamp"]) for t in trades]
    time_diffs = [(trade_times[i+1] - trade_times[i]).total_seconds() / 60 for i in range(len(trade_times)-1)]
    avg_time_between_trades = sum(time_diffs) / len(time_diffs) if time_diffs else 0

    # Price analysis
    up_buy_prices = [t["price"] for t in up_buys]
    up_sell_prices = [t["price"] for t in up_sells]
    down_buy_prices = [t["price"] for t in down_buys]
    down_sell_prices = [t["price"] for t in down_sells]

    # Size analysis
    up_buy_sizes = [t["size"] for t in up_buys]
    down_buy_sizes = [t["size"] for t in down_buys]

    return {
        "up_buys": up_buys,
        "up_sells": up_sells,
        "down_buys": down_buys,
        "down_sells": down_sells,
        "up_shares_bought": up_shares_bought,
        "up_shares_sold": up_shares_sold,
        "down_shares_bought": down_shares_bought,
        "down_shares_sold": down_shares_sold,
        "up_cost_basis": up_cost_basis,
        "up_proceeds": up_proceeds,
        "down_cost_basis": down_cost_basis,
        "down_proceeds": down_proceeds,
        "up_final_position": up_final_position,
        "down_final_position": down_final_position,
        "up_avg_price": up_avg_price if up_final_position > 0 else 0,
        "down_avg_price": down_avg_price if down_final_position > 0 else 0,
        "profitability_timeline": profitability_timeline,
        "profitable_intervals": profitable_intervals,
        "unprofitable_intervals": unprofitable_intervals,
        "first_profitable": first_profitable,
        "first_unprofitable": first_unprofitable,
        "up_realized_pnl": up_realized_pnl,
        "down_realized_pnl": down_realized_pnl,
        "total_realized_pnl": total_realized_pnl,
        "avg_time_between_trades": avg_time_between_trades,
        "up_buy_prices": up_buy_prices,
        "up_sell_prices": up_sell_prices,
        "down_buy_prices": down_buy_prices,
        "down_sell_prices": down_sell_prices,
        "up_buy_sizes": up_buy_sizes,
        "down_buy_sizes": down_buy_sizes
    }


def print_analysis(results):
    """Print comprehensive analysis results."""

    print("=" * 80)
    print("COMPREHENSIVE TRADE ANALYSIS")
    print("=" * 80)
    print()

    # Basic Statistics
    print("📊 BASIC STATISTICS")
    print("-" * 80)
    print(f"Total YES (Up) Buys:     {len(results['up_buys'])}")
    print(f"Total YES (Up) Sells:    {len(results['up_sells'])}")
    print(f"Total NO (Down) Buys:    {len(results['down_buys'])}")
    print(f"Total NO (Down) Sells:   {len(results['down_sells'])}")
    print()

    # Shares Analysis
    print("📈 SHARES ANALYSIS")
    print("-" * 80)
    print(f"YES Shares Bought:       {results['up_shares_bought']:.2f}")
    print(f"YES Shares Sold:         {results['up_shares_sold']:.2f}")
    print(f"YES Final Position:      {results['up_final_position']:.2f}")
    print()
    print(f"NO Shares Bought:        {results['down_shares_bought']:.2f}")
    print(f"NO Shares Sold:          {results['down_shares_sold']:.2f}")
    print(f"NO Final Position:       {results['down_final_position']:.2f}")
    print()

    # Dollar Analysis
    print("💰 DOLLAR ANALYSIS")
    print("-" * 80)
    print(f"YES Total Cost:          ${results['up_cost_basis']:.2f}")
    print(f"YES Total Proceeds:      ${results['up_proceeds']:.2f}")
    print(f"YES Net Investment:      ${results['up_cost_basis'] - results['up_proceeds']:.2f}")
    print()
    print(f"NO Total Cost:           ${results['down_cost_basis']:.2f}")
    print(f"NO Total Proceeds:       ${results['down_proceeds']:.2f}")
    print(f"NO Net Investment:       ${results['down_cost_basis'] - results['down_proceeds']:.2f}")
    print()
    print(f"Total Cost (YES + NO):   ${results['up_cost_basis'] + results['down_cost_basis']:.2f}")
    print(f"Total Proceeds:          ${results['up_proceeds'] + results['down_proceeds']:.2f}")
    print()

    # Average Prices
    print("💵 AVERAGE PRICES")
    print("-" * 80)
    if results['up_final_position'] > 0:
        print(f"YES Average Price:       ${results['up_avg_price']:.4f}")
    else:
        print(f"YES Average Price:       N/A (no position)")

    if results['down_final_position'] > 0:
        print(f"NO Average Price:        ${results['down_avg_price']:.4f}")
    else:
        print(f"NO Average Price:        N/A (no position)")

    if results['up_final_position'] > 0 or results['down_final_position'] > 0:
        total_avg = results['up_avg_price'] + results['down_avg_price']
        print(f"Combined Avg (YES+NO):   ${total_avg:.4f}")
        print(f"Profitability Status:     {'✅ PROFITABLE' if total_avg < 1.0 else '❌ NOT PROFITABLE'} (avg < $1.00)")
    print()

    # Profitability Timeline
    print("📅 PROFITABILITY TIMELINE")
    print("-" * 80)
    if results['first_profitable']:
        print(f"First Became Profitable: {results['first_profitable'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("First Became Profitable: Never")

    if results['first_unprofitable']:
        print(f"First Became Unprofitable: {results['first_unprofitable'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("First Became Unprofitable: Never")
    print()

    print(f"Profitable Intervals:    {len(results['profitable_intervals'])}")
    for i, interval in enumerate(results['profitable_intervals'], 1):
        duration = interval['end'] - interval['start']
        print(f"  {i}. {interval['start'].strftime('%Y-%m-%d %H:%M')} to {interval['end'].strftime('%Y-%m-%d %H:%M')} ({duration})")
    print()

    print(f"Unprofitable Intervals:  {len(results['unprofitable_intervals'])}")
    for i, interval in enumerate(results['unprofitable_intervals'], 1):
        duration = interval['end'] - interval['start']
        print(f"  {i}. {interval['start'].strftime('%Y-%m-%d %H:%M')} to {interval['end'].strftime('%Y-%m-%d %H:%M')} ({duration})")
    print()

    # PnL Analysis
    print("💹 PROFIT & LOSS (PnL)")
    print("-" * 80)
    print(f"YES Realized PnL:        ${results['up_realized_pnl']:.2f}")
    print(f"NO Realized PnL:         ${results['down_realized_pnl']:.2f}")
    print(f"Total Realized PnL:      ${results['total_realized_pnl']:.2f}")
    print()

    # Behavioral Insights
    print("🧠 TRADING BEHAVIOR INSIGHTS")
    print("-" * 80)
    print(f"Average Time Between Trades: {results['avg_time_between_trades']:.1f} minutes")
    print()

    if results['up_buy_prices']:
        print(f"YES Buy Prices:")
        print(f"  Average: ${sum(results['up_buy_prices'])/len(results['up_buy_prices']):.4f}")
        print(f"  Min:     ${min(results['up_buy_prices']):.4f}")
        print(f"  Max:     ${max(results['up_buy_prices']):.4f}")

    if results['up_sell_prices']:
        print(f"YES Sell Prices:")
        print(f"  Average: ${sum(results['up_sell_prices'])/len(results['up_sell_prices']):.4f}")
        print(f"  Min:     ${min(results['up_sell_prices']):.4f}")
        print(f"  Max:     ${max(results['up_sell_prices']):.4f}")

    if results['down_buy_prices']:
        print(f"NO Buy Prices:")
        print(f"  Average: ${sum(results['down_buy_prices'])/len(results['down_buy_prices']):.4f}")
        print(f"  Min:     ${min(results['down_buy_prices']):.4f}")
        print(f"  Max:     ${max(results['down_buy_prices']):.4f}")

    if results['down_sell_prices']:
        print(f"NO Sell Prices:")
        print(f"  Average: ${sum(results['down_sell_prices'])/len(results['down_sell_prices']):.4f}")
        print(f"  Min:     ${min(results['down_sell_prices']):.4f}")
        print(f"  Max:     ${max(results['down_sell_prices']):.4f}")
    print()

    if results['up_buy_sizes']:
        print(f"YES Buy Sizes:")
        print(f"  Average: {sum(results['up_buy_sizes'])/len(results['up_buy_sizes']):.2f}")
        print(f"  Min:     {min(results['up_buy_sizes']):.2f}")
        print(f"  Max:     {max(results['up_buy_sizes']):.2f}")

    if results['down_buy_sizes']:
        print(f"NO Buy Sizes:")
        print(f"  Average: {sum(results['down_buy_sizes'])/len(results['down_buy_sizes']):.2f}")
        print(f"  Min:     {min(results['down_buy_sizes']):.2f}")
        print(f"  Max:     {max(results['down_buy_sizes']):.2f}")
    print()

    # Trading Pattern Analysis
    print("📊 TRADING PATTERNS")
    print("-" * 80)
    total_trades = len(results['up_buys']) + len(results['up_sells']) + len(results['down_buys']) + len(results['down_sells'])
    buy_ratio = (len(results['up_buys']) + len(results['down_buys'])) / total_trades * 100 if total_trades > 0 else 0
    sell_ratio = (len(results['up_sells']) + len(results['down_sells'])) / total_trades * 100 if total_trades > 0 else 0

    print(f"Buy/Sell Ratio:          {buy_ratio:.1f}% buys / {sell_ratio:.1f}% sells")
    print(f"YES/NO Ratio:            {len(results['up_buys']) + len(results['up_sells'])} YES / {len(results['down_buys']) + len(results['down_sells'])} NO")
    print()

    # Additional insights - Enhanced detailed analysis
    print("💡 KEY INSIGHTS & BEHAVIORAL ANALYSIS")
    print("-" * 80)

    # Current Status
    current_up_avg = results['up_avg_price'] if results['up_final_position'] > 0 else 0
    current_down_avg = results['down_avg_price'] if results['down_final_position'] > 0 else 0
    current_total_avg = current_up_avg + current_down_avg
    is_currently_profitable = current_total_avg < 1.0 if (results['up_final_position'] > 0 and results['down_final_position'] > 0) else None

    print("📊 CURRENT STATUS")
    print(f"Current YES Avg Price:    ${current_up_avg:.4f}" if current_up_avg > 0 else "Current YES Avg Price:    N/A (no position)")
    print(f"Current NO Avg Price:     ${current_down_avg:.4f}" if current_down_avg > 0 else "Current NO Avg Price:     N/A (no position)")
    if is_currently_profitable is not None:
        print(f"Combined Avg (YES+NO):    ${current_total_avg:.4f}")
        print(f"Current Profitability:    {'✅ PROFITABLE' if is_currently_profitable else '❌ NOT PROFITABLE'} (avg {'<' if is_currently_profitable else '>='} $1.00)")
    else:
        print(f"Combined Avg (YES+NO):    ${current_total_avg:.4f} (incomplete hedge)")
    print()

    # Combined Position Analysis
    print("📈 COMBINED POSITION ANALYSIS")
    total_shares = results['up_final_position'] + results['down_final_position']
    total_cost = results['up_cost_basis'] + results['down_cost_basis']
    total_proceeds = results['up_proceeds'] + results['down_proceeds']
    net_investment = total_cost - total_proceeds

    if total_shares > 0:
        print(f"Total Shares (YES+NO):    {total_shares:.2f}")
        print(f"  - YES Shares:          {results['up_final_position']:.2f} ({results['up_final_position']/total_shares*100:.1f}%)")
        print(f"  - NO Shares:            {results['down_final_position']:.2f} ({results['down_final_position']/total_shares*100:.1f}%)")
    print()
    if total_cost > 0:
        print(f"Total Cost (YES+NO):      ${total_cost:.2f}")
        print(f"  - YES Cost:             ${results['up_cost_basis']:.2f} ({results['up_cost_basis']/total_cost*100:.1f}% of total)")
        print(f"  - NO Cost:              ${results['down_cost_basis']:.2f} ({results['down_cost_basis']/total_cost*100:.1f}% of total)")
    print()
    print(f"Net Investment:           ${net_investment:.2f}")
    print()

    # Strategy assessment
    print("🧠 STRATEGY ANALYSIS")
    total_buys = len(results['up_buys']) + len(results['down_buys'])
    yes_buy_pct = (len(results['up_buys']) / total_buys * 100) if total_buys > 0 else 0
    no_buy_pct = (len(results['down_buys']) / total_buys * 100) if total_buys > 0 else 0

    if len(results['up_buys']) > len(results['down_buys']) * 2:
        strategy = "YES-FOCUSED"
        strategy_desc = f"Trader prefers YES side ({yes_buy_pct:.1f}% YES trades vs {no_buy_pct:.1f}% NO trades)"
    elif len(results['down_buys']) > len(results['up_buys']) * 2:
        strategy = "NO-FOCUSED"
        strategy_desc = f"Trader prefers NO side ({no_buy_pct:.1f}% NO trades vs {yes_buy_pct:.1f}% YES trades)"
    else:
        strategy = "BALANCED HEDGING"
        strategy_desc = f"Trader balances both sides ({yes_buy_pct:.1f}% YES, {no_buy_pct:.1f}% NO)"

    print(f"Primary Strategy:         {strategy}")
    print(f"  - Interpretation:       {strategy_desc}")
    print()

    print("=" * 80)


def main():
    """Main function."""
    input_file = sys.argv[1] if len(sys.argv) > 1 else "trades.json"

    print(f"Loading trades from {input_file}...")
    trades = load_trades(input_file)
    print(f"Loaded {len(trades)} trades")
    print()

    print("Analyzing trades...")
    results = analyze_trades(trades)

    print_analysis(results)


if __name__ == "__main__":
    main()
