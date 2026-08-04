"""The Strategy Lab command DSL (`core/command_parser.py`).

Extracted from `on_strategy_change`, where the whole grammar lived inside a
Textual event handler and could only be reached by mounting the app. The rendered
output is pinned separately by `test_command_dsl_characterization.py`; this file
tests what the tokens *mean*.

The load-bearing property is parse ORDER. Each token is stripped as it is
consumed, so a token parsed too late gets mangled by an earlier regex. The four
real hazards each have a test that names the failure rather than just asserting a
value.
"""

import pytest

from core.command_parser import (
    CommandContext,
    ParsedCommand,
    parse_classification,
    parse_command,
    resolve_inception_atr,
    resolve_tp_mult,
    resolve_tp_ratio,
)

PRESETS = {
    "S": {"label": "Small", "max_r_pct": 0.30, "max_exp_pct": 1.5},
    "B": {"label": "Base", "max_r_pct": 0.60, "max_exp_pct": 3.0},
    "L": {"label": "Large/Index", "max_r_pct": 1.00, "max_exp_pct": 5.0},
}


class _Row:
    def __init__(self, label, atr, shrunk=False):
        self.label, self.atr_wilder, self.window_shrunk = label, atr, shrunk


def _ctx(**over):
    base = dict(
        entry_price=100.0, current_price=110.0, mark_price=109.0, max_since_entry=120.0,
        atr=8.0, stop_type="TRAILING", max_r_pct=1.0, max_exp_pct=5.0,
        inception_atr=10.0, ticker="TST",
    )
    base.update(over)
    return CommandContext(**base)


def _parse(command, **ctx_over):
    return parse_command(command, _ctx(**ctx_over), PRESETS)


# --------------------------------------------------------------------------
# Parse-order hazards — why the order is the design
# --------------------------------------------------------------------------
def test_exit_shape_thesis_is_not_read_as_the_trailing_flag():
    # "X:T" contains a T. Parsed after the F/T check it would silently flip a
    # FIXED stop to TRAILING — changing the stop's meaning, not just a label.
    p = _parse("95 F X:T")
    assert p.stop_type == "FIXED"
    assert p.exit_shape == "THESIS"
    assert p.stop_price == 95.0


def test_theme_tag_is_not_read_as_the_trailing_flag():
    p = _parse("95 F THM:TECH")
    assert p.stop_type == "FIXED"
    assert p.theme == "TECH"


def test_tp_percent_is_not_read_as_a_share_quantity():
    # "TP:+35%" contains "+35". Parsed after the quantity regex it would model a
    # 35-share add and leave a stray "%" to poison the stop value.
    p = _parse("10 T TP:+35%")
    assert p.add is None
    assert p.tp_atr_mult == pytest.approx(3.5)   # 100 × 35% / 10 ATR
    assert p.atr == 10.0


def test_tp_ratio_is_not_read_as_a_fixed_multiple():
    # "TP:3:1" parsed by the fixed-form regex would take "3" and leave ":1".
    p = _parse("20 T TP:3:1")
    # target = price + 3×(price − stop) = 110 + 3×(110−100) = 140 → (140−100)/10 = 4R
    assert p.tp_atr_mult == pytest.approx(4.0)


def test_gap_price_digits_are_not_read_as_the_stop():
    p = _parse("10 T G:85")
    assert p.gap_price == 85.0
    assert p.atr == 10.0
    assert p.stop_price == pytest.approx(110.0)   # 120 HWM − 10


# --------------------------------------------------------------------------
# Stop value forms
# --------------------------------------------------------------------------
def test_trailing_distance_measures_from_the_high_water_mark():
    p = _parse("10 T")
    assert p.base_price == 120.0        # max(entry, price, mark, hwm)
    assert p.stop_price == 110.0


def test_trailing_percent_is_a_fraction_of_the_base():
    p = _parse("15% T")
    assert p.atr == pytest.approx(18.0)          # 15% of 120
    assert p.stop_price == pytest.approx(102.0)


