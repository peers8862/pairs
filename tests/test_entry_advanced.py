"""CLI `pair entry --advanced` tests (I59).

The --advanced path lives in modules/pairs.py: `dispatch_pair` routes
`pair entry --advanced` / `-a` to `cmd_pair_advanced` — a fully interactive
prompt-driven entry using the full journal grammar (N postings, costs,
assertions, tags), sharing lib.entry with the web /api/entry/advanced
overlay, so serialisation, pair inference and hledger validation behave
identically in both. Only lib.entry serialisation was covered before this
file; nothing exercised the CLI layer itself.

Conventions follow tests/test_trade_hardening.py (I58): bad input fails
with a clear message to stdout + exit 1, no traceback, and nothing is
written. A user declining the final confirm is a cancellation, not a
failure, and exits 0. Tests drive the prompts via monkeypatched
builtins.input (the established pattern in tests/test_last_division.py)
and point all paths at a tmp entity dir — no real entity data is touched.

Requires hledger on PATH (validate_entry pipes to `hledger -f- print -x`
and pair inference runs `hledger accounts --types`); skipped otherwise.
"""

import re
import shutil
import subprocess

import pytest

import lib.helpers as H
import lib.ui as UI
from modules.pairs import cmd_pair_advanced, dispatch_pair

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

SEED_JOURNAL = """2026-01-05 * Seed
    Expenses:Operating:Supplies    CAD 1.00
    Assets:Current:Chequing        CAD -1.00

2026-01-05 * Other seed
    Revenue:Consulting    CAD -2.00
    Assets:Current:Chequing        CAD 2.00
"""

# Seed journal whose accounts do NOT include the posting accounts below,
# so pair inference finds no type for them.
OTHER_JOURNAL = """2026-01-05 * Seed
    Expenses:Operating:Travel    CAD 1.00
    Assets:Current:Savings        CAD -1.00
"""


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "get_entity_dir", lambda: tmp_path)
    journal = tmp_path / "company.journal"
    journal.write_text(SEED_JOURNAL)
    # cmd_pair_advanced imports get_entity_journal from lib.ui at call
    # time, so patching the lib.ui attribute is what takes effect.
    monkeypatch.setattr(UI, "get_entity_journal", lambda: journal)
    return tmp_path


