"""I35 — projected balance sheet: full O24/O25 driver set (D20).

Drivers, all derived from scenario assumptions and the existing
runway/scenario/ledger sources — never hand-entered lines:

- working capital: receivables/payables/inventory from DSO/DPO/DIO days
- equipment/depreciation: hires x cost per hire, straight-line over useful life
- debt/interest: debt balance from funding split, interest on debt and on cash
- tax loss carryforward: losses offset later taxable profit

The balance sheet must balance every month (assets == liabilities + equity)
and cash must tie out: dCash = operating + investing + financing.
"""
import shutil
from decimal import Decimal as D

import pytest

from lib import statements as ST

needs_hledger = pytest.mark.skipif(
    shutil.which('hledger') is None, reason='hledger is not installed')


# ─── helpers ────────────────────────────────────────────────────────────────

def _monthly(month, revenue=0, cogs=0, opex=0, nonop=0, funding=0, split=None,
             hires=0, source='plan'):
    return {'month': month, 'source': source, 'revenue': D(revenue), 'cogs': D(cogs),
            'opex': D(opex), 'nonop': D(nonop), 'funding': D(funding),
            'funding_split': split or {'equity': D(0), 'safe': D(0), 'debt': D(0),
                                       'note': D(0), 'grant': D(0)},
            'hires': hires}


def _split(**over):
    s = {'equity': D(0), 'safe': D(0), 'debt': D(0), 'note': D(0), 'grant': D(0)}
    s.update({k: D(v) for k, v in over.items()})
    return s


def _opening(**over):
    o = {'cash': D(0), 'receivables': D(0), 'inventory': D(0), 'ppe_gross': D(0),
         'accum_depreciation': D(0), 'other_assets': D(0), 'payables': D(0),
         'debt': D(0), 'other_liabilities': D(0), 'share_capital': D(0),
         'safe': D(0), 'other_equity': D(0), 'retained_earnings': D(0),
         'tax_loss_carryforward': D(0)}
    o.update({k: D(v) for k, v in over.items()})
    return o


# ─── assumptions ────────────────────────────────────────────────────────────

def test_assumptions_default_to_off():
    a = ST.assumptions_from(None)
    assert a['dso_days'] == 0 and a['dpo_days'] == 0 and a['dio_days'] == 0
    assert a['equipment_cost_per_hire'] == D(0) and a['useful_life_years'] == D(0)
    assert a['interest_rate_debt'] == D(0) and a['interest_rate_cash'] == D(0)
    assert a['tax_rate'] == D(0) and a['tax_loss_carryforward_opening'] == D(0)


def test_assumptions_accept_values_and_fractions():
    a = ST.assumptions_from({'dso_days': 30, 'dpo_days': 45, 'dio_days': 15,
                             'equipment_cost_per_hire': 1200, 'useful_life_years': 3,
                             'interest_rate_debt': 0.12, 'interest_rate_cash': 0.02,
                             'tax_rate': 0.2, 'tax_loss_carryforward_opening': 5000})
    assert a['dso_days'] == D(30) and a['tax_rate'] == D('0.2')
    assert a['useful_life_years'] == D(3)


def test_assumptions_reject_bad_values():
    with pytest.raises(ValueError):
        ST.assumptions_from({'dso_days': -5})
    with pytest.raises(ValueError):
        ST.assumptions_from({'tax_rate': 1.5})          # a fraction, not a percent
    with pytest.raises(ValueError):
        ST.assumptions_from({'equipment_cost_per_hire': 1200})  # no useful life


# ─── funding split ──────────────────────────────────────────────────────────

