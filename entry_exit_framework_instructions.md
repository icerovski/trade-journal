# Entry/Exit Zone Framework — Implementation Instructions

## Objective
Build a module within the existing portfolio/trading application that systematically identifies entry and exit price zones for position-trade holdings (weeks-to-months horizon) on equities/futures, using composite volume profile, anchored VWAP, and moving averages as confluence signals, integrated with the existing 5:1 risk/position-sizing framework.

## Before You Start
Read this entire document first. Then present an implementation plan back to the user — proposed file/module structure, a draft of the configuration parameters (see below), and an explicit list of open questions — before writing any code. Do not begin implementation until the user has confirmed the plan and the items flagged **[NEEDS INPUT]** below.

## Data Sources & Constraints

**Prices — Yahoo Finance (yfinance)**
- Daily OHLCV bars are the primary input. Intraday bars are only available for the trailing ~60 days and should not be relied on for the composite profile.
- Constraint: Yahoo Finance does not provide true intraday tick/volume-at-price data. The composite volume profile must therefore be an approximation — see "Volume Profile Module" below for the required method. Flag this limitation clearly in any output (e.g., a footer note: "Volume profile is a daily-bar approximation, not tick-derived").

**Portfolio — Interactive Brokers (Flex Query CSV)**
- Portfolio holdings (ticker, quantity, average cost, current market value, net liquidation value) come from a manually exported Flex Query CSV the user uploads periodically — no live API/TWS connection.
- Build a parser for this CSV format.
- **[NEEDS INPUT]**: The user will provide a sample Flex Query export so the exact column structure can be confirmed before the parser is built — do not guess the schema.

**Watchlist**
- A separate, user-maintained watchlist file (plain text/CSV list of tickers) supplements the IBKR holdings to form the full scan universe. Keep this as a simple editable file, not a database.

## Architecture

1. **Data ingestion layer** — pulls Yahoo Finance price history per ticker, parses the IBKR Flex Query CSV, merges with the watchlist into a single scan universe.
2. **Composite volume profile module** — see below.
3. **Anchored VWAP module** — see below.
4. **Moving average overlay** — 50-day and 200-day SMA as a third confluence input.
5. **Confluence detection module** — flags when 2+ signals align within a configurable threshold.
6. **Risk/position-sizing module** — converts a flagged zone into a stop distance and position size using the 5:1 reward:risk ratio.
7. **CLI report module** — outputs a plain text summary to the existing CLI.

## Module Specs

### Volume Profile (approximated from daily bars)
- For each ticker, build two composite profiles in parallel: a 6-month and a 12-month lookback.
- Method: for each daily bar, distribute that day's volume across its high-low range into price buckets (default bucket size: 0.5% of price), weighting the distribution toward the close (e.g., a skewed/triangular distribution peaking at close) rather than a flat split, since this better approximates where most volume likely traded.
- From the aggregated histogram per ticker, compute: POC (price bucket with maximum volume), VAH/VAL (boundaries containing ~70% of total volume around POC), and flag any prior POC that has not been retested within the current window ("naked POC").

### Anchored VWAP
- Auto-detect anchor points using a pivot-high/pivot-low algorithm on the daily series (default: 10-bar lookback/lookforward swing detection).
- Default anchor: the most recent significant swing low (relevant for long positions). Also compute from the most recent significant swing high as an alternate reference, and output both.
- Calculate VWAP from the anchor date to present using daily typical price (High+Low+Close)/3, cumulative against daily volume.
- **[NEEDS INPUT]**: Confirm the pivot lookback window — defaulting to 10 bars each side unless specified otherwise.

### Moving Averages
- Standard 50-day and 200-day SMA, calculated from the same Yahoo Finance daily series.

### Confluence Detection
- A "zone" is flagged when current price is within a configurable threshold (default 2.5%) of two or more of: composite VAL/VAH (6mo or 12mo), anchored VWAP (either anchor), 50-day SMA, 200-day SMA.
- Output must state which specific signals are converging at each flagged zone, not just that a zone exists — the reasoning needs to be visible, not a black box.

### Risk & Position Sizing
- Stop distance = distance from current price to the nearest invalidating structural level (composite VAL or anchored VWAP, whichever is tighter, for a long entry).
- The user works from three predefined risk/exposure presets (% of NAV risked per trade), selected case-by-case rather than a single fixed value. Do not hardcode one risk percentage — the config file must hold all three presets as named entries (e.g. `preset_1`, `preset_2`, `preset_3`, each with a `risk_pct_of_nav` value), and position size must be calculated under all three for every flagged zone.
- Position size per preset = back-solved from stop distance using the 5:1 reward:risk ratio and that preset's risk percentage of total portfolio capital.
- Total portfolio capital (NAV) is pulled from the parsed IBKR Flex Query data (net liquidation value).
- **[NEEDS INPUT]**: Actual preset labels and % NAV values — these go directly into the config file and can be filled in by the user at setup time rather than hardcoded by the agent.

## Configuration
All thresholds and lookback windows above must live in a single editable config file (YAML or JSON), not hardcoded in logic — composite lookback windows, confluence threshold, pivot window, risk-per-trade %, and volume profile bucket size should all be tunable without touching code.

## Output Format
Plain text CLI summary, run on demand (not scheduled), structured roughly as:

```
SCAN: [date]
Universe: [N tickers — holdings + watchlist]

[TICKER] — Zone flagged: ENTRY
  Price: $X.XX | Distance to zone: X.X%
  Signals aligned: 12mo VAL ($X.XX), Anchored VWAP from [date] ($X.XX)
  Suggested stop: $X.XX (-X.X%) | Target: next POC at $X.XX
  Position size — preset_1 (X.X% NAV): X shares
  Position size — preset_2 (X.X% NAV): X shares
  Position size — preset_3 (X.X% NAV): X shares

[TICKER] — No zone flagged
  ...

Note: Volume profile is a daily-bar approximation, not tick-derived.
```

## Suggested Implementation Order
1. IBKR Flex Query parser (needs sample file from the user first)
2. Yahoo Finance data ingestion + local caching (avoid re-pulling unchanged history)
3. Volume profile module + a manual validation step (sanity-check computed POC/VAH/VAL against a known reference, e.g. TradingView's profile for one test ticker)
4. Anchored VWAP module
5. Confluence detection
6. Risk/position-sizing integration
7. CLI report formatting

## Open Items Requiring User Confirmation Before Building
- Sample IBKR Flex Query CSV (to confirm schema)
- The three risk/exposure presets — label and % NAV for each (to populate the config file)
- Pivot lookback window for anchor detection (default 10 bars unless told otherwise)
- Volume bucket size methodology (default 0.5% of price unless told otherwise)
