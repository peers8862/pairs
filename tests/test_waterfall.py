from decimal import Decimal as D

from lib import captable as C
from lib.waterfall import payout, sweep


def reg(pref_terms=None, extra_classes=(), extra_issues=(), grants=(), instruments=()):
    r = {'classes': [{'id': 'common', 'name': 'Common', 'kind': 'common'},
                     {'id': 'a', 'name': 'Series A', 'kind': 'preferred', **(pref_terms or {})}, *extra_classes],
         'holders': [{'id': 'f', 'name': 'Founders', 'group': 'founder'}, {'id': 'vc', 'name': 'VC', 'group': 'investor'},
                     {'id': 'emp', 'name': 'Staff', 'group': 'employee'}, {'id': 'b', 'name': 'B fund', 'group': 'investor'},
                     {'id': 'angel', 'name': 'Angel', 'group': 'investor'}],
         'issuances': [{'holder': 'f', 'class': 'common', 'shares': 8_000_000, 'price': 0},
                       {'holder': 'vc', 'class': 'a', 'shares': 2_000_000, 'price': 1}, *extra_issues],
         'pool': {'size': sum(g['shares'] for g in grants)}, 'grants': list(grants), 'instruments': list(instruments)}
    return r


def got(res, holder):
    return next((r['proceeds'] for r in res['rows'] if r['holder'] == holder), D(0))


def close(a, b, tol=1):
    return abs(D(a) - D(b)) <= D(tol)


def test_non_participating_takes_pref_or_converts():
    low = payout(reg(), 5_000_000)
    assert close(got(low, 'vc'), 2_000_000) and close(got(low, 'f'), 3_000_000)
    high = payout(reg(), 20_000_000)
    assert close(got(high, 'vc'), 4_000_000) and close(got(high, 'f'), 16_000_000)
    assert high['classes'][0]['decision'] == 'converts to common'


def test_participating_uncapped_and_capped():
    p = payout(reg({'participating': True}), 20_000_000)
    assert close(got(p, 'vc'), 5_600_000) and close(got(p, 'f'), 14_400_000)
    capped = payout(reg({'participating': True, 'participation_cap': 3}), 25_000_000)
    assert close(got(capped, 'vc'), 6_000_000) and close(got(capped, 'f'), 19_000_000)
    converts = payout(reg({'participating': True, 'participation_cap': 3}), 50_000_000)
    assert close(got(converts, 'vc'), 10_000_000)


def test_seniority_and_pari_passu():
    b_class = {'id': 'b', 'name': 'Series B', 'kind': 'preferred', 'seniority': 2}
    senior = payout(reg(None, [b_class], [{'holder': 'b', 'class': 'b', 'shares': 1_000_000, 'price': 3}]), 4_000_000)
    assert close(got(senior, 'b'), 3_000_000) and close(got(senior, 'vc'), 1_000_000) and close(got(senior, 'f'), 0)
    even = payout(reg(None, [{**b_class, 'seniority': 1}], [{'holder': 'b', 'class': 'b', 'shares': 1_000_000, 'price': 3}]), 4_000_000)
    assert close(got(even, 'vc'), 1_600_000) and close(got(even, 'b'), 2_400_000)


def test_options_net_exercise_and_totals_add_up():
    r = reg(grants=[{'holder': 'emp', 'shares': 1_000_000, 'strike': 0.5}])
    r['issuances'] = r['issuances'][:1]       # common only
    res = payout(r, 9_000_000)
    assert close(got(res, 'emp'), 555_556) and close(got(res, 'f'), 8_444_444)
    assert close(res['undistributed'], 0)


def test_note_repaid_first_and_safe_choice():
    r = reg(instruments=[{'id': 'n1', 'holder': 'angel', 'kind': 'note', 'amount': 100_000, 'interest': 0, 'converted': False}])
    r['issuances'] = r['issuances'][:1]
    res = payout(r, 1_000_000)
    assert close(got(res, 'angel'), 100_000) and close(got(res, 'f'), 900_000)
    s = reg(instruments=[{'id': 's1', 'holder': 'angel', 'kind': 'safe', 'amount': 500_000, 'cap': 5_000_000, 'converted': False}])
    s['issuances'] = [{'holder': 'f', 'class': 'common', 'shares': 10_000_000, 'price': 0}]
    assert close(got(payout(s, 2_000_000), 'angel'), 500_000)
    assert close(got(payout(s, 100_000_000), 'angel'), 100_000_000 / 11, 2)


def test_every_exit_pays_out_in_full():
    r = reg({'participating': True, 'participation_cap': 2}, grants=[{'holder': 'emp', 'shares': 500_000, 'strike': 0.2}])
    for v in (1_000_000, 3_000_000, 12_000_000, 80_000_000):
        assert close(payout(r, v)['undistributed'], 0, 2)
    pts = sweep(r, [1_000_000, 80_000_000])
    assert pts[1]['groups']['founder'] > pts[0]['groups']['founder']


def test_vesting_with_cliff():
    g = {'shares': 4800, 'vesting': {'start': '2025-01-01', 'months': 48, 'cliff': 12}}
    assert C.vested(g, '2025-06-01') == 0
    assert C.vested(g, '2026-01-01') == 1200
    assert C.vested(g, '2030-01-01') == 4800
    assert C.vested({'shares': 10}, '2020-01-01') == 10


def test_pro_rata_in_priced_round():
    base = reg()
    base['classes'] = base['classes'][:1]
    base['issuances'] = [{'holder': 'f', 'class': 'common', 'shares': 8_000_000, 'price': 0},
                         {'holder': 'vc', 'class': 'common', 'shares': 2_000_000, 'price': 0.5}]
    out, s = C.priced_round(base, {'name': 'Seed', 'investment': 1_000_000, 'pre_money': 10_000_000, 'pro_rata': True,
                                   'liq_pref': 1, 'participating': True})
    assert s['pro_rata'][0]['holder'] == 'vc' and close(s['pro_rata'][0]['amount'], 200_000)
    seed = next(c for c in out['classes'] if c['id'] == 'seed')
    assert seed['participating'] is True
