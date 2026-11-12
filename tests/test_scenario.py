import shutil
from datetime import date
from decimal import Decimal

import pytest

from modules.scenario import (
    build_scenario_entries, step_month, account_balances,
    scenario_report_rows, find_scenario_includes,
)

needs_hledger = pytest.mark.skipif(shutil.which('hledger') is None,
                                   reason="hledger not installed")

REAL = """2026-01-05 * Rent  ; pair:0000
    Expenses:Operating:Rent                             CAD 1000.00
    Assets:Current:Chequing                             CAD -1000.00

"""


def _entries(**kw):
    args = dict(slug='studio', start='2026-03-01', description='Studio lease',
                account='Expenses:Operating:Rent', amount=1800,
                source_account='Assets:Current:Chequing', currency='CAD')
    args.update(kw)
    return build_scenario_entries(**args)


def test_single_entry_is_tagged_and_balanced():
    [entry] = _entries()
    assert entry.startswith('2026-03-01 * Studio lease')
    assert 'scenario:studio' in entry
    assert 'Expenses:Operating:Rent' in entry and 'CAD 1800.00' in entry
    assert 'Assets:Current:Chequing' in entry and 'CAD -1800.00' in entry


def test_repeat_makes_one_entry_per_month():
    entries = _entries(start='2026-03-15', repeat=3)
    assert [e[:10] for e in entries] == ['2026-03-15', '2026-04-15', '2026-05-15']


def test_step_month_clamps_to_month_end():
    assert step_month(date(2026, 1, 31), 1, 31) == date(2026, 2, 28)
    assert step_month(date(2026, 3, 15), 1, 15) == date(2026, 4, 15)
    assert step_month(date(2026, 11, 10), 2, 10) == date(2027, 1, 10)


def test_repeat_must_be_positive():
    with pytest.raises(ValueError):
        _entries(repeat=0)


@needs_hledger
def test_report_keeps_scenario_out_of_actuals(tmp_path):
    real = tmp_path / 'company.journal'
    real.write_text(REAL)
    scen = tmp_path / 'expenses.journal'
    scen.write_text(''.join(_entries(repeat=2)))

    actual = account_balances([real], ['^Expenses'])
    assert actual == {'Expenses:Operating:Rent': Decimal('1000.00')}

    rows = scenario_report_rows(real, scen, 'studio')
    assert rows == [('Expenses:Operating:Rent',
                     Decimal('1000.00'), Decimal('3600.00'), Decimal('4600.00'))]


@needs_hledger
def test_report_works_without_real_journal(tmp_path):
    scen = tmp_path / 'expenses.journal'
    scen.write_text(''.join(_entries()))
    rows = scenario_report_rows(tmp_path / 'missing.journal', scen, 'studio')
    assert rows == [('Expenses:Operating:Rent',
                     Decimal('0'), Decimal('1800.00'), Decimal('1800.00'))]


def test_guard_finds_includes_of_scenario_files(tmp_path):
    inc = tmp_path / 'include'
    inc.mkdir()
    (inc / '2026.journal').write_text('include ../generated/2026/expenses.journal\n')
    assert find_scenario_includes(tmp_path) == []
    (inc / '2027.journal').write_text('include ../scenarios/studio/expenses.journal\n')
    assert [p.name for p in find_scenario_includes(tmp_path)] == ['2027.journal']


@needs_hledger
def test_budget_actuals_include_scenario_only_when_asked(tmp_path, monkeypatch):
    import modules.scenario as scenario
    from modules.budget import _get_actual_for_periods
    monkeypatch.setattr(scenario, 'get_entity_dir', lambda: tmp_path)
    real = tmp_path / 'company.journal'
    real.write_text(REAL)
    scen = scenario.scenario_journal('studio')
    scen.parent.mkdir(parents=True)
    scen.write_text(''.join(_entries(repeat=2)))
    config = {'journal_file': str(real)}
    year = [{'label': '2026', 'from': '2026-01-01', 'to': '2027-01-01'}]

    assert _get_actual_for_periods(config, 'Expenses:Operating:Rent', year) == Decimal('1000.00')
    assert _get_actual_for_periods(config, 'Expenses:Operating:Rent', year,
                                   scenario='studio') == Decimal('4600.00')


def test_create_list_and_remove_entries(tmp_path, monkeypatch):
    import modules.scenario as scenario
    monkeypatch.setattr(scenario, 'get_entity_dir', lambda: tmp_path)
    slug = scenario.create_scenario('Studio move', 'Lease from March')
    assert slug == 'studio-move'
    assert scenario.list_scenarios() == ['studio-move']
    with pytest.raises(ValueError):
        scenario.create_scenario('Studio move')

    scenario.add_entries(slug, _entries(slug=slug, repeat=2)
                         + _entries(slug=slug, description='Camera',
                                    account='Expenses:Operating:Equipment', amount=3200))
    items = scenario.read_entries(slug)
    assert [(i['date'], i['description'], i['account'], i['amount']) for i in items] == [
        ('2026-03-01', 'Studio lease', 'Expenses:Operating:Rent', Decimal('1800.00')),
        ('2026-04-01', 'Studio lease', 'Expenses:Operating:Rent', Decimal('1800.00')),
        ('2026-03-01', 'Camera', 'Expenses:Operating:Equipment', Decimal('3200.00')),
    ]
    scenario.remove_entry(slug, 1)
    assert [i['date'] for i in scenario.read_entries(slug)] == ['2026-03-01', '2026-03-01']
    with pytest.raises(IndexError):
        scenario.remove_entry(slug, 5)


@needs_hledger
def test_budget_vs_rows_measures_variance_against_scenario(tmp_path, monkeypatch):
    import modules.scenario as scenario
    from modules.budget import budget_vs_rows
    monkeypatch.setattr(scenario, 'get_entity_dir', lambda: tmp_path)
    real = tmp_path / 'company.journal'
    real.write_text(REAL)
    scen = scenario.scenario_journal('studio')
    scen.parent.mkdir(parents=True)
    scen.write_text(''.join(_entries(repeat=2)))
    budget = {'periods': [{'label': 'H1', 'from': '2026-01-01', 'to': '2026-07-01'},
                          {'label': 'H2', 'from': '2026-07-01', 'to': '2027-01-01'}],
              'lines': [{'account': 'Expenses:Operating:Rent', 'amounts': [3000, 3000]}]}
    config = {'journal_file': str(real)}

    [plain] = budget_vs_rows(config, budget)
    assert (plain['budget'], plain['actual'], plain['with_scenario'], plain['variance']) == (
        Decimal('6000'), Decimal('1000.00'), None, Decimal('5000.00'))
    [scn] = budget_vs_rows(config, budget, scenario='studio')
    assert (scn['with_scenario'], scn['variance']) == (Decimal('4600.00'), Decimal('1400.00'))