def test_funding_split_by_instrument():
    occ = [
        {'kind': 'funding', 'instrument': 'equity', 'account': 'Equity:Share Capital',
         'date': '2026-01-10', 'amount': D(10000)},
        {'kind': 'funding', 'instrument': 'debt', 'account': 'Liabilities:Long-Term:Loans',
         'date': '2026-01-10', 'amount': D(6000)},
        {'kind': 'funding', 'instrument': 'safe', 'account': 'Equity:SAFE',
         'date': '2026-02-01', 'amount': D(2000)},
        {'kind': 'funding', 'instrument': 'note',
         'account': 'Liabilities:Long-Term:Convertible Notes',
         'date': '2026-02-01', 'amount': D(3000)},
        {'kind': 'funding', 'instrument': 'grant', 'account': 'Income:Other:Grants',
         'date': '2026-02-01', 'amount': D(1500)},
        {'kind': 'revenue', 'account': 'Income:Operating:Sales',
         'date': '2026-01-10', 'amount': D(500)},   # not funding: ignored
    ]
    s = ST.funding_split(occ)
    assert s['2026-01'] == _split(equity=10000, debt=6000)
    assert s['2026-02'] == _split(safe=2000, note=3000, grant=1500)


def test_funding_split_falls_back_to_account():
    # Manual entries carry no instrument: classify by account.
    occ = [
        {'kind': 'funding', 'account': 'Liabilities:Long-Term:Bank Loan',
         'date': '2026-01-10', 'amount': D(4000)},
        {'kind': 'funding', 'account': 'Equity:Owner Investment',
         'date': '2026-01-10', 'amount': D(1000)},
    ]
    s = ST.funding_split(occ)
    assert s['2026-01'] == _split(debt=4000, equity=1000)


# ─── hires ──────────────────────────────────────────────────────────────────

def test_hire_months_from_salary_rules():
    rules = [
        {'id': 'r1', 'kind': 'expense', 'driver': 'salary', 'salary': 60000,
         'start': '2026-01-15'},
        {'id': 'r2', 'kind': 'expense', 'driver': 'salary', 'salary': 72000,
         'start': '2026-03-01'},
        {'id': 'r3', 'kind': 'expense', 'driver': 'fixed', 'amount': 100,
         'start': '2026-01-01'},   # not a hire
        {'id': 'r4', 'kind': 'expense', 'driver': 'salary', 'salary': 48000,
         'start': '2026-01-15'},   # second hire, same month as r1
    ]
    assert ST.hire_months(rules) == {'2026-01': 2, '2026-03': 1}


# ─── working capital ────────────────────────────────────────────────────────

def test_working_capital_balances_from_days():
    # Revenue 30000 with DSO 30 -> AR 30000; COGS 12000 with DIO 30 -> Inv 12000;
    # (COGS + opex 6000) with DPO 30 -> AP 18000.
    a = ST.assumptions_from({'dso_days': 30, 'dpo_days': 30, 'dio_days': 30})
    out = ST.project_bs(_opening(cash=10000, share_capital=10000),
                        [_monthly('2026-01', revenue=30000, cogs=12000, opex=6000)], a)
    bs = out['lines']
    assert bs['bs_receivables']['2026-01'] == D(30000)
    assert bs['bs_inventory']['2026-01'] == D(12000)
    assert bs['bs_payables']['2026-01'] == D(18000)


def test_working_capital_moves_cash():
    # Runway cash would say +12000 (30000 rev - 18000 exp). With WC:
    # collections 0 (all revenue on credit), operating cash paid 0 (all on
    # credit), inventory bought 12000 -> cash falls by 12000.
    a = ST.assumptions_from({'dso_days': 30, 'dpo_days': 30, 'dio_days': 30})
    out = ST.project_bs(_opening(cash=10000, share_capital=10000),
                        [_monthly('2026-01', revenue=30000, cogs=12000, opex=6000)], a)
    assert out['lines']['bs_cash']['2026-01'] == D(-2000)
    cf = out['cash_flow']['2026-01']
    assert cf['operating'] == D(-12000) and cf['investing'] == D(0)
    assert cf['financing'] == D(0) and cf['end'] == D(-2000)


