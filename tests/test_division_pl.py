"""Division-level P&L reporting (I73).

`pair income statement [--division DIV] [--period P]` prints hledger's
own income statement filtered by the division tag; the web endpoint
GET /api/income-statement returns the same figures as JSON.

Semantics: only transactions tagged with the division count. Entries
without a division tag are excluded from a division statement but
included entity-wide.
"""
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import lib.helpers as H
import modules.income as INC
import modules.web as web

JOURNAL = """\
2026-01-15 * Client payment  ; pair:0110, division:ops
    Assets:Current:Chequing  CAD 500.00
    Income:Operating:Consulting  CAD -500.00

2026-01-16 * Untagged income  ; pair:0110
    Assets:Current:Chequing  CAD 300.00
    Income:Operating:Consulting  CAD -300.00

2026-01-20 * Office supplies  ; pair:0000, division:ops
    Expenses:Operating:Office Supplies  CAD 120.00
    Assets:Current:Chequing  CAD -120.00

2026-01-21 * Admin travel  ; pair:0000, division:admin
    Expenses:Operating:Travel  CAD 80.00
    Assets:Current:Chequing  CAD -80.00
"""

CONFIG = {
    'pair': {'currency': 'CAD'},
    'accounts': {'bank': 'Assets:Current:Chequing'},
    'divisions': ['ops', 'admin'],
}


@pytest.fixture
def entity(tmp_path, monkeypatch):
    inc = tmp_path / 'include'
    inc.mkdir(parents=True)
    (inc / 'entity.journal').write_text(JOURNAL)
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(CONFIG))
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(INC, 'get_entity_journal', lambda: inc / 'entity.journal')
    monkeypatch.setattr(INC, 'require_entity', lambda: 'test')
    monkeypatch.setattr(INC, 'load_config', lambda: CONFIG)
    monkeypatch.setattr(web, 'get_entity_journal', lambda: inc / 'entity.journal')
    monkeypatch.setattr(web, 'load_config', lambda: CONFIG)
    return tmp_path


@pytest.fixture
def client(entity):
    return TestClient(web.create_app())


# ─── CLI ────────────────────────────────────────────────────────────────────

def test_cli_division_statement(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        INC.cmd_statement({}, ['--division', 'ops'])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert 'Income Statement' in out or 'income statement' in out.lower()
    assert '380.00' in out  # 500 income - 120 expenses
    assert '300.00' not in out  # untagged income excluded
    assert 'Travel' not in out  # other division's expense excluded


def test_cli_entity_wide_statement(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        INC.cmd_statement({}, [])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert '600.00' in out  # 800 income - 200 expenses


def test_cli_unknown_division_fails_gracefully(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        INC.cmd_statement({}, ['--division', 'nope'])
    assert exc.value.code == 1
    assert 'Unknown division' in capsys.readouterr().out


def test_cli_missing_journal_fails_gracefully(entity, monkeypatch, capsys):
    monkeypatch.setattr(INC, 'get_entity_journal', lambda: Path('/nonexistent/entity.journal'))
    with pytest.raises(SystemExit) as exc:
        INC.cmd_statement({}, ['--division', 'ops'])
    assert exc.value.code == 1
    assert 'No journal found' in capsys.readouterr().out


# ─── Web ────────────────────────────────────────────────────────────────────

def test_web_division_statement(client):
    resp = client.get('/api/income-statement?division=ops')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['division'] == 'ops'
    assert data['income'] == 500.00
    assert data['expenses'] == 120.00
    assert data['net'] == 380.00
    accounts = {i['account']: i for i in data['items']}
    assert accounts['Income:Operating:Consulting']['amount'] == 500.00
    assert accounts['Expenses:Operating:Office Supplies']['amount'] == 120.00
    assert 'Expenses:Operating:Travel' not in accounts


def test_web_entity_wide_statement(client):
    resp = client.get('/api/income-statement')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['division'] is None
    assert data['income'] == 800.00
    assert data['expenses'] == 200.00
    assert data['net'] == 600.00


def test_web_admin_division_can_be_negative(client):
    resp = client.get('/api/income-statement?division=admin')
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data['income'] == 0
    assert data['expenses'] == 80.00
    assert data['net'] == -80.00


def test_web_unknown_division_400(client):
    resp = client.get('/api/income-statement?division=nope')
    assert resp.status_code == 400
    assert 'Unknown division' in resp.json()['detail']
