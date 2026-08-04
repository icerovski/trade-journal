"""The Strategy Lab command DSL — parsing and resolution.

One line drives every pre-trade decision:

    VALUE [F/T] [P:S/B/L] [R:x] [E:x] [TP:n] [C:TH/TE] [G:gap] [X:H/T] [SRC:s] [THM:t] [+N/-N/BE]

Parsing is strictly ORDER-DEPENDENT and the order is the design, not an accident.
Four traps it exists to avoid:

  * `X:T` (thesis shape) must not be read as the TRAILING flag `T`;
  * `THM:TECH` contains a T, same hazard;
  * `TP:+35%` must not be read as a `+35` share add;
  * `TP:3:1` must not be read as the fixed multiple `3`, leaving a stray `:1`.

Each token is stripped from the string as it is consumed, so by the time the bare
VALUE regex runs, only the value is left. Change the order and you change what a
command means — `tests/test_command_dsl_characterization.py` pins 51 commands
byte-for-byte.

Pure: no Textual, no database, no notifications. Messages are RETURNED (`notes`
for informational, `warnings` for user error) so the caller decides how to show
them. Extracted from `ui.risk_workspace.on_strategy_change` (2026-08-04) with no
behaviour change.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from core.exit_shapes import normalize_shape
from core.stop_loss import snap_inception_atr


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CommandContext:
    """Everything the parse needs from the position and its discovery cache.

    A plain value object, so the parser never touches a Position, the database,
    or the network — and every resolution below is reproducible from data.
    """
    entry_price: float = 0.0
    current_price: float = 0.0
    mark_price: float = 0.0
    max_since_entry: float = 0.0
    atr: float = 0.0
    stop_type: str = "FIXED"
    max_r_pct: float = 1.0
    max_exp_pct: float = 5.0
    inception_atr: Optional[float] = None
    tp_atr_mult: Optional[float] = None
    tp_is_override: bool = False
    stored_classification: str = ""
    stored_exit_shape: str = ""
    ticker: str = ""
    discovery_price: Optional[float] = None
    discovery_hwm: float = 0.0
    discovery_rows: tuple = ()

    @classmethod
    def from_position(cls, position, discovery: Optional[dict] = None) -> "CommandContext":
        disc = discovery or {}
        return cls(
            entry_price=position.entry_price, current_price=position.current_price,
            mark_price=position.mark_price, max_since_entry=position.max_since_entry,
            atr=position.atr, stop_type=position.stop_type,
            max_r_pct=position.max_r_pct, max_exp_pct=position.max_exp_pct,
            inception_atr=position.inception_atr,
            tp_atr_mult=position.tp_atr_mult,
            tp_is_override=bool(getattr(position, 'tp_is_override', False)),
            stored_classification=getattr(position, 'classification', '') or '',
            stored_exit_shape=getattr(position, 'exit_shape', '') or '',
            ticker=position.ticker,
            discovery_price=disc.get('current_price'),
            discovery_hwm=disc.get('max_price', 0.0) or 0.0,
            discovery_rows=tuple(disc.get('rows') or ()),
        )


@dataclass(frozen=True)
class ParsedCommand:
    """A fully resolved command, ready to become a draft."""
    atr: float                      # TRAILING: distance · FIXED: the literal stop price
    stop_type: str
    stop_price: float
    max_r_pct: float
    max_exp_pct: float
    base_price: float               # the price the stop is measured from
    current_price: float
    inception_atr: Optional[float]  # the frozen R unit to store
    preset: Optional[str] = None
    classification: Optional[str] = None   # None = not typed (preserve stored)
    exit_shape: Optional[str] = None       # None = not typed (preserve stored)
    source: Optional[str] = None
    theme: Optional[str] = None
    gap_price: Optional[float] = None
    tp_atr_mult: Optional[float] = None
    add: Optional[float] = None
    goal_seek: Optional[str] = None
    notes: tuple = ()               # informational, shown once (deduped by caller)
    warnings: tuple = ()            # the command did not do what was typed

    def to_draft(self, ticker: str, ctx: CommandContext) -> dict:
        """The draft dict the workspace stores and later commits. A token the user
        did NOT type this edit preserves whatever is already on the profile."""
        return {
            'atr': self.atr, 'type': self.stop_type, 'ticker': ticker,
            'max_r_pct': self.max_r_pct, 'max_exp_pct': self.max_exp_pct,
            'hypo_stop': self.stop_price, 'inception_atr': self.inception_atr,
            'profile': self.preset or None,
            'tp_atr_mult': self.tp_atr_mult,
            'hypo_add': self.add, 'goal_seek': self.goal_seek,
            'classification': (self.classification if self.classification is not None
                               else ctx.stored_classification),
            'gap_price': self.gap_price,
            'exit_shape': (self.exit_shape if self.exit_shape is not None
                           else ctx.stored_exit_shape),
            'source': self.source or '', 'theme': self.theme or '',
        }


# --------------------------------------------------------------------------
# Token resolvers (pure, individually testable)
# --------------------------------------------------------------------------
def parse_classification(raw: str):
    """Extract a `C:` classification token from an (upper-cased) command string.

    Returns (classification, stripped_raw):
      • C:TH → "THESIS",  C:TE → "TECHNICAL",  C:- → "" (explicit clear/unset);
      • classification is None when no C: token is present (leave the stored tag untouched);
      • stripped_raw is `raw` with the token removed.
    """
    m = re.search(r"C:(THESIS|TECHNICAL|TH|TE|-)", raw)
    if not m:
        return None, raw
    tok = m.group(1)
    classification = "" if tok == "-" else ("THESIS" if tok in ("TH", "THESIS") else "TECHNICAL")
    return classification, raw.replace(m.group(0), "").strip()


def resolve_tp_mult(token: str, entry: float, inception_atr: float):
    """Resolve a `TP:` token into a multiple of the inception ATR.

    Returns (mult, clear, ok):
      • clear=True  → user typed `TP:-` (revert to the default 3R), mult is None.
      • ok=False    → token could not be resolved (missing inception ATR or an
                      unrecognised form); caller should warn and ignore.
    Accepted forms (token already upper-cased, `TP:` stripped):
      4 | 4R           → explicit multiple of inception ATR
      +35% | 35%       → gain as % of entry, divided by inception ATR
    The absolute-$ form ($60K) was cut — TP:nR and TP:N:1 carry the real use
    cases; $/K tokens fall through to ok=False.
    """
    token = (token or "").strip()
    if token == '-':
        return None, True, True
    if not inception_atr or inception_atr <= 0 or not entry or entry <= 0:
        return None, False, False
    try:
        if token.endswith('R'):
            return float(token[:-1]), False, True
        if token.endswith('%'):
            pct = float(token.rstrip('%').lstrip('+'))
            return (entry * pct / 100.0) / inception_atr, False, True
        return float(token), False, True  # plain number → multiple
    except ValueError:
        return None, False, False


def resolve_tp_ratio(ratio: float, entry: float, inception_atr: float, price: float, stop: float):
    """Resolve an N:1 forward reward:risk goal into a multiple of the inception ATR.

    The target that pays `ratio`:1 measured from the CURRENT price against `stop` is
        target = price + ratio × (price − stop)
    i.e. `ratio` units of upside from here for every unit given back to the stop. It is then
    expressed — like every stored TP — as a multiple of the frozen inception ATR from entry,
    so the saved value does not drift when the stop is later tightened. This is the same
    measure the panel's TARGET line flags against, so a freshly set N:1 target reads exactly
    N.00 forward RR.

    Returns (mult, ok); ok=False when the inputs cannot form a positive-risk target — price
    at/below the stop (no risk to pay 3:1 on), or a missing inception ATR.
    """
    if not inception_atr or inception_atr <= 0 or not entry or entry <= 0:
        return None, False
    if ratio <= 0 or price <= stop:
        return None, False
    target = price + ratio * (price - stop)
    return (target - entry) / inception_atr, True


def resolve_inception_atr(stop_type: str, entry: float, stop: float, atr: float,
                          ctx: CommandContext):
    """The R unit to freeze on the profile, plus any note explaining a substitution.

    TRAILING carries its own distance. FIXED gives a stop PRICE, so the milestone
    ladder needs a volatility unit: snap the risk distance to the nearest discovery
    timeframe, so the ladder runs on the horizon the stop was actually sized against
    rather than a hardcoded daily ATR (which fired the ladder prematurely on
    deliberately deep leveraged-ETF stops).

    Never returns None: `db.set_position_risk` degrades a NULL inception to
    `atr_value`, which for FIXED is the stop PRICE — a catastrophic R unit.
    Returns (inception_atr, note_or_None).
    """
    if stop_type != 'FIXED':
        return atr, None

    risk_dist = abs(entry - stop)
    rows = list(ctx.discovery_rows)

    # Thin history shrinks a timeframe's window while keeping its label; snap_inception_atr
    # excludes those, so a "12q" computed from 2 bars can never be frozen as the R unit.
    snapped, snap_label = snap_inception_atr(rows, risk_dist)
    if snapped is not None:
        naive = {r.label: r.atr_wilder for r in rows}
        naive_label = min(naive, key=lambda k: abs(naive[k] - risk_dist)) if naive else snap_label
        if naive_label != snap_label:
            return snapped, (f"{ctx.ticker}: {naive_label} ATR has too little history (⚠) — "
                             f"R snapped to {snap_label} instead.")
        return snapped, None

    if rows and risk_dist > 0:
        if ctx.inception_atr and ctx.inception_atr > 0:
            return ctx.inception_atr, (f"{ctx.ticker}: price history too thin for a trustworthy "
                                       f"ATR snap — keeping stored inception ATR.")
        return risk_dist, (f"{ctx.ticker}: history too thin for any ATR — ladder anchored to "
                           f"entry−stop ({risk_dist:,.2f}).")

    # No discovery data at all (worker still loading, or yfinance down).
    stored = ctx.inception_atr
    if (not stored or stored <= 0) and risk_dist > 0:
        return risk_dist, None
    return stored, None


# --------------------------------------------------------------------------
# The parse
# --------------------------------------------------------------------------
def parse_command(raw: str, ctx: CommandContext, presets: dict) -> Optional[ParsedCommand]:
    """Parse one command line against `ctx`. Returns None for an empty command.

    Token order below is load-bearing — see the module docstring.
    """
    raw = (raw or "").strip().upper()
    if not raw:
        return None

    notes, warnings = [], []
    atr, stop_type = ctx.atr, ctx.stop_type
    max_r, max_exp = ctx.max_r_pct, ctx.max_exp_pct

    # 1. Preset, then explicit R:/E: so an explicit value can override a preset.
    preset_key = ""
    p_m = re.search(r"P:([SBL])", raw)
    if p_m:
        preset = presets.get(p_m.group(1))
        if preset:
            max_r, max_exp = preset["max_r_pct"], preset["max_exp_pct"]
            preset_key = p_m.group(1)
        raw = raw.replace(p_m.group(0), "").strip()

    r_m = re.search(r"R:([0-9\.]+)", raw)
    if r_m:
        max_r = float(r_m.group(1))
        raw = raw.replace(r_m.group(0), "").strip()
    e_m = re.search(r"E:([0-9\.]+)", raw)
    if e_m:
        max_exp = float(e_m.group(1))
        raw = raw.replace(e_m.group(0), "").strip()

    # 2. THESIS/TECHNICAL tag (§0a). None = not typed; "" = explicit clear.
    classification, raw = parse_classification(raw)

    # 3. Journal-only source/theme (§7). BEFORE the F/T check — "THM" contains a T.
    source = theme = None
    s_m = re.search(r"SRC:([A-Z0-9_\-\.&]+)", raw)
    if s_m:
        source = s_m.group(1)
        raw = raw.replace(s_m.group(0), "").strip()
    t_m = re.search(r"THM:([A-Z0-9_\-\.&]+)", raw)
    if t_m:
        theme = t_m.group(1)
        raw = raw.replace(t_m.group(0), "").strip()

    # 4. Gap price (§6). BEFORE the +N/-N and VALUE regexes so its digits aren't misread.
    gap_price = None
    g_m = re.search(r"G:([0-9]+(?:\.[0-9]+)?)", raw)
    if g_m:
        gap_price = float(g_m.group(1))
        raw = raw.replace(g_m.group(0), "").strip()

    # 5. Exit shape (§5a). BEFORE the F/T check so "X:T" isn't read as TRAILING.
    exit_shape = None
    x_m = re.search(r"X:(HARD|RUNNER|THESIS|H|R|T|L|-)", raw)
    if x_m:
        tok = x_m.group(1)
        exit_shape = "" if tok == "-" else normalize_shape(tok)
        raw = raw.replace(x_m.group(0), "").strip()

    # 6. §0a coupling: a THESIS tag implies the thesis exit shape — one clock per
    # trade, no guessed-at-entry target. Overridable, and only applied when no X:
    # was typed this edit and no non-default shape is already stored. MUST sit
    # below the X: parse: only there is `exit_shape is None` a truthful
    # "the user did not type X: this time".
    if classification == "THESIS" and exit_shape is None \
            and normalize_shape(ctx.stored_exit_shape) == "LADDER":
        exit_shape = "THESIS"
        notes.append(f"{ctx.ticker}: C:TH → thesis-exit shape applied "
                     f"(no price target; override with X:L or X:H).")

    # 7. TP override. BEFORE the +N/-N regex so "TP:+35%" isn't read as a share add.
    # The N:1 form is captured here but RESOLVED after the stop is known.
    tp_final = ctx.tp_atr_mult if ctx.tp_is_override else None
    tp_ratio = None
    tpr_m = re.search(r"TP:(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", raw)
    if tpr_m:
        raw = raw.replace(tpr_m.group(0), "").strip()
        num, den = float(tpr_m.group(1)), float(tpr_m.group(2))
        tp_ratio = (num / den) if den > 0 else None
    else:
        # The regex still captures the cut $/K forms so they are stripped and
        # rejected with a warning instead of leaking into the quantity parse.
        tp_m = re.search(r"TP:(\-|\+?\$?\d+(?:\.\d+)?[%KR]?)", raw)
        if tp_m:
            raw = raw.replace(tp_m.group(0), "").strip()
            inc = ctx.inception_atr if (ctx.inception_atr and ctx.inception_atr > 0) else ctx.atr
            mult, clear, ok = resolve_tp_mult(tp_m.group(1), ctx.entry_price, inc)
            if not ok:
                warnings.append("TP target not resolved — needs an inception ATR; accepted "
                                "forms: TP:nR, TP:+35%, TP:N:1, TP:- ($ form removed).")
            elif clear:
                tp_final = None
            else:
                tp_final = mult

    # 8. Quantity modeling. BEFORE the VALUE regex so "+26" isn't read as a stop.
    add = None
    goal_seek = None
    if re.search(r"\bBE\b", raw):
        goal_seek = 'BE'
        raw = re.sub(r"\bBE\b", "", raw).strip()
    add_m = re.search(r"([+\-]\d+(?:\.\d+)?)", raw)
    if add_m:
        add = float(add_m.group(1))
        raw = raw.replace(add_m.group(1), "").strip()

    # 9. Stop type. Every token containing a stray T/F has been consumed by now.
    if 'T' in raw:
        stop_type = "TRAILING"
        raw = raw.replace('T', "").strip()
    elif 'F' in raw:
        stop_type = "FIXED"
        raw = raw.replace('F', "").strip()

    # 10. The base the stop is measured from: the high-water mark for a trailing
    # stop, the entry for a fixed one.
    current_price = ctx.discovery_price if ctx.discovery_price is not None else (
        ctx.current_price or ctx.mark_price)
    hwm = max(ctx.entry_price, current_price, ctx.mark_price, ctx.discovery_hwm, ctx.max_since_entry)
    base_price = hwm if stop_type == 'TRAILING' else ctx.entry_price
    if base_price == 0:
        base_price = current_price

    # 11. The bare VALUE — whatever is left.
    val_m = re.search(r"([@\$0-9\.%]+)", raw)
    if val_m:
        v = val_m.group(1)
        is_at = v.startswith('@')      # @PRICE T → trailing anchored to an exact price
        is_dollar = v.startswith('$')
        num = float(v[1:] if (is_at or is_dollar) else (v[:-1] if v.endswith('%') else v))
        if stop_type == 'FIXED':
            atr = num                          # the value IS the literal stop price
        elif is_at:
            atr = base_price - num             # price floor → distance from the HWM
        elif v.endswith('%'):
            atr = base_price * (num / 100.0)
        else:
            atr = num                          # dollar amount ($ prefix is cosmetic)

    stop_price = atr if stop_type == 'FIXED' else base_price - atr

    # 12. Deferred TP:N:1 — the stop is known now.
    if tp_ratio is not None:
        inc = ctx.inception_atr if (ctx.inception_atr and ctx.inception_atr > 0) else ctx.atr
        mult, ok = resolve_tp_ratio(tp_ratio, ctx.entry_price, inc, current_price, stop_price)
        if ok:
            tp_final = mult
        else:
            warnings.append("TP ratio needs the price above the stop and an inception ATR.")

    # 13. The R unit to freeze.
    entry_for_snap = ctx.entry_price if ctx.entry_price > 0 else base_price
    inception_atr, snap_note = resolve_inception_atr(stop_type, entry_for_snap, stop_price, atr, ctx)
    if snap_note:
        notes.append(snap_note)

    return ParsedCommand(
        atr=atr, stop_type=stop_type, stop_price=stop_price,
        max_r_pct=max_r, max_exp_pct=max_exp,
        base_price=base_price, current_price=current_price,
        inception_atr=inception_atr, preset=preset_key or None,
        classification=classification, exit_shape=exit_shape,
        source=source, theme=theme, gap_price=gap_price,
        tp_atr_mult=tp_final, add=add, goal_seek=goal_seek,
        notes=tuple(notes), warnings=tuple(warnings),
    )
