"""Runway what-if sliders (I55) — preview-only multipliers and shifts.

Growth has sliders that scale the model before previewing; Runway gets the
same treatment, without persisting anything:

- revenue x / cost x: multipliers on the projected revenue / expense of every
  planned month (plan amounts plus the recent-pace base in 'add' mode).
  Funding is untouched.
- hire delay: salary-driver rules start N months later (amounts shift, the
  hire itself is unchanged).
- revenue start shift: revenue occurrences start N months later.

The sliders live on the query string of GET /api/runway (rev, cost,
hire_delay, rev_shift) and as flags on `pair runway`; the saved scenario and
the books are never written. Tests here are the contract: lib-level
projection, scenario-level shifts, build() end to end, and the web endpoint.
"""

from decimal import Decimal as D

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import modules.runway as RW  # noqa: E402
import modules.scenario as sc  # noqa: E402
import modules.web as web  # noqa: E402
from lib.runway import project  # noqa: E402

CONFIG = {'pair': {'currency': 'CAD'}, 'accounts': {'bank': 'Assets:Current:Chequing'}}


def _plan(**months):
    return {k[1:].replace('_', '-'): {'revenue': D(v[0]), 'expense': D(v[1]), 'funding': D(v[2])}
            for k, v in months.items()}


# ─── lib-level multipliers ────────────────────────────────────────────────────

def test_rev_mult_scales_projected_revenue():
    rows, _ = project({}, _plan(m2027_01=(1000, 500, 0), m2027_02=(1000, 500, 0)),
                      '2027-01', 2, starting_cash=0, mode='replace', rev_mult=D('1.5'))
    assert [r['revenue'] for r in rows] == [D('1500'), D('1500')]
    assert [r['end'] for r in rows] == [D('1000'), D('2000')]


def test_cost_mult_scales_projected_expense():
    rows, _ = project({}, _plan(m2027_01=(1000, 500, 0)),
                      '2027-01', 1, starting_cash=0, mode='replace', exp_mult=D('2'))
    assert rows[0]['expense'] == D('1000')
    assert rows[0]['end'] == D('0')


def test_mults_scale_base_pace_in_add_mode():
    actual = {'2026-10': {'revenue': D(100), 'expense': D(400), 'cash_end': D(10000)}}
    rows, _ = project(actual, {}, '2026-11', 1, mode='add', trailing=1,
                      rev_mult=D('2'), exp_mult=D('0.5'))
    assert rows[1]['revenue'] == D('200') and rows[1]['expense'] == D('200')


def test_mults_leave_funding_alone():
    rows, _ = project({}, _plan(m2027_01=(0, 0, 5000)),
                      '2027-01', 1, starting_cash=0, mode='replace', rev_mult=D('3'), exp_mult=D('3'))
    assert rows[0]['funding'] == D('5000') and rows[0]['end'] == D('5000')


def test_negative_mult_rejected():
    with pytest.raises(ValueError):
        project({}, _plan(m2027_01=(100, 100, 0)), '2027-01', 1,
                starting_cash=0, mode='replace', rev_mult=D('-1'))
    with pytest.raises(ValueError):
        project({}, _plan(m2027_01=(100, 100, 0)), '2027-01', 1,
                starting_cash=0, mode='replace', exp_mult=D('-0.5'))


def test_zero_mult_is_allowed():
    rows, _ = project({}, _plan(m2027_01=(1000, 500, 0)),
                      '2027-01', 1, starting_cash=0, mode='replace', rev_mult=D('0'))
    assert rows[0]['revenue'] == D('0') and rows[0]['end'] == D('-500')


# ─── scenario-level shifts ────────────────────────────────────────────────────

@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(sc, 'load_config', lambda: CONFIG)
    return tmp_path


def _mix(entity):
    slug = sc.create_scenario('Mix')
    sc.add_rule(slug, {'name': 'Dev', 'driver': 'salary', 'salary': 120000,
                       'start': '2027-01-01', 'months': 2})
    sc.add_rule(slug, {'name': 'Rent', 'account': 'Expenses:Rent', 'amount': 1000,
                       'start': '2027-01-01', 'months': 2})
    sc.add_rule(slug, {'name': 'Sales', 'kind': 'revenue', 'account': 'Income:Sales',
                       'amount': 500, 'start': '2027-01-01', 'months': 2})
    return slug


