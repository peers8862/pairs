"""Web parity for `pair market show` / `chart` / `alert` (I64).

CLI subsystems exist in modules/market.py; the web had only partial
coverage before this batch:
- `show` (price history detail): /api/commodities gave the latest price
  per symbol but no entry count, and /api/chart/prices gave the full
  history for all symbols at once but no per-symbol detail. The new
  GET /api/market/prices/{symbol} is the per-symbol show+chart data.
- `chart SYMBOL`: CLI renders a matplotlib PNG; the web renders the
  /api/chart/prices data with Chart.js. No new endpoint is needed for
  chart data itself — but chart_prices duplicated the P-line parsing,
  so it now shares modules/market.py::read_price_history with the new
  endpoint (same data, one parser).
- `alert` (add/list/check/remove): entirely absent from the web. The
  endpoints below share the CLI's own code path: alert rules live in
  entity config under market.alerts (same _get/_save helpers), and
  evaluation goes through modules/market.py::evaluate_alerts, which is
  the function _alert_check_once now calls — not a re-implementation.

No entity data is touched: config, prices journal and the live-price
fetch are all monkeypatched. yfinance is NOT installed on this VM, so
alert-check tests inject a fake live price (or assert the structured
"no live price" error); what remains unverified live is the real
yfinance quote shape.
"""

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import modules.market as M  # noqa: E402
import modules.web as web  # noqa: E402

PRICES = """P 2026-11-10 TSLA CAD 480.00
P 2026-11-11 TSLA CAD 490.50
P 2026-11-12 TSLA CAD 510.25
P 2026-11-12 "SHOP.TO" CAD 150.25
P 2026-11-11 BTC-CAD CAD 90000
P 2026-11-13 BTC-CAD CAD 92000
"""

COMMODITIES = [
    {"symbol": "TSLA", "name": "Tesla", "source": "yahoo",
     "fetch_pair": "TSLA", "currency": "CAD"},
    {"symbol": "SHOP", "name": "Shopify", "source": "yahoo",
     "fetch_pair": "SHOP.TO", "currency": "CAD"},
    {"symbol": "BTC", "name": "Bitcoin", "source": "yahoo",
     "fetch_pair": "BTC-CAD", "currency": "CAD"},
]


def _read_history(*args, **kwargs):
    # Lazily imported: the shared helper does not exist until the fix
    # lands, and a module-level import would fail collection of the file.
    from modules.market import read_price_history
    return read_price_history(*args, **kwargs)


def _evaluate(*args, **kwargs):
    from modules.market import evaluate_alerts
    return evaluate_alerts(*args, **kwargs)


def _upsert(*args, **kwargs):
    from modules.market import upsert_alert_rule
    return upsert_alert_rule(*args, **kwargs)


@pytest.fixture()
def market_env(tmp_path, monkeypatch):
    """Fake prices journal + in-memory entity config for market helpers."""
    entity_dir = tmp_path / "entity"
    prices = entity_dir / "include" / "prices.journal"
    prices.parent.mkdir(parents=True)
    prices.write_text(PRICES)
    config = {"market": {"commodities": list(COMMODITIES), "alerts": {}}}

    monkeypatch.setattr(M, "_get_prices_journal", lambda: prices)
    monkeypatch.setattr(M, "load_config", lambda: config)
    monkeypatch.setattr(M, "save_config", lambda c: config.update(c))
    # /api/chart/prices resolves the prices file through web's entity dir.
    monkeypatch.setattr(web, "get_entity_dir", lambda: entity_dir)
    return config


@pytest.fixture()
def client(market_env):
    return TestClient(web.create_app())


# ─── Shared price history (show / chart data) ───────────────────────────────

def test_read_price_history_parses_all_symbols(market_env):
    hist = _read_history()
    assert sorted(hist) == ["BTC-CAD", "SHOP.TO", "TSLA"]
    assert hist["TSLA"] == [("2026-11-10", 480.00),
                            ("2026-11-11", 490.50),
                            ("2026-11-12", 510.25)]
    # Quoted symbol token is unquoted, like cmd_show does.
    assert hist["SHOP.TO"] == [("2026-11-12", 150.25)]


def test_read_price_history_sorted_and_symbol_filtered(market_env):
    hist = _read_history(symbol="tsla")
    assert list(hist) == ["TSLA"]
    assert hist["TSLA"][0][0] == "2026-11-10"


