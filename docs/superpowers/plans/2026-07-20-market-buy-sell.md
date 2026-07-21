# `pair market buy` / `sell` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record commodity purchases and disposals as hledger journal transactions, with CRA-compliant adjusted cost base (ACB) tracking and realized gain/loss postings.

**Architecture:** A new `modules/investment.py` holds buy/sell commands and ACB computation; `modules/market.py` dispatches to it. A new `format_commodity_entry()` in `lib/journal.py` emits lot-syntax postings at correct precision, leaving the existing `format_entry` untouched so its eight callers carry no regression risk. ACB is derived by replaying prior postings read from `hledger`.

**Tech Stack:** Python 3 (stdlib only for logic), hledger CLI for journal queries, pytest for tests, PyYAML via existing `lib.helpers`.

**Spec:** `docs/superpowers/specs/2026-07-20-market-buy-design.md`

## Global Constraints

- Entity currency is CAD. Fees are always expressed in entity currency.
- Cost basis is ACB (weighted average), never FIFO. Sells reduce accumulated cost proportionally and must not alter the average.
- Holdings live at `Assets:Investments:<TaxAccount>:<SYMBOL>` where `<TaxAccount>` is one of `Taxable`, `Corporate`, `TFSA`, `RRSP`.
- Registered accounts (`TFSA`, `RRSP`) route gains to `Income:Non-Operating:Registered Gains` (configurable via `config.accounts.registered_gains`) instead of the capital-gains account. They are never omitted — the entry would not balance.
- Money renders at 2 decimal places; quantities render at up to 8, with trailing zeros stripped.
- Total cost uses hledger `@@` (total price) syntax in CAD, never `@` (unit price).
- Pair tags: buy `1011`, sell-at-gain `0110`, sell-at-loss `0010`, sell-at-break-even `1011`.
- Run Python via `.venv/bin/python` — the system Python lacks this project's dependencies.
- All new journal entries are written through `append_journal`.

---

## File Structure

| File | Responsibility |
|---|---|
| `tests/conftest.py` (create) | pytest path setup so `lib` and `modules` import |
| `tests/test_journal_format.py` (create) | Formatter unit + golden tests |
| `tests/test_investment_acb.py` (create) | ACB replay logic tests |
| `tests/test_investment_commands.py` (create) | Command-level guards and integration |
| `lib/journal.py` (modify) | Add `format_commodity_entry`; `format_entry` untouched |
| `modules/investment.py` (create) | `cmd_buy`, `cmd_sell`, `compute_acb`, helpers |
| `modules/market.py` (modify) | Dispatch `buy`/`sell`; menu entries; help text |
| `requirements-dev.txt` (create) | Pin pytest as a dev dependency |

---

### Task 1: Test infrastructure

This repo currently has no tests and no pytest. Everything downstream depends on being able to run one, so this task establishes the harness and proves it works.

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: a working `.venv/bin/python -m pytest` invocation; `tests/` importable against `lib` and `modules`

- [ ] **Step 1: Create the dev requirements file**

```
pytest==8.3.4
```

- [ ] **Step 2: Install pytest into the existing venv**

Run: `.venv/bin/pip install -r requirements-dev.txt`
Expected: `Successfully installed pytest-8.3.4` (plus iniconfig, pluggy, packaging)

- [ ] **Step 3: Create conftest.py so tests can import project modules**

`tests/conftest.py`:

```python
"""Make the project root importable from tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 4: Write a smoke test proving imports work**

`tests/test_smoke.py`:

```python
def test_project_modules_import():
    from lib import journal
    assert hasattr(journal, 'format_entry')
```

- [ ] **Step 5: Run it**

Run: `.venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS, `1 passed`

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt tests/conftest.py tests/test_smoke.py
git commit -m "test: add pytest harness"
```

---

### Task 2: `format_commodity_entry` — quantity formatting

The existing `format_entry` (`lib/journal.py:126`) applies `f"{currency} {amount:.2f}"` to every posting, which renders `0.00431 BTC` as `0.00`. This task builds the quantity formatter that avoids it.

**Files:**
- Modify: `lib/journal.py` (append after `format_entry`, which ends at line 152)
- Test: `tests/test_journal_format.py`

**Interfaces:**
- Consumes: nothing
- Produces: `format_quantity(value: float) -> str` — renders a quantity at up to 8 decimal places with trailing zeros stripped

- [ ] **Step 1: Write the failing tests**

`tests/test_journal_format.py`:

```python
from lib.journal import format_quantity


