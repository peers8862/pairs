"""Receipt file linking on expense entries (I79).

`pair expense add --receipt <path>` records a `receipt:<path>` tag on the
entry. The file must exist — a receipt path pointing at nothing is a
broken link — so a missing file fails with exit 1 and nothing is written.
Relative paths resolve against the entity dir and are stored relative to
it, so the tag stays valid when the entity folder moves between machines.
The tag goes through build_tags() + format_entry, so the I81
require_single_line rule covers it.
"""
import pytest
import yaml

import lib.helpers as H
import modules.expense as E


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    cfg = {
        'pair': {'currency': 'CAD'},
        'accounts': {'bank': 'Assets:Current:Chequing'},
        'divisions': ['ops', 'admin'],
    }
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(cfg))
    (tmp_path / 'receipts').mkdir()
    (tmp_path / 'receipts' / 'lunch.pdf').write_bytes(b'%PDF-1.4 fake')
    return tmp_path


def _inputs(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr('builtins.input', lambda prompt='': next(it))


def _journal(entity):
    return (entity / 'generated' / '2026' / 'expenses.journal').read_text()


def _batch(entity, *extra):
    E.cmd_add({'batch': True, 'quiet': True, 'date': None},
              ['--desc', 'Lunch', '--amount', '12.50', '--category', 'meals',
               '--date', '2026-11-13', *extra])


def test_batch_receipt_tag_recorded(entity):
    _batch(entity, '--receipt', 'receipts/lunch.pdf')
    assert 'receipt:receipts/lunch.pdf' in _journal(entity)


def test_batch_without_receipt_has_no_tag(entity):
    _batch(entity)
    assert 'receipt:' not in _journal(entity)


def test_batch_missing_receipt_fails_with_nothing_written(entity):
    with pytest.raises(SystemExit):
        _batch(entity, '--receipt', 'receipts/gone.pdf')
    assert not (entity / 'generated').exists()


def test_absolute_path_inside_entity_stored_relative(entity):
    _batch(entity, '--receipt', str(entity / 'receipts' / 'lunch.pdf'))
    assert 'receipt:receipts/lunch.pdf' in _journal(entity)


def test_absolute_path_outside_entity_stored_as_given(entity):
    outside = entity.parent / 'outside-receipt.pdf'
    outside.write_bytes(b'%PDF-1.4 fake')
    _batch(entity, '--receipt', str(outside))
    assert f'receipt:{outside}' in _journal(entity)


def test_receipt_path_with_newline_rejected(entity):
    with pytest.raises(ValueError, match='single line'):
        E.resolve_receipt_path('receipts/a\nb.pdf')


def test_interactive_prompt_records_receipt(entity, monkeypatch, capsys):
    # desc, amount, category(5=meals), paid-from(1=bank), date, division, receipt
    _inputs(monkeypatch, ['Lunch', '12.50', '5', '1', '2026-11-13', '', 'receipts/lunch.pdf'])
    E.cmd_add({'batch': False, 'quiet': True, 'date': None}, [])
    assert 'receipt:receipts/lunch.pdf' in _journal(entity)


def test_interactive_blank_receipt_records_none(entity, monkeypatch):
    _inputs(monkeypatch, ['Lunch', '12.50', '5', '1', '2026-11-13', '', ''])
    E.cmd_add({'batch': False, 'quiet': True, 'date': None}, [])
    assert 'receipt:' not in _journal(entity)


def test_list_shows_receipt(entity, capsys):
    _batch(entity, '--receipt', 'receipts/lunch.pdf')
    E.cmd_list({}, ['--period', '2026'])
    assert 'receipts/lunch.pdf' in capsys.readouterr().out
