import pytest
import pandas as pd
from unittest.mock import patch
from models import Position
from core.portfolio_manager import PortfolioManager


def make_position(conid, qty, entry, account="U0000001", multiplier=1.0,
                  date="2024-01-01", inception=None):
    return Position(
        name="TEST", ticker="TEST", conid=conid, asset_class="STK", ccy="USD",
        date_entry=pd.Timestamp(date), qty=qty, entry_price=entry,
        inception_price=inception or entry, multiplier=multiplier,
        account_id=account,
    )


@patch("db.promote_prospect_to_active")
class TestConsolidatePositions:
    """Tests for PortfolioManager._consolidate_positions()."""

    def setup_method(self):
        self.pm = PortfolioManager()

    def test_single_position_passes_through(self, mock_promote):
        pos = make_position("C001", qty=100, entry=50.0)
        result = self.pm._consolidate_positions([pos])
        assert len(result) == 1
        assert result[0].qty == 100.0

    def test_two_accounts_same_conid_wac(self, mock_promote):
        """Two accounts holding the same asset produce one consolidated position with WAC."""
        p1 = make_position("C001", qty=100, entry=50.0, account="U0000001")
        p2 = make_position("C001", qty=100, entry=60.0, account="U0000002")

        result = self.pm._consolidate_positions([p1, p2])

        assert len(result) == 1
        pos = result[0]
        assert pos.qty == 200.0
        assert pos.entry_price == pytest.approx(55.0)  # (100*50 + 100*60) / 200
        assert pos.account_id == "CONSOLIDATED"

    def test_wac_with_different_multipliers(self, mock_promote):
        """WAC correctly accounts for position multipliers."""
        p1 = make_position("C001", qty=10, entry=100.0, multiplier=100.0, account="U1")
        p2 = make_position("C001", qty=10, entry=120.0, multiplier=100.0, account="U2")

        result = self.pm._consolidate_positions([p1, p2])

        # (10*100*100 + 10*120*100) / (20*100) = 220000/2000 = 110.0
        assert result[0].entry_price == pytest.approx(110.0)

    def test_inception_date_uses_earliest(self, mock_promote):
        """Consolidated position inherits the earlier inception date and price."""
        p1 = make_position("C001", qty=100, entry=60.0, date="2024-03-01", inception=60.0, account="U1")
        p2 = make_position("C001", qty=100, entry=50.0, date="2024-01-01", inception=50.0, account="U2")

        result = self.pm._consolidate_positions([p1, p2])

        assert result[0].date_entry == pd.Timestamp("2024-01-01")
        assert result[0].inception_price == pytest.approx(50.0)

    def test_offsetting_positions_zero_out(self, mock_promote):
        """Long and short legs of equal size net to zero — position removed."""
        p1 = make_position("C001", qty=100,  entry=50.0, account="U1")
        p2 = make_position("C001", qty=-100, entry=50.0, account="U2")

        result = self.pm._consolidate_positions([p1, p2])

        # Consolidated qty = 0 → filtered out (qty set to 0, entry to 0)
        assert result[0].qty == 0.0

    def test_different_conids_stay_separate(self, mock_promote):
        p1 = make_position("C001", qty=100, entry=50.0)
        p2 = make_position("C002", qty=200, entry=80.0)

        result = self.pm._consolidate_positions([p1, p2])

        assert len(result) == 2
        conids = {p.conid for p in result}
        assert conids == {"C001", "C002"}

    def test_empty_list_returns_empty(self, mock_promote):
        assert self.pm._consolidate_positions([]) == []
