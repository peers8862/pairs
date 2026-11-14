"""Bank reconciliation — CSV/OFX import + automatic statement matching (I69).

Design (owner-scoped full, 2026-11-14):
- Import stores statement lines in the YAML store,
  `statements/<slug>.yaml` (lib.yaml_store), one file per account (slug =
  slugified account path). Nothing is written to the journal by import:
  the books are written by pair commands, never by a bank file; matching
  only records which statement line corresponds to which journal posting.
- Idempotency has two layers: (1) a file's sha256 is recorded on import —
  re-importing the same file is a no-op ("already imported"); (2) a
  line-level dedup key (account, date, amount, description, fitid-or-'')
  skips lines already in the store, so overlapping statements do not
  duplicate. Known limit, documented: two genuinely identical same-day
  purchases with byte-identical descriptions (CSV, no FITID) dedup to
  one line.
- CSV column mapping is DECLARED, never guessed: a named mapping in
  config.yaml `statement_mappings:` (referenced with --mapping NAME), or
  --col-date/--col-desc/--col-amount (or --col-debit/--col-credit)
  flags on the command. date_format is declared in the mapping
  (default %Y-%m-%d). A missing column fails with a clear message and
  writes nothing.
- OFX is parsed with the standard library only: OFX 2.x XML via
  xml.etree.ElementTree, OFX 1.x SGML via a tag regex (leaf elements
  have no closing tags). No new runtime dependencies.
- Matching rules (deterministic, testable): a journal posting is a
  candidate for a statement line when the amount matches exactly (to
  the cent) and the dates are within the window (default +/-3 days,
  --window to override). Exactly one candidate -> matched. Several
  candidates -> the uniquely closest date wins, a tie on distance is
  ambiguous. None -> unmatched. Re-running match only touches lines
  still unmatched; matched lines keep their match.
- `pair account reconcile` is unchanged except for one read-only line:
  when a statement store exists for the account it prints the
  matched/unmatched/ambiguous counts after the balance comparison.
- Web UI is NOT in the item as written and was NOT built: CLI only.

Tests drive the CLI against a tmp entity dir (the
tests/test_asset_transfer pattern) — no real entity data is touched.
Requires hledger on PATH for the matching and reconcile assertions.
"""

import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

import lib.helpers as H
import lib.ui as UI
import lib.reconcile as R
import modules.account as A

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures"

SEED_JOURNAL = """2026-01-05 * Payroll
    Assets:Current:Chequing  CAD 1500.00
    Income:Salary  CAD -1500.00

2026-01-06 * Groceries
    Expenses:Operating:Supplies  CAD 84.30
    Assets:Current:Chequing  CAD -84.30

2026-01-07 * Internet
    Expenses:Operating:Telecom  CAD 59.99
    Assets:Current:Chequing  CAD -59.99

2026-01-09 * Internet
    Expenses:Operating:Telecom  CAD 59.99
    Assets:Current:Chequing  CAD -59.99

2026-02-03 * Transfer in
    Assets:Current:Savings  CAD 200.00
    Assets:Current:Chequing  CAD -200.00
"""

CHEQUING = "Assets:Current:Chequing"
SAVINGS = "Assets:Current:Savings"


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "get_entity_dir", lambda: tmp_path)
    cfg = {
        "pair": {"currency": "CAD"},
        "accounts": {"bank": CHEQUING},
        "statement_mappings": {
            "chequing-csv": {
                "date": "Date",
                "description": "Description",
                "amount": "Amount",
                "date_format": "%Y-%m-%d",
            },
        },
    }
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    journal = tmp_path / "entity.journal"
    journal.write_text(SEED_JOURNAL)
    # account.py imports get_entity_journal into its own namespace at
    # import time; patch that attribute (the UI-level patch does not
    # reach it once another test imported the module).
    monkeypatch.setattr(A, "get_entity_journal", lambda: journal)
    return tmp_path


def _lines(entity, account):
    from lib.yaml_store import load_entity
    store = load_entity("statements", R.account_slug(account))
    return store["lines"] if store else []


def _import(entity, path, account, *extra):
    A.cmd_import({}, [str(path), "--account", account, *extra])


# ─── CSV parsing (pure core) ────────────────────────────────────────────────

def test_csv_parses_quoted_commas_negatives_and_parens():
    text = (FIXTURES / "statement.csv").read_text()
    mapping = {"date": "Date", "description": "Description",
               "amount": "Amount", "date_format": "%Y-%m-%d"}
    lines = R.parse_csv_statement(text, mapping)
    assert len(lines) == 6
    assert lines[0] == {"date": "2026-01-05", "description": "PAYROLL ACME",
                        "amount": D("1500.00"), "fitid": None,
                        "source_file": ""}
    assert lines[1]["description"] == "SUPERMARKET, DOWNTOWN"
    assert lines[1]["amount"] == D("-84.30")
    assert lines[5]["amount"] == D("-25.00")  # (25.00) is accounting-negative