def test_at_price_converts_a_floor_to_a_distance():
    # "@100 T" means "put the trailing floor at 100", i.e. 20 below the 120 HWM.
    p = _parse("@100 T")
    assert p.atr == pytest.approx(20.0)
    assert p.stop_price == pytest.approx(100.0)


def test_dollar_prefix_is_cosmetic():
    assert _parse("$10 T").atr == _parse("10 T").atr


def test_fixed_value_is_the_literal_stop_price():
    p = _parse("95 F")
    assert p.atr == 95.0 and p.stop_price == 95.0
    assert p.base_price == 100.0                 # entry, not the HWM


def test_bare_value_keeps_the_stored_stop_type():
    assert _parse("12", stop_type="FIXED").stop_type == "FIXED"
    assert _parse("12", stop_type="TRAILING").stop_type == "TRAILING"


# --------------------------------------------------------------------------
# Presets and limits
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key,r,e", [("S", 0.30, 1.5), ("B", 0.60, 3.0), ("L", 1.00, 5.0)])
def test_presets_set_both_limits(key, r, e):
    p = _parse(f"10 T P:{key}")
    assert (p.max_r_pct, p.max_exp_pct, p.preset) == (r, e, key)


def test_explicit_limits_override_a_preset():
    # R:/E: are parsed after P:, so the explicit value wins regardless of order typed.
    p = _parse("10 T P:S R:0.9")
    assert p.max_r_pct == 0.9
    assert p.max_exp_pct == 1.5      # preset's exposure survives
    assert p.preset == "S"


# --------------------------------------------------------------------------
# Classification and the §0a coupling
# --------------------------------------------------------------------------
@pytest.mark.parametrize("token,expected", [
    ("C:TH", "THESIS"), ("C:THESIS", "THESIS"),
    ("C:TE", "TECHNICAL"), ("C:TECHNICAL", "TECHNICAL"),
    ("C:-", ""),
])
def test_classification_tokens(token, expected):
    assert _parse(f"10 T {token}").classification == expected


def test_untyped_classification_is_none_not_empty():
    # None means "preserve what is stored"; "" means "the user cleared it".
    assert _parse("10 T").classification is None
    assert _parse("10 T C:-").classification == ""


def test_thesis_tag_implies_the_thesis_exit_shape():
    p = _parse("10 T C:TH")
    assert p.exit_shape == "THESIS"
    assert any("thesis-exit shape applied" in n for n in p.notes)


def test_explicit_shape_overrides_the_thesis_coupling():
    p = _parse("10 T C:TH X:H")
    assert p.exit_shape == "HARD"
    assert p.notes == ()


def test_coupling_respects_a_stored_non_default_shape():
    p = _parse("10 T C:TH", stored_exit_shape="HARD")
    assert p.exit_shape is None      # leave the stored shape alone
    assert p.notes == ()


def test_technical_tag_does_not_touch_the_shape():
    assert _parse("10 T C:TE").exit_shape is None


# --------------------------------------------------------------------------
# Exit shapes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("token,expected", [
    ("X:H", "HARD"), ("X:HARD", "HARD"),
    ("X:T", "THESIS"), ("X:THESIS", "THESIS"),
    ("X:L", "LADDER"),
    ("X:R", "LADDER"),        # RUNNER is a legacy alias of the default ladder
    ("X:RUNNER", "LADDER"),
])
def test_exit_shape_tokens(token, expected):
    assert _parse(f"10 T {token}").exit_shape == expected


def test_exit_shape_clear_is_distinct_from_untyped():
    assert _parse("10 T X:-").exit_shape == ""     # explicit clear → default ladder
    assert _parse("10 T").exit_shape is None       # untyped → preserve stored


# --------------------------------------------------------------------------
# Take-profit resolution
# --------------------------------------------------------------------------
def test_tp_mult_forms():
    assert resolve_tp_mult("4", 100.0, 10.0) == (4.0, False, True)
    assert resolve_tp_mult("4R", 100.0, 10.0) == (4.0, False, True)
    assert resolve_tp_mult("+35%", 100.0, 10.0)[0] == pytest.approx(3.5)
    assert resolve_tp_mult("-", 100.0, 10.0) == (None, True, True)