def test_whole_number_has_no_decimals():
    assert format_quantity(10) == "10"


def test_crypto_precision_survives():
    assert format_quantity(0.00431) == "0.00431"


def test_trailing_zeros_stripped():
    assert format_quantity(2.50000000) == "2.5"


def test_eight_decimal_places_preserved():
    assert format_quantity(0.12345678) == "0.12345678"


def test_negative_quantity():
    assert format_quantity(-6) == "-6"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_journal_format.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_quantity'`

- [ ] **Step 3: Implement**

Append to `lib/journal.py`:

```python
def format_quantity(value):
    """Format a commodity quantity at up to 8dp, trailing zeros stripped.

    Money uses 2dp, but quantities must not: 0.00431 BTC formatted as money
    rounds to 0.00, producing a balanced but silently wrong entry.
    """
    text = f"{value:.8f}".rstrip('0').rstrip('.')
    return text if text and text != '-' else '0'
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_journal_format.py -v`
Expected: PASS, `5 passed`

- [ ] **Step 5: Commit**

```bash
git add lib/journal.py tests/test_journal_format.py
git commit -m "feat: add format_quantity for commodity precision"
```

---

### Task 3: `format_commodity_entry` — full entry emission

**Files:**
- Modify: `lib/journal.py`
- Test: `tests/test_journal_format.py`

**Interfaces:**
- Consumes: `format_quantity` from Task 2
- Produces: `format_commodity_entry(date, description, commodity_posting, cash_postings, tags=None) -> str` where `commodity_posting` is `(account, quantity, symbol, total_currency, total_cost)` and `cash_postings` is a list of `(account, currency, amount)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_journal_format.py`:

```python
from lib.journal import format_commodity_entry


def test_buy_entry_uses_double_at_syntax():
    entry = format_commodity_entry(
        "2026-07-20", "Buy TSLA | 10 sh",
        ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
        [("Assets:Current:Business Chequing", "CAD", -5101.44)],
        {"pair": "1011", "price": "372.73", "fee": "9.95"},
    )
    assert "10 TSLA @@ CAD 5101.44" in entry
    assert "CAD -5101.44" in entry
    assert "; pair:1011, price:372.73, fee:9.95" in entry
    assert entry.startswith("2026-07-20 * Buy TSLA | 10 sh")


def test_sell_entry_has_negative_quantity():
    entry = format_commodity_entry(
        "2026-07-25", "Sell TSLA | 6 sh",
        ("Assets:Investments:Taxable:TSLA", -6, "TSLA", "CAD", 3060.86),
        [("Assets:Current:Business Chequing", "CAD", 3510.05),
         ("Income:Non-Operating:Capital Gains", "CAD", -449.19)],
        {"pair": "0110"},
    )
    assert "-6 TSLA @@ CAD 3060.86" in entry
    assert "CAD 3510.05" in entry
    assert "CAD -449.19" in entry


def test_crypto_quantity_not_rounded():
    entry = format_commodity_entry(
        "2026-07-20", "Buy BTC",
        ("Assets:Investments:TFSA:BTC", 0.00431, "BTC", "CAD", 396.50),
        [("Assets:Current:Business Chequing", "CAD", -396.50)],
    )
    assert "0.00431 BTC @@ CAD 396.50" in entry
    assert "0.00 BTC" not in entry


def test_entry_ends_with_blank_line():
    entry = format_commodity_entry(
        "2026-07-20", "Buy TSLA",
        ("Assets:Investments:Taxable:TSLA", 1, "TSLA", "CAD", 510.14),
        [("Assets:Current:Business Chequing", "CAD", -510.14)],
    )
    assert entry.endswith("\n\n")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_journal_format.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_commodity_entry'`

