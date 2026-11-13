from decimal import Decimal as D

import pytest

from lib import kpi as K
from lib.profile import update, load


def test_formulas_and_functions():
    vals = {('revenue', '2026-01'): D(100), ('revenue', '2026-02'): D(121), ('revenue', '2026-03'): D(146.41),
            ('mrr', '2026-03'): D(50)}
    look = lambda n, m: vals.get((n, m))
    months = ['2026-01', '2026-02', '2026-03']
    assert K.evaluate('12 * mrr', look, '2026-03', months) == D(600)
    assert round(K.evaluate('growth(revenue, 3)', look, '2026-03', months), 4) == D('0.21')
    assert K.evaluate('avg(revenue, 2)', look, '2026-02', months) == D('110.5')
    with pytest.raises(K.Missing):
        K.evaluate('mrr / revenue', look, '2026-01', months)
    assert K.check_formula('a +') is not None and K.check_formula('a / b') is None


def test_values_roundtrip(tmp_path):
    K.set_value(tmp_path, 'demos', '2026-10', 4, 'two at a fair')
    K.set_value(tmp_path, 'demos', '2026-11', '6')
    K.set_value(tmp_path, 'demos', '2026-10', None)
    values, notes = K.load_values(tmp_path)
    assert values == {'demos': {'2026-11': D(6)}}


def test_grid_ledger_derived_manual_and_projection():
    defs = K.BUILTIN
    values = {'mrr': {'2026-01': D(1000), '2026-02': D(1100)}, 'investor_meetings': {'2026-02': D(3)}}
    ledger = {'revenue': {'2026-01': D(900), '2026-02': D(1000)}, 'expenses': {'2026-01': D(3000), '2026-02': D(3500)},
              'cash': {'2026-01': D(20000), '2026-02': D(17500)}}
    cells = K.grid(defs, values, ledger, ['2026-01', '2026-02'], {'mrr': {'growth': 0.1}}, ['2026-03'])
    assert cells['arr']['2026-02']['value'] == D(13200) and cells['arr']['2026-02']['kind'] == 'derived'
    assert cells['net_burn']['2026-02']['value'] == D(2500)
    assert cells['revenue']['2026-01']['kind'] == 'ledger'
    assert cells['mrr']['2026-03']['value'] == D('1210.0') and cells['mrr']['2026-03']['kind'] == 'projected'
    assert cells['arr']['2026-03']['value'] == D('14520.0')     # derived follows the projection
    assert cells['investor_meetings']['2026-01']['value'] is None


def test_bucket_projection_and_custom_definitions(tmp_path):
    from modules.kpi import define
    define(tmp_path, 'Podcast listens', 'marketing', 'count')
    defs = K.load_definitions(tmp_path)
    assert defs['podcast_listens']['source'] == 'manual' and not defs['podcast_listens']['builtin']
    cells = K.grid(defs, {'podcast_listens': {'2026-01': D(100)}}, {}, ['2026-01'],
                   {'bucket:marketing': {'growth': 0.5}}, ['2026-02', '2026-03'])
    assert cells['podcast_listens']['2026-03']['value'] == D('225.00')
    with pytest.raises(ValueError):
        define(tmp_path, 'Bad', 'nope')


def test_every_builtin_formula_parses_and_names_exist():
    for d in K.BUILTIN.values():
        if d['source'] == 'derived':
            assert K.check_formula(d['formula']) is None, d['id']
            assert K.formula_names(d['formula']) <= set(K.BUILTIN), d['id']


def test_profile_update_and_validation():
    cfg = {}
    p = update(cfg, {'stage': 'seed', 'founders': 'Ana, Raj', 'market_share_5y': '0.02', 'founded': '2024'})
    assert p['founders'] == ['Ana', 'Raj'] and p['founded'] == 2024 and p['status'] == 'real'
    with pytest.raises(ValueError):
        update(cfg, {'stage': 'unicorn'})
    with pytest.raises(ValueError):
        update(cfg, {'market_share_5y': '5'})
    update(cfg, {'stage': None})
    assert 'stage' not in load(cfg)
