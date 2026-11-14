"""Credit line in projections (I47).

When cash would fall below the floor, the credit line draws automatically
up to its limit; when cash allows above the floor, it repays. Interest
accrues on the beginning-of-month drawn balance (the I35 convention:
interest on beginning balances, so there is no cash/net circularity) and
lands in the net interest P&L line. The floor is the runway's cash floor,
passed in from modules/runway.statements(); with no floor given the line
holds cash at 0. The sheet must still balance every month.

New scenario assumptions (all default off, so existing scenarios are
unchanged):

    credit_line_limit: 50000   # max drawn balance; 0 = no auto-draw
    credit_line_rate: 0.12     # annual fraction, like interest_rate_debt
"""

from decimal import Decimal as D

import pytest

from lib import statements as ST


def _monthly(month, revenue=0, cogs=0, opex=0, nonop=0, funding=0, split=None,
             hires=0, source='plan'):
    return {'month': month, 'source': source, 'revenue': D(revenue), 'cogs': D(cogs),
            'opex': D(opex), 'nonop': D(nonop), 'funding': D(funding),
            'funding_split': split or {'equity': D(0), 'safe': D(0), 'debt': D(0),
                                       'note': D(0), 'grant': D(0)},
            'hires': hires}


def _opening(**over):
    o = {'cash': D(0), 'receivables': D(0), 'inventory': D(0), 'ppe_gross': D(0),
         'accum_depreciation': D(0), 'other_assets': D(0), 'payables': D(0),
         'debt': D(0), 'other_liabilities': D(0), 'share_capital': D(0),
         'safe': D(0), 'other_equity': D(0), 'retained_earnings': D(0),
         'tax_loss_carryforward': D(0)}
    o.update({k: D(v) for k, v in over.items()})
    return o


ASSUMPTIONS = {'credit_line_limit': 50000, 'credit_line_rate': 0.12}


# ─── assumptions ─────────────────────────────────────────────────────────────

def test_credit_assumptions_default_to_off():
    a = ST.assumptions_from(None)
    assert a['credit_line_limit'] == D(0) and a['credit_line_rate'] == D(0)


def test_credit_assumptions_reject_bad_values():
    with pytest.raises(ValueError):
        ST.assumptions_from({'credit_line_limit': -100})
    with pytest.raises(ValueError):
        ST.assumptions_from({'credit_line_limit': 100, 'credit_line_rate': 'x'})
    with pytest.raises(ValueError):
        ST.assumptions_from({'credit_line_limit': 100, 'credit_line_rate': 2})


# ─── draw and repay ───────────────────────────────────────────────────────────

