"""CAC allocation by category (I52).

A % of each report category counts as acquisition cost; the allocation lives
in config.yaml:

    cac_allocation:
      Marketing & Sales: 1.0
      Salaries & Benefits: 0.25

Acquisition spend for a month is the allocated share of that month's expenses
from the books, summarised by report category. The KPI `acquisition_spend`
is then ledger-fed (a typed value still wins, per the KPI rules) and the
existing derived `cac = acquisition_spend / new_customers` works off the
books instead of a typed number. No allocation configured means no feed and
no behaviour change.
"""

import shutil
from decimal import Decimal as D

import pytest

from lib import cac as C
from lib import kpi as K

needs_hledger = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not installed"
)

JOURNAL = """2026-01-05 * Ads
    Expenses:Operating:Marketing    CAD 800.00
    Assets:Current:Chequing        CAD -800.00

2026-01-06 * Contractor
    Expenses:Operating:Payroll     CAD 2000.00
    Assets:Current:Chequing       CAD -2000.00

2026-01-07 * Rent
    Expenses:Operating:Rent        CAD 500.00
    Assets:Current:Chequing       CAD -500.00

2026-02-05 * Ads
    Expenses:Operating:Marketing    CAD 400.00
    Assets:Current:Chequing        CAD -400.00
"""

CONFIG = {'pair': {'currency': 'CAD'},
          'cac_allocation': {'Marketing & Sales': 1.0, 'Salaries & Benefits': 0.25}}


def _journal(tmp_path):
    p = tmp_path / 'test.journal'
    p.write_text(JOURNAL)
    return str(p)


# ─── allocation config ────────────────────────────────────────────────────────

def test_allocation_reads_fractions():
    assert C.allocation(CONFIG) == {'Marketing & Sales': D('1.0'),
                                    'Salaries & Benefits': D('0.25')}


def test_allocation_missing_is_empty():
    assert C.allocation({'pair': {'currency': 'CAD'}}) == {}


def test_allocation_rejects_bad_config():
    for bad in ({'cac_allocation': {'Marketing & Sales': 1.5}},
                {'cac_allocation': {'Marketing & Sales': -0.1}},
                {'cac_allocation': {'Marketing & Sales': 'all'}},
                {'cac_allocation': {'No Such Category': 0.5}},
                {'cac_allocation': ['Marketing & Sales']}):
        with pytest.raises(ValueError):
            C.allocation(bad)


# ─── pure computation ─────────────────────────────────────────────────────────

def test_acquisition_spend_allocates_by_category():
    by_category = {'Marketing & Sales': D(800), 'Salaries & Benefits': D(2000),
                   'Overhead': D(500)}
    assert C.acquisition_spend(by_category, CONFIG) == D('1300')  # 800 + 0.25*2000


def test_acquisition_spend_zero_without_allocation():
    assert C.acquisition_spend({'Marketing & Sales': D(800)}, {}) == D('0')


def test_cac_divides_by_new_customers():
    assert C.cac(D('1300'), D('10')) == D('130')
    assert C.cac(D('1300'), D('0')) is None
    assert C.cac(D('1300'), None) is None


# ─── from the books ───────────────────────────────────────────────────────────

@needs_hledger
def test_monthly_acquisition_spend_from_journal(tmp_path):
    out = C.monthly_acquisition_spend(_journal(tmp_path), CONFIG, 'CAD')
    assert out == {'2026-01': D('1300'), '2026-02': D('400')}


@needs_hledger
def test_monthly_acquisition_spend_empty_without_allocation(tmp_path):
    assert C.monthly_acquisition_spend(_journal(tmp_path), {}, 'CAD') == {}


# ─── KPI integration ──────────────────────────────────────────────────────────

@needs_hledger
def test_ledger_series_feeds_acquisition_spend(tmp_path):
    from modules.kpi import ledger_series
    config = dict(CONFIG, journal_file=_journal(tmp_path))
    feeds = ledger_series(config)
    assert feeds['acquisition_spend'] == {'2026-01': D('1300'), '2026-02': D('400')}


@needs_hledger
def test_ledger_series_no_feed_without_allocation(tmp_path):
    from modules.kpi import ledger_series
    feeds = ledger_series({'pair': {'currency': 'CAD'}, 'journal_file': _journal(tmp_path)})
    assert 'acquisition_spend' not in feeds


def test_grid_cac_comes_from_books_and_typed_value_wins():
    defs = K.BUILTIN
    assert defs['acquisition_spend']['source'] == 'ledger'
    values = {'new_customers': {'2026-01': D(10), '2026-02': D(5)}}
    ledger = {'acquisition_spend': {'2026-01': D(1300), '2026-02': D(400)}}
    cells = K.grid(defs, values, ledger, ['2026-01', '2026-02'])
    assert cells['acquisition_spend']['2026-01'] == {'value': D(1300), 'kind': 'ledger'}
    assert cells['cac']['2026-01']['value'] == D('130')
    assert cells['cac']['2026-02']['value'] == D('80')
    # A typed acquisition spend wins over the ledger feed, and CAC follows it.
    typed = dict(values, acquisition_spend={'2026-01': D(2000)})
    cells = K.grid(defs, typed, ledger, ['2026-01', '2026-02'])
    assert cells['acquisition_spend']['2026-01'] == {'value': D(2000), 'kind': 'manual'}
    assert cells['cac']['2026-01']['value'] == D('200')
