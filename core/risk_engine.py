from .stop_loss import audit_position_risk, calculate_position_risk, get_atr_discovery_data


class RiskEngine:
    audit_position_risk = staticmethod(audit_position_risk)
    calculate_position_risk = staticmethod(calculate_position_risk)
