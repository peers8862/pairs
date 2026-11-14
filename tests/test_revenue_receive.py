"""pair revenue receive — quick cash receipt without a full invoice (I74).

Direct cash in (pair 0110): debit bank, credit the entity's income
account. No invoice is created and no receivable is touched. Bad amount
or date fails gracefully with nothing written.
"""
import subprocess

import pytest
import yaml

import lib.helpers as H
import modules.revenue as R

CONFIG = {
    'pair': {'currency': 'CAD'},
    'accounts': {'bank': 'Assets:Current:Chequing'},
    'divisions': [],
    'defaults': {'entity': 'my-company'},
    'entities': {
        'my-company': {
            'name': 'My Company',
            'currency': 'CAD',
            'accounts': {
                'receivable': 'Assets:Accounts Receivable',
                'income': 'Income:Consulting',
                'tax_liability': 'Liabilities:HST Payable',
                'bank': 'Assets:Current:Chequing',
            },
        },
    },
}


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(CONFIG))
    (tmp_path / 'projects').mkdir()
    monkeypatch.setattr(R, 'PROJECTS_DIR', tmp_path / 'projects')
    return tmp_path


def _journal(entity, year='2026'):
    return entity / 'generated' / year / 'revenue.journal'


def _hledger_ok(path):
    r = subprocess.run(['hledger', '-f', str(path), 'bal'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_receive_flags_writes_cash_receipt(entity):
    R.cmd_receive({}, ['--amount', '250.00', '--date', '2026-11-13',
                       '--desc', 'Consulting', '--client', 'acme'])
    text = _journal(entity).read_text()
    assert 'Cash receipt' in text or 'Consulting' in text
    assert 'Assets:Current:Chequing' in text
    assert 'CAD 250.00' in text
    assert 'Income:Consulting' in text
    assert 'CAD -250.00' in text
    assert 'pair:0110' in text
    assert 'client:acme' in text
    _hledger_ok(_journal(entity))


def test_receive_with_project_uses_entity_accounts_and_tags(entity):
    project = {
        'client': 'Acme Corp',
        'project': 'Website',
        'entity': 'my-company',
        'currency': 'CAD',
    }
    (entity / 'projects' / 'acme-website.yaml').write_text(yaml.safe_dump(project))
    R.cmd_receive({}, ['--amount', '100.00', '--date', '2026-11-13',
                       '--desc', 'Website work', '--project', 'acme-website'])
    text = _journal(entity).read_text()
    assert 'client:Acme Corp' in text
    assert 'project:Website' in text
    assert 'Income:Consulting' in text
    assert H.load_config()['defaults']['last_project'] == 'acme-website'


def test_receive_bad_amount_fails_with_nothing_written(entity):
    with pytest.raises(SystemExit):
        R.cmd_receive({}, ['--amount', 'abc', '--date', '2026-11-13'])
    assert not (entity / 'generated').exists()


def test_receive_negative_amount_fails_with_nothing_written(entity):
    with pytest.raises(SystemExit):
        R.cmd_receive({}, ['--amount', '-50', '--date', '2026-11-13'])
    assert not (entity / 'generated').exists()


def test_receive_bad_date_fails_with_nothing_written(entity):
    with pytest.raises(SystemExit):
        R.cmd_receive({}, ['--amount', '50', '--date', '2026-13-45'])
    assert not (entity / 'generated').exists()


def test_receive_unknown_project_fails_with_nothing_written(entity):
    with pytest.raises(SystemExit):
        R.cmd_receive({}, ['--amount', '50', '--date', '2026-11-13',
                           '--project', 'nope'])
    assert not (entity / 'generated').exists()


def test_receive_interactive_prompts(entity, monkeypatch):
    answers = iter(['Consulting work', '75.00', '2026-11-13'])
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    R.cmd_receive({}, [])
    text = _journal(entity).read_text()
    assert 'Consulting work' in text
    assert 'CAD 75.00' in text
    _hledger_ok(_journal(entity))