def test_working_capital_unwinds_next_month():
    # Month 2: no new revenue/expense, so AR/AP/Inv unwind to zero and the
    # cash comes back: +30000 collected - 18000 paid - 12000 inventory sold.
    a = ST.assumptions_from({'dso_days': 30, 'dpo_days': 30, 'dio_days': 30})
    months = [_monthly('2026-01', revenue=30000, cogs=12000, opex=6000),
              _monthly('2026-02')]
    out = ST.project_bs(_opening(cash=10000, share_capital=10000), months, a)
    bs = out['lines']
    assert bs['bs_receivables']['2026-02'] == D(0)
    assert bs['bs_payables']['2026-02'] == D(0)
    assert bs['bs_inventory']['2026-02'] == D(0)
    assert bs['bs_cash']['2026-02'] == D(22000)


# ─── equipment / depreciation ───────────────────────────────────────────────

def test_depreciation_schedule_for_a_hire():
    # One hire in Jan, 1200 of equipment, 1-year life -> 100/month dep.
    a = ST.assumptions_from({'equipment_cost_per_hire': 1200, 'useful_life_years': 1})
    months = [_monthly('2026-01', hires=1), _monthly('2026-02'),
              _monthly('2026-03')]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), months, a)
    bs, pl = out['lines'], out['pl']
    assert pl['depreciation']['2026-01'] == D(100)
    assert pl['depreciation']['2026-02'] == D(100)
    assert bs['bs_ppe_net']['2026-01'] == D(1100)
    assert bs['bs_ppe_net']['2026-02'] == D(1000)
    assert bs['bs_ppe_net']['2026-03'] == D(900)


def test_second_hire_adds_a_vintage():
    a = ST.assumptions_from({'equipment_cost_per_hire': 1200, 'useful_life_years': 1})
    months = [_monthly('2026-01', hires=1), _monthly('2026-02'),
              _monthly('2026-03', hires=1)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), months, a)
    pl, bs = out['pl'], out['lines']
    assert pl['depreciation']['2026-03'] == D(200)   # two vintages
    assert bs['bs_ppe_net']['2026-03'] == D(2000)    # 2400 gross - 400 accum


def test_depreciation_stops_after_useful_life():
    a = ST.assumptions_from({'equipment_cost_per_hire': 1200, 'useful_life_years': 1})
    months = [_monthly(m, hires=1 if m == '2026-01' else 0) for m in
              ['2026-%02d' % m for m in range(1, 13)] + ['2027-01', '2027-02']]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), months, a)
    pl, bs = out['pl'], out['lines']
    assert pl['depreciation']['2026-12'] == D(100)
    assert pl['depreciation']['2027-01'] == D(0)
    assert bs['bs_ppe_net']['2027-01'] == D(0)


def test_depreciation_is_a_cash_free_expense():
    # Depreciation lowers net income but not cash: cash falls only by the
    # equipment purchase, in the hire month. Month 2: net -100, +100 dep
    # add-back -> cash unchanged by depreciation, so it stays 3800.
    a = ST.assumptions_from({'equipment_cost_per_hire': 1200, 'useful_life_years': 1})
    months = [_monthly('2026-01', hires=1), _monthly('2026-02')]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), months, a)
    assert out['pl']['net']['2026-01'] == D(-100)
    assert out['lines']['bs_cash']['2026-01'] == D(3800)   # 5000 - 1200 equip
    assert out['lines']['bs_cash']['2026-02'] == D(3800)


# ─── debt / interest ────────────────────────────────────────────────────────

def test_debt_balance_and_interest():
    # Opening debt 12000 at 12% -> 120/month interest on the opening balance.
    a = ST.assumptions_from({'interest_rate_debt': 0.12})
    months = [_monthly('2026-01'), _monthly('2026-02')]
    out = ST.project_bs(_opening(cash=20000, debt=12000, share_capital=8000), months, a)
    assert out['lines']['bs_debt']['2026-01'] == D(12000)
    assert out['pl']['interest']['2026-01'] == D(120)
    assert out['pl']['net']['2026-01'] == D(-120)


