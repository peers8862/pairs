"""Traction vs ownership chart (I54): one chart with a chosen traction
metric, founder ownership and cash over time.

- Traction: any KPI metric, by month, from the KPI grid (the caller picks
  the metric; the response lists the metrics that have data).
- Ownership: founder % of fully diluted shares over time, derived from the
  captable register's dated issuances and grants — only entries dated on or
  before each month-end count. Undated entries count always. SAFEs/notes are
  not shares until converted, so they do not dilute here; a conversion
  appears as an issuance with its date. Cap-table *versions* are undated
  what-ifs ("what a round would do"), not history, so they are not used.
  With no register, ownership is null for every month.
- Cash: month-end cash from the runway rows (actual months from the books,
  then the plan).

The chart is GET /api/chart/traction and `pair traction`; the web draws it
in Company > Overview.
"""

import shutil
from decimal import Decimal as D

import pytest
import yaml

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

from lib import captable as C
from lib import kpi as K
import modules.web as web  # noqa: E402

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

JOURNAL = """2026-01-05 * Seed money
    Assets:Current:Chequing    CAD 50000.00
    Equity:Share Capital       CAD -50000.00

2026-02-05 * Rent
    Expenses:Operating:Rent    CAD 1000.00
    Assets:Current:Chequing   CAD -1000.00
"""

REGISTER = {
    'classes': [{'id': 'common', 'name': 'Common', 'kind': 'common'},
                {'id': 'seed', 'name': 'Seed Preferred', 'kind': 'preferred'}],
    'holders': [{'id': 'ana', 'name': 'Ana Diaz', 'group': 'founder'},
                {'id': 'bob', 'name': 'Bob Lee', 'group': 'investor'}],
    'issuances': [{'date': '2026-01-10', 'holder': 'ana', 'class': 'common',
                   'shares': 1000, 'price': 1},
                  {'date': '2026-02-10', 'holder': 'bob', 'class': 'seed',
                   'shares': 1000, 'price': 5}],
    'pool': {'size': 100},
    'grants': [],
    'instruments': [],
}


def _register(tmp_path):
    d = tmp_path / 'captable'
    d.mkdir()
    (d / 'register.yaml').write_text(yaml.dump(REGISTER))
    return tmp_path


def _journal(tmp_path):
    p = tmp_path / 'test.journal'
    p.write_text(JOURNAL)
    return str(p)


def _config(tmp_path):
    return {'pair': {'currency': 'CAD'}, 'journal_file': _journal(tmp_path)}


def _entity(tmp_path):
    _register(tmp_path)
    K.set_value(tmp_path, 'paying_customers', '2026-01', 10)
    K.set_value(tmp_path, 'paying_customers', '2026-02', 25)
    K.set_value(tmp_path, 'mrr', '2026-01', 500)
    return tmp_path


# ─── ownership over time (pure) ───────────────────────────────────────────────

def test_founder_pct_by_month_from_dated_issuances():
    reg = C.normalise(REGISTER)
    out = C.founder_pct_by_month(reg, ['2025-12', '2026-01', '2026-02', '2026-03'])
    assert out['2025-12'] is None  # nothing issued yet
    # Jan: 1000 founder shares of 1100 fully diluted (1000 + pool 100).
    assert out['2026-01'] == pytest.approx(D(1000) / D(1100))
    # Feb: 1000 of 2100.
    assert out['2026-02'] == pytest.approx(D(1000) / D(2100))
    assert out['2026-03'] == pytest.approx(D(1000) / D(2100))


def test_founder_pct_by_month_undated_counts_always():
    reg = C.normalise({**REGISTER, 'issuances': [
        {'holder': 'ana', 'class': 'common', 'shares': 1000, 'price': 1}]})
    out = C.founder_pct_by_month(reg, ['2025-12'])
    assert out['2025-12'] == pytest.approx(D(1000) / D(1100))


