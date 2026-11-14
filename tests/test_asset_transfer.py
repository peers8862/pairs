"""pair asset transfer <slug> --to <division> (I72).

Moving an asset between divisions updates the asset YAML and writes a
real, balanced journal entry at net book value (debit and credit the same
asset account, so the books are unchanged) tagged with the new division.
"""
import subprocess

import pytest
import yaml

import lib.helpers as H
import modules.asset as A
from lib.yaml_store import save_entity, load_entity


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    cfg = {
        'pair': {'currency': 'CAD'},
        'accounts': {'bank': 'Assets:Current:Chequing'},
        'divisions': ['ops', 'admin'],
    }
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(cfg))
    return tmp_path


def _make_asset(entity, division='ops', **overrides):
    data = {
        'name': 'Lathe',
        'slug': 'lathe',
        'category': 'equipment',
        'purchase_date': '2026-01-01',
        'cost': 12000.0,
        'useful_life_months': 12,
        'amortization_method': 'straight-line',
        'salvage_value': 0.0,
        'currency': 'CAD',
        'accounts': A.DEFAULT_ACCOUNTS['equipment'].copy(),
        'payment_method': 'cash',
        'division': division,
    }
    data.update(overrides)
    save_entity('assets', 'lathe', data)
    return data


def _journal(entity, year='2026'):
    return entity / 'generated' / year / 'assets.journal'


def test_transfer_moves_division_and_writes_balanced_entry(entity):
    asset = _make_asset(entity)
    nbv = A._calculate_nbv(asset)
    assert nbv > 0
    A.cmd_transfer({}, ['lathe', '--to', 'admin', '--date', '2026-11-13'])
    assert load_entity('assets', 'lathe')['division'] == 'admin'
    text = _journal(entity).read_text()
    assert 'Transfer asset: Lathe (ops → admin)' in text
    assert 'pair:1011' in text
    assert 'division:admin' in text
    assert f'CAD {float(nbv):.2f}' in text
    assert f'CAD {-float(nbv):.2f}' in text
    # hledger reads the entry and the books still balance.
    r = subprocess.run(['hledger', '-f', str(_journal(entity)), 'bal'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_transfer_records_last_division(entity):
    _make_asset(entity)
    A.cmd_transfer({}, ['lathe', '--to', 'admin', '--date', '2026-11-13'])
    assert H.load_config()['defaults']['last_division'] == 'admin'


def test_transfer_unknown_slug_fails_gracefully(entity):
    with pytest.raises(SystemExit):
        A.cmd_transfer({}, ['nope', '--to', 'admin'])
    assert not (entity / 'generated').exists()


def test_transfer_unknown_division_fails_gracefully(entity):
    _make_asset(entity)
    with pytest.raises(SystemExit):
        A.cmd_transfer({}, ['lathe', '--to', 'nope'])
    assert load_entity('assets', 'lathe')['division'] == 'ops'
    assert not (entity / 'generated').exists()


def test_transfer_missing_to_flag_fails_gracefully(entity):
    _make_asset(entity)
    with pytest.raises(SystemExit):
        A.cmd_transfer({}, ['lathe'])
    assert not (entity / 'generated').exists()


def test_transfer_same_division_is_a_noop(entity):
    _make_asset(entity, division='ops')
    A.cmd_transfer({}, ['lathe', '--to', 'ops'])
    assert not (entity / 'generated').exists()
    assert load_entity('assets', 'lathe')['division'] == 'ops'


def test_transfer_bad_date_fails_with_nothing_written(entity):
    _make_asset(entity)
    with pytest.raises(SystemExit):
        A.cmd_transfer({}, ['lathe', '--to', 'admin', '--date', '2026-13-45'])
    assert load_entity('assets', 'lathe')['division'] == 'ops'
    assert not (entity / 'generated').exists()


def test_transfer_asset_without_division(entity):
    asset = _make_asset(entity, division=None)
    del asset['division']
    save_entity('assets', 'lathe', asset)
    A.cmd_transfer({}, ['lathe', '--to', 'admin', '--date', '2026-11-13'])
    assert load_entity('assets', 'lathe')['division'] == 'admin'
    assert '(none → admin)' in _journal(entity).read_text()