def test_tp_mult_rejects_the_cut_dollar_form():
    mult, clear, ok = resolve_tp_mult("$60K", 100.0, 10.0)
    assert ok is False and mult is None


def test_tp_mult_needs_an_inception_atr():
    assert resolve_tp_mult("4R", 100.0, 0.0)[2] is False
    assert resolve_tp_mult("4R", 0.0, 10.0)[2] is False


def test_rejected_tp_warns_and_leaves_the_target_alone():
    p = _parse("10 T TP:$60K")
    assert p.tp_atr_mult is None
    assert any("TP target not resolved" in w for w in p.warnings)


def test_tp_clear_removes_a_saved_override():
    p = _parse("10 T TP:-", tp_atr_mult=5.0, tp_is_override=True)
    assert p.tp_atr_mult is None


def test_saved_override_survives_an_unrelated_edit():
    p = _parse("10 T", tp_atr_mult=5.0, tp_is_override=True)
    assert p.tp_atr_mult == 5.0


def test_tp_ratio_pays_n_to_one_from_the_current_price():
    # 3:1 from 110 against a 100 stop → target 140.
    mult, ok = resolve_tp_ratio(3.0, 100.0, 10.0, 110.0, 100.0)
    assert ok and mult == pytest.approx(4.0)


def test_tp_ratio_needs_price_above_the_stop():
    assert resolve_tp_ratio(3.0, 100.0, 10.0, 95.0, 100.0) == (None, False)
    assert resolve_tp_ratio(3.0, 100.0, 10.0, 100.0, 100.0) == (None, False)


def test_unresolvable_ratio_warns_rather_than_guessing():
    p = _parse("10 T TP:3:1")     # stop lands exactly on the price
    assert p.tp_atr_mult is None
    assert any("TP ratio needs the price above the stop" in w for w in p.warnings)


# --------------------------------------------------------------------------
# Quantity modeling
# --------------------------------------------------------------------------
def test_quantity_modeling_tokens():
    assert _parse("10 T +50").add == 50.0
    assert _parse("10 T -200").add == -200.0
    assert _parse("10 T BE").goal_seek == "BE"
    assert _parse("10 T").add is None and _parse("10 T").goal_seek is None


def test_be_does_not_eat_the_stop_value():
    p = _parse("10 T BE")
    assert p.atr == 10.0 and p.goal_seek == "BE"


# --------------------------------------------------------------------------
# Journal tags
# --------------------------------------------------------------------------
def test_source_and_theme_are_captured():
    p = _parse("10 T SRC:STANSBERRY THM:AI-INFRA")
    assert p.source == "STANSBERRY" and p.theme == "AI-INFRA"


def test_journal_tags_accept_punctuation():
    p = _parse("10 T SRC:MOTLEY.FOOL THM:S&P_500")
    assert p.source == "MOTLEY.FOOL" and p.theme == "S&P_500"


# --------------------------------------------------------------------------
# Inception-ATR snapping (the frozen R unit)
# --------------------------------------------------------------------------
def test_trailing_freezes_its_own_distance():
    assert _parse("10 T").inception_atr == 10.0


def test_fixed_snaps_to_the_nearest_trustworthy_timeframe():
    rows = (_Row("14d", 8.0), _Row("12w", 18.0), _Row("12m", 34.0))
    p = _parse("92 F", discovery_rows=rows)      # risk distance = 8
    assert p.inception_atr == 8.0
    assert p.notes == ()


def test_fixed_never_freezes_a_shrunken_window_atr():
    # A "12q" ATR computed from 3 quarterly bars is not a quarterly ATR; freezing
    # it would mis-scale that position's ladder for its whole life.
    rows = (_Row("14d", 8.0, shrunk=True), _Row("12q", 40.0, shrunk=True))
    p = _parse("92 F", discovery_rows=rows, inception_atr=11.0)
    assert p.inception_atr == 11.0               # keeps the stored value instead
    assert any("too thin for a trustworthy ATR snap" in n for n in p.notes)


