"""Stage bands (I53): date ranges (startup, seed, growth) to total spending
by company stage, from the books.

The bands live in config.yaml — no defaults, so nothing is invented about
the owner's history:

    stage_bands:
      startup: {start: 2024-01, end: 2024-12}
      seed: {start: 2025-01, end: 2025-06}
      growth: {start: 2025-07}

An open band (no end) runs to the last month with spending in the books.
Spending is all Expenses:* postings in the band's months. Bands must not
overlap; bad months and start-after-end are rejected.
"""

import shutil
from decimal import Decimal as D

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

from lib import stages as S
import modules.web as web  # noqa: E402

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

JOURNAL = """2026-01-05 * Ads
    Expenses:Operating:Marketing    CAD 800.00
    Assets:Current:Chequing        CAD -800.00

2026-02-06 * Rent
    Expenses:Operating:Rent        CAD 500.00
    Assets:Current:Chequing       CAD -500.00

2026-03-07 * Ads
    Expenses:Operating:Marketing    CAD 400.00
    Assets:Current:Chequing        CAD -400.00

2026-03-08 * Sale
    Income:Sales                   CAD -1000.00
    Assets:Current:Chequing        CAD 1000.00
"""

CONFIG = {'pair': {'currency': 'CAD'},
          'stage_bands': {'startup': {'start': '2026-01', 'end': '2026-01'},
                          'seed': {'start': '2026-02', 'end': '2026-02'},
                          'growth': {'start': '2026-03'}}}


def _journal(tmp_path):
    p = tmp_path / 'test.journal'
    p.write_text(JOURNAL)
    return str(p)


# ─── config ───────────────────────────────────────────────────────────────────

def test_bands_reads_config_in_order():
    assert S.bands(CONFIG) == [
        {'name': 'startup', 'start': '2026-01', 'end': '2026-01'},
        {'name': 'seed', 'start': '2026-02', 'end': '2026-02'},
        {'name': 'growth', 'start': '2026-03', 'end': None}]


def test_bands_empty_without_config():
    assert S.bands({'pair': {'currency': 'CAD'}}) == []


def test_bands_rejects_bad_config():
    for bad in ({'stage_bands': {'x': {'start': '2026-13'}}},
                {'stage_bands': {'x': {'start': '2026-01', 'end': '2025-12'}}},
                {'stage_bands': {'x': {'start': '2026-01', 'end': '2026-02'},
                                 'y': {'start': '2026-02', 'end': '2026-03'}}},
                {'stage_bands': {'x': {'end': '2026-01'}}},
                {'stage_bands': ['startup']}):
        with pytest.raises(ValueError):
            S.bands(bad)


# ─── pure computation ─────────────────────────────────────────────────────────

def test_spending_by_band_totals():
    monthly = {'2026-01': D(800), '2026-02': D(500), '2026-03': D(400)}
    rows = S.spending_by_band(monthly, CONFIG)
    assert [(r['name'], r['spending'], r['months']) for r in rows] == [
        ('startup', D(800), 1), ('seed', D(500), 1), ('growth', D(400), 1)]
    assert rows[2]['start'] == '2026-03' and rows[2]['end'] == '2026-03'


def test_open_band_runs_to_last_month_with_spending():
    monthly = {'2026-01': D(800), '2026-03': D(400)}
    rows = S.spending_by_band(monthly, {'stage_bands': {'growth': {'start': '2026-01'}}})
    assert rows[0]['end'] == '2026-03' and rows[0]['spending'] == D(1200)
    assert rows[0]['months'] == 3  # Jan, Feb, Mar in the span


def test_band_with_no_spending_reports_zero():
    rows = S.spending_by_band({'2026-01': D(800)},
                              {'stage_bands': {'future': {'start': '2027-01', 'end': '2027-03'}}})
    assert rows[0]['spending'] == D('0') and rows[0]['months'] == 3


def test_open_band_with_no_spending_after_start():
    rows = S.spending_by_band({'2026-01': D(800)},
                              {'stage_bands': {'growth': {'start': '2027-01'}}})
    assert rows[0]['spending'] == D('0') and rows[0]['end'] is None and rows[0]['months'] == 0


# ─── from the books ───────────────────────────────────────────────────────────

@needs_hledger
def test_monthly_spending_from_journal(tmp_path):
    out = S.monthly_spending(_journal(tmp_path), CONFIG, 'CAD')
    assert out == {'2026-01': D(800), '2026-02': D(500), '2026-03': D(400)}


@needs_hledger
def test_build_end_to_end(tmp_path):
    rows = S.build(_journal(tmp_path), CONFIG, 'CAD')
    assert [(r['name'], r['spending']) for r in rows] == [
        ('startup', D(800)), ('seed', D(500)), ('growth', D(400))]


@needs_hledger
def test_build_empty_without_bands(tmp_path):
    assert S.build(_journal(tmp_path), {'pair': {'currency': 'CAD'}}, 'CAD') == []


# ─── CLI + web ────────────────────────────────────────────────────────────────

@needs_hledger
def test_cli_stages_lists_bands(tmp_path, monkeypatch, capsys):
    import modules.stages as ST
    config = dict(CONFIG, journal_file=_journal(tmp_path))
    monkeypatch.setattr(ST, 'load_config', lambda: config)
    ST.dispatch([])
    out = capsys.readouterr().out
    assert 'startup' in out and '800' in out
    assert 'growth' in out and '400' in out


@needs_hledger
def test_cli_stages_no_bands(tmp_path, monkeypatch, capsys):
    import modules.stages as ST
    monkeypatch.setattr(ST, 'load_config',
                        lambda: {'pair': {'currency': 'CAD'},
                                 'journal_file': _journal(tmp_path)})
    ST.dispatch([])
    assert 'no stage bands' in capsys.readouterr().out.lower()


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = dict(CONFIG, journal_file=_journal(tmp_path))
    monkeypatch.setattr(web, 'load_config', lambda: config)
    return TestClient(web.create_app())


@needs_hledger
def test_web_stages(client):
    r = client.get('/api/stages')
    assert r.status_code == 200
    rows = r.json()['bands']
    assert [(b['name'], b['spending']) for b in rows] == [
        ('startup', 800), ('seed', 500), ('growth', 400)]
