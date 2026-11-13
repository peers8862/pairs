from datetime import date
from decimal import Decimal

from lib.plan_rules import expand, validate, monthly_totals, occurrence_dates, describe, journal_text
from lib.categories import category_for, summarise


def _r(**kw):
    base = {'id': 'r1', 'name': 'x', 'kind': 'expense', 'driver': 'fixed', 'amount': 100,
            'start': '2026-01-15', 'every': 'monthly', 'months': 3}
    base.update(kw)
    return base


def test_fixed_monthly_for_n_months():
    occ = expand([_r()])
    assert [o['date'] for o in occ] == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
    assert all(o['amount'] == Decimal('100.00') for o in occ)


def test_end_date_is_inclusive_and_once():
    assert len(occurrence_dates(_r(months=None, end='2026-03-15'))) == 3
    assert occurrence_dates(_r(every='once', months=12)) == [date(2026, 1, 15)]


def test_growth_compounds_each_occurrence():
    amounts = [o['amount'] for o in expand([_r(driver='growth', rate=0.1)])]
    assert amounts == [Decimal('100.00'), Decimal('110.00'), Decimal('121.00')]


def test_step_changes_from_date():
    occ = expand([_r(driver='step', steps=[{'from': '2026-02-01', 'amount': 150}])])
    assert [o['amount'] for o in occ] == [Decimal('100.00'), Decimal('150.00'), Decimal('150.00')]


def test_percent_of_revenue_same_month():
    rev = _r(id='rev', kind='revenue', account='Income:Sales', amount=1000, driver='growth', rate=1)
    fee = _r(id='fee', driver='percent', percent=0.03, amount=None, account='Expenses:Fees')
    fees = [o['amount'] for o in expand([fee, rev]) if o['rule'] == 'fee']
    assert fees == [Decimal('30.00'), Decimal('60.00'), Decimal('120.00')]


def test_percent_of_named_rule():
    base = _r(id='ads', amount=200)
    agency = _r(id='ag', driver='percent', percent=0.5, of='ads')
    assert [o['amount'] for o in expand([base, agency]) if o['rule'] == 'ag'] == [Decimal('100.00')] * 3


def test_units_with_cost_creates_cogs_line():
    r = _r(kind='revenue', account='Income:Sales', driver='units', units=10, price=5,
           unit_growth=0.5, unit_cost=2, months=2)
    occ = expand([r])
    rev = [o['amount'] for o in occ if o['kind'] == 'revenue']
    cost = [o['amount'] for o in occ if o['kind'] == 'expense']
    assert rev == [Decimal('50.00'), Decimal('75.00')] and cost == [Decimal('20.00'), Decimal('30.00')]


def test_salary_monthly_with_benefits_and_yearly_raise_and_setup():
    r = _r(driver='salary', amount=None, salary=120000, benefits=0.1, raise_=None, months=13,
           setup_cost=1500)
    r['raise'] = 0.05
    occ = expand([r])
    pay = [o['amount'] for o in occ if o['name'] == 'x']
    assert pay[0] == Decimal('11000.00') and pay[12] == Decimal('11550.00') and len(pay) == 13
    assert any(o['name'] == 'x (setup)' and o['amount'] == Decimal('1500.00') for o in occ)


def test_funding_uses_instrument_account_and_totals():
    occ = expand([_r(kind='funding', instrument='safe', amount=50000, every='once')])
    assert occ[0]['account'] == 'Equity:SAFE'
    assert monthly_totals(occ)['2026-01']['funding'] == Decimal('50000.00')


def test_validation_catches_bad_input():
    assert validate(_r(kind='nope'))
    assert validate(_r(rate=5.0 * 3))
    assert validate(_r(kind='revenue', driver='percent'))
    assert validate(_r(end='2025-01-01'))
    assert not validate(_r())


def test_disabled_rules_are_skipped():
    assert expand([_r(disabled=True)]) == []


def test_journal_text_signs_and_tags():
    occ = expand([_r(every='once'), _r(id='r2', kind='revenue', account='Income:Sales', every='once')])
    text = journal_text('demo', occ, 'CAD', 'Assets:Bank')
    assert 'scenario:demo' in text and 'rule:r1' in text and 'rule:r2' in text
    assert 'Expenses:Operating:Other' in text and 'Income:Sales' in text


def test_describe_reads_well():
    assert 'growth' not in describe(_r(driver='growth', rate=0.05))
    assert '5% change each time' in describe(_r(driver='growth', rate=0.05))


def test_categories_default_and_custom():
    assert category_for('Expenses:Operating:Payroll:Salaries') == 'Salaries & Benefits'
    assert category_for('Expenses:Operating:Rent') == 'Overhead'
    cfg = {'report_categories': {'People': ['Expenses:Operating:Payroll'], 'Other': ['Expenses']}}
    assert category_for('Expenses:Operating:Payroll:Benefits', cfg) == 'People'
    assert summarise({'Expenses:Operating:Rent': 5, 'Expenses:Operating:Marketing': 3})['Overhead'] == 5
