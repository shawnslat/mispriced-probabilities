#!/usr/bin/env python3
"""
Seer - One Command Launcher
Starts scanner + dashboard together

Usage:
    python seer.py          # Start everything
    python seer.py --no-ui  # Scanner only (no dashboard)
    python seer.py --ui     # Dashboard only (no scanner)
"""

import subprocess
import sys
import time
import os
import threading
import argparse
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.resolve()
os.chdir(PROJECT_ROOT)


def stream_scanner_output(process):
    """Stream scanner output to console."""
    try:
        for line in process.stdout:
            print(f"[SCANNER] {line}", end="")
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description="Seer Prediction Market Scanner")
    parser.add_argument("--no-ui", action="store_true", help="Run scanner only (no dashboard)")
    parser.add_argument("--ui", action="store_true", help="Run dashboard only (no scanner)")
    args = parser.parse_args()

    print()
    print("🔮 SEER - Prediction Market Scanner")
    print("=" * 50)

    scanner_process = None

    # 1. Test Telegram connection
    if not args.ui:
        print("📱 Testing Telegram alerts...")
        try:
            from telegram_alerts import send_telegram_message
            if send_telegram_message("🔮 <b>Seer Starting</b>\n\nAlert-Only Mode active. You'll receive pings for opportunities ≥3% edge."):
                print("   ✅ Telegram connected")
            else:
                print("   ⚠️ Telegram failed (continuing anyway)")
        except Exception as e:
            print(f"   ⚠️ Telegram error: {e}")

    # 2. Start scanner
    if not args.ui:
        print("🔍 Starting scanner...")

        if args.no_ui:
            # No dashboard - run scanner in foreground
            print("=" * 50)
            print()
            try:
                subprocess.run([sys.executable, "scanner.py"])
            except KeyboardInterrupt:
                print("\n⏹️ Scanner stopped")
            return
        else:
            # Dashboard mode - run scanner in background with output streaming
            scanner_process = subprocess.Popen(
                [sys.executable, "scanner.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            print(f"   ✅ Scanner running (PID: {scanner_process.pid})")
            print(f"   📝 Logs: seer.log")

            # Stream scanner output in background thread
            output_thread = threading.Thread(
                target=stream_scanner_output,
                args=(scanner_process,),
                daemon=True
            )
            output_thread.start()

        time.sleep(2)

    # 3. Launch dashboard
    print("📊 Launching dashboard...")
    print("=" * 50)
    print()
    print("   🌐 Opening: http://localhost:8501")
    print("   📱 Alerts:  Telegram @seeralerts_bot")
    print()
    print("   Press Ctrl+C to stop")
    print()

    dashboard_path = PROJECT_ROOT / "dashboard" / "app.py"

    try:
        subprocess.run(
            ["streamlit", "run", str(dashboard_path),
             "--server.headless", "false",
             "--browser.gatherUsageStats", "false"],
            cwd=PROJECT_ROOT / "dashboard",
        )
    except KeyboardInterrupt:
        print("\n⏹️ Shutting down...")
    except FileNotFoundError:
        print("❌ Streamlit not found. Install with: pip install streamlit")
    finally:
        if scanner_process:
            print("Stopping scanner...")
            scanner_process.terminate()
            try:
                scanner_process.wait(timeout=5)
            except:
                scanner_process.kill()
        print("✅ Seer stopped")


if __name__ == "__main__":
    main()
