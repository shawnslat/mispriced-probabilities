"""
Arbitrage Detection Module for Prediction Markets
Based on research from "Unravelling the Probabilistic Forest" (arXiv:2508.03474)

Supports:
- Single condition rebalancing (YES + NO should = $1.00)
- Multi-outcome market rebalancing (all YES prices should sum to $1.00)
- Spread-adjusted profitability analysis
- Cross-market dependency detection (future: LLM-based)

Platform-agnostic: Works with Kalshi, Polymarket, or any prediction market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ArbitrageType(Enum):
    """Types of arbitrage opportunities."""
    SINGLE_CONDITION_LONG = "single_long"      # YES + NO < 1.00, buy both
    SINGLE_CONDITION_SHORT = "single_short"    # YES + NO > 1.00, sell both
    MULTI_OUTCOME_LONG = "multi_long"          # Sum of YES < 1.00, buy all YES
    MULTI_OUTCOME_SHORT = "multi_short"        # Sum of YES > 1.00, sell YES / buy NO
    CROSS_MARKET = "cross_market"              # Dependency between related markets
    EV_EDGE = "ev_edge"                        # Traditional EV-based opportunity


class RiskLevel(Enum):
    """Risk classification for opportunities."""
    RISK_FREE = "risk_free"          # Guaranteed profit (rebalancing)
    LOW_RISK = "low_risk"            # High confidence edge
    MEDIUM_RISK = "medium_risk"      # Standard EV opportunity
    HIGH_RISK = "high_risk"          # Speculative


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage or EV opportunity."""
    arb_type: ArbitrageType
    market_id: str
    market_title: str
    profit_per_dollar: float          # Expected profit per $1 invested
    max_profit: float                 # Max profit given available liquidity
    confidence: float                 # 0-1, how confident we are
    risk_level: RiskLevel
    details: dict                     # Platform-specific details
    timestamp: datetime = field(default_factory=datetime.now)
    platform: str = "kalshi"
    spread_cost: float = 0.0          # Transaction cost from bid-ask spread
    net_profit: float = 0.0           # Profit after spread
    
    def __post_init__(self):
        """Calculate net profit after spread costs."""
        self.net_profit = max(0, self.profit_per_dollar - self.spread_cost)
    
    @property
    def profit_percent(self) -> float:
        """Profit as a percentage."""
        return self.profit_per_dollar * 100
    
    @property
    def net_profit_percent(self) -> float:
        """Net profit after spreads as percentage."""
        return self.net_profit * 100
    
    @property
    def is_risk_free(self) -> bool:
        """True if this is a guaranteed profit (rebalancing arb)."""
        return self.risk_level == RiskLevel.RISK_FREE
    
    @property
    def is_profitable_after_spread(self) -> bool:
        """True if still profitable after accounting for bid-ask spread."""
        return self.net_profit > 0.005  # > 0.5% after costs
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage/display."""
        return {
            "arb_type": self.arb_type.value,
            "market_id": self.market_id,
            "market_title": self.market_title,
            "profit_percent": self.profit_percent,
            "net_profit_percent": self.net_profit_percent,
            "max_profit": self.max_profit,
            "confidence": self.confidence,
            "risk_level": self.risk_level.value,
            "is_risk_free": self.is_risk_free,
            "platform": self.platform,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }
    
    def __str__(self) -> str:
        risk_emoji = {
            RiskLevel.RISK_FREE: "🔒",
            RiskLevel.LOW_RISK: "🟢",
            RiskLevel.MEDIUM_RISK: "🟡",
            RiskLevel.HIGH_RISK: "🔴",
        }
        emoji = risk_emoji.get(self.risk_level, "⚪")
        
        return (
            f"{emoji} {self.arb_type.value.upper()} | {self.risk_level.value}\n"
            f"  Market: {self.market_title[:50]}\n"
            f"  Gross Profit: {self.profit_percent:.2f}%\n"
            f"  Net Profit: {self.net_profit_percent:.2f}% (after spread)\n"
            f"  Max Profit: ${self.max_profit:.2f}\n"
            f"  Platform: {self.platform}"
        )


class ArbitrageDetector:
    """
    Detects arbitrage opportunities in prediction markets.
    
    Usage:
        detector = ArbitrageDetector(min_profit_threshold=0.02)
        
        # Single condition check
        opp = detector.check_single_condition(
            market_id="MARKET-123",
            market_title="Will it rain tomorrow?",
            yes_bid=0.45, yes_ask=0.47,
            no_bid=0.50, no_ask=0.52,
            liquidity=10000
        )
        
        # Multi-outcome check
        opp = detector.check_multi_outcome(
            market_id="MARKET-456",
            market_title="Who will win the election?",
            outcomes=[
                {"name": "Candidate A", "yes_bid": 0.45, "yes_ask": 0.47, "liquidity": 5000},
                {"name": "Candidate B", "yes_bid": 0.48, "yes_ask": 0.50, "liquidity": 5000},
                {"name": "Other", "yes_bid": 0.03, "yes_ask": 0.05, "liquidity": 1000},
            ]
        )
    """
    
    def __init__(
        self,
        min_profit_threshold: float = 0.02,  # 2% minimum profit
        min_net_profit: float = 0.005,       # 0.5% minimum after spread
        platform: str = "kalshi"
    ):
        self.min_profit_threshold = min_profit_threshold
        self.min_net_profit = min_net_profit
        self.platform = platform
    
    def _calculate_spread_cost(
        self,
        yes_bid: float, yes_ask: float,
        no_bid: float, no_ask: float
    ) -> float:
        """
        Calculate the effective cost of entering and exiting due to bid-ask spread.
        
        For rebalancing arb, we need to buy both YES and NO, so we pay the ask prices.
        The spread cost is the difference between what we pay (asks) and fair value.
        """
        yes_spread = yes_ask - yes_bid
        no_spread = no_ask - no_bid
        
        # When buying both, we pay ask prices
        # Spread cost = (yes_ask - yes_mid) + (no_ask - no_mid)
        # Simplified: half of total spread
        return (yes_spread + no_spread) / 2
    
    def check_single_condition(
        self,
        market_id: str,
        market_title: str,
        yes_bid: float,
        no_bid: float,
        yes_ask: Optional[float] = None,
        no_ask: Optional[float] = None,
        liquidity: float = 0,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for arbitrage in a single YES/NO condition.
        
        In an efficient market: YES + NO = 1.00
        - If sum < 1.00: Buy both positions, guaranteed profit when market resolves
        - If sum > 1.00: Sell both positions (or split and sell)
        
        Uses ASK prices for buying (what you actually pay).
        
        Args:
            market_id: Unique market identifier
            market_title: Human-readable market name
            yes_bid: Current YES bid price (0-1)
            no_bid: Current NO bid price (0-1)
            yes_ask: YES ask price (for spread analysis)
            no_ask: NO ask price (for spread analysis)
            liquidity: Available liquidity in dollars
        
        Returns:
            ArbitrageOpportunity if found, None otherwise
        """
        # Default ask prices if not provided
        yes_ask = yes_ask if yes_ask is not None else yes_bid
        no_ask = no_ask if no_ask is not None else no_bid
        
        # For BUYING, use ASK prices (what we pay)
        buy_cost = yes_ask + no_ask
        
        # For SELLING, use BID prices (what we receive)
        sell_value = yes_bid + no_bid
        
        # Calculate spread cost
        spread_cost = self._calculate_spread_cost(yes_bid, yes_ask, no_bid, no_ask)
        
        # Check for LONG arbitrage (buy both)
        # We pay ask prices, receive $1 at resolution
        if buy_cost < (1.0 - self.min_profit_threshold):
            gross_profit = 1.0 - buy_cost
            net_profit = gross_profit  # Already using ask prices
            
            # Skip if not profitable after minimum threshold
            if net_profit < self.min_net_profit:
                return None
            
            max_profit = net_profit * liquidity if liquidity > 0 else net_profit * 100
            
            return ArbitrageOpportunity(
                arb_type=ArbitrageType.SINGLE_CONDITION_LONG,
                market_id=market_id,
                market_title=market_title,
                profit_per_dollar=gross_profit,
                max_profit=max_profit,
                confidence=min(1.0, gross_profit / 0.10),
                risk_level=RiskLevel.RISK_FREE,
                spread_cost=spread_cost,
                details={
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "buy_cost": buy_cost,
                    "action": "BUY YES @ ask + BUY NO @ ask",
                    "liquidity": liquidity,
                },
                platform=self.platform,
            )
        
        # Check for SHORT arbitrage (sell both / split and sell)
        # We receive bid prices, owe $1 at resolution
        if sell_value > (1.0 + self.min_profit_threshold):
            gross_profit = sell_value - 1.0
            net_profit = gross_profit  # Already using bid prices
            
            if net_profit < self.min_net_profit:
                return None
            
            max_profit = net_profit * liquidity if liquidity > 0 else net_profit * 100
            
            return ArbitrageOpportunity(
                arb_type=ArbitrageType.SINGLE_CONDITION_SHORT,
                market_id=market_id,
                market_title=market_title,
                profit_per_dollar=gross_profit,
                max_profit=max_profit,
                confidence=min(1.0, gross_profit / 0.10),
                risk_level=RiskLevel.RISK_FREE,
                spread_cost=spread_cost,
                details={
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "sell_value": sell_value,
                    "action": "SELL YES @ bid + SELL NO @ bid",
                    "liquidity": liquidity,
                },
                platform=self.platform,
            )
        
        return None
    
    def check_multi_outcome(
        self,
        market_id: str,
        market_title: str,
        outcomes: list[dict],
        min_probability_threshold: float = 0.02,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Check for arbitrage in a multi-outcome market.
        
        In an efficient market: Sum of all YES prices = 1.00
        - If sum < 1.00: Buy YES on all outcomes
        - If sum > 1.00: Sell YES / Buy NO on all outcomes
        
        Args:
            market_id: Unique market identifier
            market_title: Human-readable market name
            outcomes: List of dicts with keys: name, yes_bid, yes_ask (optional), liquidity (optional)
            min_probability_threshold: Ignore outcomes below this probability
        
        Returns:
            ArbitrageOpportunity if found, None otherwise
        """
        if len(outcomes) < 2:
            return None
        
        # Filter to relevant outcomes
        relevant_outcomes = [
            o for o in outcomes 
            if o.get("yes_bid", 0) >= min_probability_threshold
        ]
        
        if len(relevant_outcomes) < 2:
            return None
        
        # Calculate sums using ask prices for buying
        yes_ask_sum = sum(
            o.get("yes_ask", o.get("yes_bid", 0)) 
            for o in relevant_outcomes
        )
        yes_bid_sum = sum(o.get("yes_bid", 0) for o in relevant_outcomes)
        
        # Calculate minimum liquidity across outcomes
        min_liquidity = min(
            (o.get("liquidity", 0) for o in relevant_outcomes),
            default=0
        )
        
        # Estimate spread cost
        spread_cost = (yes_ask_sum - yes_bid_sum) / 2
        
        # Check for LONG arbitrage (buy all YES at ask)
        if yes_ask_sum < (1.0 - self.min_profit_threshold):
            gross_profit = 1.0 - yes_ask_sum
            
            if gross_profit < self.min_net_profit:
                return None
            
            max_profit = gross_profit * min_liquidity if min_liquidity > 0 else gross_profit * 100
            
            return ArbitrageOpportunity(
                arb_type=ArbitrageType.MULTI_OUTCOME_LONG,
                market_id=market_id,
                market_title=market_title,
                profit_per_dollar=gross_profit,
                max_profit=max_profit,
                confidence=min(1.0, gross_profit / 0.10),
                risk_level=RiskLevel.RISK_FREE,
                spread_cost=spread_cost,
                details={
                    "outcomes": relevant_outcomes,
                    "yes_ask_sum": yes_ask_sum,
                    "yes_bid_sum": yes_bid_sum,
                    "num_outcomes": len(relevant_outcomes),
                    "action": "BUY YES on ALL outcomes @ ask",
                    "min_liquidity": min_liquidity,
                },
                platform=self.platform,
            )
        
        # Check for SHORT arbitrage (sell all YES at bid)
        if yes_bid_sum > (1.0 + self.min_profit_threshold):
            gross_profit = yes_bid_sum - 1.0
            
            if gross_profit < self.min_net_profit:
                return None
            
            max_profit = gross_profit * min_liquidity if min_liquidity > 0 else gross_profit * 100
            
            return ArbitrageOpportunity(
                arb_type=ArbitrageType.MULTI_OUTCOME_SHORT,
                market_id=market_id,
                market_title=market_title,
                profit_per_dollar=gross_profit,
                max_profit=max_profit,
                confidence=min(1.0, gross_profit / 0.10),
                risk_level=RiskLevel.RISK_FREE,
                spread_cost=spread_cost,
                details={
                    "outcomes": relevant_outcomes,
                    "yes_ask_sum": yes_ask_sum,
                    "yes_bid_sum": yes_bid_sum,
                    "num_outcomes": len(relevant_outcomes),
                    "action": "SELL YES on ALL outcomes @ bid",
                    "min_liquidity": min_liquidity,
                },
                platform=self.platform,
            )
        
        return None
    
    def create_ev_opportunity(
        self,
        market_id: str,
        market_title: str,
        ev: float,
        side: str,
        market_price: float,
        true_prob: float,
        quality_score: float,
        liquidity: float = 0,
    ) -> ArbitrageOpportunity:
        """
        Create an EV-based opportunity (non-arbitrage, speculative edge).
        
        This wraps traditional EV signals in the same format as arbitrage
        for unified handling.
        """
        # Determine risk level based on EV and confidence
        if ev >= 0.05 and quality_score >= 8:
            risk_level = RiskLevel.LOW_RISK
        elif ev >= 0.02 and quality_score >= 6:
            risk_level = RiskLevel.MEDIUM_RISK
        else:
            risk_level = RiskLevel.HIGH_RISK
        
        return ArbitrageOpportunity(
            arb_type=ArbitrageType.EV_EDGE,
            market_id=market_id,
            market_title=market_title,
            profit_per_dollar=ev,
            max_profit=ev * liquidity if liquidity > 0 else ev * 100,
            confidence=min(1.0, quality_score / 10),
            risk_level=risk_level,
            spread_cost=0,  # Already factored into EV calc
            details={
                "side": side,
                "market_price": market_price,
                "true_prob": true_prob,
                "quality_score": quality_score,
                "action": f"BUY {side} @ {market_price:.1%}",
                "liquidity": liquidity,
            },
            platform=self.platform,
        )


def calculate_kelly_fraction(
    probability: float,
    odds: float,
    bankroll: float,
    kelly_fraction: float = 0.25,  # Quarter Kelly is safer
) -> float:
    """
    Calculate optimal bet size using Kelly Criterion.
    
    For arbitrage (100% probability), Kelly suggests betting everything,
    but we use a fraction for safety.
    
    Args:
        probability: Estimated true probability (0-1)
        odds: Decimal odds (payout per dollar)
        bankroll: Available bankroll
        kelly_fraction: Fraction of Kelly to use (0.25 = quarter Kelly)
    
    Returns:
        Recommended bet size in dollars
    """
    if probability <= 0 or probability >= 1:
        return 0
    
    # Kelly formula: f* = (bp - q) / b
    # where b = odds - 1, p = probability, q = 1 - p
    b = odds - 1
    p = probability
    q = 1 - p
    
    if b <= 0:
        return 0
    
    kelly = (b * p - q) / b
    
    if kelly <= 0:
        return 0
    
    # Apply Kelly fraction and bankroll
    bet_size = kelly * kelly_fraction * bankroll
    
    return max(0, bet_size)


def calculate_arb_position_size(
    opportunity: ArbitrageOpportunity,
    bankroll: float,
    max_position_pct: float = 0.20,
) -> dict:
    """
    Calculate position sizes for arbitrage opportunities.
    
    For rebalancing arb, we need to buy both sides in specific ratios.
    
    Returns:
        Dict with position sizes for each side
    """
    if not opportunity.is_risk_free:
        # For EV opportunities, use Kelly
        kelly_size = calculate_kelly_fraction(
            probability=opportunity.confidence,
            odds=1 + opportunity.profit_per_dollar,
            bankroll=bankroll,
        )
        return {
            "total_size": min(kelly_size, bankroll * max_position_pct),
            "method": "kelly",
        }
    
    # For risk-free arb, we can be more aggressive
    # but still cap at max position size for safety
    max_size = bankroll * max_position_pct
    
    # Limit by available liquidity
    if opportunity.max_profit > 0:
        liquidity_limit = opportunity.max_profit / opportunity.profit_per_dollar
        max_size = min(max_size, liquidity_limit)
    
    details = opportunity.details
    
    if opportunity.arb_type == ArbitrageType.SINGLE_CONDITION_LONG:
        yes_ask = details.get("yes_ask", 0.5)
        no_ask = details.get("no_ask", 0.5)
        total_cost = yes_ask + no_ask
        
        return {
            "total_size": max_size,
            "yes_size": max_size * (yes_ask / total_cost),
            "no_size": max_size * (no_ask / total_cost),
            "method": "rebalancing_long",
        }
    
    elif opportunity.arb_type == ArbitrageType.MULTI_OUTCOME_LONG:
        outcomes = details.get("outcomes", [])
        total_cost = details.get("yes_ask_sum", 1.0)
        
        sizes = {}
        for o in outcomes:
            name = o.get("name", "unknown")
            ask = o.get("yes_ask", o.get("yes_bid", 0))
            sizes[name] = max_size * (ask / total_cost)
        
        return {
            "total_size": max_size,
            "outcome_sizes": sizes,
            "method": "multi_rebalancing_long",
        }
    
    return {"total_size": max_size, "method": "default"}


# Quick test
if __name__ == "__main__":
    detector = ArbitrageDetector(min_profit_threshold=0.02)
    
    print("=" * 60)
    print("ARBITRAGE DETECTOR TEST")
    print("=" * 60)
    
    # Test single condition - should find arb
    print("\n--- Test 1: Single Condition (Should Find Arb) ---")
    opp = detector.check_single_condition(
        market_id="TEST-001",
        market_title="Will it rain tomorrow in NYC?",
        yes_bid=0.45, yes_ask=0.46,
        no_bid=0.48, no_ask=0.49,
        liquidity=10000,
    )
    if opp:
        print(opp)
        print(f"Profitable after spread? {opp.is_profitable_after_spread}")
    else:
        print("No arbitrage found")
    
    # Test single condition - no arb
    print("\n--- Test 2: Single Condition (No Arb) ---")
    opp2 = detector.check_single_condition(
        market_id="TEST-002",
        market_title="Will BTC hit 100k?",
        yes_bid=0.52, yes_ask=0.53,
        no_bid=0.48, no_ask=0.49,
        liquidity=5000,
    )
    if opp2:
        print(opp2)
    else:
        print("No arbitrage: YES_ask + NO_ask = 1.02 (no opportunity)")
    
    # Test multi-outcome
    print("\n--- Test 3: Multi-Outcome (Should Find Arb) ---")
    opp3 = detector.check_multi_outcome(
        market_id="TEST-003",
        market_title="2024 Election Winner",
        outcomes=[
            {"name": "Trump", "yes_bid": 0.50, "yes_ask": 0.51, "liquidity": 100000},
            {"name": "Harris", "yes_bid": 0.42, "yes_ask": 0.43, "liquidity": 100000},
            {"name": "Other", "yes_bid": 0.02, "yes_ask": 0.03, "liquidity": 10000},
        ]
    )
    if opp3:
        print(opp3)
    else:
        print("No multi-outcome arbitrage found")
    
    # Test position sizing
    print("\n--- Test 4: Position Sizing ---")
    if opp:
        sizes = calculate_arb_position_size(opp, bankroll=5000)
        print(f"Position sizes for $5000 bankroll:")
        for k, v in sizes.items():
            print(f"  {k}: {v}")
