# Session Log: Transfer Washing and Cost Basis Integrity
**Date:** 2026-03-17

## Objectives
- Fix incorrect cost basis for `XLB` post-split.
- Investigate and resolve systemic cost-basis inflation for positions with inter-account transfers (`NLY`, `BXMT`, `JPC`, `EMD`).
- Reconcile `NKE` cost basis discrepancies.

## Technical Changes
- **`services/ibkr_parser.py`**: Patched `parse_corporate_actions_csv` to skip records where `account_id == '-'`. This prevents redundant split ingestion from IBKR Flex reports that include both account-specific and consolidated rows.
- **`core/ledger_engine.py`**: 
    - Implemented **Net-Transfer Logic**. The engine now groups trades by date and calculates a net quantity for transfers. This ensures that internal same-day moves (OUT from one account, IN to another) wash out perfectly in the `CONSOLIDATED` view.
    - Fixed a bug where internal transfers were triggering "Reset-on-Zero" and wiping historical cost basis.
    - Added safety checks in `rep_transfer_price` calculation to prevent `ZeroDivisionError` when processing zero-quantity transfer records.
- **Database Maintenance**: Purged redundant `SPLIT` records with `account_id = '-'` for `XLB`, `LRCX`, and `TQQQ`.

## Logic & Decisions
- **Transfer Tunnelling**: To maintain a true "Inception Cost" across the entire family portfolio, internal transfers must be transparent. By netting transfers before processing the ledger, we "tunnel" the original cost basis through account moves, ignoring the broker's "Step-up" or "Mark-to-Market" transfer prices.
- **WAC vs. Tax Lot**: Confirmed that our system uses a Global Weighted Average Cost (WAC) for institutional tracking, which may differ from the broker's tax-reporting basis if the broker resets costs during transfers.
- **Option Premium Integration**: Traced `NKE` discrepancy to short put premiums. Decided to maintain the separation of Stock Cost vs. Option P/L to keep the equity inception price "pure," despite the broker's practice of reducing stock cost by premium received.

## Verification
- **`XLB`**: Cost basis corrected to ~$60,750 (Avg $42.84), matching the broker exactly.
- **`NLY`**: Healed from $22.07 to **$19.92** (Matching broker's $60k basis).
- **`BXMT`**: Healed from $20.11 to **$18.23**.
- **`JPC`/`EMD`**: Reverted to true historical outlay prices.

## Next Steps
- Monitor automated split ingestion to ensure no further duplicate records from different Flex sections.
- Audit older positions for similar transfer-induced cost basis inflation.