def _inputs(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def _happy_inputs(monkeypatch, *, date="2026-11-13", confirm="y",
                  pair_override="", amount2=""):
    """Full prompt flow for a 2-posting Supplies/Chequing entry.

    Date, status, code, payee, note, tags, posting 1 (account, amount,
    cost, assertion), posting 2, blank account to finish, pair override,
    confirm. The second amount defaults to blank (hledger infers it).
    """
    _inputs(monkeypatch, [
        date, "", "", "Test purchase", "", "",
        "Expenses:Operating:Supplies", "100", "", "",
        "Assets:Current:Chequing", amount2, "", "",
        "", pair_override, confirm,
    ])


def _entries_text(entity):
    path = entity / "generated" / "2026" / "entries.journal"
    return path.read_text() if path.exists() else None


# ─── happy path ─────────────────────────────────────────────────────────────

@needs_hledger
def test_advanced_happy_path_writes_entry(entity, monkeypatch):
    _happy_inputs(monkeypatch)
    cmd_pair_advanced([])
    text = _entries_text(entity)
    assert text is not None
    assert "2026-11-13 Test purchase" in text
    assert "Expenses:Operating:Supplies" in text
    # The amount is written exactly as typed (bare '100', no currency).
    assert re.search(r"Expenses:Operating:Supplies\s+100\n", text)
    assert "mode:advanced" in text
    assert "pair:0000" in text  # X + A, operating expense -> 0000
    # The year aggregator includes the new journal (not orphaned).
    assert "include ../generated/2026/entries.journal" in (
        entity / "include" / "2026.journal").read_text()


@needs_hledger
def test_advanced_written_entry_balances_in_hledger(entity, monkeypatch):
    """The written file parses and balances; the blank 2nd amount infers."""
    _happy_inputs(monkeypatch)
    cmd_pair_advanced([])
    path = entity / "generated" / "2026" / "entries.journal"
    r = subprocess.run(["hledger", "-f", str(path), "bal"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "Expenses:Operating:Supplies" in r.stdout
    assert "Assets:Current:Chequing" in r.stdout
    rendered = subprocess.run(["hledger", "-f", str(path), "print", "-x"],
                              capture_output=True, text=True, timeout=30)
    assert "-100" in rendered.stdout  # inferred balancing amount


@needs_hledger
def test_advanced_cost_written(entity, monkeypatch):
    """The cost (@) prompt branch is exercised; the other posting infers."""
    _inputs(monkeypatch, [
        "2026-11-13", "", "", "Priced purchase", "", "",
        "Expenses:Operating:Supplies", "100", "CAD 90.00", "", "",
        "Assets:Current:Chequing", "", "", "",
        "", "", "y",
    ])
    cmd_pair_advanced([])
    text = _entries_text(entity)
    assert text is not None
    assert "@ CAD 90.00" in text


@needs_hledger
def test_advanced_assertion_written(entity, monkeypatch):
    """The balance-assertion (=) prompt branch is exercised.

    validate_entry checks the assertion against the entry alone, so it
    must match the isolated balance — and the amount needs its currency,
    or the CAD balance is 0 and the assertion fails. +CAD 100 to
    Supplies is a CAD 100.00 balance.
    """
    _inputs(monkeypatch, [
        "2026-11-13", "", "", "Asserted purchase", "", "",
        "Expenses:Operating:Supplies", "CAD 100", "", "CAD 100.00", "",
        "Assets:Current:Chequing", "", "", "",
        "", "", "y",
    ])
    cmd_pair_advanced([])
    text = _entries_text(entity)
    assert text is not None
    assert "= CAD 100.00" in text


# ─── pair inference ─────────────────────────────────────────────────────────

@needs_hledger
def test_advanced_pair_override_dash_writes_without_pair_tag(
        entity, monkeypatch, capsys):
    _happy_inputs(monkeypatch, pair_override="-")
    cmd_pair_advanced([])
    text = _entries_text(entity)
    assert text is not None
    assert "mode:advanced" in text
    assert "pair:" not in text
    assert "Inferred pair: 0000" in capsys.readouterr().out


@needs_hledger
def test_advanced_unknown_account_writes_without_pair_tag(
        entity, monkeypatch, capsys):
    """Accounts absent from the books: inference unavailable, entry still
    writes with mode:advanced only (no pair tag, no pair prompt)."""
    (entity / "company.journal").write_text(OTHER_JOURNAL)
    _inputs(monkeypatch, [
        "2026-11-13", "", "", "Test purchase", "", "",
        "Expenses:Operating:Supplies", "100", "", "",
        "Assets:Current:Chequing", "", "", "",
        "", "y",
    ])
    cmd_pair_advanced([])
    out = capsys.readouterr().out
    assert "Pair inference unavailable" in out
    assert "unknown account type" in out
    text = _entries_text(entity)
    assert text is not None
    assert "mode:advanced" in text
    assert "pair:" not in text


@needs_hledger
def test_advanced_three_postings_write(entity, monkeypatch):
    """N postings: a 3-posting entry writes (pair inference is compound)."""
    _inputs(monkeypatch, [
        "2026-11-13", "", "", "Split purchase", "", "",
        "Expenses:Operating:Supplies", "60", "", "",
        "Expenses:Operating:Travel", "40", "", "",
        "Assets:Current:Chequing", "", "", "",
        "", "", "y",
    ])
    cmd_pair_advanced([])
    text = _entries_text(entity)
    assert text is not None
    assert "Split purchase" in text
    assert "mode:advanced" in text


# ─── failure paths: clear message + exit 1, nothing written ────────────────

@needs_hledger
def test_advanced_fewer_than_two_postings_exits_1(
        entity, monkeypatch, capsys):
    _inputs(monkeypatch, [
        "2026-11-13", "", "", "Lonely posting", "", "",
        "Expenses:Operating:Supplies", "100", "", "",
        "",
    ])
    with pytest.raises(SystemExit):
        cmd_pair_advanced([])
    assert "Need at least two postings" in capsys.readouterr().out
    assert not (entity / "generated").exists()


@needs_hledger
def test_advanced_unbalanced_entry_exits_1(entity, monkeypatch, capsys):
    """Two explicit amounts that do not balance: hledger rejects it."""
    _happy_inputs(monkeypatch, amount2="50")
    with pytest.raises(SystemExit):
        cmd_pair_advanced([])
    assert "hledger rejected this entry" in capsys.readouterr().out
    assert not (entity / "generated").exists()


@needs_hledger
def test_advanced_bad_date_exits_1(entity, monkeypatch, capsys):
    _happy_inputs(monkeypatch, date="2026-13-45")
    with pytest.raises(SystemExit):
        cmd_pair_advanced([])
    assert "hledger rejected this entry" in capsys.readouterr().out
    assert not (entity / "generated").exists()


# ─── user cancellation: exit 0, nothing written ─────────────────────────────

@needs_hledger
def test_advanced_decline_writes_nothing(entity, monkeypatch, capsys):
    _happy_inputs(monkeypatch, confirm="n")
    cmd_pair_advanced([])  # no SystemExit: a decline is not a failure
    assert "Cancelled" in capsys.readouterr().out
    assert not (entity / "generated").exists()


# ─── dispatch: --advanced / -a routing ──────────────────────────────────────

@needs_hledger
@pytest.mark.parametrize("flag", ["--advanced", "-a"])
def test_dispatch_pair_advanced_flag_routes(entity, monkeypatch, flag):
    _happy_inputs(monkeypatch)
    dispatch_pair([flag])
    assert _entries_text(entity) is not None