- [ ] **Step 3: Implement**

Append to `lib/journal.py`:

```python
def format_commodity_entry(date, description, commodity_posting, cash_postings, tags=None):
    """Format an hledger entry containing one commodity posting.

    Args:
        date: str YYYY-MM-DD
        description: str transaction description
        commodity_posting: (account, quantity, symbol, total_currency, total_cost)
            Emitted as `QTY SYMBOL @@ CUR TOTAL` — total-price syntax, so the
            cost is stated in entity currency and FX stays out of the basis.
        cash_postings: list of (account, currency, amount) tuples
        tags: dict of tag key:value pairs (optional)

    Returns:
        str: formatted journal entry with trailing newline
    """
    tag_str = ""
    if tags:
        pairs = [f"{k}:{v}" for k, v in tags.items()]
        tag_str = "  ; " + ", ".join(pairs)

    lines = [f"{date} * {description}{tag_str}"]

    account, quantity, symbol, total_currency, total_cost = commodity_posting
    amount_str = f"{format_quantity(quantity)} {symbol} @@ {total_currency} {total_cost:.2f}"
    padding = max(1, 52 - len(account))
    lines.append(f"    {account}{' ' * padding}{amount_str}")

    for acct, currency, amount in cash_postings:
        amount_str = f"{currency} {amount:.2f}"
        padding = max(1, 52 - len(acct))
        lines.append(f"    {acct}{' ' * padding}{amount_str}")

    lines.append("")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_journal_format.py -v`
Expected: PASS, `9 passed`

- [ ] **Step 5: Commit**

```bash
git add lib/journal.py tests/test_journal_format.py
git commit -m "feat: add format_commodity_entry with lot syntax"
```

---

### Task 4: hledger accepts the emitted syntax

Golden-file assertions prove our formatter is self-consistent, not that hledger parses the output. This task closes that gap.

**Files:**
- Test: `tests/test_journal_format.py`

**Interfaces:**
- Consumes: `format_commodity_entry` from Task 3
- Produces: nothing consumed downstream

- [ ] **Step 1: Write the failing test**

Append to `tests/test_journal_format.py`:

```python
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("hledger") is None, reason="hledger not installed")
def test_hledger_parses_generated_entries(tmp_path):
    """Real hledger must accept our lot syntax, not just our own assertions."""
    buy = format_commodity_entry(
        "2026-07-20", "Buy TSLA | 10 sh",
        ("Assets:Investments:Taxable:TSLA", 10, "TSLA", "CAD", 5101.44),
        [("Assets:Current:Business Chequing", "CAD", -5101.44)],
        {"pair": "1011"},
    )
    sell = format_commodity_entry(
        "2026-07-25", "Sell TSLA | 6 sh",
        ("Assets:Investments:Taxable:TSLA", -6, "TSLA", "CAD", 3060.86),
        [("Assets:Current:Business Chequing", "CAD", 3510.05),
         ("Income:Non-Operating:Capital Gains", "CAD", -449.19)],
        {"pair": "0110"},
    )
    journal = tmp_path / "test.journal"
    journal.write_text(buy + sell)

    result = subprocess.run(
        ["hledger", "-f", str(journal), "print"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "TSLA" in result.stdout
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_journal_format.py::test_hledger_parses_generated_entries -v`
Expected: PASS (or SKIPPED if hledger is absent). If it FAILS, the `@@` syntax or posting alignment is wrong — fix the formatter before continuing, since every later task depends on this output being valid.

- [ ] **Step 3: Commit**

```bash
git add tests/test_journal_format.py
git commit -m "test: verify hledger parses commodity entries"
```

---

### Task 5: ACB replay logic

The core correctness surface. `compute_acb_from_events` is pure — it takes a list of events, not hledger output — so it is testable without journals or subprocesses.

**Files:**
- Create: `modules/investment.py`
- Test: `tests/test_investment_acb.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `compute_acb_from_events(events) -> (quantity, cost, average)` where `events` is a list of `('buy'|'sell', quantity, total_cost)` tuples; `average` is `0.0` when quantity is zero
  - `InsufficientHoldingError` exception

- [ ] **Step 1: Write the failing tests**

`tests/test_investment_acb.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_investment_acb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.investment'`