def test_csv_debit_credit_columns():
    text = ("Date,What,Out,In\n"
            "2026-01-05,SHOP,84.30,\n"
            "2026-01-06,CLIENT,,2500.00\n")
    mapping = {"date": "Date", "description": "What",
               "debit": "Out", "credit": "In", "date_format": "%Y-%m-%d"}
    lines = R.parse_csv_statement(text, mapping)
    assert [l["amount"] for l in lines] == [D("-84.30"), D("2500.00")]


def test_csv_declared_date_format():
    text = ("Date,Description,Amount\n05/01/2026,SHOP,10.00\n")
    mapping = {"date": "Date", "description": "Description",
               "amount": "Amount", "date_format": "%d/%m/%Y"}
    lines = R.parse_csv_statement(text, mapping)
    assert lines[0]["date"] == "2026-01-05"


def test_csv_missing_column_raises():
    text = "Date,Description\n2026-01-05,SHOP\n"
    mapping = {"date": "Date", "description": "Description",
               "amount": "Amount", "date_format": "%Y-%m-%d"}
    with pytest.raises(ValueError, match="Amount"):
        R.parse_csv_statement(text, mapping)


def test_csv_amount_and_debit_credit_together_raises():
    text = "Date,Description,Amount,Out\n2026-01-05,SHOP,10.00,5.00\n"
    mapping = {"date": "Date", "description": "Description",
               "amount": "Amount", "debit": "Out",
               "date_format": "%Y-%m-%d"}
    with pytest.raises(ValueError, match="amount"):
        R.parse_csv_statement(text, mapping)


# ─── OFX parsing (pure core) ────────────────────────────────────────────────

def test_ofx_sgml_parses_fitid_and_memo():
    text = (FIXTURES / "statement.ofx").read_text()
    lines = R.parse_ofx_statement(text)
    assert len(lines) == 2
    assert lines[0]["date"] == "2026-02-03"
    assert lines[0]["amount"] == D("200.00")
    assert lines[0]["fitid"] == "20260203001"
    assert "TRANSFER IN" in lines[0]["description"]
    assert "From chequing" in lines[0]["description"]
    assert lines[1]["amount"] == D("-25.50")
    assert lines[1]["description"] == "COFFEE SHOP"


