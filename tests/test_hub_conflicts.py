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

from sync_config import CANONICAL_HUB_FILES, check_data_hub, find_duplicate_hub_files


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