- [ ] **Step 3: Implement**

`modules/investment.py`:

```python
"""Investment purchases and disposals with adjusted cost base tracking.

ACB (weighted average) is what the CRA requires for identical properties in
non-registered accounts. FIFO and specific-lot identification are US concepts
and are not permissible here.
"""


class InsufficientHoldingError(Exception):
    """Raised when a disposal exceeds the quantity held."""


def compute_acb_from_events(events):
    """Replay buy/sell events and return (quantity, cost, average).

    Args:
        events: list of (kind, quantity, total_cost) tuples in chronological
            order, where kind is 'buy' or 'sell'. A sell's total_cost is
            ignored — its basis is derived from the running average.

    Returns:
        (quantity, cost, average). average is 0.0 when quantity is 0.

    Raises:
        InsufficientHoldingError: a sell exceeds the quantity held.
    """
    qty = 0
    cost = 0.0

    for kind, event_qty, total_cost in events:
        if kind == 'buy':
            qty += event_qty
            cost += total_cost
        elif kind == 'sell':
            if event_qty > qty:
                raise InsufficientHoldingError(
                    f"Cannot sell {event_qty}; only {qty} held"
                )
            # Reduce cost proportionally so the average is unchanged.
            # Reducing by lot instead would be FIFO.
            basis = event_qty * (cost / qty) if qty else 0.0
            cost -= basis
            qty -= event_qty

    average = (cost / qty) if qty else 0.0
    return qty, cost, average
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_investment_acb.py -v`
Expected: PASS, `9 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/investment.py tests/test_investment_acb.py
git commit -m "feat: add ACB replay logic"
```

---

### Task 6: Read holdings history from hledger

**Files:**
- Modify: `modules/investment.py`
- Test: `tests/test_investment_acb.py`

**Interfaces:**
- Consumes: `compute_acb_from_events` from Task 5
- Produces:
  - `parse_hledger_events(output) -> list` — converts `hledger print` output into the event tuples Task 5 consumes
  - `holding_account(tax_account, symbol) -> str`
  - `TAX_ACCOUNTS` — tuple of valid tax account slugs
  - `REGISTERED_ACCOUNTS` — tuple of slugs that skip gain/loss

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_investment_acb.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_investment_acb.py -v`
Expected: FAIL with `ImportError: cannot import name 'holding_account'`

- [ ] **Step 3: Implement**

Append to `modules/investment.py`:

```python
import re
import subprocess

TAX_ACCOUNTS = ('taxable', 'corporate', 'tfsa', 'rrsp')
REGISTERED_ACCOUNTS = ('tfsa', 'rrsp')

_ACCOUNT_LABELS = {
    'taxable': 'Taxable',
    'corporate': 'Corporate',
    'tfsa': 'TFSA',
    'rrsp': 'RRSP',
}

# Matches: "<qty> <SYMBOL> @@ <CUR> <total>" within a posting line.
_POSTING_RE = re.compile(
    r'(-?[\d.]+)\s+(\S+)\s+@@\s+[A-Z]{3}\s+(-?[\d.]+)'
)


def holding_account(tax_account, symbol):
    """Return the account path for a holding."""
    label = _ACCOUNT_LABELS[tax_account.lower()]
    return f"Assets:Investments:{label}:{symbol}"


def parse_hledger_events(output, symbol):
    """Extract chronological buy/sell events for one symbol from hledger print.

    Returns a list of (kind, quantity, total_cost) tuples suitable for
    compute_acb_from_events.
    """
    events = []
    for line in output.splitlines():
        match = _POSTING_RE.search(line)
        if not match:
            continue
        qty_str, line_symbol, total_str = match.groups()
        if line_symbol != symbol:
            continue
        qty = float(qty_str)
        total = abs(float(total_str))
        events.append(('sell' if qty < 0 else 'buy', abs(qty), total))
    return events


