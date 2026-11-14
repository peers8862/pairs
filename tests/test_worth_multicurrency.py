"""Multi-currency worth report (I75).

`pair worth --cost` values holdings at cost; `pair worth --value=now`
at current market prices (both converted to the entity currency with
hledger -X, so the report total stays single-currency). Holdings with no
price are omitted under --value=now and listed in a note; --cost still
shows them. The default report (no flag) is unchanged.
"""
import pytest

import lib.helpers as H
import modules.worth as W

JOURNAL = """\
2026-01-01 * Open
    Assets:Current:Chequing  CAD 1000.00
    Assets:Current:USD Account  USD 500.00
    Equity:Opening Balances  CAD -1000.00
    Equity:Opening Balances  USD -500.00

2026-02-01 * Buy TSLA
    Assets:Investments:TSLA  10 TSLA @@ USD 100.00
    Assets:Current:USD Account  USD -100.00

2026-03-01 * Buy NOPE (no price ever published)
    Assets:Investments:NOPE  5 NOPE @@ USD 50.00
    Assets:Current:USD Account  USD -50.00

P 2026-11-01 TSLA USD 150.00
P 2026-11-01 USD CAD 1.36
"""

JOURNAL_NO_PRICES = JOURNAL.split("P 2026-11-01")[0]


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    journal = tmp_path / 'entity.journal'
    journal.write_text(JOURNAL)
    config = {
        'pair': {'currency': 'CAD', 'name': 'Test'},
        'accounts': {'bank': 'Assets:Current:Chequing'},
        'journal_file': str(journal),
    }
    monkeypatch.setattr(W, 'load_config', lambda: config)
    return tmp_path, config, journal


def _run(capsys, *args):
    W.cmd_worth({}, list(args))
    return capsys.readouterr().out


def test_default_report_unchanged_no_investments_section(entity, capsys):
    tmp_path, config, journal = entity
    out = _run(capsys)
    # Baseline behaviour, locked in: foreign cash is shown at face value
    # (the parser strips the currency label) and commodity quantities are
    # not numbers, so no Investments section appears without a flag.
    assert 'Investments' not in out
    assert 'USD Account' in out
    assert '350.00' in out  # USD 350 shown as CAD 350.00 (pre-existing)


def test_cost_values_holdings_at_cost(entity, capsys):
    out = _run(capsys, '--cost')
    assert 'Investments' in out
    # Cost basis, FX-converted to CAD at the published USD rate (1.36):
    # TSLA 100 USD -> 136.00, NOPE 50 USD -> 68.00, USD cash 350 -> 476.00.
    assert '136.00' in out
    assert '68.00' in out
    assert '476.00' in out
    assert 'Valued at cost' in out
    # Total assets: 1000 + 476 + 136 + 68 = 1680.
    assert '1,680.00' in out


def test_value_now_values_holdings_at_market(entity, capsys):
    out = _run(capsys, '--value=now')
    assert 'Investments' in out
    # TSLA 10 x USD 150 = 1500 USD -> 2040 CAD; USD cash 350 -> 476 CAD.
    assert '2,040.00' in out
    assert '476.00' in out
    assert 'Valued at current prices' in out
    # NOPE has no price: omitted from the numbers, named in the note.
    assert 'NOPE' in out
    assert 'No price available' in out
    # Total assets: 1000 + 476 + 2040 = 3516.
    assert '3,516.00' in out


def test_value_now_without_any_prices_omits_holdings(entity, monkeypatch, capsys):
    tmp_path, config, journal = entity
    journal.write_text(JOURNAL_NO_PRICES)
    out = _run(capsys, '--value=now')
    # No price for anything: holdings are omitted, cash stays at face value.
    assert 'TSLA' in out  # named in the omitted note, not as a value
    assert '2,040.00' not in out
    assert 'No price available' in out


def test_cost_and_value_together_is_an_error(entity, capsys):
    with pytest.raises(SystemExit):
        W.cmd_worth({}, ['--cost', '--value=now'])
    assert 'cannot be combined' in capsys.readouterr().out


def test_value_flag_rejects_other_modes(entity, capsys):
    with pytest.raises(SystemExit):
        W.cmd_worth({}, ['--value=end'])
    assert 'Only --value=now' in capsys.readouterr().out
