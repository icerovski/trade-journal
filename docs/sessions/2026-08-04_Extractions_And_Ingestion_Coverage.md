# Extractions, Sync Hardening & Ingestion Coverage

**Date:** 2026-08-04 (second session of the day)
**Branch:** `feature/entry-stop-system`
**Commits:** `6c65630` … `51b031b`
**Precedes:** `2026-08-04_Application_Assessment_And_Integrity_Fixes.md`, which covers the assessment itself and its must-fix items 1–7.

## Objectives

Work the structural items the morning's assessment left queued — the ones too large to fold into a fix commit:

1. Resolve the OneDrive conflict copies in the data hub and stop a forked ledger being undetectable.
2. Extract the modeling engine and the command DSL out of `ui/risk_workspace.py` — the repo's top complexity scores, in its highest-churn file, with no headless entry point.
3. Cover the ingestion boundary, the last large untested surface.

## Technical Changes

### 1. OneDrive conflict copies (`6c65630`)

Diffed the fork before deleting anything: `trade_journal-LAPTOP-20V5N4Q9.db` (6/28) held **2,188 trades / 44 profiles** against the live **2,306 / 57**, with **zero** trades or profiles unique to it — a strict subset, nothing lost. Deleted it plus five stray `-LAPTOP-*.log` files (26 MB); kept `trade_journal.backup_20260626_205655.db`, which is a deliberate backup.

New `sync_config.check_data_hub()`, called from `main()` before `init_db()`. `find_duplicate_hub_files()` is pure and keys off the app's own canonical filenames rather than OneDrive's naming conventions (which differ by client and version). A `.db` duplicate warns loudly; stray `.log` copies get one line; a hand-made `.backup_*` is recognised and stays silent.

### 2. Modeling engine → `core/modeling.py` (`f97d2b7`, `a6c08cc`)

`build_position_model()` returns a frozen `PositionModel`: resolved inputs, the dual-constraint audit, reward geometry (`r_unit`/`tp_target`/`efficiency`), the reconciled `Verdict`, and the post-action `SizingProjection`. `decide_verdict()` and `project_sizing()` are separately callable. `_exit_recommendation` is injected rather than moved — one seam per commit.

`refresh_risk_checklist`: **336 → 231 lines, 139 → 74 branches, nesting 7 → 4**, and now renders only.

### 3. NAV-unavailable crash (`c6aa3e0`)

Surfaced by the new harness on its first run. `audit_position_risk`'s `nav <= 0` branch returned 4 keys where the normal path returns 12 (and named two of them `*_remaining` vs `*_rem`), so `int(audit['adjustment'])` raised `KeyError`. Reachable: `fetch_nav_data` returns `0.0` when the IBKR Flex download fails, so **a failed sync made selecting a row throw**.

Both paths now return identical keys plus `nav_known`. The panel gives `NAV UNAVAILABLE — sizing suspended`, shows `R n/a  Exp n/a`, and suppresses the sizing table.

### 4. Command DSL → `core/command_parser.py` (`79e14be`, `666ced5`)

`parse_command(raw, CommandContext, presets) → ParsedCommand` (+ `to_draft()`). `CommandContext` is a plain value object, so the parser touches no Position, database or network. Messages are returned as `notes`/`warnings` rather than emitted. `parse_classification`, `resolve_tp_mult`, `resolve_tp_ratio` and `resolve_inception_atr` moved with it; all four stay re-exported from `ui.risk_workspace`.

`on_strategy_change`: **258 → 107 lines, 81 → 29 branches**. `re` is now entirely absent from the UI module.

### 5. Ingestion boundary coverage (`1119715`, `51b031b`)

74 hermetic tests over `TickerMapper.resolve_yf_ticker` (38) and `DataLoader.get_broker_verified_snapshot` / `clean_trade_data` (36). No network, no data hub — verified by running them with `DATA_PATH` pointing at a non-existent directory.

Three defects found; one fixed, two pinned (see below).

## Logic & Decisions

**Snapshot-first is what makes a refactor provable.** Both extractions followed the same order: capture the observable output of the *unmodified* code, commit that snapshot in its own commit, then move the source and require byte-identical output. The risk panel's 32 scenarios and the DSL's 51 commands both held. When the NAV fix later did change behaviour, the snapshot diff was the evidence it was confined: **2 scenarios added, 0 changed**.