def read_holding_events(journal_path, tax_account, symbol):
    """Query hledger for a holding's history and return replay events."""
    account = holding_account(tax_account, symbol)
    result = subprocess.run(
        ['hledger', '-f', str(journal_path), 'print', account],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"hledger failed: {result.stderr.strip()}")
    return parse_hledger_events(result.stdout, symbol)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_investment_acb.py -v`
Expected: PASS, `15 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/investment.py tests/test_investment_acb.py
git commit -m "feat: read holding history from hledger"
```

---

### Task 7: `cmd_buy`

**Files:**
- Modify: `modules/investment.py`
- Test: `tests/test_investment_commands.py`

**Interfaces:**
- Consumes: `format_commodity_entry` (Task 3), `holding_account` / `TAX_ACCOUNTS` (Task 6)
- Produces:
  - `build_buy_entry(date, symbol, qty, unit_price, quote_currency, fx, fee, tax_account, cash_account, entity_currency) -> str`
  - `cmd_buy(flags, args)`

- [ ] **Step 1: Write the failing tests**

`tests/test_investment_commands.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_investment_commands.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_buy_entry'`

- [ ] **Step 3: Implement**

First consolidate imports at the top of `modules/investment.py`, replacing the `import re` / `import subprocess` lines added in Task 6 with a single block below the module docstring:

```python
import re
import subprocess

from lib.journal import format_commodity_entry, format_quantity
```

Then append the builder:

```python
def build_buy_entry(date, symbol, qty, unit_price, quote_currency, fx, fee,
                    tax_account, cash_account, entity_currency):
    """Build the journal entry for a purchase.

    Total cost is stated in entity currency using @@ syntax, so ACB is
    denominated in CAD by construction and FX stays out of the basis.
    Commission is folded into the total per CRA treatment.
    """
    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got {qty}")
    if unit_price <= 0:
        raise ValueError(f"Price must be positive, got {unit_price}")
    if tax_account.lower() not in TAX_ACCOUNTS:
        raise ValueError(
            f"Invalid tax account '{tax_account}'. Valid: {', '.join(TAX_ACCOUNTS)}"
        )

    total = round(qty * unit_price * fx + fee, 2)

    tags = {'pair': '1011', 'price': f"{unit_price:.2f}", 'fee': f"{fee:.2f}"}
    if quote_currency != entity_currency:
        tags['fx'] = f"{fx:g}"

    description = f"Buy {symbol} | {format_quantity(qty)} units"
    return format_commodity_entry(
        date, description,
        (holding_account(tax_account, symbol), qty, symbol, entity_currency, total),
        [(cash_account, entity_currency, -total)],
        tags,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_investment_commands.py -v`
Expected: PASS, `6 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/investment.py tests/test_investment_commands.py
git commit -m "feat: add build_buy_entry"
```

---

### Task 8: `cmd_sell` with gain/loss

**Files:**
- Modify: `modules/investment.py`
- Test: `tests/test_investment_commands.py`

**Interfaces:**
- Consumes: `compute_acb_from_events` (Task 5), `REGISTERED_ACCOUNTS` (Task 6), `format_commodity_entry` (Task 3)
- Produces: `build_sell_entry(date, symbol, qty, unit_price, fee, tax_account, cash_account, entity_currency, events, gains_account, registered_gains_account="Income:Non-Operating:Registered Gains") -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_investment_commands.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_investment_commands.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_sell_entry'`

- [ ] **Step 3: Implement**

Append to `modules/investment.py`:

