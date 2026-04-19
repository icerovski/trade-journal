from datetime import datetime
from config import KIDS_ACCOUNT_ID, KIDS_GLIDE_PATH
from db import get_kids_config, get_kids_trades

class KidsFundEngine:
    """
    Engine for calculating individual ownership and Glide Path compliance
    for Angelina, Ivan, and Boris.
    """

    @staticmethod
    def calculate_ownership():
        """
        Calculates the unit-based ownership split for the kids.
        Base Units (JSON) + 33/33/33 split for everything after March 5, 2026.
        """
        config_df = get_kids_config()
        if config_df.empty:
            return {}

        kids_data = {row['name']: {
            'base_units': row['base_units'],
            'birthdate': row['birthdate'],
            'base_date': row['base_date'],
            'current_units': row['base_units']
        } for _, row in config_df.iterrows()}

        base_date_str = config_df['base_date'].iloc[0]
        new_trades = get_kids_trades(KIDS_ACCOUNT_ID, base_date_str)
        
        # Healing: Handle NULL multipliers from older or manual entries
        if not new_trades.empty:
            new_trades['multiplier'] = new_trades['multiplier'].fillna(1.0)
        
        # Split every new dollar equally
        for _, trade in new_trades.iterrows():
            # net_val is the cash flow of the trade
            net_val = trade['quantity'] * trade['price'] * trade['multiplier']
            if trade['side'] == 'SELL':
                # Sells reduce the pool, reducing units proportionally
                # But for simplicity, the user's rule is "Equal amount every time I put into the fund"
                # So we only track BUYs as unit issuance.
                continue
                
            # Split buy equally
            share_per_child = net_val / 3.0
            for name in kids_data:
                kids_data[name]['current_units'] += share_per_child
                
        # 3. Calculate Percentages
        total_units = sum(k['current_units'] for k in kids_data.values())
        for name in kids_data:
            kids_data[name]['ownership_pct'] = (kids_data[name]['current_units'] / total_units * 100) if total_units > 0 else 0
            
        return kids_data

    @staticmethod
    def get_glide_path_audit(kids_data, total_fund_nav):
        """
        Applies the Glide Path targets to each child's NAV share.
        """
        audit_results = []
        today = datetime.now()
        
        for name, data in kids_data.items():
            # Calculate Age
            dob = datetime.strptime(data['birthdate'], "%Y-%m-%d")
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            
            # Determine Target Ratio (Safety %)
            # Find the highest age threshold in the glide path that is <= current age
            thresholds = sorted([t for t in KIDS_GLIDE_PATH.keys() if t <= age], reverse=True)
            target_safety_ratio = KIDS_GLIDE_PATH[thresholds[0]] if thresholds else 0.0
            
            # Calculate Dollars
            child_nav = total_fund_nav * (data['ownership_pct'] / 100.0)
            target_safety_val = child_nav * target_safety_ratio
            target_growth_val = child_nav * (1.0 - target_safety_ratio)
            
            audit_results.append({
                'name': name,
                'age': age,
                'child_nav': child_nav,
                'target_safety_pct': target_safety_ratio * 100,
                'target_safety_val': target_safety_val,
                'target_growth_val': target_growth_val
            })
            
        return audit_results
