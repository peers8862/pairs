import shutil
import subprocess

import pytest

from lib.journal import format_quantity, format_commodity_entry


def test_whole_number_has_no_decimals():
    assert format_quantity(10) == "10"


def test_crypto_precision_survives():
    assert format_quantity(0.00431) == "0.00431"


def test_trailing_zeros_stripped():
    assert format_quantity(2.50000000) == "2.5"


def test_eight_decimal_places_preserved():
    assert format_quantity(0.12345678) == "0.12345678"


def test_negative_quantity():
    assert format_quantity(-6) == "-6"


def test_buy_entry_uses_double_at_syntax():
    entry = format_commodity_entry(
        "2026-07-20", "Buy TSLA | 10 sh",
        ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
        [("Assets:Current:Business Chequing", "CAD", -5101.44)],
        {"pair": "1011", "price": "372.73", "fee": "9.95"},
    )
    assert "10 TSLA @@ CAD 5101.44" in entry
    assert "CAD -5101.44" in entry
    assert "; pair:1011, price:372.73, fee:9.95" in entry
    assert entry.startswith("2026-07-20 * Buy TSLA | 10 sh")


def test_sell_entry_has_negative_quantity():
    entry = format_commodity_entry(
        "2026-07-25", "Sell TSLA | 6 sh",
        ("Assets:Investments:Taxable:TSLA", -6, "TSLA", "CAD", 3060.86),
        [("Assets:Current:Business Chequing", "CAD", 3510.05),
         ("Income:Non-Operating:Capital Gains", "CAD", -449.19)],
        {"pair": "0110"},
    )
    assert "-6 TSLA @@ CAD 3060.86" in entry
    assert "CAD 3510.05" in entry
    assert "CAD -449.19" in entry


def test_crypto_quantity_not_rounded():
    entry = format_commodity_entry(
        "2026-07-20", "Buy BTC",
        ("Assets:Investments:TFSA:BTC", 0.00431, "BTC", "CAD", 396.50),
        [("Assets:Current:Business Chequing", "CAD", -396.50)],
    )
    assert "0.00431 BTC @@ CAD 396.50" in entry
    assert "0.00 BTC" not in entry


def test_entry_ends_with_blank_line():
    entry = format_commodity_entry(
        "2026-07-20", "Buy TSLA",
        ("Assets:Investments:Taxable:TSLA", 1, "TSLA", "CAD", 510.14),
        [("Assets:Current:Business Chequing", "CAD", -510.14)],
    )
    assert entry.endswith("\n\n")


@pytest.mark.skipif(shutil.which("hledger") is None, reason="hledger not installed")
def test_hledger_parses_generated_entries(tmp_path):
    """Real hledger must accept our lot syntax, not just our own assertions."""
    buy = format_commodity_entry(
        "2026-07-20", "Buy TSLA | 10 sh",
        ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
        [("Assets:Current:Business Chequing", "CAD", -5101.44)],
        {"pair": "1011"},
    )
    sell = format_commodity_entry(
        "2026-07-25", "Sell TSLA | 6 sh",
        ("Assets:Investments:Taxable:TSLA", -6, "TSLA", "CAD", 3060.86),
        [("Assets:Current:Business Chequing", "CAD", 3510.05),
         ("Income:Non-Operating:Capital Gains", "CAD", -449.19)],
        {"pair": "0110"},
    )
    journal = tmp_path / "test.journal"
    journal.write_text(buy + sell)

    result = subprocess.run(
        ["hledger", "-f", str(journal), "print"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "TSLA" in result.stdout


# ─── ensure_generated_include ────────────────────────────────────────────────
# Regression: investment entries were written to generated/<year>/investments.journal
# but never included in the year aggregator, so hledger never saw them (holdings
# read as zero). ensure_generated_include wires the include line in.

def _write_aggregator(tmp_path, lines):
    inc = tmp_path / "include"
    inc.mkdir()
    year_file = inc / "2026.journal"
    year_file.write_text(lines)
    return inc, year_file


def test_ensure_generated_include_appends_missing(tmp_path, monkeypatch):
    import lib.journal as J
    inc, year_file = _write_aggregator(tmp_path, "include ../generated/2026/assets.journal\n")
    monkeypatch.setattr(J, "get_include_dir", lambda: inc)
    J.ensure_generated_include("2026", "investments.journal")
    assert "include ../generated/2026/investments.journal" in year_file.read_text()


def test_ensure_generated_include_is_idempotent(tmp_path, monkeypatch):
    import lib.journal as J
    inc, year_file = _write_aggregator(tmp_path, "include ../generated/2026/investments.journal\n")
    monkeypatch.setattr(J, "get_include_dir", lambda: inc)
    J.ensure_generated_include("2026", "investments.journal")
    assert year_file.read_text().count("investments.journal") == 1


def test_ensure_generated_include_noop_when_aggregator_absent(tmp_path, monkeypatch):
    import lib.journal as J
    inc = tmp_path / "include"
    inc.mkdir()
    monkeypatch.setattr(J, "get_include_dir", lambda: inc)
    J.ensure_generated_include("2026", "investments.journal")  # must not raise
    assert not (inc / "2026.journal").exists()
