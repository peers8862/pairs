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