```python
def build_sell_entry(date, symbol, qty, unit_price, fee, tax_account,
                     cash_account, entity_currency, events, gains_account,
                     registered_gains_account="Income:Non-Operating:Registered Gains"):
    """Build the journal entry for a disposal.

    Basis comes from the running ACB average.

    Registered accounts (TFSA, RRSP) route the gain to a separate account
    rather than omitting it. The gain is economically real and the entry must
    balance; keeping it in its own account is what lets tax reporting exclude
    it without breaking double-entry.
    """
    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got {qty}")
    if tax_account.lower() not in TAX_ACCOUNTS:
        raise ValueError(
            f"Invalid tax account '{tax_account}'. Valid: {', '.join(TAX_ACCOUNTS)}"
        )

    held_qty, _, average = compute_acb_from_events(events)
    if qty > held_qty:
        raise InsufficientHoldingError(
            f"Cannot sell {format_quantity(qty)} {symbol}; "
            f"only {format_quantity(held_qty)} held in {tax_account}"
        )

    basis = round(qty * average, 2)
    proceeds = round(qty * unit_price - fee, 2)
    gain = round(proceeds - basis, 2)

    registered = tax_account.lower() in REGISTERED_ACCOUNTS

    cash_postings = [(cash_account, entity_currency, proceeds)]
    if gain == 0:
        pair = '1011'
    else:
        pair = '0110' if gain > 0 else '0010'
        target = registered_gains_account if registered else gains_account
        cash_postings.append((target, entity_currency, -gain))

    tags = {'pair': pair, 'acb_per_unit': f"{average:.4f}", 'fee': f"{fee:.2f}"}

    description = f"Sell {symbol} | {format_quantity(qty)} units"
    return format_commodity_entry(
        date, description,
        (holding_account(tax_account, symbol), -qty, symbol, entity_currency, basis),
        cash_postings,
        tags,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_investment_commands.py -v`
Expected: PASS, `11 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/investment.py tests/test_investment_commands.py
git commit -m "feat: add build_sell_entry with ACB gain/loss"
```

---

### Task 9: CLI commands and dispatch

Wires the pure builders into interactive commands and the `pair market` dispatcher.

**Files:**
- Modify: `modules/investment.py`
- Modify: `modules/market.py:25-38` (MARKET_OPTIONS), `modules/market.py:63-90` (dispatch), `print_help` at `modules/market.py:966`

**Interfaces:**
- Consumes: `build_buy_entry` (Task 7), `build_sell_entry` (Task 8), `read_holding_events` (Task 6)
- Produces: `cmd_buy(flags, args)`, `cmd_sell(flags, args)`

- [ ] **Step 1: Implement the commands**

Append to `modules/investment.py`:

