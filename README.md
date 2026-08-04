# Trade Journal & Risk Management System

A terminal-based portfolio management and risk-analysis system for a family-office
equity book. Ledger-based accounting for mathematical integrity, institutional risk
limits enforced on every position, and a Textual/rich TUI cockpit for daily work.

## Key Principles

*   **Ledger replay** — positions are never stored; they are derived by replaying the
    `trades` table chronologically. **Reset-on-zero**: cost basis clears when a
    position closes, so re-entries start clean lots.
*   **Dual-constraint risk** — every position is audited against a Risk limit
    (`(entry − stop) × qty / NAV`) and an Exposure limit (HCM / NAV); the tighter
    constraint wins. Sizing is FX-normalized to the NAV currency.
*   **ATR-anchored exits** — Wilder ATR stops (Fixed / Trailing with ratchet), an
    entry-anchored M1/M2/TP ladder in frozen inception-R units, and a regime-aware
    trim matrix. RR is informational only — never an exit trigger.
*   **Entry & Stop System** — advisory entry gates (G1–G8), THESIS/TECHNICAL
    classification, exit shapes, gap-aware sizing, a decision journal with an
    expectancy report, and a 3–6-month horizon calibration lens. All additive and
    default-off; defaults are pinned by a golden-master characterization test.
*   **IBKR integration** — Flex Web Service sync (trades, open positions, NAV,
    confirmations) with snapshot + delta reconciliation and cost-basis healing.

## Three-Tier Storage (never mixed)

| Layer | Location | Contents |
|---|---|---|
| Code repo | `C:\repos\trade-journal` | Pure logic + docs, no secrets |
| Config vault | OneDrive `Documents\Logos\.repos\trade-journal` | `.env` (IBKR tokens, paths), private config |
| Data hub | OneDrive `Companies\HTC_EOOD\TradeJournalData` | `trade_journal.db`, `prices.db`, CSVs, logs |

`sync_config.smart_sync()` pulls `.env` from the vault on startup; run
`uv run python sync_config.py` to back it up on exit.

## Setup & Usage

Prerequisites: Python 3.10+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync                     # install dependencies
uv run python main.py      # run the application
uv run python -m pytest tests/ -v   # run the test suite
```

`.env` (in the config vault) must define `DATA_PATH` and the IBKR Flex credentials
(`IBKR_TOKEN`, `IBKR_QUERY_ID_*`) — see `config.py` for the resolved keys.

## Menu Map

| # | Workspace | Purpose |
|---|---|---|
| 1 | SYNC ALL | IBKR fetch + ledger update + price sync |
| 2 | RISK WORKSPACE | ATR discovery, risk audit, Strategy Lab commands, gates |
| 3 | DASHBOARD | Performance & risk monitoring cockpit |
| 4 | KIDS FUND | Private wealth glide-path audit |
| 5 | MAINTENANCE | Surgical rebuilds & system tools |
| 6 | WATCH LIST | Prospect monitoring; the dedicated add-a-name flow |
| 7 | PORTFOLIO RISK | Aggregate R%, stop-out loss, HHI, FX exposure |
| 8 | ZONE SCANNER | Volume profile + AVWAP + MA confluence entry zones |
| 9 | EXPECTANCY | Decision-journal E[R] report + §7 capture (backfill, skipped picks) |

Press `F1` inside any workspace for the full guides (rendered from `docs/guides/`).

## Documentation

*   `CLAUDE.md` — architecture, core invariants, module map, schema (start here).
*   `docs/TECHNICAL_DOCS.md` — user-facing feature reference (also the F1 help).
*   `docs/guides/` — canonical definitions and workflows (Entry & Stop System,
    horizon calibration, indicator glossary, stop-placement playbook).
*   `docs/sessions/` — per-session engineering logs (PE-grade audit trail).
*   `docs/OPEN_ITEMS.md` — living work queue, surfaced at startup.

## License

Private proprietary tool. All rights reserved.