def test_ofx_xml_parses():
    text = """<?xml version="1.0"?>
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20260301</DTPOSTED>
<TRNAMT>75.00</TRNAMT><FITID>X1</FITID><NAME>REFUND</NAME></STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
    lines = R.parse_ofx_statement(text)
    assert len(lines) == 1
    assert lines[0]["date"] == "2026-03-01"
    assert lines[0]["amount"] == D("75.00")
    assert lines[0]["fitid"] == "X1"


# ─── matching (pure core) ───────────────────────────────────────────────────

def _postings():
    return [
        {"date": "2026-01-05", "description": "Payroll",
         "amount": D("1500.00")},
        {"date": "2026-01-06", "description": "Groceries",
         "amount": D("-84.30")},
        {"date": "2026-01-07", "description": "Internet",
         "amount": D("-59.99")},
        {"date": "2026-01-09", "description": "Internet",
         "amount": D("-59.99")},
    ]


def _line(date, amount, description="X"):
    return {"date": date, "description": description,
            "amount": D(amount), "fitid": None, "source_file": ""}


def test_match_exact_and_window():
    # Within the window (2 days off) still matches.
    results = R.match_lines([_line("2026-01-07", "1500.00")],
                            _postings(), window_days=3)
    assert results[0]["status"] == "matched"
    assert results[0]["posting"]["date"] == "2026-01-05"


def test_match_outside_window_is_unmatched():
    # Same amount, 6 days off: the near-miss must NOT match.
    results = R.match_lines([_line("2026-01-12", "-84.30")],
                            _postings(), window_days=3)
    assert results[0]["status"] == "unmatched"


def test_match_tie_on_distance_is_ambiguous():
    # Two candidates equally close (Jan 7 and Jan 9 from Jan 8).
    results = R.match_lines([_line("2026-01-08", "-59.99")],
                            _postings(), window_days=3)
    assert results[0]["status"] == "ambiguous"
    assert len(results[0]["candidates"]) == 2


def test_match_unique_closest_wins():
    # Jan 7 is closer than Jan 9 from Jan 6: unique closest wins.
    results = R.match_lines([_line("2026-01-06", "-59.99")],
                            _postings(), window_days=3)
    assert results[0]["status"] == "matched"
    assert results[0]["posting"]["date"] == "2026-01-07"


def test_match_amount_must_be_exact():
    results = R.match_lines([_line("2026-01-05", "1500.01")],
                            _postings(), window_days=3)
    assert results[0]["status"] == "unmatched"


# ─── CLI: import ────────────────────────────────────────────────────────────

def test_import_csv_with_named_mapping(entity, capsys):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    lines = _lines(entity, CHEQUING)
    assert len(lines) == 6
    assert lines[0]["description"] == "PAYROLL ACME"
    assert lines[0]["amount"] == "1500.00"
    out = capsys.readouterr().out
    assert "6 lines" in out
    # Import does not touch the journal: no generated entries.
    assert not (entity / "generated").exists()


def test_import_csv_with_flag_mapping(entity):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--col-date", "Date", "--col-desc", "Description",
            "--col-amount", "Amount")
    assert len(_lines(entity, CHEQUING)) == 6


def test_import_twice_is_idempotent(entity, capsys):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    assert len(_lines(entity, CHEQUING)) == 6
    out = capsys.readouterr().out
    assert "Already imported" in out


def test_import_ofx(entity):
    _import(entity, FIXTURES / "statement.ofx", SAVINGS)
    lines = _lines(entity, SAVINGS)
    assert len(lines) == 2
    assert lines[0]["fitid"] == "20260203001"
    assert lines[0]["amount"] == "200.00"


def test_import_missing_file_and_bad_mapping_fail_cleanly(entity):
    with pytest.raises(SystemExit):
        _import(entity, entity / "nope.csv", CHEQUING,
                "--mapping", "chequing-csv")
    with pytest.raises(SystemExit):
        _import(entity, FIXTURES / "statement.csv", CHEQUING,
                "--mapping", "no-such-mapping")
    with pytest.raises(SystemExit):
        _import(entity, FIXTURES / "statement.csv", CHEQUING)
    assert _lines(entity, CHEQUING) == []
    assert not (entity / "generated").exists()


def test_import_unknown_extension_fails(entity):
    with pytest.raises(SystemExit):
        _import(entity, FIXTURES / "statement.csv", CHEQUING,
                "--mapping", "chequing-csv", "--format", "pdf")


# ─── CLI: match ─────────────────────────────────────────────────────────────

@needs_hledger
def test_match_reports_matched_ambiguous_unmatched(entity, capsys):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    A.cmd_match({}, [CHEQUING])
    out = capsys.readouterr().out
    assert "2 matched" in out
    assert "1 ambiguous" in out
    assert "3 unmatched" in out
    lines = _lines(entity, CHEQUING)
    by_desc = {l["description"]: l for l in lines}
    assert by_desc["PAYROLL ACME"]["matched"] is not None
    assert by_desc["PAYROLL ACME"]["matched"]["date"] == "2026-01-05"
    assert by_desc["CLIENT PAYMENT"]["matched"] is None
    assert by_desc["INTERNET PROVIDER"]["matched"] is None  # ambiguous
    assert by_desc["SUPERMARKET"]["matched"] is None  # near-miss, outside window


@needs_hledger
def test_match_twice_is_stable(entity, capsys):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    A.cmd_match({}, [CHEQUING])
    first = _lines(entity, CHEQUING)
    A.cmd_match({}, [CHEQUING])
    assert _lines(entity, CHEQUING) == first
    out = capsys.readouterr().out
    assert "2 matched" in out  # same counts on the second run


@needs_hledger
def test_match_ofx_lines(entity, capsys):
    _import(entity, FIXTURES / "statement.ofx", SAVINGS)
    A.cmd_match({}, [SAVINGS])
    out = capsys.readouterr().out
    assert "1 matched" in out
    assert "1 unmatched" in out


def test_match_no_statement_store_fails_cleanly(entity):
    with pytest.raises(SystemExit):
        A.cmd_match({}, [CHEQUING])


# ─── cmd_reconcile wiring ───────────────────────────────────────────────────

@needs_hledger
def test_reconcile_still_works_and_shows_statement_summary(
        entity, capsys, monkeypatch):
    _import(entity, FIXTURES / "statement.csv", CHEQUING,
            "--mapping", "chequing-csv")
    # Book balance: 1500 - 84.30 - 59.99 - 59.99 - 200 = 1095.72.
    inputs = iter(["1095.72", "", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    A.cmd_reconcile({}, [CHEQUING])
    out = capsys.readouterr().out
    assert "Reconciled. No discrepancy." in out
    assert "Statement lines:" in out
    assert "0 matched" in out and "6 unmatched" in out