def test_new_debt_funding_raises_debt_and_cash():
    a = ST.assumptions_from({'interest_rate_debt': 0.12})
    months = [_monthly('2026-01', funding=6000, split=_split(debt=6000)),
              _monthly('2026-02')]
    out = ST.project_bs(_opening(cash=1000, share_capital=1000), months, a)
    assert out['lines']['bs_debt']['2026-01'] == D(6000)
    assert out['lines']['bs_cash']['2026-01'] == D(7000)
    assert out['pl']['interest']['2026-02'] == D(60)   # on the 6000 balance


def test_interest_on_cash_is_income():
    # Cash 12000 at 12% -> 120 of interest income, i.e. net interest -120.
    a = ST.assumptions_from({'interest_rate_cash': 0.12})
    out = ST.project_bs(_opening(cash=12000, share_capital=12000), [_monthly('2026-01')], a)
    assert out['pl']['interest']['2026-01'] == D(-120)
    assert out['pl']['net']['2026-01'] == D(120)
    assert out['lines']['bs_cash']['2026-01'] == D(12120)


def test_grant_is_income_not_equity():
    # A grant is cash in and income: it lands in retained earnings via net,
    # not in share capital.
    months = [_monthly('2026-01', funding=1500, split=_split(grant=1500))]
    out = ST.project_bs(_opening(cash=1000, share_capital=1000), months, ST.assumptions_from(None))
    assert out['lines']['bs_share_capital']['2026-01'] == D(1000)  # opening, unchanged
    assert out['lines']['bs_retained']['2026-01'] == D(1500)
    assert out['lines']['bs_cash']['2026-01'] == D(2500)


# ─── tax loss carryforward ──────────────────────────────────────────────────

def test_tax_loss_carryforward_offsets_later_profit():
    a = ST.assumptions_from({'tax_rate': 0.2})
    months = [_monthly('2026-01', revenue=0, cogs=0, opex=10000),   # -10000 loss
              _monthly('2026-02', revenue=15000, cogs=0, opex=0)]  # +15000 profit
    out = ST.project_bs(_opening(cash=20000, share_capital=20000), months, a)
    pl = out['pl']
    assert pl['tax']['2026-01'] == D(0)
    assert pl['tax']['2026-02'] == D(1000)      # 20% of (15000 - 10000)
    assert pl['net']['2026-02'] == D(14000)
    assert out['carryforward']['2026-02'] == D(0)


def test_tax_with_no_loss_is_straight_rate():
    a = ST.assumptions_from({'tax_rate': 0.2})
    out = ST.project_bs(_opening(cash=0),
                        [_monthly('2026-01', revenue=10000, cogs=2000, opex=3000)], a)
    assert out['pl']['tax']['2026-01'] == D(1000)   # 20% of 5000
    assert out['pl']['net']['2026-01'] == D(4000)


def test_opening_carryforward_is_used_first():
    a = ST.assumptions_from({'tax_rate': 0.2, 'tax_loss_carryforward_opening': 8000})
    out = ST.project_bs(_opening(cash=0),
                        [_monthly('2026-01', revenue=10000, cogs=0, opex=0)], a)
    assert out['pl']['tax']['2026-01'] == D(400)    # 20% of (10000 - 8000)
    assert out['carryforward']['2026-01'] == D(0)


# ─── balance + cash tie-out ─────────────────────────────────────────────────

def test_balance_sheet_balances_every_month_with_all_drivers():
    a = ST.assumptions_from({'dso_days': 30, 'dpo_days': 15, 'dio_days': 30,
                             'equipment_cost_per_hire': 1200, 'useful_life_years': 2,
                             'interest_rate_debt': 0.12, 'interest_rate_cash': 0.02,
                             'tax_rate': 0.2})
    months = [
        _monthly('2026-01', revenue=30000, cogs=12000, opex=8000, hires=2,
                 funding=20000, split=_split(equity=14000, debt=6000)),
        _monthly('2026-02', revenue=36000, cogs=14000, opex=9000, hires=1,
                 funding=1500, split=_split(grant=1500)),
        _monthly('2026-03', revenue=20000, cogs=9000, opex=12000),
        _monthly('2026-04', revenue=42000, cogs=15000, opex=9000),
    ]
    out = ST.project_bs(_opening(cash=17000, debt=12000, share_capital=5000), months, a)
    for m in ('2026-01', '2026-02', '2026-03', '2026-04'):
        assert out['lines']['bs_check'][m] == D(0), m
        cf = out['cash_flow'][m]
        assert cf['operating'] + cf['investing'] + cf['financing'] == \
            cf['end'] - cf['begin'], m
        assert out['lines']['bs_cash'][m] == cf['end'], m