def test_founder_pct_by_month_grants_dilute():
    reg = C.normalise({**REGISTER, 'grants': [
        {'date': '2026-02-15', 'holder': 'bob', 'shares': 100, 'strike': 1}]})
    out = C.founder_pct_by_month(reg, ['2026-01', '2026-02'])
    assert out['2026-01'] == pytest.approx(D(1000) / D(1100))
    # Feb: issued 2000 + granted 100, pool available drops to 0 (100 - 100).
    assert out['2026-02'] == pytest.approx(D(1000) / D(2100))


# ─── builder ──────────────────────────────────────────────────────────────────

@needs_hledger
def test_build_combines_traction_ownership_cash(tmp_path):
    from modules.traction import build
    data = build(_config(tmp_path), 'paying_customers', 2, '2026-02', _entity(tmp_path))
    assert data['months'] == ['2026-01', '2026-02']
    assert data['traction'] == {'2026-01': 10, '2026-02': 25}
    assert data['ownership']['2026-01'] == pytest.approx(1000 / 1100)
    assert data['ownership']['2026-02'] == pytest.approx(1000 / 2100)
    assert data['cash'] == {'2026-01': 50000, '2026-02': 49000}
    assert data['has_captable'] is True
    assert any(m['id'] == 'paying_customers' and m['has_data'] for m in data['metrics'])


@needs_hledger
def test_build_unknown_metric_is_400(tmp_path):
    from modules.traction import build
    with pytest.raises(ValueError):
        build(_config(tmp_path), 'nope', 2, '2026-02', _entity(tmp_path))


@needs_hledger
def test_build_without_captable_has_null_ownership(tmp_path):
    from modules.traction import build
    K.set_value(tmp_path, 'paying_customers', '2026-01', 10)
    data = build(_config(tmp_path), 'paying_customers', 2, '2026-02', tmp_path)
    assert data['has_captable'] is False
    assert data['ownership'] == {'2026-01': None, '2026-02': None}
    assert data['traction']['2026-01'] == 10


# ─── CLI + web ────────────────────────────────────────────────────────────────

@needs_hledger
def test_cli_traction_table(tmp_path, monkeypatch, capsys):
    import modules.traction as T
    config = _config(tmp_path)
    monkeypatch.setattr(T, 'load_config', lambda: config)
    monkeypatch.setattr(T, 'get_entity_dir', lambda: _entity(tmp_path))
    T.dispatch(['--metric', 'paying_customers', '--months', '2', '--end', '2026-02'])
    out = capsys.readouterr().out
    assert '2026-01' in out and '10' in out and '49,000' in out
    assert '90.9%' in out  # founder % in Jan


@pytest.fixture
def client(tmp_path, monkeypatch):
    import modules.traction as T
    config = _config(tmp_path)
    monkeypatch.setattr(web, 'load_config', lambda: config)
    monkeypatch.setattr(T, 'get_entity_dir', lambda: _entity(tmp_path))
    return TestClient(web.create_app())


@needs_hledger
def test_web_traction_chart(client):
    r = client.get('/api/chart/traction?metric=paying_customers&months=2&end=2026-02')
    assert r.status_code == 200
    d = r.json()
    assert d['months'] == ['2026-01', '2026-02']
    assert d['traction'] == {'2026-01': 10, '2026-02': 25}
    assert d['cash'] == {'2026-01': 50000, '2026-02': 49000}
    assert d['ownership']['2026-01'] == pytest.approx(1000 / 1100)
    assert any(m['id'] == 'mrr' for m in d['metrics'])


@needs_hledger
def test_web_traction_unknown_metric_is_400(client):
    r = client.get('/api/chart/traction?metric=nope')
    assert r.status_code == 400


@needs_hledger
def test_web_traction_default_metric(client):
    r = client.get('/api/chart/traction?months=2&end=2026-02')
    assert r.status_code == 200
    assert r.json()['metric'] == 'paying_customers'
