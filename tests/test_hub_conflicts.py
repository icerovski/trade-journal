"""Data-hub duplicate detection (sync_config).

The ledger is a live SQLite file in a synced OneDrive folder. Two machines writing
it does not raise — OneDrive silently writes a second database beside the first, and
nothing in the app reports which copy was opened. A forked ledger is therefore
indistinguishable from a healthy one at the point where it matters. These tests pin
the detector that closes that gap.

Real artifacts recovered from the hub on 2026-08-04 are used as fixtures, so the
patterns are the ones OneDrive actually produced, not invented ones.
"""

import pytest

import sync_config
from sync_config import (
    CANONICAL_HUB_FILES,
    check_data_hub,
    env_value,
    find_duplicate_hub_files,
)


# Exactly what was found in the hub (5 conflict logs + 1 conflict db + 1 backup).
REAL_HUB = [
    "trade_journal.db",
    "prices.db",
    "trade_journal.log",
    "trade_journal-LAPTOP-20V5N4Q9.db",
    "trade_journal-LAPTOP-20V5N4Q9.log",
    "trade_journal-LAPTOP-20V5N4Q9-2.log",
    "trade_journal-LAPTOP-20V5N4Q9-3.log",
    "trade_journal-LAPTOP-DH0IF9MG.log",
    "trade_journal-LAPTOP-DH0IF9MG-2.log",
    "trade_journal.backup_20260626_205655.db",
]


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def test_canonical_files_are_never_reported():
    assert find_duplicate_hub_files(CANONICAL_HUB_FILES) == {"conflict": [], "other": []}


def test_real_hub_snapshot_classified_correctly():
    found = find_duplicate_hub_files(REAL_HUB)
    assert found["conflict"] == [
        "trade_journal-LAPTOP-20V5N4Q9-2.log",
        "trade_journal-LAPTOP-20V5N4Q9-3.log",
        "trade_journal-LAPTOP-20V5N4Q9.db",
        "trade_journal-LAPTOP-20V5N4Q9.log",
        "trade_journal-LAPTOP-DH0IF9MG-2.log",
        "trade_journal-LAPTOP-DH0IF9MG.log",
    ]
    # A hand-made backup is an extra copy, but not a fork — it must not be
    # reported as a sync conflict or the warning becomes noise to ignore.
    assert found["other"] == ["trade_journal.backup_20260626_205655.db"]


@pytest.mark.parametrize("name", [
    "trade_journal-LAPTOP-20V5N4Q9.db",
    "trade_journal-DESKTOP-ABC123.db",
    "trade_journal (conflicted copy 2026-06-28).db",
    "trade_journal-PC-HOME-2.db",
    "prices-LAPTOP-20V5N4Q9.db",
    "trade_journal (2).db",
])
def test_conflict_naming_variants_detected(name):
    # OneDrive's naming differs by client and version; Dropbox differs again.
    assert name in find_duplicate_hub_files([name])["conflict"]


@pytest.mark.parametrize("name", [
    "trade_journal.backup_20260626_205655.db",
    "prices.backup.db",
])
def test_deliberate_backups_are_other_not_conflict(name):
    found = find_duplicate_hub_files([name])
    assert found["conflict"] == [] and found["other"] == [name]


@pytest.mark.parametrize("name", [
    "snapshots.json",
    "ticker_map.json",
    "notes.txt",
    "trades_ytd.csv",
    "some_other_thing.db",       # a database, but not one of ours
    "trade_journal_notes.txt",   # shares the stem, wrong extension
])
def test_unrelated_files_are_ignored(name):
    assert find_duplicate_hub_files([name]) == {"conflict": [], "other": []}


# --------------------------------------------------------------------------
# Filesystem scan + reporting
# --------------------------------------------------------------------------
def _hub(tmp_path, names):
    for n in names:
        (tmp_path / n).write_text("x")
    return tmp_path


def test_scan_warns_loudly_on_a_forked_ledger(tmp_path, capsys):
    found = check_data_hub(_hub(tmp_path, REAL_HUB))
    out = capsys.readouterr().out
    assert "SYNC CONFLICT" in out
    assert "trade_journal-LAPTOP-20V5N4Q9.db" in out
    assert "conflict-copy log file(s)" in out     # logs get one line, not six
    assert len(found["conflict"]) == 6


def test_scan_is_silent_on_a_clean_hub(tmp_path, capsys):
    found = check_data_hub(_hub(tmp_path, list(CANONICAL_HUB_FILES) + ["snapshots.json"]))
    assert capsys.readouterr().out == ""
    assert found == {"conflict": [], "other": []}


def test_a_backup_alone_does_not_warn(tmp_path, capsys):
    # Keeping a manual backup must not produce a scary message on every launch.
    found = check_data_hub(_hub(tmp_path, list(CANONICAL_HUB_FILES) + ["trade_journal.backup_20260626_205655.db"]))
    assert capsys.readouterr().out == ""
    assert found["other"] == ["trade_journal.backup_20260626_205655.db"]