```python
from datetime import date as _date

from lib.helpers import (
    load_config, prompt, validate_positive_number, get_active_entity,
)
from lib.journal import append_journal, ensure_year_structure, get_generated_dir
from lib.ui import get_entity_currency, get_entity_journal


def _parse_flags(args):
    """Parse buy/sell flags into a dict."""
    parsed = {}
    keys = ('--qty', '--price', '--date', '--account', '--cash', '--fee', '--desc')
    i = 0
    while i < len(args):
        if args[i] in keys and i + 1 < len(args):
            parsed[args[i].lstrip('-')] = args[i + 1]
            i += 2
        else:
            if not args[i].startswith('--') and 'symbol' not in parsed:
                parsed['symbol'] = args[i]
            i += 1
    return parsed


def _resolve_common(opts, commodity):
    """Fill in date, account, cash, and fee from flags, config, or prompts."""
    config = load_config()
    accounts = config.get('accounts', {})
    tax_account = (opts.get('account')
                   or commodity.get('tax_account')
                   or 'taxable').lower()
    if tax_account not in TAX_ACCOUNTS:
        raise ValueError(
            f"Invalid tax account '{tax_account}'. Valid: {', '.join(TAX_ACCOUNTS)}"
        )
    return {
        'date': opts.get('date') or _date.today().strftime('%Y-%m-%d'),
        'tax_account': tax_account,
        'cash_account': (opts.get('cash')
                         or accounts.get('bank', 'Assets:Current:Chequing')),
        'fee': float(opts.get('fee', 0) or 0),
        'gains_account': accounts.get(
            'capital_gains', 'Income:Non-Operating:Capital Gains'
        ),
        'registered_gains_account': accounts.get(
            'registered_gains', 'Income:Non-Operating:Registered Gains'
        ),
    }


def _write(entry, date_str, label):
    """Append an entry to generated/<year>/investments.journal."""
    year = date_str[:4]
    ensure_year_structure(int(year))
    path = get_generated_dir() / year / 'investments.journal'
    append_journal(path, entry)
    print(f"\n  Recorded: {label}")
    print(f"  Written to: generated/{year}/investments.journal")


def cmd_buy(flags, args):
    """Record a commodity purchase."""
    from modules.market import _find_commodity

    opts = _parse_flags(args)
    symbol = opts.get('symbol') or prompt("  Symbol")
    commodity, _ = _find_commodity(symbol)
    if commodity is None:
        print(f"\n  '{symbol}' is not tracked. Add it first: pair market add {symbol}\n")
        return
    symbol = commodity['symbol']

    common = _resolve_common(opts, commodity)
    entity_currency = get_entity_currency()
    quote_currency = commodity.get('currency', entity_currency)

    qty = float(opts.get('qty') or prompt("  Quantity", validator=validate_positive_number))
    unit_price = float(opts.get('price') or prompt(
        f"  Unit price ({quote_currency})", validator=validate_positive_number))

    fx = 1.0
    if quote_currency != entity_currency:
        fx = float(prompt(f"  FX rate {quote_currency}->{entity_currency}",
                          validator=validate_positive_number))

    entry = build_buy_entry(
        date=common['date'], symbol=symbol, qty=qty, unit_price=unit_price,
        quote_currency=quote_currency, fx=fx, fee=common['fee'],
        tax_account=common['tax_account'], cash_account=common['cash_account'],
        entity_currency=entity_currency,
    )
    _write(entry, common['date'], f"Buy {format_quantity(qty)} {symbol}")


def cmd_sell(flags, args):
    """Record a commodity disposal with ACB-based gain/loss."""
    from modules.market import _find_commodity

    opts = _parse_flags(args)
    symbol = opts.get('symbol') or prompt("  Symbol")
    commodity, _ = _find_commodity(symbol)
    if commodity is None:
        print(f"\n  '{symbol}' is not tracked.\n")
        return
    symbol = commodity['symbol']

    common = _resolve_common(opts, commodity)
    entity_currency = get_entity_currency()

    qty = float(opts.get('qty') or prompt("  Quantity", validator=validate_positive_number))
    unit_price = float(opts.get('price') or prompt(
        f"  Unit price ({entity_currency})", validator=validate_positive_number))

    events = read_holding_events(
        get_entity_journal(), common['tax_account'], symbol)

    try:
        entry = build_sell_entry(
            date=common['date'], symbol=symbol, qty=qty, unit_price=unit_price,
            fee=common['fee'], tax_account=common['tax_account'],
            cash_account=common['cash_account'], entity_currency=entity_currency,
            events=events, gains_account=common['gains_account'],
            registered_gains_account=common['registered_gains_account'],
        )
    except InsufficientHoldingError as e:
        print(f"\n  {e}\n")
        return

    _write(entry, common['date'], f"Sell {format_quantity(qty)} {symbol}")
    if common['tax_account'] in REGISTERED_ACCOUNTS:
        print(f"  Gain booked to {common['registered_gains_account']} — "
              f"{common['tax_account'].upper()} gains are not taxable.")
```

- [ ] **Step 2: Wire dispatch in `modules/market.py`**

Add to `MARKET_OPTIONS` (after the `'add'` entry at line 27):

```python
    {'key': 'buy',       'label': 'Record a purchase'},
    {'key': 'sell',      'label': 'Record a sale'},
```

Add to the dispatch chain (after the `elif action == 'add':` branch):

```python
        elif action == 'buy':
            from modules.investment import cmd_buy
            cmd_buy(flags, action_args)
        elif action == 'sell':
            from modules.investment import cmd_sell
            cmd_sell(flags, action_args)
```

Add to `print_help()` under `Commands:`:

```
  buy [SYMBOL]          Record a purchase (ACB tracked)
  sell [SYMBOL]         Record a sale (computes capital gain/loss)
```

- [ ] **Step 3: Verify the commands are reachable**

Run: `.venv/bin/python pair market --help`
Expected: output includes `buy [SYMBOL]` and `sell [SYMBOL]`

- [ ] **Step 4: Verify an unknown symbol is rejected without writing**

