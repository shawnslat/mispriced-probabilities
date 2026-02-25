"""UI helpers for metrics blocks."""

# READ-ONLY DASHBOARD
# LIVE TRADING DISABLED

from __future__ import annotations

import streamlit as st
from platform_api import get_live_balance, is_api_available


def render_status_metrics(status: dict) -> None:
    cols = st.columns(3)
    
    # Scanner status
    scanner_status = status.get("status", "Unknown")
    status_icon = "✅" if scanner_status == "Running" else "⚠️"
    cols[0].metric("Scanner Status", f"{status_icon} {scanner_status}")
    
    # Last scan time
    last_scan = status.get("last_scan_time") or "N/A"
    if last_scan != "N/A":
        # Show just time if it's today
        try:
            from datetime import datetime
            scan_time = datetime.fromisoformat(last_scan.replace('Z', '+00:00'))
            last_scan = scan_time.strftime("%H:%M:%S")
        except:
            pass
    cols[1].metric("Last Scan", last_scan)
    
    # Kalshi API status
    api_status = "✅ Connected" if is_api_available() else "❌ Offline"
    cols[2].metric("Kalshi API", api_status)


def render_portfolio_metrics(summary: dict) -> None:
    cols = st.columns(4)
    
    # Paper trading metrics
    bankroll = summary.get("paper_bankroll")
    pnl = summary.get("total_pnl")
    trades = summary.get("total_trades")
    
    cols[0].metric("📝 Paper Bankroll", _format_currency(bankroll))
    cols[1].metric("📈 Paper P&L", _format_currency(pnl), delta=_format_pnl_delta(pnl))
    cols[2].metric("🎯 Paper Trades", trades if trades is not None else 0)
    
    # Live Kalshi balance
    live_balance = get_live_balance()
    if live_balance is not None:
        cols[3].metric("💰 Kalshi Balance", f"${live_balance:,.2f}")
    else:
        cols[3].metric("💰 Kalshi Balance", "N/A")


def _format_currency(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_pnl_delta(pnl) -> str:
    """Format P&L delta for metric display."""
    if pnl is None or pnl == 0:
        return None
    try:
        pnl_val = float(pnl)
        if pnl_val > 0:
            return f"+${pnl_val:,.2f}"
        else:
            return f"${pnl_val:,.2f}"
    except (TypeError, ValueError):
        return None