def test_draws_to_the_floor_when_cash_falls_short():
    monthly = [_monthly('2027-01', opex=3000), _monthly('2027-02', opex=3000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        ASSUMPTIONS, floor=D(1000))
    # Jan: 5000 - 3000 = 2000, above the floor, no draw. Feb: 2000 - 3000 = -1000.
    assert out['lines']['bs_cash'] == {'2027-01': D(2000), '2027-02': D(1000)}
    assert out['lines']['bs_credit_line'] == {'2027-01': D(0), '2027-02': D(2000)}
    assert out['lines']['bs_check'] == {'2027-01': D(0), '2027-02': D(0)}
    assert out['cash_flow']['2027-02']['financing'] == D(2000)


def test_no_draw_when_cash_stays_above_floor():
    monthly = [_monthly('2027-01', opex=3000),
               _monthly('2027-02', revenue=10000, opex=1000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        ASSUMPTIONS, floor=D(1000))
    # Jan: 5000 - 3000 = 2000, above the floor. Feb: 2000 + 9000 = 11000.
    assert out['lines']['bs_credit_line'] == {'2027-01': D(0), '2027-02': D(0)}


def test_repay_after_draw():
    monthly = [_monthly('2027-01', opex=6000),
               _monthly('2027-02', revenue=10000, opex=1000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        ASSUMPTIONS, floor=D(1000))
    assert out['lines']['bs_credit_line']['2027-01'] == D(2000)  # 5000-6000=-1000 -> draw 2000
    # Feb: interest on the drawn 2000 is 20, so net is 8980; 1000 + 8980 = 9980,
    # repay 2000 -> cash 7980, line 0.
    assert out['pl']['interest']['2027-02'] == D(20)
    assert out['lines']['bs_credit_line']['2027-02'] == D(0)
    assert out['lines']['bs_cash']['2027-02'] == D(7980)


def test_limit_caps_the_draw():
    monthly = [_monthly('2027-01', opex=6000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        {'credit_line_limit': 500, 'credit_line_rate': 0}, floor=D(1000))
    assert out['lines']['bs_credit_line']['2027-01'] == D(500)
    assert out['lines']['bs_cash']['2027-01'] == D(-500)  # floor missed: limit exhausted
    assert out['lines']['bs_check']['2027-01'] == D(0)


def test_no_limit_means_no_draw():
    monthly = [_monthly('2027-01', opex=6000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        None, floor=D(1000))
    assert out['lines']['bs_credit_line']['2027-01'] == D(0)
    assert out['lines']['bs_cash']['2027-01'] == D(-1000)


def test_floor_defaults_to_zero():
    monthly = [_monthly('2027-01', opex=6000)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly, ASSUMPTIONS)
    assert out['lines']['bs_cash']['2027-01'] == D(0)
    assert out['lines']['bs_credit_line']['2027-01'] == D(1000)


# ─── interest ─────────────────────────────────────────────────────────────────

def test_interest_on_beginning_drawn_balance():
    monthly = [_monthly('2027-01', opex=6000),
               _monthly('2027-02', opex=0, revenue=0)]
    out = ST.project_bs(_opening(cash=5000, share_capital=5000), monthly,
                        ASSUMPTIONS, floor=D(1000))
    # Jan draws 2000; Feb interest is 2000 * 0.12 / 12 = 20, paid in Feb.
    assert out['pl']['interest']['2027-01'] == D(0)
    assert out['pl']['interest']['2027-02'] == D(20)
    # Feb cash: 1000 - 20 interest = 980, below the floor -> draws 20 more.
    assert out['lines']['bs_cash']['2027-02'] == D(1000)
    assert out['lines']['bs_credit_line']['2027-02'] == D(2020)
    assert out['lines']['bs_check']['2027-02'] == D(0)


def test_opening_drawn_balance_accrues_interest():
    monthly = [_monthly('2027-01', opex=0, revenue=0)]
    # A drawn line means cash was received: opening cash 6000 balances
    # against share capital 5000 + the drawn 1000.
    out = ST.project_bs(_opening(cash=6000, share_capital=5000, credit_line=1000),
                        monthly, ASSUMPTIONS, floor=D(1000))
    assert out['pl']['interest']['2027-01'] == D(10)  # 1000 * 0.12 / 12
    # Cash 6000 - 10 interest = 5990, far above the floor: the opening balance
    # is repaid in full in the first month (repay when cash allows).
    assert out['lines']['bs_credit_line']['2027-01'] == D(0)
    assert out['lines']['bs_cash']['2027-01'] == D(4990)


# ─── through ST.build ─────────────────────────────────────────────────────────

def test_build_shows_credit_line_and_floor_cash():
    rows = [{'month': '2027-01', 'source': 'plan', 'revenue': D(0), 'expense': D(6000),
             'funding': D(0), 'begin': D(5000), 'end': D(-1000)},
            {'month': '2027-02', 'source': 'plan', 'revenue': D(10000), 'expense': D(1000),
             'funding': D(0), 'begin': D(-1000), 'end': D(8000)}]
    out = ST.build(rows, {}, {}, D(0), 'replace', assumptions=ASSUMPTIONS,
                   opening=_opening(cash=5000, share_capital=5000), floor=D(1000))
    by_key = {l['key']: l for l in out['lines']}
    assert by_key['bs_credit_line']['values'] == {'2027-01': D(2000), '2027-02': D(0)}
    # Feb: interest 20 on the drawn 2000, so cash is 7980, not 8000.
    assert by_key['cash_end']['values'] == {'2027-01': D(1000), '2027-02': D(7980)}
    assert by_key['bs_check']['values'] == {'2027-01': D(0), '2027-02': D(0)}


# ─── end to end through modules/runway.statements() ────────────────────────

def test_statements_wires_runway_floor_to_credit_line(tmp_path, monkeypatch):
    import modules.runway as RW
    import modules.scenario as sc
    monkeypatch.setattr(sc, 'get_entity_dir', lambda: tmp_path)
    config = {'pair': {'currency': 'CAD'},
              'runway': {'min_cash_months': 0, 'min_cash': 1000}}
    monkeypatch.setattr(sc, 'load_config', lambda: config)
    slug = sc.create_scenario('Burn')
    sc.add_rule(slug, {'name': 'Rent', 'account': 'Expenses:Rent', 'amount': 6000,
                       'start': '2027-01-01', 'months': 2})
    meta = sc.load_scenario(slug)
    meta['assumptions'] = {'credit_line_limit': 50000, 'credit_line_rate': 0.12}
    from modules.scenario import _save_meta
    _save_meta(slug, meta)
    out = RW.statements(config, slug, 2, 'replace', start='2027-01')
    by_key = {l['key']: l for l in out['lines']}
    # Floor is the runway's: max(min_cash 1000, 0 months of expenses) = 1000.
    # Jan draws 7000 (cash would be -6000); Feb interest is 70, draws 6070.
    assert by_key['bs_credit_line']['values'] == {'2027-01': D(7000), '2027-02': D(13070)}
    assert by_key['cash_end']['values'] == {'2027-01': D(1000), '2027-02': D(1000)}
    assert by_key['interest']['values'] == {'2027-01': D(0), '2027-02': D(70)}
    assert by_key['bs_check']['values'] == {'2027-01': D(0), '2027-02': D(0)}


def test_build_without_credit_line_is_unchanged():
    rows = [{'month': '2027-01', 'source': 'plan', 'revenue': D(0), 'expense': D(6000),
             'funding': D(0), 'begin': D(5000), 'end': D(-1000)}]
    out = ST.build(rows, {}, {}, D(0), 'replace',
                   opening=_opening(cash=5000, share_capital=5000))
    by_key = {l['key']: l for l in out['lines']}
    # All-zero lines are filtered from the display list, as before; the raw
    # balance-sheet dict still carries the zero line.
    assert 'bs_credit_line' not in by_key
    assert out['balance_sheet']['bs_credit_line'] == {'2027-01': D(0)}
    assert by_key['cash_end']['values'] == {'2027-01': D(-1000)}
