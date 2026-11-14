"""Tests for `pair market verify [--deep]` in the web (I63).

The verify core lives in modules/market.py::verify_commodities — a shared,
structured function used by both the CLI (`cmd_verify`, which keeps its
exact printed output and exit-0 contract) and the new web endpoint
POST /api/market/verify. pricehist is NOT installed on this VM, so every
test mocks the pricehist subprocess boundary (subprocess.run) and never
executes pricehist; what remains unverified live is the real pricehist
output shape (P-line symbol tokens, exit codes).

Weaknesses addressed here (audit):
- _check_price_gaps substring-matched the symbol, so BTC also matched
  BTCX lines. test_verify_deep_gaps_exact_match pins exact matching.
- No stored-price freshness check. verify reports stored_latest_date /
  stored_age_days / stale for every commodity.
- No --symbol filter. Both the CLI (bare symbol arg, like cmd_fetch) and
  the web endpoint accept one.
- Identity: NOT verified from pricehist output alone — a wrong fetch_pair
  pointing at a different valid instrument is indistinguishable without a
  second price source, and pricehist echoes the requested pair. The
  returned P-line symbol tokens are exposed as `returned_symbols`, and a
  token matching neither the fetch_pair nor the symbol is surfaced as an
  advisory issue only (test_verify_returned_symbol_surprise) — it never
  flips `ok`, because the token format is unverified against live
  pricehist and must not false-fail legitimate pairs.
"""

import subprocess
from datetime import date, timedelta

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import modules.market as M  # noqa: E402
import modules.web as web  # noqa: E402

TODAY = date(2026, 11, 13)

COMMODITIES = [
    {"symbol": "BTC", "name": "Bitcoin", "source": "yahoo",
     "fetch_pair": "BTC-CAD", "currency": "CAD"},
    {"symbol": "SHOP", "name": "Shopify", "source": "yahoo",
     "fetch_pair": "SHOP.TO", "currency": "CAD"},
]


def _verify(**kwargs):
    # Lazily imported: the shared function does not exist until the fix
    # lands, and a module-level import would fail collection of the file.
    from modules.market import verify_commodities
    return verify_commodities(**kwargs)


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _p_lines(symbol, dates_prices, currency="CAD"):
    return "".join(
        f"P {d} {symbol} {currency} {p}\n" for d, p in dates_prices)


def _fake_run_factory(outputs, calls=None):
    """outputs: {pair_str: (returncode, stdout, stderr) or Exception}."""
    def _run(cmd, **kwargs):
        if calls is not None:
            calls.append(list(cmd))
        pair = cmd[-1]
        if pair not in outputs:
            raise AssertionError(f"unexpected pricehist pair {pair!r}")
        out = outputs[pair]
        if isinstance(out, Exception):
            raise out
        return _FakeResult(*out)
    return _run


@pytest.fixture()
def market_env(tmp_path, monkeypatch):
    prices = tmp_path / "prices.journal"
    prices.write_text("")
    monkeypatch.setattr(M, "_get_commodities", lambda: list(COMMODITIES))
    monkeypatch.setattr(M, "_get_prices_journal", lambda: prices)
    monkeypatch.setattr(M, "_pricehist_available", lambda: True)
    return prices


def _good_outputs():
    return {
        "BTC-CAD": (0, _p_lines("BTC-CAD", [
            ("2026-11-11", "90000"), ("2026-11-12", "91000"),
            ("2026-11-13", "92000")]), ""),
        "SHOP.TO": (0, _p_lines("SHOP.TO", [("2026-11-13", "150.25")]), ""),
    }


# ─── Shared function: fetch outcomes ─────────────────────────────────────────

def test_verify_success(market_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    result = _verify(today=TODAY)
    assert result["pricehist_available"] is True
    assert result["ok"] is True
    assert result["ok_count"] == 2 and result["failed_count"] == 0
    assert result["total"] == 2
    btc = result["results"][0]
    assert btc["symbol"] == "BTC"
    assert btc["status"] == "ok" and btc["ok"] is True
    assert btc["prices"] == 3
    assert btc["latest_fetched"] == "2026-11-13"
    assert btc["returned_symbols"] == ["BTC-CAD"]
    assert btc["error"] is None


def test_verify_fetch_failure(market_env, monkeypatch):
    outputs = _good_outputs()
    outputs["SHOP.TO"] = (1, "", "source exploded")
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(outputs))
    result = _verify(today=TODAY)
    assert result["ok"] is False
    assert result["ok_count"] == 1 and result["failed_count"] == 1
    shop = result["results"][1]
    assert shop["status"] == "failed" and shop["ok"] is False
    assert "exploded" in (shop["error"] or "")


