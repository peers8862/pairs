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
    """This is ACB, not FIFO. A FIFO implementation gives 2290.92 remaining
    cost here (oldest lot consumed first); ACB gives 3436.38."""
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
