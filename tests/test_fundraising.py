from decimal import Decimal as D

import pytest

import lib.helpers as H
import modules.fundraise as FR
import modules.captable as CT
from lib import fundraising as F
from lib import captable as C

CONFIG = {'pair': {'currency': 'CAD'}, 'accounts': {'bank': 'Assets:Current:Chequing'}}


@pytest.fixture
def entity(tmp_path, monkeypatch):
    for mod in (H, FR, CT):
        monkeypatch.setattr(mod, 'get_entity_dir', lambda: tmp_path)
    return tmp_path


def test_round_progress_and_stages(entity):
    r = FR.add_round({'name': 'Pre-seed', 'type': 'pre-seed', 'instrument': 'safe', 'target': 500000, 'cap': 5000000})
    a = FR.add_deal({'investor': 'Ann Angel', 'round': r['id'], 'amount': 50000}, config=CONFIG)
    b = FR.add_deal({'investor': 'Big VC', 'round': r['id'], 'amount': 200000}, config=CONFIG)
    FR.update_deal(a['id'], {'stage': 'soft committed'}, config=CONFIG)
    FR.update_deal(b['id'], {'stage': 'signed'}, config=CONFIG)
    p = F.progress(r, FR.load_deals(), CONFIG)
    assert p['soft'] == D(250000) and p['signed'] == D(200000) and p['remaining'] == D(250000)
    FR.update_deal(a['id'], {'stage': 'passed'}, config=CONFIG)
    assert F.progress(r, FR.load_deals(), CONFIG)['passed'] == 1
    with pytest.raises(ValueError):
        FR.update_deal(a['id'], {'stage': 'maybe'}, config=CONFIG)
    with pytest.raises(ValueError):
        FR.add_round({'name': 'x', 'instrument': 'crypto'})


def test_momentum_counts_from_pipeline(entity):
    d = FR.add_deal({'investor': 'Ann', 'first_meeting': '2026-10-03'}, config=CONFIG)
    FR.update_deal(d['id'], {'note': 'follow-up call', 'meeting': True, 'date': '2026-11-02'}, config=CONFIG)
    FR.update_deal(d['id'], {'stage': 'signed', 'date': '2026-11-20'}, config=CONFIG)
    m = F.momentum(FR.load_deals(), CONFIG)
    assert m['investor_connections'] == {'2026-10': 1}
    assert m['investor_meetings'] == {'2026-10': 1, '2026-11': 1}
    assert m['investors_converted'] == {'2026-11': 1}


def test_receive_safe_writes_books_and_captable(entity):
    r = FR.add_round({'name': 'Pre-seed', 'instrument': 'safe', 'target': 500000, 'cap': 5000000, 'discount': 0.2})
    d = FR.add_deal({'investor': 'Ann Angel', 'round': r['id'], 'amount': 50000}, config=CONFIG)
    s = FR.receive(d['id'], '2026-11-15', CONFIG)
    text = (entity / 'generated' / '2026' / 'equity.journal').read_text()
    assert 'Equity:SAFE' in text and 'CAD -50000.00' in text and 'funding:safe' in text
    reg = CT.load_register()
    assert C.open_instruments(reg)[0]['cap'] == 5000000 and C.open_instruments(reg)[0]['post_money']
    assert FR.load_deals()[0]['stage'] == 'capital received'
    with pytest.raises(ValueError):
        FR.receive(d['id'], '2026-11-16', CONFIG)


def test_receive_priced_equity_issues_shares(entity):
    r = FR.add_round({'name': 'Seed', 'instrument': 'equity', 'price': 0.5})
    d = FR.add_deal({'investor': 'Big VC', 'round': r['id'], 'amount': 100000}, config=CONFIG)
    FR.receive(d['id'], '2026-12-01', CONFIG)
    reg = CT.load_register()
    assert reg['issuances'][0]['shares'] == 200000 and reg['issuances'][0]['class'] == 'seed'


def test_receive_needs_a_round(entity):
    d = FR.add_deal({'investor': 'Nobody', 'amount': 10}, config=CONFIG)
    with pytest.raises(ValueError):
        FR.receive(d['id'], '2026-12-01', CONFIG)


def test_versions_compare(entity):
    reg = C.normalise(None)
    reg = CT.apply_change(reg, {'type': 'holder', 'name': 'Ana', 'group': 'founder'})
    reg = CT.apply_change(reg, {'type': 'issue', 'holder': 'ana', 'shares': 9_000_000})
    CT.save_register(reg)
    CT.save_version('seed', {'name': 'Seed', 'steps': [{'type': 'priced', 'investment': 2_000_000, 'pre_money': 8_000_000}]})
    rows = CT.compare(['seed'])
    assert rows[0]['groups']['founder'] == 1
    assert abs(rows[1]['groups']['founder'] - D('0.8')) < D('0.0001')
