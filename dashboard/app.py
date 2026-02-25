"""
Seer Dashboard - Prediction Market Scanner
==========================================

Real-time prediction market monitoring with:
- EV-based opportunity detection
- Risk-free arbitrage scanning (YES+NO rebalancing)
- Multi-outcome market arbitrage
- Market efficiency metrics
- Paper trading simulation

Supports Kalshi, Polymarket, and other prediction markets.

Based on research from "Unravelling the Probabilistic Forest" (arXiv:2508.03474)
which documented $40M in arbitrage profit extracted from Polymarket.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from components.metrics import render_portfolio_metrics, render_status_metrics
from components.tables import (
    render_analytics_charts,
    render_arbitrage_opportunities,
    render_arb_summary,
    render_market_health,
    render_opportunities,
    render_recent_scans,
    render_trending_markets,
    render_watchlist,
)
from db import (
    get_connection,
    get_opportunities,
    get_opportunity_timeseries,
    get_portfolio_summary,
    get_recent_scans,
    get_scanner_status,
    get_trade_pnl_timeseries,
    get_watchlist,
)


# Page config
st.set_page_config(
    page_title="Seer",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: bold;
        margin-bottom: 0.3rem;
        color: #1f77b4;
    }
    .sub-header {
        color: #666;
        font-size: 0.9rem;
        margin-bottom: 1.5rem;
    }
    div[data-testid="metric-container"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        padding: 12px;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="main-header">🔮 Seer</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Multi-platform arbitrage scanner • Kalshi • Polymarket • PredictIt</div>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    
    refresh_seconds = st.slider(
        "Auto-refresh (sec)",
        min_value=10,
        max_value=120,
        value=30,
        step=10,
    )
    
    st.divider()
    
    st.header("📊 Display")
    show_arb = st.checkbox("Arbitrage Scanner", value=True)
    show_trending = st.checkbox("Trending Markets", value=True)
    show_analytics = st.checkbox("Analytics Charts", value=False)
    show_health = st.checkbox("Market Health", value=False)
    
    st.divider()
    
    st.header("🎯 Mode")
    st.info("📝 Paper Trading")
    st.caption("Simulated trades • Tracking P&L")

    st.divider()

    st.header("📡 Platforms")
    st.markdown("✅ [Kalshi](https://kalshi.com/markets) (API)")
    st.markdown("✅ [Polymarket](https://polymarket.com) (read-only)")
    st.markdown("✅ [PredictIt](https://www.predictit.org/markets) (read-only)")
    st.markdown("⚡ [Poly Crypto](https://polymarket.com/crypto) (5-min)")

    st.divider()

    st.header("⚡ Alert Settings")
    st.caption("Min edge: 3% (events) / 1.5% (crypto)")
    st.caption("Max days: 30")
    st.caption("Cooldown: 15 min / 5 min (crypto)")

    st.divider()

    st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
    
    # Info expander
    with st.expander("📖 Quick Guide"):
        st.markdown("""
        **EV (Expected Value)**
        - Estimated edge vs market price
        - Positive = potential profit
        
        **Arbitrage** (Risk-Free)
        - YES + NO should = $1.00
        - Profit when they don't
        
        **Market Score**
        - Quality rating 0-10
        - Liquidity + clarity
        """)

# Auto-refresh
if "_last_refresh" not in st.session_state:
    st.session_state["_last_refresh"] = time.time()

if time.time() - st.session_state["_last_refresh"] >= refresh_seconds:
    st.session_state["_last_refresh"] = time.time()
    st.rerun()

# Fetch data
with get_connection() as conn:
    status = get_scanner_status(conn)
    summary = get_portfolio_summary(conn)
    recent_scans = get_recent_scans(conn)
    opportunities = get_opportunities(conn)
    watchlist = get_watchlist(conn)
    opportunity_ts = get_opportunity_timeseries(conn)
    pnl_ts = get_trade_pnl_timeseries(conn)

# Top metrics row
render_status_metrics(status)
st.divider()
render_portfolio_metrics(summary)
st.divider()

# Main content with tabs
tab1, tab2, tab3 = st.tabs(["🔒 Arbitrage", "📊 EV Scanner", "📈 Analytics"])

with tab1:
    if show_arb:
        render_arbitrage_opportunities()
    else:
        st.info("Enable 'Arbitrage Scanner' in sidebar to see opportunities")
    
    st.divider()
    
    if show_trending:
        render_trending_markets()

with tab2:
    col1, col2 = st.columns([2, 1])
    
    with col1:
        render_opportunities(opportunities)
    
    with col2:
        render_watchlist(watchlist)
    
    st.divider()
    
    # Recent scans
    render_recent_scans(recent_scans)
    
    # Opportunity pulse chart
    if not opportunity_ts.empty:
        st.subheader("📈 Opportunity Pulse")
        chart_data = opportunity_ts.rename(columns={"metric": "Signal"}).set_index("timestamp")
        st.line_chart(chart_data, height=250)

with tab3:
    if show_health:
        render_market_health()
        st.divider()
    
    if show_analytics and opportunities is not None and not opportunities.empty:
        render_analytics_charts(opportunities)
        st.divider()
    
    # P&L chart
    if not pnl_ts.empty:
        st.subheader("💰 Paper Trading P&L")
        pnl_chart = pnl_ts.set_index("timestamp")
        st.area_chart(pnl_chart, height=300)
    else:
        st.subheader("💰 Paper Trading P&L")
        st.info("No paper trade data yet. P&L will appear here when trades resolve.")

# Strategy info at bottom
with st.expander("📋 Detection Strategy"):
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        ### Detection Methods
        
        | Type | Description | Risk |
        |------|-------------|------|
        | **Single Rebalancing** | YES + NO ≠ $1.00 | Risk-Free ✅ |
        | **Multi Rebalancing** | Sum of YES ≠ $1.00 | Risk-Free ✅ |
        | **EV Edge** | True prob vs market | Speculative ⚠️ |
        | **Cross-Market** | Related market arb | Lower Risk 🟡 |
        """)
    
    with col2:
        st.markdown("""
        ### Current Thresholds
        
        - **Min EV Edge**: 0.8%
        - **Min Arb Profit**: 2.0%
        - **Min Net Profit**: 0.5% (after spread)
        - **Min Market Score**: 6.0
        
        ### Research Basis
        
        Based on arXiv:2508.03474 which found **$40M** in arbitrage profit on Polymarket over 1 year.
        """)

# Footer
st.divider()
cols = st.columns(4)
cols[0].caption("🔮 Seer")
cols[1].caption("📊 Kalshi • Polymarket • PredictIt")
cols[2].caption("📝 Paper Trading Mode")
cols[3].caption(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Prevent page from sleeping
time.sleep(0.5)