Run: `.venv/bin/python pair market buy NOSUCHSYM --qty 1 --price 1`
Expected: `'NOSUCHSYM' is not tracked. Add it first: pair market add NOSUCHSYM`

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS, all tests green

- [ ] **Step 6: Commit**

```bash
git add modules/investment.py modules/market.py
git commit -m "feat: wire market buy/sell into CLI dispatch"
```

---

### Task 10: End-to-end verification against a real journal

Proves the whole path works and that hledger reports the resulting position correctly.

**Files:**
- Test: `tests/test_investment_commands.py`

**Interfaces:**
- Consumes: everything above
- Produces: nothing consumed downstream

- [ ] **Step 1: Write the failing test**

Append to `tests/test_investment_commands.py`:

```python
import shutil
import subprocess


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
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/test_investment_commands.py::test_buy_then_sell_reports_correct_position -v`
Expected: PASS (or SKIPPED without hledger)

- [ ] **Step 3: Run the whole suite once more**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_investment_commands.py
git commit -m "test: end-to-end buy/sell against hledger"
```

---

### Task 11: Fix the prerequisite config faults

The spec names two config entries that must be corrected before real purchases are recorded, since a wrong currency in `config.yaml` is a one-line edit while the same error inside a journal entry is an accounting correction.

**Files:**
- Modify: `entities/deskone/config.yaml`
- Modify: `web/index.html` (the `openCommodityModal` currency default)

- [ ] **Step 1: Confirm the `appl` entry is broken**

Run: `.venv/bin/python pair market fetch --symbol appl`
Expected: `✗ appl: CRITICAL Invalid pair 'APPL/CAD'`

- [ ] **Step 2: Fix both entries**

In `entities/deskone/config.yaml`, replace the `appl` commodity with:

```yaml
- symbol: AAPL
  name: Apple Inc
  source: yahoo
  fetch_pair: AAPL
  currency: USD
  type: equity
```

And change the `TSLA` entry's `currency: CAD` to `currency: USD`.

- [ ] **Step 3: Verify both now fetch**

Run: `.venv/bin/python pair market fetch --symbol AAPL --days 5`
Expected: `✓ AAPL: N new price(s)`

- [ ] **Step 4: Stop the modal reproducing the fault**

In `web/index.html`, the modal defaults currency to the entity currency, which is wrong for foreign-listed securities. Replace the currency fallback line in `openCommodityModal`:

```javascript
if (!document.getElementById('cm-currency').value) document.getElementById('cm-currency').value = state.currency || 'CAD';
```

with a version that leaves it blank and relies on the placeholder, so the user must choose:

```javascript
// No default — entity currency is wrong for foreign-listed securities,
// and a wrong currency here propagates into cost basis.
document.getElementById('cm-currency').placeholder = state.currency || 'CAD';
```

- [ ] **Step 5: Verify the JS still parses**

Run:

```bash
.venv/bin/python - <<'EOF'
import re, subprocess, pathlib
html = pathlib.Path('web/index.html').read_text()
src = "\n".join(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S))
p = pathlib.Path('/tmp/bundle_check.js'); p.write_text(src)
r = subprocess.run(['node', '--check', str(p)], capture_output=True, text=True)
print("JS SYNTAX OK" if r.returncode == 0 else r.stderr[:800])
EOF
```

Expected: `JS SYNTAX OK`. Then load the Commodities tab, click `+ Commodity`, and confirm the Currency field is empty with a `CAD` placeholder rather than pre-filled with `CAD`.

- [ ] **Step 6: Commit**

```bash
git add entities/deskone/config.yaml web/index.html
git commit -m "fix: correct AAPL/TSLA config and stop currency default"
```

---

## Deferred

Out of scope per the spec, each needing its own cycle: dividends and DRIP, stock splits, return of capital, superficial-loss rules, and web UI parity for buy/sell.

**The spec's ACB display cache is deliberately not implemented here.** Its only consumer would be a web surface showing cost basis or unrealized gain, and web parity is deferred. Sells derive ACB fresh and never consult a cache, so nothing in this plan needs it. Building it now would mean shipping mtime-invalidation logic with no caller — add it alongside the web work that reads it.