def test_balance_sheet_balances_from_a_real_opening():
    # Opening with every bucket filled still balances after rollforward.
    a = ST.assumptions_from({'dso_days': 15, 'interest_rate_debt': 0.06})
    opening = _opening(cash=48000, receivables=3000, inventory=2000, ppe_gross=12000,
                       accum_depreciation=2000, other_assets=500, payables=500,
                       debt=10000, other_liabilities=300, share_capital=45000,
                       safe=5000, other_equity=1000, retained_earnings=1700)
    assert (opening['cash'] + opening['receivables'] + opening['inventory']
            + opening['ppe_gross'] - opening['accum_depreciation']
            + opening['other_assets']
            == opening['payables'] + opening['debt'] + opening['other_liabilities']
            + opening['share_capital'] + opening['safe'] + opening['other_equity']
            + opening['retained_earnings'])
    out = ST.project_bs(opening, [_monthly('2026-01', revenue=20000, cogs=8000,
                                            opex=5000)], a)
    assert out['lines']['bs_check']['2026-01'] == D(0)


# ─── opening balances from the books ────────────────────────────────────────

_JOURNAL = """\
2026-01-05 Owner invests
    Assets:Current:Chequing  50000 CAD
    Equity:Share Capital  -50000 CAD

2026-01-10 Buy equipment
    Assets:Fixed:Equipment  12000 CAD
    Assets:Current:Chequing  -12000 CAD

2026-01-15 Sale on credit
    Assets:Current:Receivable  3000 CAD
    Income:Operating:Sales  -3000 CAD

2026-01-20 Supplier bill
    Expenses:Operating:Rent  500 CAD
    Liabilities:Current:Payables  -500 CAD

2026-01-25 Loan received
    Assets:Current:Chequing  10000 CAD
    Liabilities:Long-Term:Loans  -10000 CAD

2026-02-05 Collected
    Assets:Current:Chequing  2000 CAD
    Assets:Current:Receivable  -2000 CAD
"""


@needs_hledger
def test_opening_balances_from_books(tmp_path):
    journal = tmp_path / 'test.journal'
    journal.write_text(_JOURNAL)
    o = ST.opening_balances(journal, 'CAD', '2026-02')
    assert o['cash'] == D(48000)
    assert o['receivables'] == D(3000)
    assert o['ppe_gross'] == D(12000) and o['accum_depreciation'] == D(0)
    assert o['payables'] == D(500) and o['debt'] == D(10000)
    assert o['share_capital'] == D(50000)
    assert o['retained_earnings'] == D(2500)   # 3000 sales - 500 rent
    assert (o['cash'] + o['receivables'] + o['inventory'] + o['ppe_gross']
            - o['accum_depreciation'] + o['other_assets']
            == o['payables'] + o['debt'] + o['other_liabilities']
            + o['share_capital'] + o['safe'] + o['other_equity']
            + o['retained_earnings'])


@needs_hledger
def test_actual_bs_by_month_from_books(tmp_path):
    journal = tmp_path / 'test.journal'
    journal.write_text(_JOURNAL)
    actual = ST.actual_bs(journal, 'CAD', ['2026-01', '2026-02'])
    assert actual['2026-01']['cash'] == D(48000)
    assert actual['2026-02']['cash'] == D(50000)
    assert actual['2026-02']['receivables'] == D(1000)
    assert actual['2026-02']['retained_earnings'] == D(2500)


