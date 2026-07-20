import pytest

from modules.investment import build_buy_entry


def test_buy_entry_matches_spec_example():
    entry = build_buy_entry(
        date="2026-07-20", symbol="TSLA", qty=10, unit_price=372.73,
        quote_currency="USD", fx=1.3660, fee=9.95,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    assert "10 TSLA @@ CAD 5101.44" in entry
    assert "Assets:Current:Business Chequing" in entry
    assert "CAD -5101.44" in entry
    assert "pair:1011" in entry


def test_fee_is_added_to_cost_basis():
    """CRA: commission is added to ACB on acquisition, not expensed."""
    without = build_buy_entry(
        date="2026-07-20", symbol="TSLA", qty=10, unit_price=100.00,
        quote_currency="CAD", fx=1.0, fee=0.0,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    with_fee = build_buy_entry(
        date="2026-07-20", symbol="TSLA", qty=10, unit_price=100.00,
        quote_currency="CAD", fx=1.0, fee=9.95,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    assert "@@ CAD 1000.00" in without
    assert "@@ CAD 1009.95" in with_fee
    assert "Expenses" not in with_fee


def test_fx_tag_only_when_currencies_differ():
    same = build_buy_entry(
        date="2026-07-20", symbol="SHOP.TO", qty=5, unit_price=100.00,
        quote_currency="CAD", fx=1.0, fee=0.0,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    differ = build_buy_entry(
        date="2026-07-20", symbol="TSLA", qty=5, unit_price=100.00,
        quote_currency="USD", fx=1.3660, fee=0.0,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    assert "fx:" not in same
    assert "fx:1.366" in differ


def test_registered_account_buy_uses_registered_path():
    entry = build_buy_entry(
        date="2026-07-20", symbol="BTC", qty=0.00431, unit_price=92018.55,
        quote_currency="CAD", fx=1.0, fee=0.0,
        tax_account="tfsa", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    assert "Assets:Investments:TFSA:BTC" in entry
    assert "0.00431 BTC" in entry


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        build_buy_entry(
            date="2026-07-20", symbol="TSLA", qty=-5, unit_price=100.00,
            quote_currency="CAD", fx=1.0, fee=0.0,
            tax_account="taxable", cash_account="Assets:Current:Business Chequing",
            entity_currency="CAD",
        )


def test_invalid_tax_account_rejected():
    with pytest.raises(ValueError):
        build_buy_entry(
            date="2026-07-20", symbol="TSLA", qty=5, unit_price=100.00,
            quote_currency="CAD", fx=1.0, fee=0.0,
            tax_account="resp", cash_account="Assets:Current:Business Chequing",
            entity_currency="CAD",
        )


from modules.investment import build_sell_entry, InsufficientHoldingError

BUY_10_TSLA = [("buy", 10, 5101.44)]


def test_sell_entry_matches_spec_example():
    entry = build_sell_entry(
        date="2026-07-25", symbol="TSLA", qty=6, unit_price=586.6667,
        fee=9.95, tax_account="taxable",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=BUY_10_TSLA,
        gains_account="Income:Non-Operating:Capital Gains",
    )
    assert "-6 TSLA @@ CAD 3060.86" in entry
    assert "CAD 3510.05" in entry
    assert "CAD -449.19" in entry
    assert "pair:0110" in entry


def test_loss_uses_loss_pair_code():
    entry = build_sell_entry(
        date="2026-07-25", symbol="TSLA", qty=6, unit_price=400.00,
        fee=0.0, tax_account="taxable",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=BUY_10_TSLA,
        gains_account="Income:Non-Operating:Capital Gains",
    )
    assert "pair:0010" in entry


def test_registered_gain_posts_to_non_taxable_account():
    """A TFSA gain is still economically real and must balance — it goes to a
    separate account so tax reporting can exclude it. Omitting it entirely
    would leave the transaction out of balance and hledger would reject it."""
    entry = build_sell_entry(
        date="2026-07-25", symbol="BTC", qty=0.002, unit_price=100000.00,
        fee=0.0, tax_account="tfsa",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=[("buy", 0.00431, 396.50)],
        gains_account="Income:Non-Operating:Capital Gains",
        registered_gains_account="Income:Non-Operating:Registered Gains",
    )
    assert "Income:Non-Operating:Registered Gains" in entry
    assert "Income:Non-Operating:Capital Gains" not in entry


def test_registered_sell_balances():
    entry = build_sell_entry(
        date="2026-07-25", symbol="BTC", qty=0.002, unit_price=100000.00,
        fee=0.0, tax_account="tfsa",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=[("buy", 0.00431, 396.50)],
        gains_account="Income:Non-Operating:Capital Gains",
        registered_gains_account="Income:Non-Operating:Registered Gains",
    )
    amounts = []
    for line in entry.splitlines():
        if "@@ CAD " in line:
            amounts.append(-float(line.split("@@ CAD ")[1].strip()))
        elif "CAD " in line:
            amounts.append(float(line.split("CAD ")[1].strip()))
    assert sum(amounts) == pytest.approx(0.0, abs=0.01)


def test_sell_more_than_held_raises():
    with pytest.raises(InsufficientHoldingError):
        build_sell_entry(
            date="2026-07-25", symbol="TSLA", qty=20, unit_price=500.00,
            fee=0.0, tax_account="taxable",
            cash_account="Assets:Current:Business Chequing",
            entity_currency="CAD", events=BUY_10_TSLA,
            gains_account="Income:Non-Operating:Capital Gains",
        )


def test_sell_transaction_balances_to_zero():
    """Every amount in the entry must sum to zero or hledger rejects it."""
    entry = build_sell_entry(
        date="2026-07-25", symbol="TSLA", qty=6, unit_price=586.6667,
        fee=9.95, tax_account="taxable",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=BUY_10_TSLA,
        gains_account="Income:Non-Operating:Capital Gains",
    )
    amounts = []
    for line in entry.splitlines():
        if "CAD " in line and "@@" not in line:
            amounts.append(float(line.split("CAD ")[1].strip()))
        elif "@@ CAD " in line:
            amounts.append(-float(line.split("@@ CAD ")[1].strip()))
    assert sum(amounts) == pytest.approx(0.0, abs=0.01)