def test_fixed_falls_back_to_the_risk_distance_when_nothing_is_trustworthy():
    rows = (_Row("14d", 8.0, shrunk=True),)
    p = _parse("92 F", discovery_rows=rows, inception_atr=None)
    assert p.inception_atr == pytest.approx(8.0)  # entry 100 − stop 92
    assert any("anchored to entry−stop" in n for n in p.notes)


def test_snap_note_names_the_timeframe_that_was_skipped():
    # The nearest row is shrunken, so the snap moves elsewhere — say so rather
    # than switching horizons silently.
    rows = (_Row("14d", 8.1, shrunk=True), _Row("12w", 9.0))
    p = _parse("92 F", discovery_rows=rows)
    assert p.inception_atr == 9.0
    assert any("14d ATR has too little history" in n for n in p.notes)


def test_inception_atr_is_never_none_for_fixed():
    # db.set_position_risk degrades a NULL inception to atr_value, which for FIXED
    # is the stop PRICE — a catastrophic R unit. Never return None.
    for kwargs in ({}, {"inception_atr": None}, {"discovery_rows": ()}):
        p = _parse("92 F", **kwargs)
        assert p.inception_atr is not None and p.inception_atr > 0


def test_resolve_inception_atr_is_directly_callable():
    ctx = _ctx(discovery_rows=(_Row("14d", 8.0),), ticker="X")
    atr, note = resolve_inception_atr("FIXED", 100.0, 92.0, 0.0, ctx)
    assert atr == 8.0 and note is None


# --------------------------------------------------------------------------
# Draft construction
# --------------------------------------------------------------------------
def test_untyped_tokens_preserve_the_stored_profile_values():
    ctx = _ctx(stored_classification="TECHNICAL", stored_exit_shape="HARD")
    draft = parse_command("10 T", ctx, PRESETS).to_draft("TST", ctx)
    assert draft["classification"] == "TECHNICAL"
    assert draft["exit_shape"] == "HARD"


def test_typed_tokens_replace_the_stored_values():
    ctx = _ctx(stored_classification="TECHNICAL", stored_exit_shape="HARD")
    draft = parse_command("10 T C:TH X:L", ctx, PRESETS).to_draft("TST", ctx)
    assert draft["classification"] == "THESIS"
    assert draft["exit_shape"] == "LADDER"


def test_explicit_clear_wins_over_a_stored_value():
    ctx = _ctx(stored_classification="THESIS")
    draft = parse_command("10 T C:-", ctx, PRESETS).to_draft("TST", ctx)
    assert draft["classification"] == ""


def test_draft_carries_every_field_the_commit_needs():
    ctx = _ctx()
    draft = parse_command("291.60 F P:B C:TE X:H TP:4R SRC:ZACKS THM:SEMIS G:250",
                          ctx, PRESETS).to_draft("TST", ctx)
    assert draft == {
        'atr': 291.60, 'type': 'FIXED', 'ticker': 'TST',
        'max_r_pct': 0.60, 'max_exp_pct': 3.0,
        'hypo_stop': 291.60, 'inception_atr': draft['inception_atr'],
        'profile': 'B', 'tp_atr_mult': 4.0,
        'hypo_add': None, 'goal_seek': None,
        'classification': 'TECHNICAL', 'gap_price': 250.0, 'exit_shape': 'HARD',
        'source': 'ZACKS', 'theme': 'SEMIS',
    }


# --------------------------------------------------------------------------
# Degenerate input
# --------------------------------------------------------------------------
@pytest.mark.parametrize("command", ["", "   ", None])
def test_empty_command_parses_to_nothing(command):
    assert parse_command(command, _ctx(), PRESETS) is None


def test_case_is_normalised():
    assert _parse("10 t c:th src:zacks").classification == "THESIS"
    assert _parse("10 t src:zacks").source == "ZACKS"


def test_parse_classification_leaves_an_unrelated_string_untouched():
    cls, rest = parse_classification("15 T P:L")
    assert cls is None and rest == "15 T P:L"
