"""UI helpers for tables and data display."""

# READ-ONLY DASHBOARD
# LIVE TRADING DISABLED

from __future__ import annotations

import pandas as pd
import streamlit as st
from platform_api import (
    get_live_market_price,
    get_trending_markets,
    scan_arbitrage_opportunities,
    get_market_efficiency_metrics,
    get_arb_summary,
)


def render_table(title: str, dataframe, height: int | None = None) -> None:
    """Render a generic dataframe table."""
    st.subheader(title)
    if dataframe is None or dataframe.empty:
        st.info("No data available.")
        return
    st.dataframe(dataframe, width="stretch", height=height, hide_index=True)


def render_recent_scans(dataframe) -> None:
    """Render recent scanner activity."""
    st.subheader("📡 Recent Scans")
    if dataframe is None or dataframe.empty:
        st.info("No scan data available.")
        return
    
    display_df = dataframe.copy()
    
    # Simplify timestamp
    if 'timestamp' in display_df.columns:
        try:
            display_df['timestamp'] = pd.to_datetime(display_df['timestamp']).dt.strftime('%H:%M:%S')
        except:
            pass
    
    # Rename columns
    column_renames = {
        'timestamp': 'Time',
        'bankroll': 'Bankroll',
        'total_pnl': 'Total P&L',
        'open_positions': 'Open Pos',
        'win_rate': 'Win Rate',
        'avg_ev': 'Avg EV',
        'total_trades': 'Trades'
    }
    display_df = display_df.rename(columns={k: v for k, v in column_renames.items() if k in display_df.columns})
    
    # Format numeric columns
    if 'Bankroll' in display_df.columns:
        display_df['Bankroll'] = display_df['Bankroll'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A")
    if 'Total P&L' in display_df.columns:
        display_df['Total P&L'] = display_df['Total P&L'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
    if 'Win Rate' in display_df.columns:
        display_df['Win Rate'] = display_df['Win Rate'].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) and x > 0 else "N/A")
    if 'Avg EV' in display_df.columns:
        display_df['Avg EV'] = display_df['Avg EV'].apply(lambda x: f"{x*100:.2f}%" if pd.notna(x) and x > 0 else "N/A")
    
    st.dataframe(display_df, width="stretch", height=280, hide_index=True)


def render_opportunities(dataframe) -> None:
    """Render EV-based opportunities."""
    st.subheader("📊 EV Opportunities Found")
    
    if dataframe is None or dataframe.empty:
        st.info("No EV opportunities detected yet. Scanner is looking for mispriced markets...")
        return
    
    display_df = dataframe.copy()
    
    # Format percentages
    if 'ev' in display_df.columns:
        display_df['EV'] = (display_df['ev'] * 100).round(2).astype(str) + '%'
    
    if 'quality_score' in display_df.columns:
        display_df['Score'] = display_df['quality_score'].round(1)
    elif 'score' in display_df.columns:
        display_df['Score'] = display_df['score'].round(1)
    
    if 'timestamp' in display_df.columns:
        try:
            display_df['Time'] = pd.to_datetime(display_df['timestamp']).dt.strftime('%m/%d %H:%M')
        except:
            display_df['Time'] = display_df['timestamp']
    
    # Select columns for display
    col_mapping = {
        'Time': 'Time',
        'market_title': 'Market',
        'title': 'Market',
        'outcome': 'Side',
        'side': 'Side',
        'EV': 'EV',
        'Score': 'Score',
        'executed': 'Executed'
    }
    
    display_cols = []
    for orig_col, display_name in col_mapping.items():
        if orig_col in display_df.columns and display_name not in display_cols:
            display_df = display_df.rename(columns={orig_col: display_name})
            display_cols.append(display_name)
    
    if display_cols:
        available_cols = [c for c in display_cols if c in display_df.columns]
        display_df = display_df[available_cols]
    
    st.dataframe(display_df, width="stretch", height=360, hide_index=True)


