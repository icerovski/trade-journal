from logger import logger

class AssetRegistry:
    """
    Centralized registry for asset-class specific valuation and metadata rules.
    This ensures that heuristics for Bonds, Bills, and other complex assets 
    are kept out of the core business logic.
    """
    
    # Asset classes that typically report prices in % of par (e.g. 98.5).
    # This requires a 10.0 multiplier correction (Price * Qty * 10).
    PERCENT_OF_PAR_ASSETS = ['BOND', 'BILL', 'FIXED']

    @classmethod
    def enrich_position_metadata(cls, position):
        """
        Applies heuristic corrections to position metadata based on asset class.
        """
        asset_upper = position.asset_class.upper()

        # 1. Multiplier Correction for Bonds/Bills
        # HEURISTIC: IBKR reports Bond/Bill prices in % of par (e.g. 85.0).
        # Multiplier 10.0 correctly scales Face Value to Market Value (Quantity * Price * 10).
        if asset_upper in cls.PERCENT_OF_PAR_ASSETS:
            if position.multiplier == 1.0:
                position.multiplier = 10.0
                logger.info(f"AssetRegistry: Applied Bond/Bill Multiplier Correction (1.0 -> 10.0) for {position.ticker}")
        
        # Add future heuristics here (e.g., custom multipliers for specific exchanges or tickers)
        
        return position

    @classmethod
    def standardize_asset_quantity_and_multiplier(cls, asset_class: str, qty: float, multiplier: float) -> tuple[float, float]:
        """
        Standardizes quantity and multiplier based on asset class rules.
        Specifically handles Bond/Bill scaling (Face Value -> Shares).
        """
        asset_upper = asset_class.upper()
        if asset_upper in cls.PERCENT_OF_PAR_ASSETS:
            # Bond/Bill Scaling: IBKR reports Face Value, but we want 'Shares' ($1000 par)
            qty = qty / 1000.0
            if multiplier == 1.0:
                multiplier = 10.0
        return qty, multiplier
