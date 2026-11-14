"""Regression tests for two injection holes found by the pairs audit.

HOLE 1 (HIGH) — pricehist flag injection: POST /api/commodity stored
`source` / `fetch_pair` verbatim, and cmd_fetch / cmd_verify passed them
as positional argv to pricehist, so a stored `--output-file=/tmp/x`
became a flag. Fixed by validate_pricehist_arg (modules/market.py):
the same leading-dash rejection as _safe_query_terms, applied at
commodity-write time (web + CLI add/edit) and defensively where the argv
is built, so a value stored before the guard existed still cannot reach
pricehist. pricehist itself is not installed here, so these tests stop at
the guard / write boundary and never execute pricehist.

HOLE 2 (MEDIUM) — journal injection via newlines: format_entry,
format_commodity_entry and serialize_entry interpolated description,
account and tag values verbatim, so a newline in a description smuggled
extra postings — or a whole second transaction — into the journal file.
validate_entry does NOT catch this: an amount-less forged posting is
inferred by hledger and balances, and a forged transaction parses
cleanly (verified against hledger 1.52.1). Fixed by rejecting CR/LF in
every value the formatters interpolate, so every caller (web + CLI) is
covered at once. The web handlers turn the ValueError into a 400 and
write nothing.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import lib.helpers as helpers  # noqa: E402
import lib.journal as J  # noqa: E402
import modules.market as M  # noqa: E402
import modules.web as web  # noqa: E402
from lib.entry import serialize_entry  # noqa: E402
from lib.journal import format_commodity_entry, format_entry  # noqa: E402
from modules.market import _build_fetch_pair  # noqa: E402


def _validate_pricehist_arg(value, field):
    # Imported lazily: the validator does not exist until the fix lands,
    # and a module-level import would fail collection of the whole file.
    from modules.market import validate_pricehist_arg
    return validate_pricehist_arg(value, field)

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)


# ─── HOLE 1: pricehist flag injection ────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "--output-file=/tmp/x",
    "-f",
    "--",
    "--days=30",
    " --output-file=/tmp/x",          # leading whitespace, then a dash
    "AAPL\n--output-file=/tmp/x",     # newline smuggling a flag
    "yahoo\r\n--x",
])
def test_pricehist_arg_rejects_leading_dash(bad):
    with pytest.raises(ValueError):
        _validate_pricehist_arg(bad, "fetch_pair")
    with pytest.raises(ValueError):
        _validate_pricehist_arg(bad, "source")


@pytest.mark.parametrize("good", [
    "",               # empty means "default / fall back to the symbol"
    "yahoo", "yfinance", "bankofcanada", "ecb", "coinbasepro", "alphavantage",
    "SHOP.TO", "BTC-CAD", "AAPL",
])
def test_pricehist_arg_accepts_legitimate_values(good):
    _validate_pricehist_arg(good, "fetch_pair")  # must not raise
    _validate_pricehist_arg(good, "source")


def test_build_fetch_pair_returns_value_unchanged():
    assert _build_fetch_pair({"symbol": "BTC", "fetch_pair": "BTC-CAD"}) == "BTC-CAD"
    assert _build_fetch_pair({"symbol": "AAPL"}) == "AAPL"


@pytest.fixture()
def commodity_client(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        web, "load_config",
        lambda: {"pair": {"currency": "CAD"}, "market": {"commodities": []}})
    monkeypatch.setattr(helpers, "save_config", lambda config: saved.update(config))
    return TestClient(web.create_app()), saved


def test_commodity_write_rejects_leading_dash_fetch_pair(commodity_client):
    client, saved = commodity_client
    resp = client.post("/api/commodity", json={
        "symbol": "EVIL", "source": "yahoo", "fetch_pair": "--output-file=/tmp/x"})
    assert resp.status_code == 400
    assert saved == {}, "a rejected commodity must not be persisted"


def test_commodity_write_rejects_leading_dash_source(commodity_client):
    client, saved = commodity_client
    resp = client.post("/api/commodity", json={
        "symbol": "EVIL", "source": "--output-file=/tmp/x", "fetch_pair": "EVIL"})
    assert resp.status_code == 400
    assert saved == {}, "a rejected commodity must not be persisted"


def test_commodity_write_accepts_legitimate_pair(commodity_client):
    client, saved = commodity_client
    resp = client.post("/api/commodity", json={
        "symbol": "BTC", "source": "yahoo", "fetch_pair": "BTC-CAD"})
    assert resp.status_code == 200, resp.text
    assert saved["market"]["commodities"][0]["fetch_pair"] == "BTC-CAD"
    assert saved["market"]["commodities"][0]["source"] == "yahoo"


def test_save_commodities_refuses_unsafe_value(monkeypatch):
    """The save layer is the backstop: no writer may persist a bad value."""
    saved = {}
    monkeypatch.setattr(M, "load_config", lambda: {"market": {"commodities": []}})
    monkeypatch.setattr(M, "save_config", lambda config: saved.update(config))
    with pytest.raises(ValueError):
        M._save_commodities([{"symbol": "EVIL", "source": "yahoo",
                              "fetch_pair": "--output-file=/tmp/x"}])
    assert saved == {}


def _boom(*args, **kwargs):
    raise AssertionError("pricehist must never be invoked for an unsafe commodity")


def test_fetch_skips_unsafe_commodity_without_running_pricehist(
        tmp_path, monkeypatch, capsys):
    """A value stored before the guard existed still cannot reach argv."""
    monkeypatch.setattr(M, "_pricehist_available", lambda: True)
    monkeypatch.setattr(M, "_get_commodities", lambda: [
        {"symbol": "EVIL", "source": "--output-file=/tmp/x", "fetch_pair": "AAPL"}])
    monkeypatch.setattr(M, "_ensure_prices_journal",
                        lambda: tmp_path / "prices.journal")
    monkeypatch.setattr(subprocess, "run", _boom)
    M.cmd_fetch({}, [])
    out = capsys.readouterr().out
    assert "EVIL" in out
    assert "skip" in out.lower()


def test_verify_skips_unsafe_commodity_without_running_pricehist(
        monkeypatch, capsys):
    monkeypatch.setattr(M, "_pricehist_available", lambda: True)
    monkeypatch.setattr(M, "_get_commodities", lambda: [
        {"symbol": "EVIL", "source": "yahoo", "fetch_pair": "--output-file=/tmp/x"}])
    monkeypatch.setattr(subprocess, "run", _boom)
    M.cmd_verify({}, [])
    out = capsys.readouterr().out
    assert "EVIL" in out
    assert "skip" in out.lower()


# ─── HOLE 2: journal injection via newlines ──────────────────────────────────

POSTINGS = [
    ("Assets:Current:Chequing", "CAD", -50.0),
    ("Expenses:Operating:Supplies", "CAD", 50.0),
]


def test_format_entry_rejects_newline_in_description():
    with pytest.raises(ValueError):
        format_entry("2026-01-05", "Lunch\n    Assets:Cash", POSTINGS)


def test_format_entry_rejects_forged_transaction():
    with pytest.raises(ValueError):
        format_entry("2026-01-05",
                     "Lunch\n2026-01-06 * Forged\n"
                     "    Expenses:Fake  999.00\n    Assets:Cash",
                     POSTINGS)


def test_format_entry_rejects_carriage_return_in_description():
    with pytest.raises(ValueError):
        format_entry("2026-01-05", "Lunch\r\n    Assets:Cash", POSTINGS)


def test_format_entry_rejects_newline_in_account():
    with pytest.raises(ValueError):
        format_entry("2026-01-05", "Lunch", [
            ("Assets:Current:Chequing\n    Expenses:Fake  1.00", "CAD", -50.0),
            ("Expenses:Operating:Supplies", "CAD", 50.0),
        ])


def test_format_entry_rejects_newline_in_tag_value():
    with pytest.raises(ValueError):
        format_entry("2026-01-05", "Lunch", POSTINGS,
                     {"pair": "1\n    Assets:Cash"})


def test_format_entry_still_formats_normal_entry():
    entry = format_entry("2026-01-05", "Lunch", POSTINGS, {"pair": "1"})
    assert entry.startswith("2026-01-05 * Lunch")
    assert "Assets:Current:Chequing" in entry


def test_format_commodity_entry_rejects_newline_in_description():
    with pytest.raises(ValueError):
        format_commodity_entry(
            "2026-07-20", "Buy TSLA\n    Assets:Cash",
            ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
            [("Assets:Current:Business Chequing", "CAD", -5101.44)],
            {"pair": "1011"})


def test_format_commodity_entry_rejects_newline_in_symbol():
    with pytest.raises(ValueError):
        format_commodity_entry(
            "2026-07-20", "Buy TSLA",
            ("Assets:Investments:Taxable:TSLA", 10, "TSLA\n    Assets:Cash",
             "CAD", 5101.44),
            [("Assets:Current:Business Chequing", "CAD", -5101.44)],
            {"pair": "1011"})


def test_format_commodity_entry_still_formats_normal_entry():
    entry = format_commodity_entry(
        "2026-07-20", "Buy TSLA | 10 sh",
        ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
        [("Assets:Current:Business Chequing", "CAD", -5101.44)],
        {"pair": "1011"},
    )
    assert "10 TSLA @@ CAD 5101.44" in entry


def _fields(**over):
    fields = {
        "date": "2026-01-05",
        "description": "Lunch",
        "postings": [
            {"account": "Assets:Current:Chequing", "amount": "-50.00"},
            {"account": "Expenses:Operating:Supplies", "amount": "50.00"},
        ],
    }
    fields.update(over)
    return fields


def test_serialize_entry_rejects_newline_in_description():
    with pytest.raises(ValueError):
        serialize_entry(_fields(description="Lunch\n    Assets:Cash"))


def test_serialize_entry_rejects_newline_in_note():
    with pytest.raises(ValueError):
        serialize_entry(_fields(payee="Cafe", note="x\n    Assets:Cash"))


def test_serialize_entry_rejects_newline_in_posting_comment():
    with pytest.raises(ValueError):
        serialize_entry(_fields(postings=[
            {"account": "Assets:Current:Chequing", "amount": "-50.00",
             "comment": "ok\n    Assets:Cash"},
            {"account": "Expenses:Operating:Supplies", "amount": "50.00"},
        ]))


def test_serialize_entry_rejects_newline_in_account():
    with pytest.raises(ValueError):
        serialize_entry(_fields(postings=[
            {"account": "Assets:Current:Chequing\n    Assets:Cash",
             "amount": "-50.00"},
            {"account": "Expenses:Operating:Supplies", "amount": "50.00"},
        ]))


def test_serialize_entry_still_serializes_normal_entry():
    text = serialize_entry(_fields())
    # No '*' marker: serialize_entry only adds one when status is '!' or '*'.
    assert text.startswith("2026-01-05 Lunch")
    assert "Assets:Current:Chequing" in text


# ─── HOLE 2 through the web handlers ─────────────────────────────────────────

@pytest.fixture()
def entry_client(tmp_path, monkeypatch):
    gen = tmp_path / "generated"
    inc = tmp_path / "include"
    gen.mkdir()
    inc.mkdir()
    monkeypatch.setattr(web, "load_config", lambda: {"pair": {"currency": "CAD"}})
    monkeypatch.setattr(web, "get_generated_dir", lambda: gen)
    monkeypatch.setattr(
        web, "ensure_year_structure",
        lambda year: (gen / str(year)).mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(J, "get_include_dir", lambda: inc)
    return TestClient(web.create_app()), gen


ENTRY = {
    "expr": "<",
    "first_account": "Assets:Current:Chequing",
    "second_account": "Expenses:Operating:Supplies",
    "amount": 50,
    "entry_date": "2026-01-05",
}

TRANSFER = {
    "amount": 25,
    "from_account": "Assets:Current:Chequing",
    "to_account": "Assets:Current:Savings",
    "date": "2026-01-05",
}


def test_entry_rejects_forged_posting(entry_client):
    client, gen = entry_client
    resp = client.post("/api/entry", json={
        **ENTRY, "description": "Lunch\n    Assets:Cash"})
    assert resp.status_code == 400
    journal = gen / "2026" / "links.journal"
    assert not journal.exists() or "Assets:Cash" not in journal.read_text()


def test_entry_rejects_forged_transaction(entry_client):
    client, gen = entry_client
    resp = client.post("/api/entry", json={
        **ENTRY,
        "description": "Lunch\n2026-01-06 * Forged\n"
                       "    Expenses:Fake  999.00\n    Assets:Cash"})
    assert resp.status_code == 400
    journal = gen / "2026" / "links.journal"
    assert not journal.exists() or "Forged" not in journal.read_text()


def test_entry_still_writes_normal_entry(entry_client):
    client, gen = entry_client
    resp = client.post("/api/entry", json={**ENTRY, "description": "Lunch"})
    assert resp.status_code == 200, resp.text
    text = (gen / "2026" / "links.journal").read_text()
    assert "Lunch" in text
    assert "Expenses:Operating:Supplies" in text


@needs_hledger
def test_entry_written_journal_parses(entry_client):
    client, gen = entry_client
    resp = client.post("/api/entry", json={**ENTRY, "description": "Lunch"})
    assert resp.status_code == 200, resp.text
    journal = gen / "2026" / "links.journal"
    result = subprocess.run(
        ["hledger", "-f", str(journal), "print"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Lunch" in result.stdout


def test_transfer_rejects_forged_posting(entry_client):
    client, gen = entry_client
    resp = client.post("/api/transfer", json={
        **TRANSFER, "description": "Move\n    Expenses:Fake  999.00"})
    assert resp.status_code == 400
    journal = gen / "2026" / "transfers.journal"
    assert not journal.exists() or "Expenses:Fake" not in journal.read_text()


def test_transfer_still_writes_normal_entry(entry_client):
    client, gen = entry_client
    resp = client.post("/api/transfer", json={
        **TRANSFER, "description": "Move to savings"})
    assert resp.status_code == 200, resp.text
    text = (gen / "2026" / "transfers.journal").read_text()
    assert "Move to savings" in text
    assert "Assets:Current:Savings" in text


# ─── RAW MODE DATE CHECK (D19) ───────────────────────────────────────────────
# Raw mode writes hand-edited text as-is, and record_entry files it by the
# DATE FIELD while hledger reads the date from the TEXT — so a 2022-dated
# entry typed today used to land in generated/2026/entries.journal but
# count as 2022. The write path now rejects any raw transaction whose
# date differs from the entry date (400, nothing written). validate_entry
# cannot do this job: it only proves hledger parses the text.

RAW_OK = """2026-01-06 * Raw lunch
    Assets:Current:Chequing  -50.00
    Expenses:Operating:Supplies  50.00
