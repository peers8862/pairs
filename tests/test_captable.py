from decimal import Decimal as D

import pytest

from lib import captable as C


def base():
    return {'holders': [{'id': 'ana', 'name': 'Ana', 'group': 'founder'}, {'id': 'raj', 'name': 'Raj', 'group': 'founder'}],
            'issuances': [{'date': '2025-01-01', 'holder': 'ana', 'class': 'common', 'shares': 4_000_000},
                          {'date': '2025-01-01', 'holder': 'raj', 'class': 'common', 'shares': 4_000_000}],
            'pool': {'size': 1_000_000}}


def close(a, b, tol='0.5'):
    return abs(D(a) - D(b)) <= D(tol)


def test_current_table():
    t = C.table(C.normalise(base()))
    assert t['fully_diluted'] == D(9_000_000)
    assert close(t['pool_pct'] * 9_000_000, 1_000_000)
    assert [r['holder'] for r in t['rows']] == ['ana', 'raj']


def test_priced_round_with_pool_shuffle():
    reg, s = C.priced_round(base(), {'name': 'Seed', 'investment': 2_000_000, 'pre_money': 8_000_000,
                                     'pool_target': 0.10, 'date': '2026-01-01'})
    assert close(s['pool_increase'], 142857.14)
    assert close(s['price'] * 1000, 875)                     # 0.875 per share
    assert close(s['new_shares'], 2285714.29)
    assert close(s['post_money'], 10_000_000, '2')
    g = C.by_group(reg)
    assert close(g['investor'] * 1000, 200, '0.01') and close(g['pool'] * 1000, 100, '0.01')


def test_post_money_safe_converts_to_its_cap_share():
    reg, _ = C.add_instrument(base(), {'kind': 'safe', 'holder': 'angels', 'amount': 500_000, 'cap': 5_000_000})
    reg, s = C.priced_round(reg, {'name': 'Seed', 'investment': 2_000_000, 'pre_money': 10_000_000,
                                  'date': '2026-01-01'})
    assert close(s['conversion_shares'], 1_000_000, '1')
    assert close(s['price'], 1, '0.0001')
    assert not C.open_instruments(reg)
    assert close(C.last_price(reg), s['price'], '0.000001')   # not the SAFE's conversion price


def test_pre_money_note_with_cap_and_discount():
    reg, _ = C.add_instrument(base(), {'kind': 'note', 'holder': 'bank', 'amount': 100_000, 'cap': 4_500_000,
                                       'discount': 0.2, 'date': '2026-01-01'})
    reg, s = C.priced_round(reg, {'investment': 2_000_000, 'pre_money': 10_000_000, 'date': '2026-01-01'})
    assert close(s['conversion_shares'], 200_000, '1')      # cap price 0.50 beats 80% of ~1.087


def test_note_interest_accrues():
    reg, _ = C.add_instrument(base(), {'kind': 'note', 'holder': 'bank', 'amount': 100_000, 'interest': 0.08,
                                       'discount': 0.2, 'date': '2025-01-01'})
    reg, s = C.priced_round(reg, {'investment': 1_000_000, 'pre_money': 9_000_000, 'date': '2026-01-01'})
    conv = [i for i in reg['issuances'] if 'converted' in i.get('note', '')][0]
    assert close(D(conv['shares']) * D(conv['price']), 108_000, '1')


def test_percent_sold_and_validation():
    reg, s = C.priced_round(base(), {'investment': 1_000_000, 'percent_sold': 0.2})
    assert close(s['pre_money'], 4_000_000)
    with pytest.raises(ValueError):
        C.priced_round(base(), {'investment': 1})
    with pytest.raises(ValueError):
        C.priced_round(C.empty_register(), {'investment': 1, 'pre_money': 1})


def test_version_steps_track_founder_dilution():
    steps = [{'type': 'safe', 'holder': 'angels', 'amount': 500_000, 'cap': 5_000_000},
             {'type': 'priced', 'name': 'Seed', 'investment': 2_000_000, 'pre_money': 10_000_000, 'pool_target': 0.1},
             {'type': 'grant', 'holder': 'dev', 'shares': 100_000}]
    reg, out = C.apply_steps(base(), steps)
    founders = [s['groups']['founder'] for s in out]
    assert founders[0] == founders[1] + 0 or founders[0] > founders[1]
    assert out[-1]['groups']['employee'] > 0
    with pytest.raises(ValueError):
        C.apply_steps(base(), [{'type': 'grant', 'holder': 'x', 'shares': 10_000_000}])
