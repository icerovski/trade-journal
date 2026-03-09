# phase_1_1_modeling.py
# -----------------------------------------------------------------------------
# PHASE 1.1: Modeling Reality with Advanced Data Structures
# CONCEPT: Events (Trades) vs. State (Positions)
# -----------------------------------------------------------------------------

from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime
from typing import List, Optional

# --- CONCEPT 1: ENUMS (Preventing String Errors) ---
class TradeSide(Enum):
    """
    Using an Enum ensures we only have two possible sides.
    Typing 'BUY' vs 'Buy' vs 'buy' is a common bug source in simple systems.
    """
    BUY = auto()
    SELL = auto()

# --- CONCEPT 2: IMMUTABLE DATACLASSES (The Fact) ---
@dataclass(frozen=True)
class Trade:
    """
    A Trade is a 'Fact'. It happened in the past. 
    'frozen=True' means once this object is created, it CANNOT be changed.
    This is essential for an auditable ledger.
    """
    ticker: str
    side: TradeSide
    quantity: float
    price: float
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """
        The __post_init__ is an advanced Python 'hook'. 
        It runs immediately AFTER the object is created but BEFORE it is used.
        Perfect for validation logic.
        """
        if self.quantity <= 0:
            raise ValueError(f"Invalid quantity {self.quantity}. Must be positive.")
        if self.price < 0:
            raise ValueError(f"Invalid price {self.price}. Cannot be negative.")

# --- CONCEPT 3: MUTABLE DATACLASSES (The Calculation) ---
@dataclass
class Position:
    """
    A Position is a 'Calculation'. It changes every time a trade happens.
    Therefore, it is NOT frozen.
    """
    ticker: str
    total_quantity: float = 0.0
    average_cost: float = 0.0
    
    @property
    def market_value(self) -> float:
        """
        A @property is a 'Calculated Attribute'. 
        It looks like data but is actually a function.
        """
        # For now, we assume current price is the same as avg cost
        return self.total_quantity * self.average_cost

# --- DEMONSTRATION ---
if __name__ == "__main__":
    print("--- STEP 1: Creating an Institutional Trade Object ---")
    try:
        # Create a valid trade
        t1 = Trade(ticker="AGQ", side=TradeSide.BUY, quantity=100, price=35.50)
        print(f"SUCCESS: Created Trade -> {t1}")
        
        # TRY TO CHANGE IT (This will fail because of frozen=True)
        # print("Attempting to cheat and change trade price...")
        # t1.price = 10.0 
        
    except ValueError as e:
        print(f"VALIDATION ERROR: {e}")

    print("\n--- STEP 2: Modeling a Current Position ---")
    pos = Position(ticker="AGQ", total_quantity=100, average_cost=35.50)
    print(f"Position: {pos.ticker} | Qty: {pos.total_quantity} | Value: ${pos.market_value:,.2f}")

# -----------------------------------------------------------------------------
# ADVANCED CONCEPTS COVERED:
# 1. @dataclass: Modern Python way to create data structures.
# 2. frozen=True: Enforces data integrity (Immutability).
# 3. __post_init__: Automated validation logic.
# 4. @property: Creating smart data fields that calculate on-the-fly.
# -----------------------------------------------------------------------------
