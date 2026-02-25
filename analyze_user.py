#!/usr/bin/env python3
"""
One-command tool: Fetch trades and analyze them automatically.
Usage: python3 analyze_user.py "<market_query>" <user_address> [output_file]
"""

import sys
import subprocess
import os
from pathlib import Path


def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import requests
    except ImportError:
        print("=" * 80)
        print("ERROR: Missing required dependency")
        print("=" * 80)
        print("\nPlease install dependencies first:")
        print("  pip3 install -r requirements.txt")
        print("\nOr:")
        print("  pip3 install requests")
        print()
        sys.exit(1)


def main():
    """Main function - fetch trades and analyze them."""

    # Check dependencies first
    check_dependencies()

    if len(sys.argv) < 3:
        print("Usage: python3 analyze_user.py \"<market_query>\" <user_address> [output_file]")
        print("\nExample:")
        print('  python3 analyze_user.py "Solana Up or Down on February 5?" 0x4ee29e4e7d4c380babeae5e22e5c02400c2246e1')
        print("\nNote: Make sure to install dependencies first:")
        print("  pip3 install -r requirements.txt")
        sys.exit(1)

    market_query = sys.argv[1]
    user_address = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else "trades.json"

    # Ensure output directory exists
    output_path = Path(output_file)
    if output_path.parent != Path('.'):
        output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("POLYMARKET TRADE ANALYSIS")
    print("=" * 80)
    print()
    print(f"Market:     {market_query}")
    print(f"User:       {user_address}")
    print(f"Output:     {output_file}")
    print()
    print("-" * 80)
    print("STEP 1: Fetching trades...")
    print("-" * 80)

    # Step 1: Fetch trades
    fetch_cmd = [
        sys.executable,
        "fetch_trades.py",
        market_query,
        user_address,
        output_file
    ]

    try:
        result = subprocess.run(fetch_cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching trades: {e}", file=sys.stderr)
        print(e.stdout)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)

    print()
    print("-" * 80)
    print("STEP 2: Analyzing trades...")
    print("-" * 80)
    print()

    # Step 2: Analyze trades
    analyze_cmd = [
        sys.executable,
        "analyze_trades.py",
        output_file
    ]

    try:
        result = subprocess.run(analyze_cmd, check=True)
        # Output is already printed by analyze_trades.py
    except subprocess.CalledProcessError as e:
        print(f"Error analyzing trades: {e}", file=sys.stderr)
        sys.exit(1)

    print()
    print("-" * 80)
    print("ANALYSIS COMPLETE")
    print("-" * 80)
    print(f"\nTrade data saved to: {output_file}")


if __name__ == "__main__":
    main()
