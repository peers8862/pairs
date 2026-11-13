from decimal import Decimal as D

from lib.statements import build


def test_pl_lines_by_category_and_pace():
    rows = [{'month': '2026-10', 'source': 'actual', 'revenue': D(500), 'expense': D(1300), 'funding': D(0), 'begin': D(5000), 'end': D(4200)},
            {'month': '2026-11', 'source': 'plan', 'revenue': D(800), 'expense': D(2400), 'funding': D(10000), 'begin': D(4200), 'end': D(12600)}]
    actual = {'2026-10': {'Expenses:Operating:Payroll:Salaries': D(1000), 'Expenses:COGS': D(100), 'Expenses:Operating:Rent': D(200)}}
    plan = {'2026-11': {'Expenses:Operating:Marketing': D(400)}}
    out = build(rows, actual, plan, D(2000), 'add')
    line = {l['key']: l['values'] for l in out['lines']}
    assert line['gross']['2026-10'] == D(400) and line['Salaries & Benefits']['2026-10'] == D(1000)
    assert line['pace']['2026-11'] == D(2000) and line['Marketing & Sales']['2026-11'] == D(400)
    assert line['net']['2026-11'] == D(800) - D(2400)
    assert line['cash_end']['2026-11'] == D(12600)
    assert out['sources'] == {'2026-10': 'actual', '2026-11': 'plan'}


def test_unexplained_expense_goes_to_last_category():
    rows = [{'month': '2027-01', 'source': 'plan', 'revenue': D(0), 'expense': D(300), 'funding': D(0), 'begin': D(0), 'end': D(-300)}]
    out = build(rows, {}, {}, D(0), 'replace')
    line = {l['key']: l['values'] for l in out['lines']}
    assert line['Overhead']['2027-01'] == D(300) and 'pace' not in line