"""

RAW_OLD = """2022-03-04 * Raw lunch
    Assets:Current:Chequing  -50.00
    Expenses:Operating:Supplies  50.00
"""

RAW_TWO_MIXED = """2026-01-06 * First
    Assets:Current:Chequing  -50.00
    Expenses:Operating:Supplies  50.00

2022-03-04 * Second
    Assets:Current:Chequing  -10.00
    Expenses:Operating:Supplies  10.00
"""


@pytest.fixture()
def advanced_client(tmp_path, monkeypatch):
    import lib.entry as E
    gen = tmp_path / "generated"
    gen.mkdir()
    monkeypatch.setattr(web, "load_config", lambda: {"pair": {"currency": "CAD"}})
    # record_entry resolves these in lib.entry's namespace (patch where
    # looked up); the include wiring is a no-op in the fixture.
    monkeypatch.setattr(E, "get_generated_dir", lambda: gen)
    monkeypatch.setattr(
        E, "ensure_year_structure",
        lambda year: (gen / str(year)).mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(E, "ensure_generated_include", lambda year, name: None)
    return TestClient(web.create_app()), gen


def _all_written_text(gen):
    return "".join(p.read_text() for p in gen.rglob("*.journal"))


def test_raw_rejects_mismatched_date(advanced_client):
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True, "journal_text": RAW_OLD})
    assert resp.status_code == 400, resp.text
    assert "2022-03-04" not in _all_written_text(gen)
    assert "Raw lunch" not in _all_written_text(gen)


def test_raw_rejects_second_transaction_with_mismatched_date(advanced_client):
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True, "journal_text": RAW_TWO_MIXED})
    assert resp.status_code == 400, resp.text
    assert "Second" not in _all_written_text(gen)
    assert "First" not in _all_written_text(gen)


@needs_hledger
def test_raw_matching_date_still_writes(advanced_client):
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True, "journal_text": RAW_OK})
    assert resp.status_code == 200, resp.text
    text = (gen / "2026" / "entries.journal").read_text()
    assert "Raw lunch" in text
    assert "mode:advanced" in text


@needs_hledger
def test_raw_written_journal_parses(advanced_client):
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True, "journal_text": RAW_OK})
    assert resp.status_code == 200, resp.text
    journal = gen / "2026" / "entries.journal"
    result = subprocess.run(
        ["hledger", "-f", str(journal), "print"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "2026-01-06" in result.stdout
    assert "2022" not in result.stdout


def test_raw_rejects_slash_date_bypass(advanced_client):
    # hledger also accepts 2022/03/04 as a date; a separator change must
    # not slip past the check.
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True,
        "journal_text": RAW_OLD.replace("2022-03-04", "2022/03/04")})
    assert resp.status_code == 400, resp.text
    assert "Raw lunch" not in _all_written_text(gen)


def test_raw_rejects_mismatched_secondary_date(advanced_client):
    client, gen = advanced_client
    resp = client.post("/api/entry/advanced", json={
        "date": "2026-01-06", "raw": True,
        "journal_text": RAW_OK.replace(
            "2026-01-06 *", "2026-01-06=2022-03-04 *")})
    assert resp.status_code == 400, resp.text
    assert "Raw lunch" not in _all_written_text(gen)


def test_raw_transaction_dates_helper():
    from modules.web import _raw_transaction_dates
    assert _raw_transaction_dates(RAW_OK) == ["2026-01-06"]
    assert _raw_transaction_dates(RAW_TWO_MIXED) == ["2026-01-06", "2022-03-04"]
    # Status, code, secondary date, comments and directives are not dates.
    assert _raw_transaction_dates(
        "2026-01-06 * (42) Titled\n"
        "    Assets:Current:Chequing  -50.00\n"
        "    Expenses:Operating:Supplies  50.00\n") == ["2026-01-06"]
    assert _raw_transaction_dates(
        "2026-01-06=2026-01-05 * Dated\n"
        "    Assets:Current:Chequing  -50.00\n"
        "    Expenses:Operating:Supplies  50.00\n") == ["2026-01-06", "2026-01-05"]
    assert _raw_transaction_dates(
        "; 2022-03-04 in a comment is not a transaction\n"
        "Y2026\n"
        "2026-01-06 * Real\n"
        "    Assets:Current:Chequing  -50.00\n"
        "    Expenses:Operating:Supplies  50.00\n") == ["2026-01-06"]
    assert _raw_transaction_dates("") == []
    assert _raw_transaction_dates("not a journal at all\n") == []
