import pytest

from modules.investment import compute_acb_from_events, InsufficientHoldingError


def test_single_buy():
    qty, cost, avg = compute_acb_from_events([("buy", 10, 5101.44)])
    assert qty == 10
    assert cost == pytest.approx(5101.44)
    assert avg == pytest.approx(510.144)


def test_two_buys_average():
    qty, cost, avg = compute_acb_from_events([
        ("buy", 10, 3727.30),
        ("buy", 5, 2000.00),
    ])
    assert qty == 15
    assert cost == pytest.approx(5727.30)
    assert avg == pytest.approx(381.82)


def test_sell_reduces_cost_proportionally_not_by_lot():
    """This is ACB, not FIFO. A FIFO implementation would leave 3490.92
    remaining cost here (only the oldest lot consumed); ACB leaves 3436.38."""
    qty, cost, avg = compute_acb_from_events([
        ("buy", 10, 3727.30),
        ("buy", 5, 2000.00),
        ("sell", 6, 0),
    ])
    assert qty == 9
    assert cost == pytest.approx(3436.38, abs=0.01)
    assert avg == pytest.approx(381.82)


def test_average_unchanged_by_sell():
    _, _, avg_before = compute_acb_from_events([("buy", 10, 5101.44)])
    _, _, avg_after = compute_acb_from_events([
        ("buy", 10, 5101.44),
        ("sell", 6, 0),
    ])
    assert avg_before == pytest.approx(avg_after)


def test_buy_after_sell_reaverages():
    qty, cost, avg = compute_acb_from_events([
        ("buy", 10, 1000.00),
        ("sell", 5, 0),
        ("buy", 5, 800.00),
    ])
    assert qty == 10
    assert cost == pytest.approx(1300.00)
    assert avg == pytest.approx(130.00)


def test_sell_more_than_held_raises():
    with pytest.raises(InsufficientHoldingError):
        compute_acb_from_events([("buy", 5, 500.00), ("sell", 6, 0)])


def test_empty_history_is_zero():
    qty, cost, avg = compute_acb_from_events([])
    assert (qty, cost, avg) == (0, 0.0, 0.0)


def test_full_disposal_returns_zero_average():
    qty, cost, avg = compute_acb_from_events([
        ("buy", 10, 1000.00),
        ("sell", 10, 0),
    ])
    assert qty == 0
    assert cost == pytest.approx(0.0)
    assert avg == 0.0


def test_crypto_fractional_quantities():
    qty, cost, avg = compute_acb_from_events([
        ("buy", 0.5, 45000.00),
        ("buy", 0.25, 25000.00),
    ])
    assert qty == pytest.approx(0.75)
    assert avg == pytest.approx(93333.333, abs=0.01)


def test_full_disposal_of_fractional_position_is_exact_zero():
    """Float dust must not survive a full disposal, or the average becomes
    nonsensical and capital-gains reporting is corrupted."""
    qty, cost, avg = compute_acb_from_events([
        ("buy", 0.1, 100.0),
        ("buy", 0.2, 200.0),
        ("sell", 0.3, 0),
    ])
    assert qty == 0
    assert cost == pytest.approx(0.0)
    assert avg == 0.0


def test_sell_all_fractional_does_not_falsely_raise():
    """Selling exactly the held fractional amount must not trip the
    insufficient-holding guard on float residue."""
    qty, cost, avg = compute_acb_from_events([
        ("buy", 0.1, 100.0),
        ("buy", 0.2, 200.0),
        ("sell", 0.3, 0),
    ])
    assert qty == 0


from modules.investment import (
    holding_account, parse_hledger_events, TAX_ACCOUNTS, REGISTERED_ACCOUNTS,
)


def test_holding_account_path():
    assert holding_account("taxable", "TSLA") == "Assets:Investments:Taxable:TSLA"
    assert holding_account("tfsa", "BTC") == "Assets:Investments:TFSA:BTC"
    assert holding_account("rrsp", "GE") == "Assets:Investments:RRSP:GE"
    assert holding_account("corporate", "SHOP.TO") == "Assets:Investments:Corporate:SHOP.TO"


def test_registered_accounts_are_a_subset_of_tax_accounts():
    assert set(REGISTERED_ACCOUNTS) < set(TAX_ACCOUNTS)
    assert "tfsa" in REGISTERED_ACCOUNTS
    assert "rrsp" in REGISTERED_ACCOUNTS
    assert "taxable" not in REGISTERED_ACCOUNTS


def test_parse_buy_and_sell_from_hledger_print():
    output = """2026-07-20 * Buy TSLA | 10 sh
    Assets:Investments:Taxable:TSLA      10 TSLA @@ CAD 5101.44
    Assets:Current:Business Chequing        CAD -5101.44

2026-07-25 * Sell TSLA | 6 sh
    Assets:Investments:Taxable:TSLA      -6 TSLA @@ CAD 3060.86
    Assets:Current:Business Chequing         CAD 3510.05
"""
    events = parse_hledger_events(output, "TSLA")
    assert events == [("buy", 10.0, 5101.44), ("sell", 6.0, 3060.86)]


def test_parse_ignores_other_symbols():
    output = """2026-07-20 * Buy BTC
    Assets:Investments:TFSA:BTC      0.5 BTC @@ CAD 45000.00
"""
    assert parse_hledger_events(output, "TSLA") == []


def test_parse_handles_fractional_quantities():
    output = """2026-07-20 * Buy BTC
    Assets:Investments:TFSA:BTC      0.00431 BTC @@ CAD 396.50
"""
    assert parse_hledger_events(output, "BTC") == [("buy", 0.00431, 396.50)]


def test_parse_empty_output():
    assert parse_hledger_events("", "TSLA") == []