def render_arbitrage_opportunities() -> None:
    """Render arbitrage opportunities detected from platform APIs."""
    st.subheader("🔒 Arbitrage Opportunities")
    
    # Get opportunities
    opportunities = scan_arbitrage_opportunities(limit=20)
    
    if not opportunities:
        st.info("No arbitrage opportunities detected. Markets are efficiently priced.")
        
        # Show efficiency metrics
        metrics = get_market_efficiency_metrics()
        if metrics:
            col1, col2, col3 = st.columns(3)
            col1.metric("Efficiency Score", f"{metrics.get('efficiency_score', 0):.0f}%")
            col2.metric("Avg YES+NO", f"{metrics.get('avg_price_sum', 1)*100:.1f}¢")
            col3.metric("Markets Checked", metrics.get('markets_analyzed', 0))
        
        with st.expander("ℹ️ What is Arbitrage?"):
            st.markdown("""
            **Arbitrage** = guaranteed profit when market prices don't add up correctly.
            
            - **Single Condition**: YES + NO should = $1.00
              - If YES=45¢ + NO=48¢ = 93¢ → Buy both, profit 7¢ guaranteed
            
            - **Multi-Outcome**: All YES prices should sum to $1.00
              - If Trump=50¢ + Harris=42¢ + Other=3¢ = 95¢ → Buy all, profit 5¢
            
            Based on research showing **$40M** in arbitrage was extracted from Polymarket in one year.
            """)
        return
    
    # Convert to display format
    rows = []
    for opp in opportunities:
        details = opp.details
        
        # Format based on type
        if opp.arb_type.value.startswith("single"):
            yes_price = details.get('yes_ask', details.get('yes_bid', 0))
            no_price = details.get('no_ask', details.get('no_bid', 0))
            buy_cost = details.get('buy_cost', yes_price + no_price)
            price_info = f"YES:{yes_price*100:.0f}¢ + NO:{no_price*100:.0f}¢ = {buy_cost*100:.0f}¢"
        else:
            yes_sum = details.get('yes_ask_sum', details.get('yes_bid_sum', 0))
            num_outcomes = details.get('num_outcomes', 0)
            price_info = f"Sum: {yes_sum*100:.0f}¢ ({num_outcomes} outcomes)"
        
        # Type indicator
        if 'long' in opp.arb_type.value:
            type_label = '🟢 BUY BOTH'
        else:
            type_label = '🔴 SELL BOTH'
        
        rows.append({
            'Type': type_label,
            'Market': opp.market_title[:40] + ('...' if len(opp.market_title) > 40 else ''),
            'Prices': price_info,
            'Gross': f"{opp.profit_percent:.1f}%",
            'Net': f"{opp.net_profit_percent:.1f}%",
            'Max $': f"${opp.max_profit:,.0f}" if opp.max_profit > 0 else "—",
        })
    
    df = pd.DataFrame(rows)
    
    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🎯 Opportunities", len(opportunities))
    col2.metric("🔒 Risk-Free", sum(1 for o in opportunities if o.is_risk_free))
    col3.metric("📈 Avg Profit", f"{sum(o.profit_percent for o in opportunities) / len(opportunities):.1f}%")
    col4.metric("💰 Total Potential", f"${sum(o.max_profit for o in opportunities):,.0f}")
    
    st.dataframe(df, width="stretch", height=320, hide_index=True)
    
    # Detailed view expander
    with st.expander("📋 View Details"):
        for i, opp in enumerate(opportunities[:5]):
            st.markdown(f"**{i+1}. {opp.market_title[:60]}**")
            st.markdown(f"- Action: `{opp.details.get('action', 'N/A')}`")
            st.markdown(f"- Gross Profit: {opp.profit_percent:.2f}% | Net: {opp.net_profit_percent:.2f}%")
            st.markdown(f"- Liquidity: ${opp.details.get('liquidity', 0):,.0f}")
            st.divider()


def render_arb_summary() -> None:
    """Render a compact arbitrage summary widget."""
    summary = get_arb_summary()
    
    if summary.get('total_count', 0) == 0:
        st.metric("🔒 Arbitrage", "None found", delta="Markets efficient")
        return
    
    st.metric(
        "🔒 Arbitrage",
        f"{summary['total_count']} found",
        delta=f"${summary['total_potential_profit']:,.0f} potential"
    )


def render_watchlist(dataframe) -> None:
    """Render markets in the watch list."""
    st.subheader("👁️ Watch List")
    
    if dataframe is None or dataframe.empty:
        st.info("No markets in watch list.")
        return
    
    display_df = dataframe.copy()
    
    # Add live prices if tickers available
    if 'ticker' in display_df.columns or 'market_ticker' in display_df.columns:
        ticker_col = 'ticker' if 'ticker' in display_df.columns else 'market_ticker'
        
        live_prices = []
        for ticker in display_df[ticker_col]:
            price_data = get_live_market_price(ticker)
            if price_data:
                live_prices.append(f"{price_data['yes_price']:.1%}")
            else:
                live_prices.append("N/A")
        
        display_df['Live Price'] = live_prices
    
    st.dataframe(display_df, width="stretch", height=320, hide_index=True)


