from decimal import Decimal as D

from lib.runway import project, sources_and_uses, add_months, months_between
from modules.budget import project_with_scenario


def _plan(**months):
    return {k[1:].replace('_', '-'): {'revenue': D(v[0]), 'expense': D(v[1]), 'funding': D(v[2])}
            for k, v in months.items()}


def test_month_helpers():
    assert add_months('2026-11', 3) == '2027-02'
    assert months_between('2026-11', '2027-01') == ['2026-11', '2026-12', '2027-01']


def test_standalone_replace_runs_out_with_partial_month():
    rows, s = project({}, _plan(m2027_01=(0, 1000, 0), m2027_02=(0, 1000, 0), m2027_03=(0, 1000, 0)),
                      '2027-01', 3, starting_cash=1500, mode='replace')
    assert [r['end'] for r in rows] == [D(500), D(-500), D(-1500)]
    assert s['cash_out_month'] == '2027-02'
    assert s['runway_months'] == D('1.5')


def test_add_mode_uses_recent_pace_from_books():
    actual = {'2026-09': {'revenue': D(100), 'expense': D(400), 'cash_end': D(10000)},
              '2026-10': {'revenue': D(100), 'expense': D(400), 'cash_end': D(9700)}}
    rows, s = project(actual, _plan(m2026_11=(0, 1000, 0)), '2026-11', 2, mode='add', trailing=2)
    plan = [r for r in rows if r['source'] == 'plan']
    assert plan[0]['begin'] == D(9700)
    assert plan[0]['expense'] == D(1400) and plan[1]['expense'] == D(400)
    assert s['base_expense'] == D(400)
    assert rows[1]['funding'] == D(0)          # cash change fully explained by net


def test_actual_other_cash_shows_as_funding():
    actual = {'2026-09': {'revenue': D(0), 'expense': D(0), 'cash_end': D(1000)},
              '2026-10': {'revenue': D(0), 'expense': D(500), 'cash_end': D(50500)}}
    rows, _ = project(actual, {}, '2026-11', 1, mode='replace')
    assert rows[1]['funding'] == D(50000)


def test_funding_extends_runway_and_raise_target_uses_buffer():
    plan = _plan(m2027_01=(0, 1000, 0), m2027_02=(0, 1000, 5000))
    rows, s = project({}, plan, '2027-01', 2, starting_cash=1500, mode='replace', buffer_months=15)
    assert s['cash_out_month'] is None and s['runway_text'] == 'beyond the projection'
    assert s['raise_target'] == D(15000)


def test_breakeven_and_floor():
    plan = _plan(m2027_01=(500, 1000, 0), m2027_02=(1200, 1000, 0))
    _, s = project({}, plan, '2027-01', 2, starting_cash=2000, mode='replace', min_cash_months=2)
    assert s['breakeven_month'] == '2027-02'
    assert s['floor'] == D(2000) and s['below_floor_month'] == '2027-01'


def test_sources_and_uses_split():
    rows, covers = sources_and_uses(12000, {'People': D(6000), 'Overhead': D(2000)}, 4)
    assert [(n, a) for n, _, a in rows] == [('People', D(9000)), ('Overhead', D(3000))]
    assert covers == D(6)


def test_budget_forecast_adds_scenario_to_run_rate():
    assert project_with_scenario(D(600), 6, 12, D(100)) == D(1300)
    assert project_with_scenario(D(0), 0, 12, D(100)) == D(100)