def test_market_prices_endpoint_show_detail(client):
    resp = client.get("/api/market/prices/TSLA")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["symbol"] == "TSLA"
    assert data["latest_price"] == 510.25
    assert data["latest_date"] == "2026-11-12"
    assert data["count"] == 3
    assert data["dates"] == ["2026-11-10", "2026-11-11", "2026-11-12"]
    assert data["prices"] == [480.00, 490.50, 510.25]


def test_market_prices_endpoint_unknown_symbol_404(client):
    resp = client.get("/api/market/prices/NOPE")
    assert resp.status_code == 404


def test_chart_prices_uses_shared_history(client):
    """GET /api/chart/prices still returns the same shape, now parsed once."""
    resp = client.get("/api/chart/prices")
    assert resp.status_code == 200, resp.text
    commodities = resp.json()["commodities"]
    assert commodities["TSLA"] == {
        "dates": ["2026-11-10", "2026-11-11", "2026-11-12"],
        "prices": [480.00, 490.50, 510.25]}


# ─── Alerts: shared add/list/remove ─────────────────────────────────────────

def test_upsert_alert_rule_add_and_replace(market_env):
    rule, replaced = _upsert("TSLA", 5.0, tags=["equity"])
    assert replaced is False
    assert rule["symbol"] == "TSLA" and rule["threshold"] == 5.0
    assert rule["type"] == "drop_from_close" and rule["enabled"] is True
    rule2, replaced2 = _upsert("TSLA", 3.0, replace=True)
    assert replaced2 is True and rule2["threshold"] == 3.0
    assert len(market_env["market"]["alerts"]["rules"]) == 1


def test_upsert_alert_rule_duplicate_without_replace_rejected(market_env):
    _upsert("TSLA", 5.0)
    with pytest.raises(ValueError, match="already exists"):
        _upsert("TSLA", 3.0)


def test_upsert_alert_rule_bad_threshold_rejected(market_env):
    with pytest.raises(ValueError):
        _upsert("TSLA", 0)
    with pytest.raises(ValueError):
        _upsert("TSLA", -2)
    with pytest.raises(ValueError):
        _upsert("TSLA", "abc")


def test_upsert_alert_rule_untracked_symbol_rejected(market_env):
    # Mirrors the CLI batch-mode behaviour: an alert needs a tracked
    # commodity (the interactive CLI offers to add it; the web has no
    # interactive step, so it refuses instead of inventing one).
    with pytest.raises(ValueError, match="not tracked"):
        _upsert("NOPE", 5.0)


