"""KPI starting column and unit retention (I56), two parts.

Part 1 — starting column: an opt-in first column in the KPI grid showing
each metric's value in the month before the window opens (the opening value
for stock metrics, the previous month for flow metrics). Off by default, so
existing output is unchanged. `pair kpi --start`, `GET /api/kpis?start=1`,
checkbox in the web KPIs tab.

Part 2 — retention on per-product unit lines: a `units` rule takes an
optional `retention` fraction (0-1). Active units compound across periods:

    active[i] = new[i] + retention * active[i-1]
    new[i]    = units * (1 + unit_growth) ** i

Revenue is active units x price; the unit-cost (COGS) line stays on new
units only — COGS is paid on units sold that period, not on the retained
base. Without retention the rule behaves exactly as before.
"""

from decimal import Decimal as D

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

from lib import kpi as K
from lib.plan_rules import expand, validate
import modules.kpi as KM
import modules.web as web  # noqa: E402

CONFIG = {'pair': {'currency': 'CAD'}}


# ─── Part 1: starting column ──────────────────────────────────────────────────

def test_build_start_column_off_by_default(tmp_path):
    data = KM.build(CONFIG, tmp_path, end='2026-06', months=3)
    assert data.get('start_month') is None
    assert data['months'] == ['2026-04', '2026-05', '2026-06']


def test_build_start_column_adds_prior_month(tmp_path):
    K.set_value(tmp_path, 'mrr', '2026-03', 500)
    K.set_value(tmp_path, 'mrr', '2026-04', 600)
    data = KM.build(CONFIG, tmp_path, end='2026-06', months=3, start_column=True)
    assert data['start_month'] == '2026-03'
    assert data['months'] == ['2026-04', '2026-05', '2026-06']
    assert data['cells']['mrr']['2026-03']['value'] == D(500)
    assert data['cells']['mrr']['2026-04']['value'] == D(600)
    # A derived metric can use the start month as history.
    assert data['cells']['arr']['2026-03']['value'] == D(6000)


def test_cli_show_start_column(tmp_path, monkeypatch, capsys):
    import modules.kpi as KM
    K.set_value(tmp_path, 'mrr', '2026-03', 500)
    monkeypatch.setattr(KM, 'load_config', lambda: CONFIG)
    monkeypatch.setattr(KM, 'get_entity_dir', lambda: tmp_path)
    KM.dispatch(['show', '--months', '2', '--end', '2026-05', '--start'])
    out = capsys.readouterr().out
    assert 'Start' in out and '500' in out


def test_cli_show_without_start_has_no_start_column(tmp_path, monkeypatch, capsys):
    import modules.kpi as KM
    K.set_value(tmp_path, 'mrr', '2026-03', 500)
    monkeypatch.setattr(KM, 'load_config', lambda: CONFIG)
    monkeypatch.setattr(KM, 'get_entity_dir', lambda: tmp_path)
    KM.dispatch(['show', '--months', '2', '--end', '2026-05'])
    assert 'Start' not in capsys.readouterr().out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'load_config', lambda: CONFIG)
    # build() reads the entity dir for definitions/values; point it at tmp.
    import modules.kpi as KM
    import lib.features as F
    monkeypatch.setattr(KM, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(F, 'is_enabled', lambda name: True)
    return TestClient(web.create_app())


def test_web_kpis_start_param(tmp_path, client):
    K.set_value(tmp_path, 'mrr', '2026-03', 500)
    r = client.get('/api/kpis?months=2&end=2026-05&start=1')
    assert r.status_code == 200
    d = r.json()
    assert d['start_month'] == '2026-03'
    mrr = next(x for x in d['metrics'] if x['id'] == 'mrr')
    assert mrr['cells']['2026-03']['value'] == 500
    r = client.get('/api/kpis?months=2&end=2026-05')
    assert r.json().get('start_month') is None


# ─── Part 2: retention on units rules ─────────────────────────────────────────

def _units_rule(**extra):
    rule = {'name': 'Widget', 'kind': 'revenue', 'driver': 'units', 'units': 100,
            'price': 10, 'unit_growth': 0, 'start': '2027-01-01', 'months': 3}
    rule.update(extra)
    return rule


def test_units_without_retention_unchanged():
    occ = [o for o in expand([_units_rule()]) if o['kind'] == 'revenue']
    assert [float(o['amount']) for o in occ] == [1000, 1000, 1000]


def test_units_retention_compounds_active_base():
    occ = [o for o in expand([_units_rule(retention=0.9)]) if o['kind'] == 'revenue']
    assert [float(o['amount']) for o in occ] == [1000, 1900, 2710]


def test_units_retention_one_keeps_everything():
    occ = [o for o in expand([_units_rule(retention=1)]) if o['kind'] == 'revenue']
    assert [float(o['amount']) for o in occ] == [1000, 2000, 3000]


def test_units_retention_with_growth():
    occ = [o for o in expand([_units_rule(unit_growth=0.1, retention=0.5)])
           if o['kind'] == 'revenue']
    # new: 100, 110, 121; active: 100, 160, 201; revenue x10.
    assert [float(o['amount']) for o in occ] == [1000, 1600, 2010]


def test_units_retention_cost_stays_on_new_units():
    occ = expand([_units_rule(retention=0.9, unit_cost=2)])
    cost = [o for o in occ if o['kind'] == 'expense']
    assert [float(o['amount']) for o in cost] == [200, 200, 200]


def test_retention_validated():
    assert validate(_units_rule(retention=0.9)) == []
    assert validate(_units_rule(retention=1.5)) != []
    assert validate(_units_rule(retention=-0.1)) != []
    assert validate(_units_rule(retention='x')) != []
    fixed = {'name': 'Rent', 'amount': 100, 'start': '2027-01-01', 'months': 1,
             'retention': 0.9}
    assert validate(fixed) != []  # retention only means something on units


def test_cli_rule_flag_parses_retention():
    from modules.scenario import rule_from_args
    rule = rule_from_args(['--name', 'Widget', '--kind', 'revenue', '--driver', 'units',
                           '--units', '100', '--price', '10', '--retention', '0.9',
                           '--start', '2027-01-01', '--months', '3'])
    assert rule['retention'] == 0.9


def test_scenario_monthly_uses_retained_units(tmp_path, monkeypatch):
    import modules.scenario as sc
    monkeypatch.setattr(sc, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(sc, 'load_config', lambda: CONFIG)
    slug = sc.create_scenario('Prod')
    sc.add_rule(slug, _units_rule())
    sc.add_rule(slug, {'name': 'Widget B', 'kind': 'revenue', 'driver': 'units',
                       'units': 100, 'price': 10, 'unit_growth': 0, 'retention': 0.9,
                       'start': '2027-01-01', 'months': 3})
    months, _ = sc.scenario_monthly(slug)
    # A (no retention) 1000/mo + B (retained) 1000/1900/2710.
    assert [float(months[m]['revenue']) for m in ('2027-01', '2027-02', '2027-03')] == \
        [2000, 2900, 3710]
