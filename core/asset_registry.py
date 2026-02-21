from logger import logger

class AssetRegistry:
    """
    Centralized registry for asset-class specific valuation and metadata rules.
    This ensures that heuristics for Bonds, Bills, and other complex assets 
    are kept out of the core business logic.
    """
    
    # Asset classes that typically report prices in % of par (e.g. 98.5 instead of 0.985)
    # This requires a 0.01 multiplier correction to get the correct Market Value.
    PERCENT_OF_PAR_ASSETS = ['BOND', 'BILL', 'FIXED']

    @classmethod
    def enrich_position_metadata(cls, position):
        """
        Applies heuristic corrections to position metadata based on asset class.
        """
        asset_upper = position.asset_class.upper()

        # 1. Multiplier Correction for Bonds/Bills
        # HEURISTIC: IBKR reports Bond/Bill prices in % of par (e.g. 98.5).
        # Multiplier 0.01 correctly scales face value quantity to market value (Face * Price / 100).
        if asset_upper in cls.PERCENT_OF_PAR_ASSETS:
            if position.multiplier == 1.0:
                position.multiplier = 0.01
                logger.info(f"AssetRegistry: Applied Bond/Bill Multiplier Correction (1.0 -> 0.01) for {position.ticker}")
        
        # Add future heuristics here (e.g., custom multipliers for specific exchanges or tickers)
        
        return position

    @classmethod
    def get_valuation_multiplier(cls, asset_class: str, current_multiplier: float) -> float:
        """Returns the correct multiplier for an asset class if not already set."""
        if asset_class.upper() in cls.PERCENT_OF_PAR_ASSETS and current_multiplier == 1.0:
            return 0.01
        return current_multiplier
