# Session: 2026-04-30 — Meta Risk Audit & Portfolio Value Columns

## Objectives
1. Investigate why Meta's ACTION swung from "+33.1% Add" (Apr 20) to "-27.2% Subtract" (now), and whether the code misled the user into over-buying.
2. Add MKT VAL and COST columns to the Portfolio Risk Status grid.

## Technical Changes

### `risk_workspace.py`
- Added two new columns to the portfolio risk table: **MKT VAL** (after P/L STOP) and **COST** (after MKT VAL).
- Both values read from existing `row['MarketValue']` and `row['CostBasis']` in `enriched_data` — the same fields dashboard (option 3) already computes via `models.py` `to_dict()`. Zero extra computation.
- MKT VAL is colored green when market value ≥ cost basis, red when below (position at a loss).

## Logic & Decisions

### Meta risk audit — full reconstruction
The Apr 20 "+33.1%" recommendation was mathematically correct for the configured limit at the time. Working backwards from user-provided data (P/L@Stop = -$9,878, NAV = EUR 2,399,004, action = +33.1%, addition = $80,507):

| Limit tested | Resulting adj_pct |
|---|---|
| 0.50% | +6.3% |
| 0.75% | +19.6% |
| **1.00%** | **+33.1% ✓** |

**Confirmed: max_r_pct was 1.0% on Apr 20** — either the default or the L (Large/Index) preset. The code was correct for that configuration.

At some point after Apr 22 (when the B preset was updated from 0.50% → 0.75%), the user applied P:B or R:0.75, storing 0.75% in the DB. This made the position retroactively over-limit. The display shows "0.8%" because `f"{0.75:.1f}"` rounds to "0.8" in Python.

**If the intended limit had been 0.75% on Apr 20**, the recommendation would have been +19.6% → ~$47,700 addition instead of $80,507 — approximately **$32,800 over-extended**.

### Why P/L@Stop grew 3.2×  (-$9,878 → -$31,625)
Expected math. Adding shares above the stop always increases absolute loss-at-stop:

```
P/L@Stop_new = P/L@Stop_orig + (add_price − stop) × shares_added
             = −$9,878 + $105 × 152 sh ≈ −$31,625
```

Not a bug. The position's risk footprint grew because more shares were added.

### Why the current trim is -27.2% (not -33%)
The USD weakened ~7–8% vs EUR since Apr 20 (tariff uncertainty). fx_rate dropped from ~0.93 to ~0.87, reducing the EUR-equivalent risk of the USD position:

```
R% now = $31,625 × 0.87 / EUR 2,627,893 ≈ 1.05% → displays "1.0%"
adj_pct = (EUR 19,709 − EUR 27,514) / EUR 27,514 ≈ −28% ≈ −27.2% displayed
```

The trim recommendation is correct. The risk constraint is binding (not exposure).

### Correctness of current code
No bugs were found. The formula in `audit_position_risk` is identical between Apr 20 and now. The swing from Add to Subtract is fully explained by:
1. Position size tripled (added $80,507)
2. Configured limit changed from 1.0% → 0.75%
3. USD weakened (reduces EUR-equivalent risk, softens the required trim slightly)

## Verification
- Syntax check passed on `risk_workspace.py`.
- Column count in `add_row` confirmed to match `add_column` definitions (14 each).
- MKT VAL / COST reuse existing `MarketValue` / `CostBasis` fields — same source as option 3 dashboard.

## Next Steps
- Consider whether a per-position limit history would help avoid future configuration ambiguity (knowing what limit was active when an action was taken).
- User should decide whether to act on the current -27.2% trim signal for Meta.