def render_trending_markets() -> None:
    """Render trending markets from platform APIs."""
    st.subheader("🔥 Trending Markets")
    
    trending = get_trending_markets(limit=10)
    
    if not trending:
        st.info("No active markets found.")
        return
    
    df = pd.DataFrame(trending)
    
    if not df.empty:
        # Build display columns
        display_data = {
            'Market': df['title'].str[:40],
            'YES': df['yes_price'].apply(lambda x: f"{x*100:.0f}¢" if x > 0 else "—"),
            'NO': df['no_price'].apply(lambda x: f"{x*100:.0f}¢" if x > 0 else "—"),
            'Sum': df['price_sum'].apply(lambda x: f"{x*100:.0f}¢"),
            'Volume': df['volume'].apply(lambda x: f"${x:,.0f}" if x > 0 else "—"),
        }

        # Add platform column if available
        if 'platform' in df.columns:
            display_data['Platform'] = df['platform'].str.title()

        display_df = pd.DataFrame(display_data)
        
        # Highlight markets where sum deviates from $1.00
        st.dataframe(display_df, width="stretch", height=320, hide_index=True)
        
        # Quick arb check
        potential_arbs = [t for t in trending if abs(1.0 - t['price_sum']) > 0.02]
        if potential_arbs:
            st.warning(f"⚠️ {len(potential_arbs)} market(s) have YES+NO deviation > 2%")


def render_market_health() -> None:
    """Render overall market efficiency metrics."""
    st.subheader("📈 Market Efficiency")
    
    metrics = get_market_efficiency_metrics()
    
    if not metrics:
        st.info("Unable to calculate market health.")
        return
    
    col1, col2, col3, col4 = st.columns(4)
    
    efficiency = metrics.get('efficiency_score', 0)
    col1.metric(
        "Efficiency Score",
        f"{efficiency:.0f}%",
        delta="Good" if efficiency > 95 else "Opportunities exist"
    )
    
    avg_sum = metrics.get('avg_price_sum', 1)
    col2.metric(
        "Avg YES+NO",
        f"{avg_sum*100:.1f}¢",
        delta=f"{(avg_sum-1)*100:+.1f}¢" if avg_sum != 1 else None
    )
    
    col3.metric("Avg Spread", f"{metrics.get('avg_spread', 0)*100:.1f}¢")
    col4.metric("Deviation >2%", metrics.get('markets_with_deviation', 0))


def render_analytics_charts(opportunity_df: pd.DataFrame) -> None:
    """Render analytics charts for opportunities."""
    if opportunity_df is None or opportunity_df.empty:
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 EV Distribution")
        
        if 'ev' in opportunity_df.columns:
            ev_values = opportunity_df['ev'] * 100
            
            bins = [0, 1.0, 1.5, 2.0, 100]
            labels = ['0.5-1.0%', '1.0-1.5%', '1.5-2.0%', '2.0%+']
            
            try:
                ev_dist = pd.cut(ev_values, bins=bins, labels=labels, include_lowest=True).value_counts()
                st.bar_chart(ev_dist)
            except:
                st.info("Not enough data for EV distribution")
        else:
            st.info("No EV data available")
    
    with col2:
        st.subheader("📊 By Category")
        
        if 'category' in opportunity_df.columns:
            category_counts = opportunity_df['category'].value_counts().head(5)
            st.bar_chart(category_counts)
        elif 'market_title' in opportunity_df.columns or 'title' in opportunity_df.columns:
            title_col = 'market_title' if 'market_title' in opportunity_df.columns else 'title'
            
            def infer_category(title):
                title_lower = str(title).lower()
                if any(word in title_lower for word in ['fed', 'cpi', 'rate', 'inflation', 'gdp']):
                    return 'Economics'
                elif any(word in title_lower for word in ['trump', 'president', 'election', 'congress']):
                    return 'Politics'
                elif any(word in title_lower for word in ['bitcoin', 'crypto', 'eth']):
                    return 'Crypto'
                else:
                    return 'Other'
            
            opportunity_df['inferred_category'] = opportunity_df[title_col].apply(infer_category)
            category_counts = opportunity_df['inferred_category'].value_counts()
            st.bar_chart(category_counts)
        else:
            st.info("No category data available")
