"""defaults.last_division auto-tracking (I71).

The division prompt defaults to the last used division; an explicit
--division flag always wins and is itself recorded as the last used.
"""
import pytest
import yaml

import lib.helpers as H
from lib.helpers import prompt_division, resolve_division_flag


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


def _inputs(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr('builtins.input', lambda prompt='': next(it))


# ─── prompt_division helper ─────────────────────────────────────────────────

def test_no_divisions_returns_none_and_writes_nothing(entity, monkeypatch):
    (entity / 'config.yaml').write_text(yaml.safe_dump(
        {'pair': {'currency': 'CAD'},
         'accounts': {'bank': 'Assets:Current:Chequing'}}))
    config = H.load_config()
    assert prompt_division(config) is None
    assert 'defaults' not in H.load_config()


def test_first_division_is_default_and_saved(entity, monkeypatch):
    _inputs(monkeypatch, [''])
    config = H.load_config()
    assert prompt_division(config) == 'ops'
    assert H.load_config()['defaults']['last_division'] == 'ops'


def test_last_division_is_default(entity, monkeypatch):
    _inputs(monkeypatch, [''])
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'admin'
    H.save_config(config)
    assert prompt_division(H.load_config()) == 'admin'


def test_stale_last_division_falls_back_to_first(entity, monkeypatch):
    _inputs(monkeypatch, [''])
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'gone'
    H.save_config(config)
    assert prompt_division(H.load_config()) == 'ops'


def test_typed_division_overrides_default_and_is_saved(entity, monkeypatch):
    _inputs(monkeypatch, ['admin'])
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'ops'
    H.save_config(config)
    assert prompt_division(H.load_config()) == 'admin'
    assert H.load_config()['defaults']['last_division'] == 'admin'


# ─── explicit --division flag ───────────────────────────────────────────────

def test_resolve_flag_records_last_used(entity):
    config = H.load_config()
    assert resolve_division_flag(config, 'admin') == 'admin'
    assert H.load_config()['defaults']['last_division'] == 'admin'


def test_resolve_flag_rejects_unknown_division(entity):
    config = H.load_config()
    with pytest.raises(ValueError, match="Unknown division 'nope'"):
        resolve_division_flag(config, 'nope')
    assert 'defaults' not in H.load_config()


# ─── expense add honours the flag and the prompt ────────────────────────────

def test_expense_batch_flag_sets_division_and_last(entity):
    import modules.expense as E
    flags = {'batch': True, 'quiet': True, 'date': None}
    E.cmd_add(flags, ['--desc', 'Paper', '--amount', '25.00',
                      '--category', 'office', '--date', '2026-11-13',
                      '--division', 'admin'])
    text = (entity / 'generated' / '2026' / 'expenses.journal').read_text()
    assert 'division:admin' in text
    assert H.load_config()['defaults']['last_division'] == 'admin'


def test_expense_batch_flag_rejects_unknown_division(entity):
    import modules.expense as E
    flags = {'batch': True, 'quiet': True, 'date': None}
    with pytest.raises(SystemExit):
        E.cmd_add(flags, ['--desc', 'Paper', '--amount', '25.00',
                          '--category', 'office', '--date', '2026-11-13',
                          '--division', 'nope'])
    assert not (entity / 'generated').exists()


def test_expense_interactive_prompt_defaults_to_last(entity, monkeypatch):
    import modules.expense as E
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'admin'
    H.save_config(config)
    # desc, amount, category(1=office), paid-from(1=bank), date, division(blank=admin), receipt(blank)
    _inputs(monkeypatch, ['Paper', '25.00', '1', '1', '', '', ''])
    E.cmd_add({'batch': False, 'quiet': True, 'date': None}, [])
    text = (entity / 'generated' / '2026' / 'expenses.journal').read_text()
    assert 'division:admin' in text


# ─── asset add honours the flag and the prompt ──────────────────────────────

def _asset_inputs(monkeypatch, division_answer):
    # name, slug, category(1=equipment), division, date, cost, life,
    # method(1=straight-line), salvage, payment(1=cash)
    _inputs(monkeypatch, ['Lathe', '', '1', division_answer, '',
                          '5000', '60', '1', '', '1'])


def test_asset_add_prompt_defaults_to_last(entity, monkeypatch):
    import modules.asset as A
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'admin'
    H.save_config(config)
    _asset_inputs(monkeypatch, '')
    A.cmd_add({}, [])
    import yaml as _y
    asset = _y.safe_load((entity / 'assets' / 'lathe.yaml').read_text())
    assert asset['division'] == 'admin'


def test_asset_add_flag_wins_over_last(entity, monkeypatch):
    import modules.asset as A
    config = H.load_config()
    config.setdefault('defaults', {})['last_division'] = 'admin'
    H.save_config(config)
    _asset_inputs(monkeypatch, '')
    A.cmd_add({}, ['--division', 'ops'])
    import yaml as _y
    asset = _y.safe_load((entity / 'assets' / 'lathe.yaml').read_text())
    assert asset['division'] == 'ops'
    assert H.load_config()['defaults']['last_division'] == 'ops'


def test_asset_add_flag_rejects_unknown_division(entity, monkeypatch):
    import modules.asset as A
    _asset_inputs(monkeypatch, '')
    with pytest.raises(SystemExit):
        A.cmd_add({}, ['--division', 'nope'])
    assert not (entity / 'assets').exists()