@needs_hledger
def test_opening_balances_none_without_books(tmp_path):
    assert ST.opening_balances(tmp_path / 'missing.journal', 'CAD', '2026-02') is None


# ─── build() integration ────────────────────────────────────────────────────

def test_build_without_opening_is_unchanged():
    # Backwards compatibility: no opening -> no BS keys, old lines identical.
    rows = [{'month': '2026-10', 'source': 'actual', 'revenue': D(500), 'expense': D(1300),
             'funding': D(0), 'begin': D(5000), 'end': D(4200)},
            {'month': '2026-11', 'source': 'plan', 'revenue': D(800), 'expense': D(2400),
             'funding': D(10000), 'begin': D(4200), 'end': D(12600)}]
    actual = {'2026-10': {'Expenses:Operating:Payroll:Salaries': D(1000),
                          'Expenses:COGS': D(100), 'Expenses:Operating:Rent': D(200)}}
    plan = {'2026-11': {'Expenses:Operating:Marketing': D(400)}}
    out = ST.build(rows, actual, plan, D(2000), 'add')
    line = {l['key']: l['values'] for l in out['lines']}
    assert line['net']['2026-11'] == D(800) - D(2400)
    assert line['cash_end']['2026-11'] == D(12600)
    assert 'balance_sheet' not in out and 'cash_flow' not in out
    assert not any(k.startswith('bs_') for k in line)


def test_build_with_opening_and_no_drivers_keeps_cash():
    # Drivers off: BS cash must equal the runway cash_end exactly, and the
    # sheet must balance with cash + retained earnings + equity funding only.
    rows = [{'month': '2026-11', 'source': 'plan', 'revenue': D(800), 'expense': D(2400),
             'funding': D(10000), 'begin': D(4200), 'end': D(12600)}]
    plan = {'2026-11': {'Expenses:Operating:Marketing': D(400)}}
    out = ST.build(rows, {}, plan, D(2000), 'add',
                   opening=_opening(cash=4200, share_capital=4200), funding_split={'2026-11': _split(equity=10000)})
    line = {l['key']: l['values'] for l in out['lines']}
    assert line['cash_end']['2026-11'] == D(12600)
    assert line['bs_cash']['2026-11'] == D(12600)
    assert line['bs_check']['2026-11'] == D(0)
    assert line['bs_retained']['2026-11'] == D(-1600)   # net -1600
    assert line['bs_share_capital']['2026-11'] == D(14200)   # 4200 opening + 10000
    assert 'depreciation' not in line   # zero driver lines stay hidden


def test_build_with_drivers_feeds_pl():
    rows = [{'month': '2026-11', 'source': 'plan', 'revenue': D(30000), 'expense': D(18000),
             'funding': D(0), 'begin': D(10000), 'end': D(22000)}]
    plan = {'2026-11': {'Expenses:COGS': D(12000), 'Expenses:Operating:Rent': D(6000)}}
    a = ST.assumptions_from({'dso_days': 30, 'equipment_cost_per_hire': 1200,
                             'useful_life_years': 1, 'tax_rate': 0.2})
    out = ST.build(rows, {}, plan, D(0), 'replace', assumptions=a,
                   opening=_opening(cash=10000, share_capital=10000), hires={'2026-11': 1})
    line = {l['key']: l['values'] for l in out['lines']}
    assert line['depreciation']['2026-11'] == D(100)
    # net = 30000 - 12000 - 6000 - 100 dep = 11900; tax 20% = 2380; net 9520
    assert line['tax']['2026-11'] == D(2380)
    assert line['net']['2026-11'] == D(9520)
    assert line['bs_check']['2026-11'] == D(0)
    # cash: 10000 + collections 0 - operating paid 0 - inventory 12000
    # - equipment 1200 + net... tie-out is via the cash-flow section instead:
    assert out['cash_flow']['2026-11']['end'] == line['bs_cash']['2026-11']
