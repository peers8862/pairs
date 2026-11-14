"""Report builder web endpoints + UI hooks (I76).

Endpoints list/run named reports from config.yaml and run ad-hoc
flag-composed reports, all through the same lib/report_builder.py
core as the CLI — the end-to-end test below proves a named run, an
ad-hoc run, and the CLI run return the same rows.

TestClient only for the endpoints; the real-browser check of the new
Reports tab lives in tests/test_browser_reports.py. Fixture journal +
config only; no entity data is touched.
"""

import shutil
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

import lib.report_builder as RB  # noqa: E402
import modules.web as web  # noqa: E402

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

JOURNAL = """2026-01-05 * Big purchase
    Expenses:Operating:Supplies    CAD 500.00
    Assets:Current:Chequing        CAD -500.00

2026-01-06 * Small purchase
    Expenses:Operating:Supplies    CAD 50.00
    Assets:Current:Chequing        CAD -50.00

2026-02-01 * Sale
    Assets:Current:Chequing        CAD 1000.00
    Income:Sales                   CAD -1000.00
"""

CONFIG = {
    'pair': {'currency': 'CAD'},
    'reports': {
        'monthly-expenses': {
            'title': 'Monthly expenses',
            'command': 'register',
            'query': 'acct:Expenses',
            'monthly': True,
        },
        'balances': {'command': 'bal'},
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    journal = tmp_path / 'company.journal'
    journal.write_text(JOURNAL)
    monkeypatch.setattr(web, 'get_entity_journal', lambda: journal)
    monkeypatch.setattr(web, 'load_config', lambda: dict(CONFIG))
    return TestClient(web.create_app())


def test_list_reports(client):
    r = client.get('/api/reports')
    assert r.status_code == 200
    reports = r.json()['reports']
    assert [x['name'] for x in reports] == ['monthly-expenses', 'balances']
    assert reports[0]['command'] == 'register'
    assert reports[0]['monthly'] is True
    assert reports[1]['title'] == 'balances'


def test_list_reports_empty(client, monkeypatch):
    monkeypatch.setattr(web, 'load_config', lambda: {'pair': {'currency': 'CAD'}})
    assert client.get('/api/reports').json() == {'reports': []}


@needs_hledger
def test_run_named(client):
    r = client.post('/api/reports/run', json={'name': 'balances'})
    assert r.status_code == 200
    data = r.json()
    assert data['ok'] is True and data['name'] == 'balances'
    assert data['columns'] == ['account', 'balance']
    by_acct = {row['account']: row['balance'] for row in data['rows']}
    assert by_acct['Assets:Current:Chequing'] == 'CAD 450.00'
    assert 'CAD 450.00' in data['text']


@needs_hledger
def test_run_named_unknown_is_404(client):
    r = client.post('/api/reports/run', json={'name': 'nope'})
    assert r.status_code == 404


@needs_hledger
def test_run_named_bad_stored_definition_is_400(client, monkeypatch):
    bad = {'pair': {'currency': 'CAD'},
           'reports': {'evil': {'command': 'bal',
                                'query': '--output-file=/tmp/x'}}}
    monkeypatch.setattr(web, 'load_config', lambda: bad)
    r = client.post('/api/reports/run', json={'name': 'evil'})
    assert r.status_code == 400


@needs_hledger
def test_build_adhoc_fields(client):
    r = client.post('/api/reports/build',
                    json={'command': 'register',
                          'fields': {'acct': 'Expenses'}})
    assert r.status_code == 200
    data = r.json()
    assert data['ok'] is True and len(data['rows']) == 2
    assert data['query'] == 'acct:Expenses'


@needs_hledger
def test_build_adhoc_raw_query_and_period(client):
    r = client.post('/api/reports/build',
                    json={'command': 'bs', 'query': '', 'period': '2026-01'})
    assert r.status_code == 200
    data = r.json()
    by_acct = {row['Account']: row[data['columns'][1]] for row in data['rows']}
    assert by_acct['Assets:Current:Chequing'] == 'CAD -550.00'


def test_build_rejects(client):
    # Leading-dash term: the guard, on the web path.
    r = client.post('/api/reports/build',
                    json={'command': 'register',
                          'query': '--output-file=/tmp/x'})
    assert r.status_code == 400
    # Unknown hledger command.
    r = client.post('/api/reports/build', json={'command': 'bogus'})
    assert r.status_code == 400
    # Bad period.
    r = client.post('/api/reports/build',
                    json={'command': 'bal', 'period': 'last month'})
    assert r.status_code == 400


@needs_hledger
def test_named_flagbuilt_and_web_return_same_rows(client, tmp_path):
    """Named run, ad-hoc run, and the core agree on the same rows."""
    journal = tmp_path / 'company.journal'
    journal.write_text(JOURNAL)
    core = RB.run_report(journal, RB.named_reports(CONFIG)['balances'])
    web_data = client.post('/api/reports/run',
                           json={'name': 'balances'}).json()
    adhoc = client.post('/api/reports/build',
                        json={'command': 'bal'}).json()
    assert [dict(r) for r in core['rows']] == web_data['rows'] == adhoc['rows']


def test_ui_hooks_present():
    html = (Path(__file__).resolve().parent.parent / 'web' / 'index.html').read_text()
    for needle in ('/api/reports', '/api/reports/run', '/api/reports/build',
                   'id="view-reports"', 'id="builder-report-select"',
                   'id="builder-results"', 'loadReportsView(',
                   'runBuilderNamed(', 'runBuilderAdhoc(',
                   "switchView('reports')"):
        assert needle in html, f"missing UI hook: {needle}"
