"""Migration script for existing consult users (I77).

`pair entity migrate --from <consult-config.yaml>` converts each entity
in the consult config's `entities:` section into a pair contact
(contacts/<slug>.yaml, role: entity, billing nested per the contact
schema) and creates the standard pair directories. The source config is
never modified; journals and PDFs are untouched; re-running skips
contacts that already exist.
"""
import yaml

import pytest

import lib.helpers as H
import modules.entity as ENT

CONSULT_CONFIG = {
    'entities': {
        'my-company': {
            'name': 'My Company',
            'business_number': '123-456-789-RT0001',
            'email': 'you@example.com',
            'phone': '555-1234',
            'payment_terms': 'Net 30 days',
            'currency': 'CAD',
            'tax': 13,
            'invoice_prefix': '',
            'next_invoice': '2026-042',
            'journal_file': '~/.hledger.journal',
            'template': None,
            'accounts': {
                'receivable': 'Assets:Accounts Receivable',
                'income': 'Income:Consulting',
                'tax_liability': 'Liabilities:HST Payable',
                'bank': 'Assets:Chequing',
            },
        },
        'side-hustle': {
            'name': 'Side Hustle',
            'currency': 'USD',
            'tax': 0,
            'next_invoice': '2026-001',
            'accounts': {},
        },
    },
    'defaults': {'entity': 'my-company'},
}


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    src = tmp_path / 'consult-config.yaml'
    src.write_text(yaml.safe_dump(CONSULT_CONFIG))
    return tmp_path, src


def _contact(entity, slug):
    return yaml.safe_load((entity / 'contacts' / f'{slug}.yaml').read_text())


def test_migrate_converts_entities_to_contacts(entity):
    tmp_path, src = entity
    ENT.cmd_migrate(['--from', str(src)])
    mine = _contact(tmp_path, 'my-company')
    assert mine['name'] == 'My Company'
    assert mine['slug'] == 'my-company'
    assert mine['role'] == 'entity'
    assert mine['email'] == 'you@example.com'
    assert mine['phone'] == '555-1234'
    assert mine['payment_terms'] == 'Net 30 days'
    billing = mine['billing']
    assert billing['business_number'] == '123-456-789-RT0001'
    assert billing['currency'] == 'CAD'
    assert billing['tax'] == 13.0
    assert billing['invoice_prefix'] == ''
    assert billing['next_invoice'] == '2026-042'
    assert billing['template'] is None
    assert billing['accounts'] == {
        'receivable': 'Assets:Accounts Receivable',
        'income': 'Income:Consulting',
        'tax_liability': 'Liabilities:HST Payable',
        'bank': 'Assets:Chequing',
    }
    # The consult journal path is preserved on the contact; the journal
    # itself is untouched.
    assert mine['journal_file'] == '~/.hledger.journal'

    side = _contact(tmp_path, 'side-hustle')
    assert side['role'] == 'entity'
    assert side['billing']['currency'] == 'USD'
    assert side['billing']['tax'] == 0.0
    # Missing accounts fall back to the contact defaults.
    assert side['billing']['accounts']['receivable'] == 'Assets:Current:Accounts Receivable'
    assert side['billing']['accounts']['income'] == 'Income:Operating:Consulting'


def test_migrate_creates_standard_directories(entity):
    tmp_path, src = entity
    ENT.cmd_migrate(['--from', str(src)])
    for d in ('assets', 'liabilities', 'contacts', 'contracts',
              'journal', 'generated', 'include'):
        assert (tmp_path / d).is_dir(), d


def test_migrate_is_idempotent_and_never_overwrites(entity):
    tmp_path, src = entity
    ENT.cmd_migrate(['--from', str(src)])
    mine = _contact(tmp_path, 'my-company')
    mine['notes'] = 'hand-edited after migration'
    (tmp_path / 'contacts' / 'my-company.yaml').write_text(yaml.safe_dump(mine))
    ENT.cmd_migrate(['--from', str(src)])
    assert _contact(tmp_path, 'my-company')['notes'] == 'hand-edited after migration'


def test_migrate_dry_run_writes_nothing(entity, capsys):
    tmp_path, src = entity
    ENT.cmd_migrate(['--from', str(src), '--dry-run'])
    assert not (tmp_path / 'contacts').exists()
    out = capsys.readouterr().out
    assert 'my-company' in out and 'side-hustle' in out


def test_migrate_missing_source_fails_gracefully(entity):
    tmp_path, src = entity
    with pytest.raises(SystemExit):
        ENT.cmd_migrate(['--from', str(tmp_path / 'nope.yaml')])
    assert not (tmp_path / 'contacts').exists()


def test_migrate_no_entities_is_a_noop(entity, capsys):
    tmp_path, src = entity
    src.write_text(yaml.safe_dump({'defaults': {}}))
    ENT.cmd_migrate(['--from', str(src)])
    assert not (tmp_path / 'contacts').exists()
    assert 'No entities' in capsys.readouterr().out


def test_migrate_leaves_source_config_untouched(entity):
    tmp_path, src = entity
    before = src.read_text()
    ENT.cmd_migrate(['--from', str(src)])
    assert src.read_text() == before
