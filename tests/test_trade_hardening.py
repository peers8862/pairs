"""CLI trade hardening (I60–I62) — command-layer and web tests.

Builder-level tests for the same items live in
tests/test_investment_commands.py. These tests drive `cmd_buy` / `cmd_sell`
and POST /api/market/buy|sell with bad flags, and prove three things the
builders alone cannot: the error is reported gracefully (a clear message, no
traceback), the process fails non-zero (SystemExit(1) on the CLI, HTTP 400
on the web), and nothing is written.

Conventions under test (established repo pattern, verified before writing):
- Fatal CLI user errors print "  <message>" to stdout and exit 1
  (pair main, modules/market dispatch, modules/asset sys.exit(1) sites).
  cmd_buy/cmd_sell previously printed and returned (exit 0) for bad
  _to_number input, and let builder ValueErrors escape as tracebacks.
- Web trade endpoints already return 400 for qty/price <= 0; a malformed
  date must get the same treatment before record_investment_entry writes.

No entity data is touched: commodity lookup, config, currency, journal
path and the write itself are all monkeypatched to fakes/recorders.
pricehist and hledger are never invoked.
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import modules.investment as inv  # noqa: E402
import modules.market as market  # noqa: E402
import modules.web as web  # noqa: E402

COMMODITY_CAD = {"symbol": "TSLA", "name": "Tesla", "source": "yahoo",
                 "fetch_pair": "TSLA", "currency": "CAD",
                 "tax_account": "taxable"}
COMMODITY_USD = dict(COMMODITY_CAD, currency="USD")

CONFIG = {"accounts": {
    "bank": "Assets:Current:Chequing",
    "capital_gains": "Income:Non-Operating:Capital Gains",
    "registered_gains": "Income:Non-Operating:Registered Gains",
}}

EVENTS_10_TSLA = [("buy", 10, 5101.44)]


@pytest.fixture()
def trade_env(tmp_path, monkeypatch):
    """Fake commodity/config/currency/journal + a write recorder."""
    writes = []

    def fake_find(identifier):
        return COMMODITY_CAD, 0

    monkeypatch.setattr(market, "_find_commodity", fake_find)
    monkeypatch.setattr(inv, "load_config", lambda: dict(CONFIG))
    monkeypatch.setattr(inv, "get_entity_currency", lambda: "CAD")
    monkeypatch.setattr(inv, "get_entity_journal",
                        lambda: tmp_path / "entity.journal")
    monkeypatch.setattr(inv, "read_holding_events",
                        lambda *a: list(EVENTS_10_TSLA))
    monkeypatch.setattr(
        inv, "record_investment_entry",
        lambda entry, date_str: writes.append((entry, date_str)) or "2026")
    monkeypatch.setattr(
        inv, "prompt", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("prompt() must not be called when flags are given")))
    return writes


def _buy_args(**over):
    args = ["TSLA", "--qty", "5", "--price", "100",
            "--date", "2026-07-20"]
    for flag, value in over.items():
        args += [f"--{flag}", str(value)]
    return args


def _sell_args(**over):
    args = ["TSLA", "--qty", "5", "--price", "500",
            "--date", "2026-07-25"]
    for flag, value in over.items():
        args += [f"--{flag}", str(value)]
    return args


# ─── I60: bad --qty / --price ───────────────────────────────────────────────

@pytest.mark.parametrize("qty", ["0", "-5", "abc"])
def test_cmd_buy_bad_qty_fails_cleanly(trade_env, qty, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, _buy_args(qty=qty))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


@pytest.mark.parametrize("price", ["0", "-50", "abc"])
def test_cmd_buy_bad_price_fails_cleanly(trade_env, price, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, _buy_args(price=price))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


@pytest.mark.parametrize("price", ["0", "-50", "abc"])
def test_cmd_sell_bad_price_fails_cleanly(trade_env, price, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_sell({}, _sell_args(price=price))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


def test_cmd_buy_negative_fee_fails_cleanly(trade_env, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, _buy_args(fee="-9.95"))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


def test_cmd_sell_negative_fee_fails_cleanly(trade_env, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_sell({}, _sell_args(fee="-9.95"))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


def test_cmd_buy_happy_path_still_writes(trade_env):
    inv.cmd_buy({}, _buy_args())
    assert len(trade_env) == 1
    entry, date_str = trade_env[0]
    assert date_str == "2026-07-20"
    assert "5 TSLA @@ CAD 500.00" in entry


def test_cmd_sell_happy_path_still_writes(trade_env):
    inv.cmd_sell({}, _sell_args())
    assert len(trade_env) == 1
    entry, date_str = trade_env[0]
    assert date_str == "2026-07-25"
    assert "-5 TSLA @@ CAD 2550.72" in entry


# ─── I61: malformed --date ──────────────────────────────────────────────────

@pytest.mark.parametrize("bad_date", ["2026-13-45", "2026/07/20", "garbage",
                                      "2026-02-30"])
def test_cmd_buy_bad_date_fails_cleanly(trade_env, bad_date, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, _buy_args(date=bad_date))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


@pytest.mark.parametrize("bad_date", ["2026-13-45", "2026/07/20", "garbage"])
def test_cmd_sell_bad_date_fails_cleanly(trade_env, bad_date, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_sell({}, _sell_args(date=bad_date))
    assert exc.value.code == 1
    assert "Traceback" not in capsys.readouterr().out
    assert trade_env == []


# ─── I62: epsilon sell + genuine over-sell ──────────────────────────────────

def test_cmd_sell_full_fractional_sell_succeeds(trade_env, monkeypatch):
    """Ten 0.1 buys replay short of 1.0 by float dust; selling 1.0 must
    succeed (I62). Pre-fix this printed InsufficientHoldingError and
    wrote nothing."""
    monkeypatch.setattr(inv, "read_holding_events",
                        lambda *a: [("buy", 0.1, 10.0)] * 10)
    inv.cmd_sell({}, _sell_args(qty="1.0", price="500"))
    assert len(trade_env) == 1
    assert "-1 TSLA @@ CAD 100.00" in trade_env[0][0]


def test_cmd_sell_genuinely_over_held_still_rejected(trade_env, capsys):
    with pytest.raises(SystemExit) as exc:
        inv.cmd_sell({}, _sell_args(qty="20", price="500"))
    assert exc.value.code == 1
    assert "only 10 held in taxable" in capsys.readouterr().out
    assert trade_env == []


# ─── Remaining cmd paths (closes I58) ─────────────────────────────────────

def test_cmd_buy_unknown_symbol_fails_cleanly(trade_env, monkeypatch, capsys):
    monkeypatch.setattr(market, "_find_commodity",
                        lambda identifier: (None, None))
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, ["NOPE", "--qty", "5", "--price", "100"])
    assert exc.value.code == 1
    assert "not tracked" in capsys.readouterr().out
    assert trade_env == []


def test_cmd_sell_unknown_symbol_fails_cleanly(trade_env, monkeypatch, capsys):
    monkeypatch.setattr(market, "_find_commodity",
                        lambda identifier: (None, None))
    with pytest.raises(SystemExit) as exc:
        inv.cmd_sell({}, ["NOPE", "--qty", "5", "--price", "500"])
    assert exc.value.code == 1
    assert "not tracked" in capsys.readouterr().out
    assert trade_env == []


def test_cmd_buy_invalid_tax_account_fails_cleanly(trade_env, monkeypatch,
                                                   capsys):
    monkeypatch.setattr(market, "_find_commodity",
                        lambda identifier: (dict(COMMODITY_CAD,
                                                 tax_account="resp"), 0))
    with pytest.raises(SystemExit) as exc:
        inv.cmd_buy({}, _buy_args())
    assert exc.value.code == 1
    assert "Invalid tax account" in capsys.readouterr().out
    assert trade_env == []


def _prompt_fake(monkeypatch):
    def fake_prompt(text, **kwargs):
        if "Quantity" in text:
            return "5"
        if "Unit price" in text:
            return "100"
        raise AssertionError(f"unexpected prompt: {text!r}")
    monkeypatch.setattr(inv, "prompt", fake_prompt)


def test_cmd_buy_prompt_path_writes(trade_env, monkeypatch):
    """No --qty/--price flags: the interactive prompts supply them."""
    _prompt_fake(monkeypatch)
    inv.cmd_buy({}, ["TSLA", "--date", "2026-07-20"])
    assert len(trade_env) == 1
    assert "5 TSLA @@ CAD 500.00" in trade_env[0][0]


def test_cmd_sell_prompt_path_writes(trade_env, monkeypatch):
    _prompt_fake(monkeypatch)
    inv.cmd_sell({}, ["TSLA", "--date", "2026-07-25"])
    assert len(trade_env) == 1
    assert "-5 TSLA @@ CAD 2550.72" in trade_env[0][0]


# ─── _parse_flags / _to_number (I58 command layer) ──────────────────────────

def test_parse_flags_basic():
    assert inv._parse_flags(["TSLA", "--qty", "5", "--price", "100",
                             "--date", "2026-07-20", "--fee", "9.95"]) == {
        "symbol": "TSLA", "qty": "5", "price": "100",
        "date": "2026-07-20", "fee": "9.95"}


def test_parse_flags_negative_value_is_kept():
    # "-5" does not start with "--", so it is parsed as the flag's value
    # (and rejected downstream) rather than silently dropped.
    assert inv._parse_flags(["TSLA", "--qty", "-5"])["qty"] == "-5"


def test_parse_flags_flag_without_value_left_unset():
    parsed = inv._parse_flags(["TSLA", "--qty", "--price", "100"])
    assert "qty" not in parsed
    assert parsed["price"] == "100"


def test_parse_flags_unknown_flags_ignored():
    assert inv._parse_flags(["TSLA", "--bogus", "x", "--qty", "5"]) == {
        "symbol": "TSLA", "qty": "5"}


def test_to_number_valid_and_invalid(capsys):
    assert inv._to_number("5", "quantity") == 5.0
    assert inv._to_number("0.00431", "quantity") == 0.00431
    assert inv._to_number("abc", "quantity") is None
    assert "Invalid quantity" in capsys.readouterr().out
    assert inv._to_number(None, "quantity") is None


# ─── Web: malformed date + negative fx (I61, fee/fx) ────────────────────────

@pytest.fixture()
def web_client(tmp_path, monkeypatch):
    writes = []
    monkeypatch.setattr(market, "_find_commodity",
                        lambda identifier: (COMMODITY_CAD, 0))
    monkeypatch.setattr(web, "load_config", lambda: dict(CONFIG))
    monkeypatch.setattr(web, "get_entity_currency", lambda: "CAD")
    monkeypatch.setattr(web, "get_entity_journal",
                        lambda: tmp_path / "entity.journal")
    monkeypatch.setattr(inv, "read_holding_events",
                        lambda *a: list(EVENTS_10_TSLA))
    monkeypatch.setattr(
        inv, "record_investment_entry",
        lambda entry, date_str: writes.append((entry, date_str)) or "2026")
    client = TestClient(web.create_app())
    client.writes = writes
    return client


def _trade(client, endpoint, **over):
    body = {"symbol": "TSLA", "qty": 5, "price": 100,
            "date": "2026-07-20"}
    body.update(over)
    return client.post(endpoint, json=body)


@pytest.mark.parametrize("bad_date", ["2026-13-45", "2026/07/20", "garbage",
                                      "2026-02-30"])
def test_web_buy_bad_date_is_400_and_writes_nothing(web_client, bad_date):
    resp = _trade(web_client, "/api/market/buy", date=bad_date)
    assert resp.status_code == 400, resp.text
    assert web_client.writes == []


@pytest.mark.parametrize("bad_date", ["2026-13-45", "2026/07/20", "garbage"])
def test_web_sell_bad_date_is_400_and_writes_nothing(web_client, bad_date):
    resp = _trade(web_client, "/api/market/sell", date=bad_date, price=500)
    assert resp.status_code == 400, resp.text
    assert web_client.writes == []


def test_web_buy_valid_date_still_writes(web_client):
    resp = _trade(web_client, "/api/market/buy")
    assert resp.status_code == 200, resp.text
    assert len(web_client.writes) == 1
    assert "5 TSLA @@ CAD 500.00" in web_client.writes[0][0]


def test_web_sell_valid_date_still_writes(web_client):
    resp = _trade(web_client, "/api/market/sell", price=500)
    assert resp.status_code == 200, resp.text
    assert len(web_client.writes) == 1


def test_web_buy_negative_fx_is_400(web_client, monkeypatch):
    """fx arrives via the web body; a negative rate must not reach the
    journal. Commodity currency USD so fx is actually used."""
    monkeypatch.setattr(market, "_find_commodity",
                        lambda identifier: (COMMODITY_USD, 0))
    resp = _trade(web_client, "/api/market/buy", fx=-1.366)
    assert resp.status_code == 400, resp.text
    assert web_client.writes == []


def test_web_buy_negative_fee_is_400(web_client):
    resp = _trade(web_client, "/api/market/buy", fee=-9.95)
    assert resp.status_code == 400, resp.text
    assert web_client.writes == []


def test_web_sell_zero_price_still_400(web_client):
    # Already guarded at the top of market_sell; pinned so the builder
    # check below cannot silently become the only guard.
    resp = _trade(web_client, "/api/market/sell", price=0)
    assert resp.status_code == 400, resp.text
    assert web_client.writes == []