**Each golden master fails on bootstrap.** A snapshot that silently re-arms around whatever the behaviour is at generation time is worse than no snapshot — it looks like a tripwire and isn't one.

**Behaviour changes never ride inside a refactor.** The NAV crash was found during the modeling extraction and deliberately *pinned as broken* (`pytest.raises(KeyError)`) so the extraction stayed neutral, then fixed in its own commit which replaced that pin. Same discipline for the three ingestion defects.

**A partial dict is the bug, not the missing key.** The NAV branch could have been patched by adding `adjustment`; the real defect was two return paths with different shapes, so a caller could not rely on any key. Key parity is now asserted directly. It also hid a worse bug: the branch hardcoded `is_breached: False`, so **with NAV unreadable a breached stop reported as not breached**. A breach is a pure price comparison and needs no NAV — it now survives the degraded path.

**`R n/a`, never `R 0.00%`.** Zero reads as "no risk"; the truth is "not measured". Same failure mode as the ghost data hub found this morning — a system that looks like it is working while telling you nothing.

**The conflict detector never picks a winner.** Which copy of a forked ledger is authoritative depends on what was done on each machine. It reports; the user decides. A lock file was considered and rejected: on a synced folder its own propagation lags by minutes, so it would be advisory at best, and sequential single-machine use does not need it.

**Tests that read the user's live data are a defect in the test.** The ticker-mapper suite initially picked up the real `open_positions_lbd.csv` through the class-level `_positions_df` cache. That is how the `UnboundLocalError` was found — but it also made the suite non-hermetic, so the fixture now seeds a controlled frame and the bug is reproduced deliberately.

## Verification

- **Full suite: 579 passed** (298 at the start of the day, 502 before the ingestion work). `tests/` is now 6,373 lines against ~11,600 of source.
- **All three golden masters byte-identical** through both extractions.
- Every fix was **run against the pre-fix source and confirmed failing**: 4 tests for the ticker mapper, 4 for portfolio heat, 7 for migrations/promotion, 3 for the notification path, 2 for the DSL coupling.
- Ingestion tests confirmed hermetic by running with a broken `DATA_PATH`.
- Live-data checks: the fork DB diffed by `external_id` before deletion; the broker CSV inspected for `ReportDate` format, `Conid` dtype and LOT-row presence before drawing conclusions about which defects actually fire.

### Defects found

| Defect | Status |
|---|---|
| `refresh_risk_checklist` raised `KeyError` when NAV was 0 (failed sync) | **Fixed** — `c6aa3e0` |
| `ticker_mapper` `UnboundLocalError` — resolving a held symbol without a conid | **Fixed** — `51b031b` |
| `yyyyMMdd` `ReportDate` parses to 1970 → double-counted positions | Pinned; latent (live query is ISO) |
| Blank `Conid` drops every LOT inception date | Pinned; latent (live query returns no LOT rows) |

The ticker-mapper bug is the notable one: `info` was bound only inside `if conid:`, but a symbol matched in the cached positions CSV *assigns* `conid` further down, so `if conid and info:` stopped short-circuiting and read an unbound name. It fired on the prospect/discovery path for any symbol already held — the live book contains `BRK B`, `FOUR PRA` and an IWM option — and `get_atr_discovery_data` swallowed it, so discovery silently returned nothing. Same class as the `C:TH` use-before-assignment fixed in the morning session; the reassignment it broke also meant CSV-discovered conids were never persisted to the asset master.

## Next Steps

1. **Push DB writes out of read paths** — the last structural item from the assessment. `calculate_position_risk` writes the ratchet inside the enrichment loop, `_consolidate_positions` promotes prospects, `get_broker_verified_snapshot` writes the asset master. Return the values; let one caller persist. The ratchet is monotonic, so a transient bad price becomes permanent state.
2. **Other laptop** — launch once and confirm it reports `Companies\`; its `.env` should self-heal from the vault, but a newer local mtime would push the old path back. Then run menu 1: the hub's broker CSVs are from 7/30.
3. Optional: the two pinned ingestion defects, if the Flex queries are ever reconfigured (lot detail, date format).
4. Optional: `db.py` opens 33 connections against one `try/finally`.