def test_verify_no_data(market_env, monkeypatch):
    outputs = _good_outputs()
    outputs["BTC-CAD"] = (0, "fetch completed\n", "")
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(outputs))
    result = _verify(today=TODAY)
    btc = result["results"][0]
    assert btc["status"] == "no_data" and btc["ok"] is False
    assert btc["prices"] == 0


def test_verify_timeout(market_env, monkeypatch):
    outputs = _good_outputs()
    outputs["BTC-CAD"] = subprocess.TimeoutExpired(cmd="pricehist", timeout=15)
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(outputs))
    result = _verify(today=TODAY)
    assert result["results"][0]["status"] == "timeout"
    assert result["ok"] is False


def test_verify_skips_unsafe_pair(market_env, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("pricehist must never be invoked for an unsafe pair")
    monkeypatch.setattr(M, "_get_commodities", lambda: [
        {"symbol": "EVIL", "source": "yahoo",
         "fetch_pair": "--output-file=/tmp/x"}])
    monkeypatch.setattr(subprocess, "run", _boom)
    result = _verify(today=TODAY)
    assert result["results"][0]["status"] == "skipped"
    assert result["results"][0]["ok"] is False
    assert result["failed_count"] == 1


def test_verify_pricehist_missing(market_env, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("pricehist must never be invoked when unavailable")
    monkeypatch.setattr(M, "_pricehist_available", lambda: False)
    monkeypatch.setattr(subprocess, "run", _boom)
    result = _verify(today=TODAY)
    assert result["pricehist_available"] is False
    assert result["ok"] is False
    assert result["results"] == []


def test_verify_no_commodities(market_env, monkeypatch):
    monkeypatch.setattr(M, "_get_commodities", lambda: [])
    result = _verify(today=TODAY)
    assert result["total"] == 0 and result["results"] == []


# ─── Shared function: gaps (exact match) + freshness ─────────────────────────

def test_verify_deep_gaps_exact_match(market_env, monkeypatch):
    # BTC has a 9-day gap; BTCX lines fill it — they must NOT count for BTC.
    market_env.write_text(
        "P 2026-01-01 BTC CAD 100\n"
        "P 2026-01-10 BTC CAD 110\n"
        "P 2026-01-05 BTCX CAD 50\n"
        "P 2026-01-06 BTCX CAD 51\n"
    )
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    result = _verify(deep=True, today=TODAY)
    btc = result["results"][0]
    assert btc["history_count"] == 2
    assert btc["gaps"] == [{"days": 9, "from": "2026-01-01", "to": "2026-01-10"}]
    assert btc["history_range"] == ["2026-01-01", "2026-01-10"]


def test_verify_freshness(market_env, monkeypatch):
    market_env.write_text(
        "P 2026-11-03 BTC CAD 88000\n"
        "P 2026-11-12 SHOP.TO CAD 149.00\n"
    )
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    result = _verify(today=TODAY)
    btc, shop = result["results"]
    assert btc["stored_latest_date"] == "2026-11-03"
    assert btc["stored_age_days"] == 10
    assert btc["stale"] is True
    assert shop["stored_latest_date"] == "2026-11-12"
    assert shop["stored_age_days"] == 1
    assert shop["stale"] is False


def test_verify_no_history_is_stale(market_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    result = _verify(today=TODAY)
    assert result["results"][0]["stored_latest_date"] is None
    assert result["results"][0]["stale"] is True


def test_verify_returned_symbol_surprise_is_advisory_only(
        market_env, monkeypatch):
    # P lines labelled with a symbol matching neither the fetch_pair nor
    # the configured symbol: surfaced as an issue, never flips ok — the
    # token format is unverified against live pricehist.
    outputs = _good_outputs()
    outputs["BTC-CAD"] = (0, _p_lines("DOGE", [("2026-11-13", "0.20")]), "")
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(outputs))
    result = _verify(today=TODAY)
    btc = result["results"][0]
    assert btc["ok"] is True
    assert btc["returned_symbols"] == ["DOGE"]
    assert any("DOGE" in i for i in btc["issues"])


# ─── Shared function: symbol filter ──────────────────────────────────────────

def test_verify_symbol_filter(market_env, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs(), calls))
    result = _verify(symbol="shop", today=TODAY)
    assert result["total"] == 1
    assert result["results"][0]["symbol"] == "SHOP"
    assert len(calls) == 1 and calls[0][-1] == "SHOP.TO"


def test_verify_symbol_not_found(market_env, monkeypatch):
    with pytest.raises(ValueError, match="not tracked"):
        _verify(symbol="NOPE", today=TODAY)


# ─── CLI: exact output preserved ─────────────────────────────────────────────

@pytest.fixture()
def cli_env(market_env, monkeypatch):
    monkeypatch.setattr(M, "get_active_entity", lambda: "deskone")
    return market_env


def test_cmd_verify_output(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    M.cmd_verify({}, [])
    out = capsys.readouterr().out
    assert "✓ fetchable" in out
    assert "(3 price(s) in last 5 days)" in out
    assert "2/2 verified. All good." in out


def test_cmd_verify_deep_prints_gaps(cli_env, monkeypatch, capsys):
    cli_env.write_text(
        "P 2026-01-01 BTC CAD 100\n"
        "P 2026-01-10 BTC CAD 110\n"
    )
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    M.cmd_verify({}, ["--deep"])
    out = capsys.readouterr().out
    assert "2 entries (2026-01-01 → 2026-01-10)" in out
    assert "⚠ gap: 9 days (2026-01-01 → 2026-01-10)" in out


def test_cmd_verify_symbol_filter(cli_env, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs(), calls))
    M.cmd_verify({}, ["SHOP"])
    out = capsys.readouterr().out
    assert len(calls) == 1 and calls[0][-1] == "SHOP.TO"
    assert "1/1 verified. All good." in out


# ─── Web endpoint ────────────────────────────────────────────────────────────

@pytest.fixture()
def verify_client(tmp_path, monkeypatch):
    prices = tmp_path / "prices.journal"
    prices.write_text(
        "P 2026-11-12 BTC CAD 91000\n"
        "P 2026-11-12 SHOP.TO CAD 149.00\n"
    )
    monkeypatch.setattr(M, "_get_commodities", lambda: list(COMMODITIES))
    monkeypatch.setattr(M, "_get_prices_journal", lambda: prices)
    monkeypatch.setattr(M, "_pricehist_available", lambda: True)
    monkeypatch.setattr(subprocess, "run",
                        _fake_run_factory(_good_outputs()))
    return TestClient(web.create_app())


def test_web_verify_all(verify_client):
    resp = verify_client.post("/api/market/verify", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["total"] == 2 and data["ok_count"] == 2
    btc = data["results"][0]
    assert btc["symbol"] == "BTC" and btc["status"] == "ok"
    assert btc["prices"] == 3
    assert btc["stale"] is False


def test_web_verify_symbol(verify_client):
    resp = verify_client.post("/api/market/verify", json={"symbol": "BTC"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert data["results"][0]["symbol"] == "BTC"


def test_web_verify_unknown_symbol(verify_client):
    resp = verify_client.post("/api/market/verify", json={"symbol": "NOPE"})
    assert resp.status_code == 404


def test_web_verify_deep_gaps(verify_client, tmp_path, monkeypatch):
    # Swap in a gappy history and re-run deep.
    prices = tmp_path / "gappy.journal"
    prices.write_text(
        "P 2026-01-01 BTC CAD 100\n"
        "P 2026-01-10 BTC CAD 110\n"
    )
    monkeypatch.setattr(M, "_get_prices_journal", lambda: prices)
    resp = verify_client.post("/api/market/verify", json={"deep": True})
    assert resp.status_code == 200, resp.text
    btc = resp.json()["results"][0]
    assert btc["gaps"] == [{"days": 9, "from": "2026-01-01", "to": "2026-01-10"}]


def test_web_verify_pricehist_missing(verify_client, monkeypatch):
    monkeypatch.setattr(M, "_pricehist_available", lambda: False)
    resp = verify_client.post("/api/market/verify", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pricehist_available"] is False
    assert data["ok"] is False
    assert data["results"] == []