def test_hire_delay_shifts_only_salary_rules(entity):
    slug = _mix(entity)
    months, _ = sc.scenario_monthly(slug, whatif={'hire_delay': 1})
    # Dev: 120000/12 = 10000/mo (no benefits set); was Jan/Feb, now Feb/Mar.
    assert float(months['2027-01']['expense']) == 1000  # rent only
    assert float(months['2027-02']['expense']) == 11000  # rent 1000 + dev 10000
    assert float(months['2027-03']['expense']) == 10000  # dev only
    assert float(months['2027-01']['revenue']) == 500  # revenue untouched


def test_revenue_shift_moves_revenue_only(entity):
    slug = _mix(entity)
    months, _ = sc.scenario_monthly(slug, whatif={'revenue_shift': 2})
    assert float(months['2027-01']['revenue']) == 0
    assert float(months['2027-02']['revenue']) == 0
    assert float(months['2027-03']['revenue']) == 500
    assert float(months['2027-04']['revenue']) == 500
    assert float(months['2027-01']['expense']) == 11000  # dev + rent, unshifted


def test_whatif_zero_is_a_noop(entity):
    slug = _mix(entity)
    plain, _ = sc.scenario_monthly(slug)
    shifted, _ = sc.scenario_monthly(slug, whatif={'hire_delay': 0, 'revenue_shift': 0})
    assert shifted == plain


def test_negative_shift_rejected(entity):
    slug = _mix(entity)
    with pytest.raises(ValueError):
        sc.scenario_monthly(slug, whatif={'hire_delay': -1})
    with pytest.raises(ValueError):
        sc.scenario_monthly(slug, whatif={'revenue_shift': -2})


# ─── build() end to end ───────────────────────────────────────────────────────

def test_build_applies_whatif_without_touching_saved_scenario(entity):
    slug = _mix(entity)
    data = RW.build(CONFIG, slug, 3, 'replace', start='2027-01',
                    whatif={'revenue_mult': D('2'), 'cost_mult': D('1'),
                            'hire_delay': 1, 'revenue_shift': 0})
    plan = [r for r in data['rows'] if r['source'] == 'plan']
    assert [r['revenue'] for r in plan] == [D('1000'), D('1000'), D('0')]
    assert [r['expense'] for r in plan] == [D('1000'), D('11000'), D('10000')]
    # Saved scenario unchanged: re-reading without whatif gives the original.
    months, _ = sc.scenario_monthly(slug)
    assert float(months['2027-01']['expense']) == 11000


# ─── web endpoint ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(entity, tmp_path, monkeypatch):
    import lib.features as F
    monkeypatch.setattr(web, 'load_config', lambda: CONFIG)
    monkeypatch.setattr(F, 'is_enabled', lambda name: True)
    return TestClient(web.create_app())


def test_web_runway_whatif_params(client, entity):
    slug = _mix(entity)
    r = client.get(f'/api/runway?scenario={slug}&mode=replace&start=2027-01&months=3'
                   f'&rev=2&cost=1&hire_delay=1&rev_shift=0')
    assert r.status_code == 200
    rows = [x for x in r.json()['rows'] if x['source'] == 'plan']
    assert [x['revenue'] for x in rows] == [1000, 1000, 0]
    assert [x['expense'] for x in rows] == [1000, 11000, 10000]


def test_web_runway_whatif_defaults_are_neutral(client, entity):
    slug = _mix(entity)
    plain = client.get(f'/api/runway?scenario={slug}&mode=replace&start=2027-01&months=3')
    with_params = client.get(f'/api/runway?scenario={slug}&mode=replace&start=2027-01&months=3'
                             f'&rev=1&cost=1&hire_delay=0&rev_shift=0')
    assert plain.status_code == 200 == with_params.status_code
    assert plain.json()['rows'] == with_params.json()['rows']


def test_web_runway_whatif_bad_values_are_400(client, entity):
    slug = _mix(entity)
    for q in ('rev=-1', 'cost=-2', 'hire_delay=-1', 'rev_shift=-1', 'rev=abc', 'hire_delay=1.5'):
        r = client.get(f'/api/runway?scenario={slug}&mode=replace&start=2027-01&months=3&{q}')
        assert r.status_code == 400, q