def test_alerts_endpoints_crud(client):
    assert client.get("/api/market/alerts").json() == {"rules": []}
    resp = client.post("/api/market/alerts",
                       json={"symbol": "TSLA", "threshold": 5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rule"]["threshold"] == 5.0
    assert resp.json()["replaced"] is False

    listed = client.get("/api/market/alerts").json()["rules"]
    assert len(listed) == 1
    assert listed[0]["symbol"] == "TSLA"
    # Resolved interval + status, like cmd_alert_list prints.
    assert listed[0]["interval"] == "5m" and listed[0]["enabled"] is True

    # Re-adding replaces (web has no interactive confirm step).
    resp = client.post("/api/market/alerts",
                       json={"symbol": "TSLA", "threshold": 3})
    assert resp.status_code == 200
    assert resp.json()["replaced"] is True
    assert len(client.get("/api/market/alerts").json()["rules"]) == 1

    resp = client.delete("/api/market/alerts/TSLA")
    assert resp.status_code == 200, resp.text
    assert client.get("/api/market/alerts").json() == {"rules": []}


def test_alerts_endpoints_validate(client):
    assert client.post("/api/market/alerts",
                       json={"symbol": "TSLA", "threshold": 0}).status_code == 400
    assert client.post("/api/market/alerts",
                       json={"symbol": "NOPE", "threshold": 5}).status_code == 400
    assert client.delete("/api/market/alerts/NOPE").status_code == 404


# ─── Alerts: shared evaluation (same code path as the CLI check) ────────────

def _rules():
    return [{"symbol": "TSLA", "type": "drop_from_close",
             "threshold": 5.0, "enabled": True},
            {"symbol": "BTC", "type": "drop_from_close",
             "threshold": 10.0, "enabled": True}]


def test_evaluate_alerts_triggered_and_ok(market_env):
    # Previous closes from the fixture prices.journal (before today):
    # TSLA 510.25 on 2026-11-12; BTC is priced under its fetch pair
    # BTC-CAD, 92000 on 2026-11-13 — the close lookup resolves the
    # fetch pair, so the BTC rule finds its close too.
    results = _evaluate(_rules(), today="2026-11-14",
                        live_price_fn=lambda c: {"TSLA": 480.00,
                                                "BTC": 91000.0}[c["symbol"]])
    by_sym = {r["symbol"]: r for r in results}
    # TSLA: (510.25-480)/510.25 = 5.93% >= 5 -> triggered.
    assert by_sym["TSLA"]["triggered"] is True
    assert by_sym["TSLA"]["close_price"] == 510.25
    assert by_sym["TSLA"]["live_price"] == 480.00
    assert abs(by_sym["TSLA"]["pct_drop"] - 5.9288) < 0.01
    # BTC: (92000-91000)/92000 = 1.09% < 10 -> ok.
    assert by_sym["BTC"]["triggered"] is False
    assert by_sym["BTC"]["status"] == "ok"


def test_evaluate_alerts_no_previous_close(market_env):
    results = _evaluate(
        [{"symbol": "NOPE", "threshold": 5.0, "enabled": True}],
        today="2026-11-14", live_price_fn=lambda c: 100.0)
    assert results[0]["status"] == "no_close"
    assert results[0]["triggered"] is False
    assert results[0]["error"] is not None


def test_evaluate_alerts_no_live_price(market_env):
    results = _evaluate(
        [{"symbol": "TSLA", "threshold": 5.0, "enabled": True}],
        today="2026-11-14", live_price_fn=lambda c: None)
    assert results[0]["status"] == "no_live_price"
    assert results[0]["triggered"] is False


def test_alert_check_endpoint_uses_shared_evaluation(client, monkeypatch):
    _upsert("TSLA", 5.0)
    _upsert("BTC", 10.0)
    monkeypatch.setattr(
        M, "_get_live_price",
        lambda c: {"TSLA": 480.00, "BTC": 91000.0}[c["symbol"]])
    # Previous close counts only dates before real today (2026-11-13):
    # TSLA 510.25 on 2026-11-12, BTC (fetch pair BTC-CAD) 90000 on
    # 2026-11-11.
    resp = client.post("/api/market/alerts/check", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    by_sym = {r["symbol"]: r for r in data["results"]}
    assert by_sym["TSLA"]["triggered"] is True
    assert by_sym["BTC"]["triggered"] is False
    assert data["triggered"] == 1
    assert data["total"] == 2


def test_alert_check_endpoint_symbol_filter(client, monkeypatch):
    _upsert("TSLA", 5.0)
    _upsert("BTC", 10.0)
    monkeypatch.setattr(M, "_get_live_price", lambda c: 1.0)
    resp = client.post("/api/market/alerts/check", json={"symbol": "TSLA"})
    assert resp.status_code == 200, resp.text
    assert [r["symbol"] for r in resp.json()["results"]] == ["TSLA"]


def test_alert_check_endpoint_yfinance_missing_reports_error(client):
    # yfinance is not installed here: the check must report the failure
    # per rule (status no_live_price), not 500 and not a silent pass.
    _upsert("TSLA", 5.0)
    resp = client.post("/api/market/alerts/check", json={})
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "no_live_price"
    assert result["triggered"] is False
    assert resp.json()["errors"] == 1


# ─── UI hooks (static: no JS test infra in this repo) ───────────────────────

def test_commodities_ui_wires_alerts_and_history():
    """The Commodities tab must call the new endpoints and render them.

    This is a static check only — the JS itself is exercised for real by
    the browser smoke test (I66), which loads this page in Chromium.
    """
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text()
    for needle in ("/api/market/alerts", "/api/market/alerts/check",
                   "/api/market/prices/",
                   'id="alerts-list"', 'id="alert-results"',
                   'id="price-history"', "loadAlerts()",
                   "showPriceHistory(", "checkAlerts()"):
        assert needle in html, f"missing UI hook: {needle}"
