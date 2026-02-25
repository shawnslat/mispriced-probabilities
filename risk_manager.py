"""
Risk Manager V2 - Kill Switch, Position Limits, Correlation Checks
"""
from datetime import datetime, timedelta
import config


class RiskManager:
    """Centralized risk management and safety controls."""
    
    def __init__(self, initial_bankroll):
        self.starting_bankroll = initial_bankroll
        self.daily_start_bankroll = initial_bankroll
        self.daily_reset_time = datetime.now().replace(hour=0, minute=0, second=0)
        self.kill_switch_active = False
        self.kill_switch_reason = None
        
    def check_kill_switch(self, current_bankroll):
        """
        Check if kill switch should be activated.
        
        Args:
            current_bankroll: Current account/paper balance
            
        Returns:
            tuple: (should_halt, reason)
        """
        if self.kill_switch_active:
            return True, self.kill_switch_reason
        
        # Reset daily tracking at midnight
        now = datetime.now()
        if now.date() > self.daily_reset_time.date():
            self.daily_start_bankroll = current_bankroll
            self.daily_reset_time = now.replace(hour=0, minute=0, second=0)
            print(f"📅 Daily reset - New starting balance: ${current_bankroll:.2f}")
        
        # Calculate daily loss
        daily_pnl = current_bankroll - self.daily_start_bankroll
        daily_loss_pct = abs(daily_pnl / self.daily_start_bankroll) if daily_pnl < 0 else 0
        
        # Check loss limit
        if daily_loss_pct > config.DAILY_LOSS_LIMIT:
            reason = f"Daily loss limit exceeded: {daily_loss_pct*100:.1f}% (limit: {config.DAILY_LOSS_LIMIT*100:.1f}%)"
            self.activate_kill_switch(reason)
            return True, reason
        
        return False, None
    
    def activate_kill_switch(self, reason):
        """Activate kill switch and log reason."""
        self.kill_switch_active = True
        self.kill_switch_reason = reason
        config.KILL_SWITCH_ACTIVE = True
        config.KILL_SWITCH_REASON = reason
        
        print(f"\n{'='*60}")
        print(f"🛑 KILL SWITCH ACTIVATED")
        print(f"Reason: {reason}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
    
    def deactivate_kill_switch(self):
        """Manually deactivate kill switch (use with caution)."""
        self.kill_switch_active = False
        self.kill_switch_reason = None
        config.KILL_SWITCH_ACTIVE = False
        config.KILL_SWITCH_REASON = None
        
        print("✅ Kill switch deactivated")
    
    def validate_position_size(self, size, bankroll, open_positions):
        """
        Validate proposed position size against limits.
        
        Args:
            size: Proposed position size (as fraction of bankroll)
            bankroll: Current bankroll
            open_positions: List of current positions
            
        Returns:
            tuple: (is_valid, adjusted_size, reason)
        """
        # Check minimum
        if size < config.MIN_POSITION_SIZE:
            return False, 0, f"Position too small: {size*100:.2f}% < {config.MIN_POSITION_SIZE*100:.2f}%"
        
        # Check maximum
        if size > config.MAX_POSITION_SIZE:
            adjusted = config.MAX_POSITION_SIZE
            return True, adjusted, f"Position capped at {config.MAX_POSITION_SIZE*100:.1f}%"
        
        # Check total exposure
        total_exposure = sum(p.get("size", 0) for p in open_positions) / bankroll
        new_total = total_exposure + size
        
        if new_total > config.MAX_POSITION_VALUE:
            remaining = max(config.MAX_POSITION_VALUE - total_exposure, 0)
            if remaining < config.MIN_POSITION_SIZE:
                return False, 0, f"Max total exposure reached: {total_exposure*100:.1f}%"
            return True, remaining, f"Position reduced to stay under {config.MAX_POSITION_VALUE*100:.1f}% total exposure"
        
        return True, size, "OK"
    
    def check_position_limits(self, open_positions):
        """
        Check if position count limits are exceeded.
        
        Args:
            open_positions: List of current positions
            
        Returns:
            tuple: (is_ok, reason)
        """
        count = len(open_positions)
        
        if count >= config.MAX_OPEN_POSITIONS:
            return False, f"Max positions reached: {count}/{config.MAX_OPEN_POSITIONS}"
        
        return True, None
    
    def get_risk_metrics(self, current_bankroll, open_positions):
        """
        Calculate current risk metrics.
        
        Returns:
            dict: Risk metrics
        """
        daily_pnl = current_bankroll - self.daily_start_bankroll
        daily_return = (daily_pnl / self.daily_start_bankroll) * 100
        
        total_pnl = current_bankroll - self.starting_bankroll
        total_return = (total_pnl / self.starting_bankroll) * 100
        
        total_exposure = sum(p.get("size", 0) for p in open_positions)
        exposure_pct = (total_exposure / current_bankroll) * 100 if current_bankroll > 0 else 0
        
        return {
            "current_bankroll": current_bankroll,
            "daily_pnl": daily_pnl,
            "daily_return_pct": daily_return,
            "total_pnl": total_pnl,
            "total_return_pct": total_return,
            "open_positions": len(open_positions),
            "total_exposure": total_exposure,
            "exposure_pct": exposure_pct,
            "kill_switch_active": self.kill_switch_active,
        }
    
    def print_risk_summary(self, current_bankroll, open_positions):
        """Print formatted risk summary."""
        metrics = self.get_risk_metrics(current_bankroll, open_positions)
        
        print(f"\n{'='*60}")
        print(f"📊 RISK SUMMARY")
        print(f"{'='*60}")
        print(f"Current Bankroll: ${metrics['current_bankroll']:,.2f}")
        print(f"Daily P&L: ${metrics['daily_pnl']:+,.2f} ({metrics['daily_return_pct']:+.2f}%)")
        print(f"Total P&L: ${metrics['total_pnl']:+,.2f} ({metrics['total_return_pct']:+.2f}%)")
        print(f"Open Positions: {metrics['open_positions']}/{config.MAX_OPEN_POSITIONS}")
        print(f"Total Exposure: ${metrics['total_exposure']:,.2f} ({metrics['exposure_pct']:.1f}%)")
        print(f"Kill Switch: {'🛑 ACTIVE' if metrics['kill_switch_active'] else '✅ OK'}")
        print(f"{'='*60}\n")
