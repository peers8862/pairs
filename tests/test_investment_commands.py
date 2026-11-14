import pytest
import shutil
import subprocess

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


from modules.investment import (  # noqa: E402
    build_sell_entry, compute_acb_from_events, InsufficientHoldingError)

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


# ─── Trade hardening (I60–I62) — builder-level validation ────────────────
# These tests were written first and failed before the fix: sell accepted a
# zero/negative price, negative fee/fx passed through, malformed dates were
# written verbatim, and a full fractional sell was false-rejected on float
# dust. The command-layer tests for the same items live in
# tests/test_trade_hardening.py.

from modules.investment import build_buy_entry as _buy  # noqa: E402


def _buy_kwargs(**over):
    kw = dict(date="2026-07-20", symbol="TSLA", qty=5, unit_price=100.00,
              quote_currency="CAD", fx=1.0, fee=0.0,
              tax_account="taxable",
              cash_account="Assets:Current:Business Chequing",
              entity_currency="CAD")
    kw.update(over)
    return kw


def _sell_kwargs(**over):
    kw = dict(date="2026-07-25", symbol="TSLA", qty=6, unit_price=500.00,
              fee=0.0, tax_account="taxable",
              cash_account="Assets:Current:Business Chequing",
              entity_currency="CAD", events=BUY_10_TSLA,
              gains_account="Income:Non-Operating:Capital Gains")
    kw.update(over)
    return kw


def test_sell_zero_price_rejected():
    with pytest.raises(ValueError, match="Price must be positive"):
        build_sell_entry(**_sell_kwargs(unit_price=0))


def test_sell_negative_price_rejected():
    with pytest.raises(ValueError, match="Price must be positive"):
        build_sell_entry(**_sell_kwargs(unit_price=-50.00))


def test_buy_negative_fee_rejected():
    with pytest.raises(ValueError, match="Fee must not be negative"):
        _buy(**_buy_kwargs(fee=-9.95))


def test_sell_negative_fee_rejected():
    with pytest.raises(ValueError, match="Fee must not be negative"):
        build_sell_entry(**_sell_kwargs(fee=-9.95))


def test_buy_zero_fx_rejected():
    with pytest.raises(ValueError, match="FX rate must be positive"):
        _buy(**_buy_kwargs(quote_currency="USD", fx=0.0))


def test_buy_negative_fx_rejected():
    with pytest.raises(ValueError, match="FX rate must be positive"):
        _buy(**_buy_kwargs(quote_currency="USD", fx=-1.366))


@pytest.mark.parametrize("bad_date", ["2026-13-45", "2026/07/20", "garbage",
                                      "2026-02-30", "2026-7-20", ""])
def test_builders_reject_malformed_dates(bad_date):
    with pytest.raises(ValueError, match="Invalid date"):
        _buy(**_buy_kwargs(date=bad_date))
    with pytest.raises(ValueError, match="Invalid date"):
        build_sell_entry(**_sell_kwargs(date=bad_date))


def test_full_fractional_sell_succeeds_despite_float_dust():
    """Ten 0.1 buys replay to 0.9999999999999999, not 1.0 — selling 1.0
    must not be false-rejected (I62). Pre-fix this raised
    InsufficientHoldingError."""
    events = [("buy", 0.1, 10.0)] * 10
    held, _, _ = compute_acb_from_events(events)
    assert held < 1.0  # float dust: the replay really is short of 1.0
    assert 1.0 - held < 1e-9
    entry = build_sell_entry(**_sell_kwargs(qty=1.0, unit_price=500.00,
                                            events=events))
    assert "-1 TSLA @@ CAD 100.00" in entry


def test_sell_just_over_epsilon_still_rejected():
    """Genuinely over-held sells must still fail (I62): 1.0 + 0.01 held
    against 1.0 is over by far more than _EPSILON."""
    events = [("buy", 0.1, 10.0)] * 10
    with pytest.raises(InsufficientHoldingError):
        build_sell_entry(**_sell_kwargs(qty=1.01, unit_price=500.00,
                                        events=events))


def test_sell_at_exact_epsilon_boundary_succeeds():
    events = [("buy", 10, 1000.0)]
    held, _, _ = compute_acb_from_events(events)
    entry = build_sell_entry(**_sell_kwargs(qty=held + 5e-10,
                                            unit_price=500.00, events=events))
    assert "-10 TSLA @@ CAD 1000.00" in entry


@pytest.mark.skipif(shutil.which("hledger") is None, reason="hledger not installed")
def test_buy_then_sell_reports_correct_position(tmp_path):
    """A buy followed by a partial sell must leave hledger reporting the
    remaining quantity, and the whole file must parse."""
    buy = build_buy_entry(
        date="2026-07-20", symbol="TSLA", qty=10, unit_price=372.73,
        quote_currency="USD", fx=1.3660, fee=9.95,
        tax_account="taxable", cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD",
    )
    sell = build_sell_entry(
        date="2026-07-25", symbol="TSLA", qty=6, unit_price=586.6667,
        fee=9.95, tax_account="taxable",
        cash_account="Assets:Current:Business Chequing",
        entity_currency="CAD", events=[("buy", 10, 5101.44)],
        gains_account="Income:Non-Operating:Capital Gains",
    )
    journal = tmp_path / "e2e.journal"
    journal.write_text(buy + sell)

    parsed = subprocess.run(
        ["hledger", "-f", str(journal), "print"],
        capture_output=True, text=True,
    )
    assert parsed.returncode == 0, parsed.stderr

    balance = subprocess.run(
        ["hledger", "-f", str(journal), "bal",
         "Assets:Investments:Taxable:TSLA", "--no-total"],
        capture_output=True, text=True,
    )
    assert balance.returncode == 0, balance.stderr
    assert "4 TSLA" in balance.stdout
