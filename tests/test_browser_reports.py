"""Browser smoke test for the report builder's Reports tab (I76).

Follows the tests/test_browser_trade_modal.py harness: a fixture
entity (real config.yaml + journals under tmp_path), the FastAPI app
served by uvicorn in a thread *in this process* (so the monkeypatched
entity resolution applies to the server too), Playwright driving
headless Chromium against it. Skips cleanly when Playwright, uvicorn,
or a launchable Chromium is absent.

What it proves: the Reports tab renders in a real browser, the saved
report select is populated from config.yaml, running a named report
renders its rows in the results table, and running an ad-hoc build
from the form renders its rows too. The endpoints themselves are
covered by tests/test_report_builder_web.py; this test covers the
JavaScript that TestClient never runs.

Same CDN shim as the trade-modal test: index.html loads Chart.js from
the jsdelivr CDN, and the page's top-level `Chart.defaults.*`
statements abort the whole script when Chart is undefined. This VM's
browser cannot reach the CDN (proxy tunnel failure), even though curl
can, so the test fulfils the three CDN script requests from
byte-identical vendored copies under tests/fixtures/chartjs/.
"""

import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright", reason="playwright not installed")
uvicorn = pytest.importorskip("uvicorn", reason="uvicorn not installed")
from playwright.sync_api import sync_playwright  # noqa: E402

import modules.web as web  # noqa: E402
import lib.helpers as helpers  # noqa: E402
import lib.ui as ui  # noqa: E402
import modules.market as market  # noqa: E402

CONFIG_YAML = """pair:
  currency: CAD
reports:
  monthly-expenses:
    title: Monthly expenses
    command: register
    query: "acct:Expenses"
    monthly: true
  balances:
    command: bal
"""

JOURNAL = """2026-01-05 * Big purchase
    Expenses:Operating:Supplies    CAD 500.00
    Assets:Current:Chequing        CAD -500.00

2026-01-06 * Small purchase
    Expenses:Operating:Supplies    CAD 50.00
    Assets:Current:Chequing        CAD -50.00

2026-02-01 * Sale
    Assets:Current:Chequing        CAD 1000.00
    Income:Sales                   CAD -1000.00
"""

GLOBAL = {"active": "fixture",
          "entities": [{"slug": "fixture", "name": "Fixture",
                        "currency": "CAD"}]}

CDN_SHIM = {
    "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js":
        "chart.umd.min.js",
    "https://cdn.jsdelivr.net/npm/chartjs-chart-sankey@0.14.0/dist/chartjs-chart-sankey.min.js":
        "chartjs-chart-sankey.min.js",
    "https://cdn.jsdelivr.net/npm/chartjs-chart-treemap@3.1.0/dist/chartjs-chart-treemap.min.js":
        "chartjs-chart-treemap.min.js",
}


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def browser_env(tmp_path, monkeypatch):
    """Fixture entity + in-process server. Yields (base_url, entity_dir)."""
    entity_dir = tmp_path / "entity"
    include = entity_dir / "include"
    include.mkdir(parents=True)
    (entity_dir / "config.yaml").write_text(CONFIG_YAML)
    (include / "entity.journal").write_text(JOURNAL)

    monkeypatch.setattr(helpers, "get_entity_dir", lambda: entity_dir)
    monkeypatch.setattr(helpers, "load_global_config", lambda: dict(GLOBAL))
    monkeypatch.setattr(ui, "get_entity_dir", lambda: entity_dir)
    monkeypatch.setattr(ui, "load_global_config", lambda: dict(GLOBAL))
    monkeypatch.setattr(web, "get_entity_dir", lambda: entity_dir)
    monkeypatch.setattr(market, "get_entity_dir", lambda: entity_dir)

    app = web.create_app()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while True:
        try:
            with urllib.request.urlopen(base_url + "/api/status",
                                        timeout=2) as r:
                assert r.status == 200
            break
        except Exception:
            if time.time() > deadline:
                server.should_exit = True
                raise RuntimeError("test server did not start")
            time.sleep(0.2)
    yield base_url, entity_dir
    server.should_exit = True
    thread.join(timeout=10)


def _open_reports(page, base_url):
    """Load the app and open the Reports tab; return collected page errors."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    fixtures = Path(__file__).resolve().parent / "fixtures" / "chartjs"
    for url, name in CDN_SHIM.items():
        path = str(fixtures / name)
        # This Playwright version calls the handler as handler(route, request).
        page.route(url, lambda route, _request, p=path: route.fulfill(
            path=p, content_type="application/javascript"))
    page.goto(base_url, wait_until="domcontentloaded")
    page.locator("#main-tabs .tab", has_text="Reports").click()
    page.locator("#view-reports").wait_for(state="visible", timeout=10000)
    return errors


def test_named_report_runs_in_browser(browser_env):
    base_url, _entity_dir = browser_env
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium did not launch: {e}")
        page = browser.new_page()
        errors = _open_reports(page, base_url)

        select = page.locator("#builder-report-select")
        select.wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            "document.getElementById('builder-report-select').options.length >= 2",
            timeout=10000)
        assert page.locator(
            "#builder-report-select option[value='monthly-expenses']").count() == 1
        assert "Monthly expenses" in select.inner_text()
        select.select_option(label="Monthly expenses — register")

        page.locator("#view-reports button", has_text="Run").first.click()
        results = page.locator("#builder-results")
        results.wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            "document.getElementById('builder-results').textContent.includes('550.00')",
            timeout=10000)
        assert "Expenses:Operating:Supplies" in results.inner_text()
        assert not errors, f"page errors: {errors}"
        browser.close()


def test_adhoc_report_runs_in_browser(browser_env):
    base_url, _entity_dir = browser_env
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium did not launch: {e}")
        page = browser.new_page()
        errors = _open_reports(page, base_url)

        page.fill("#builder-acct", "Expenses")
        page.locator("#builder-cmd").select_option("register")
        page.locator("#view-reports button", has_text="Run").nth(1).click()
        results = page.locator("#builder-results")
        page.wait_for_function(
            "document.getElementById('builder-results').textContent.includes('500.00')",
            timeout=10000)
        assert "CAD 50.00" in results.inner_text()
        assert "Income:Sales" not in results.inner_text()
        assert not errors, f"page errors: {errors}"
        browser.close()
