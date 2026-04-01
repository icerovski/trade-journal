
import pytest
import pandas as pd
from datetime import datetime
from core.risk_engine import RiskEngine
from models import Position

def test_audit_position_risk_current_price_anchoring():
    """
    Verifies that audit_position_risk uses current_price for risk distance
    when adding shares, as per the Synchronized Price Anchoring mandate.
    """
    nav = 100000
    max_r = 1.0
    
    # 10 shares at 100. Stop is 100 (Breakeven).
    # Risk at Stop = 0.
    # Current Price is 110.
    # Max Risk Cap = 1000.
    # 
    # If we add more shares at 110 with stop at 100, 
    # each new share adds 10 risk units.
    # So we should be allowed 1000 / 10 = 100 MORE shares.
    
    res = RiskEngine.audit_position_risk(
        current_price=110.0,
        stop=100.0,
        entry_price=100.0,
        qty=10.0,
        multiplier=1.0,
        nav=nav,
        max_r_pct=max_r,
        max_exp_pct=50.0 # High exposure limit to focus on risk
    )
    
    # Pre-fix, risk_dist would be abs(100 - 100) = 0, leading to inf adjustment.
    # Post-fix, risk_dist is abs(110 - 100) = 10.
    # risk_budget_rem = 1000 - 0 = 1000.
    # adjustment = 1000 / 10 = 100.
    
    assert res['adjustment'] == 100.0

def test_audit_position_risk_trimming_uses_entry():
    """
    Verifies that trimming still uses entry_price-based distance to accurately
    calculate how many shares to remove to hit a risk limit.
    """
    nav = 100000
    max_r = 1.0 # $1,000 cap
    
    # 200 shares at 100. Stop is 90. 
    # Current risk = (100 - 90) * 200 = 2,000.
    # We are $1,000 over cap.
    # 
    # Each share removed reduces risk by (100 - 90) = 10.
    # So we must remove 1,000 / 10 = 100 shares.
    
    res = RiskEngine.audit_position_risk(
        current_price=95.0, # price is down, but not at stop
        stop=90.0,
        entry_price=100.0,
        qty=200.0,
        multiplier=1.0,
        nav=nav,
        max_r_pct=max_r,
        max_exp_pct=100.0 # Focus on risk limit
    )
    
    # risk_budget_rem = 1000 - 2000 = -1000.
    # risk_dist (for trimming) = abs(100 - 90) = 10.
    # adjustment = -1000 / 10 = -100.
    
    assert res['adjustment'] == -100.0