def test_scan_never_deletes_anything(tmp_path):
    # Which copy is authoritative is a judgement call; guessing is how a ledger dies.
    hub = _hub(tmp_path, REAL_HUB)
    check_data_hub(hub)
    assert sorted(p.name for p in hub.iterdir()) == sorted(REAL_HUB)


def test_missing_hub_is_not_an_error(tmp_path):
    assert check_data_hub(tmp_path / "nope") == {"conflict": [], "other": []}


# --------------------------------------------------------------------------
# Stale DATA_PATH — the ghost hub
#
# `config.DATA_DIR` mkdirs its path, so a DATA_PATH naming a folder that has been
# renamed away is not an error: it is recreated, init_db fills it with empty
# tables, and the app runs normally against a book with no history. That happened
# in 2026-08. Nothing failed; the reports just went quiet.
# --------------------------------------------------------------------------
def test_a_hub_without_a_ledger_is_called_out(tmp_path, capsys):
    # check_data_hub runs BEFORE init_db, so this is the last moment the empty
    # book can still be questioned rather than explained afterwards.
    (tmp_path / "prices.db").write_text("x")
    check_data_hub(tmp_path)
    out = capsys.readouterr().out
    assert "NO LEDGER IN THE CONFIGURED DATA HUB" in out
    assert "DATA_PATH" in out
    assert str(tmp_path) in out              # name the path, so it can be checked


def test_a_hub_with_a_ledger_says_nothing(tmp_path, capsys):
    (tmp_path / "trade_journal.db").write_text("x")
    check_data_hub(tmp_path)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("text,expected", [
    ('DATA_PATH=C:\\Users\\U\\OneDrive\\Companies\\HTC_EOOD\\TradeJournalData',
     'C:\\Users\\U\\OneDrive\\Companies\\HTC_EOOD\\TradeJournalData'),
    ('DATA_PATH="C:\\a\\b"', 'C:\\a\\b'),
    ("DATA_PATH='C:\\a\\b'", 'C:\\a\\b'),
    ('  DATA_PATH = C:\\a\\b  ', 'C:\\a\\b'),
    ('DATA_PATH=C:\\a\\b\\', 'C:\\a\\b'),            # trailing separator is not a difference
    ('IBKR_TOKEN=abc\nDATA_PATH=C:\\a\\b\n', 'C:\\a\\b'),
    ('# DATA_PATH=C:\\old\nDATA_PATH=C:\\new', 'C:\\new'),   # a comment is not a value
    ('DATA_PATH=C:\\first\nDATA_PATH=C:\\last', 'C:\\last'),  # last wins, as dotenv does
    ('IBKR_TOKEN=abc', None),
    ('', None),
    ('DATA_PATH=', None),
    ('garbage without an equals sign', None),
])
def test_env_value_reads_data_path(text, expected):
    assert env_value(text) == expected


def _env_pair(tmp_path, local_text, remote_text):
    local, remote = tmp_path / ".env", tmp_path / "vault" / ".env"
    remote.parent.mkdir()
    local.write_text(local_text)
    remote.write_text(remote_text)
    return local, remote


def test_diverging_data_paths_are_reported_before_the_sync_picks_one(tmp_path, capsys):
    """THE OTHER-LAPTOP CASE. A machine that missed a path change still names the
    old hub; whichever .env is newer wins on mtime alone and can push the stale
    path back. Warn before that is decided silently."""
    local, remote = _env_pair(tmp_path, "DATA_PATH=C:\\OneDrive\\Accounts\\X",
                              "DATA_PATH=C:\\OneDrive\\Companies\\X")
    result = sync_config._warn_on_data_path_divergence(local, remote)

    out = capsys.readouterr().out
    assert "DIFFERENT DATA HUBS" in out
    assert "Accounts" in out and "Companies" in out    # both named, neither chosen
    assert result == ("C:\\OneDrive\\Accounts\\X", "C:\\OneDrive\\Companies\\X")


def test_matching_data_paths_are_silent(tmp_path, capsys):
    local, remote = _env_pair(tmp_path, "DATA_PATH=C:\\same\nIBKR_TOKEN=a",
                              "IBKR_TOKEN=b\nDATA_PATH=C:\\same")
    assert sync_config._warn_on_data_path_divergence(local, remote) is None
    assert capsys.readouterr().out == ""


def test_a_missing_data_path_on_either_side_is_not_a_divergence(tmp_path, capsys):
    # Only one side declaring a hub says nothing about the other being wrong.
    local, remote = _env_pair(tmp_path, "IBKR_TOKEN=a", "DATA_PATH=C:\\b")
    assert sync_config._warn_on_data_path_divergence(local, remote) is None
    assert capsys.readouterr().out == ""


def test_an_unreadable_env_never_breaks_startup(tmp_path, capsys):
    # This runs before anything else on launch; it must degrade, not raise.
    local, remote = _env_pair(tmp_path, "DATA_PATH=C:\\a", "DATA_PATH=C:\\b")
    remote.unlink()
    assert sync_config._warn_on_data_path_divergence(local, remote) is None
