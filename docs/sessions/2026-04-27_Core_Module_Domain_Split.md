# Session — 2026-04-27: Core Module Domain Split

## Objectives

Split the monolithic `core/risk_engine.py` into focused, single-responsibility domain modules, following a plan agreed with the user after a full functionality audit.

## Technical Changes

### New modules created

| Module | Responsibility |
|---|---|
| `core/confluence.py` | `evaluate_confluence()` — ATR-distance zone detection for price and stop |
| `core/profit_taking.py` | `compute_exit_milestones()`, `enrich_regime()` — exit stage ladder and 200-DMA regime classification |
| `core/stop_loss.py` | `audit_position_risk()`, `calculate_position_risk()`, full ATR discovery pipeline (`get_atr_discovery_data`, `_fetch_price_data`, `_compute_atr_rows`) |
| `core/sizing.py` | `compute_position_size()`, `compute_portfolio_risk()`, `hhi_label()` |

### Shims (backwards-compat, no callers updated)

- **`core/risk_engine.py`** — reduced to 5 lines: re-exports from `stop_loss.py` + `RiskEngine` class wrapper
- **`core/portfolio_analytics.py`** — reduced to 1 line: re-exports from `sizing.py`

### Migration notes

- `_enrich_regime` removed from `PortfolioManager`; `get_dashboard_df()` now calls `enrich_regime(positions, self.mapper)` directly from `profit_taking.py`
- Prospect sizing block (6 lines in `_compute_atr_rows`) extracted into `compute_position_size()` in `sizing.py`
- `evaluate_confluence` was previously defined in `RiskEngine` class but never called from Python code; moved to `confluence.py` as a module-level function

## Logic & Decisions

- **Shim pattern chosen over updating all callers** — `risk_engine.py` and `portfolio_analytics.py` kept as thin re-export shims so that `portfolio_risk.py`, `risk_workspace.py`, `watch_list_workspace.py`, and the test suite required zero changes.
- **`portfolio_analytics.py` content moved to `sizing.py`** — portfolio-level risk aggregation (HHI, R% totals, currency breakdown) is fundamentally a sizing/capital-allocation concern.
- **UI workspace inline confluence logic left untouched** — `watch_list_workspace.py` has its own table-building loop that overlaps with `evaluate_confluence`; refactoring the UI is a separate pass with different risk profile.
- **One split per session** — each extraction was followed by a full test run before proceeding to the next.

## Verification

All 42 tests passed after each individual split (4 runs total, 0 failures).

## Next Steps

- Optional: update callers (`risk_workspace.py`, `watch_list_workspace.py`, tests) to import directly from domain modules and delete the shims
- Optional: thin `watch_list_workspace.py` by replacing its inline confluence loop with a call to `core.confluence.evaluate_confluence`
