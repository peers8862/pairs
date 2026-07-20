"""Investment purchases and disposals with adjusted cost base tracking.

ACB (weighted average) is what the CRA requires for identical properties in
non-registered accounts. FIFO and specific-lot identification are US concepts
and are not permissible here.
"""

import re
import subprocess

from lib.journal import format_commodity_entry, format_quantity


class InsufficientHoldingError(Exception):
    """Raised when a disposal exceeds the quantity held."""


_EPSILON = 1e-9


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
            if event_qty > qty + _EPSILON:
                raise InsufficientHoldingError(
                    f"Cannot sell {event_qty}; only {qty} held"
                )
            # Reduce cost proportionally so the average is unchanged.
            # Reducing by lot instead would be FIFO.
            basis = event_qty * (cost / qty) if qty else 0.0
            cost -= basis
            qty -= event_qty
            # Snap float dust from a full disposal to exact zero.
            if abs(qty) < _EPSILON:
                qty = 0
                cost = 0.0

    average = (cost / qty) if qty else 0.0
    return qty, cost, average


TAX_ACCOUNTS = ('taxable', 'corporate', 'tfsa', 'rrsp')
REGISTERED_ACCOUNTS = ('tfsa', 'rrsp')

_ACCOUNT_LABELS = {
    'taxable': 'Taxable',
    'corporate': 'Corporate',
    'tfsa': 'TFSA',
    'rrsp': 'RRSP',
}

# Matches: "<qty> <SYMBOL> @@ <CUR> <total>" within a posting line. hledger
# double-quotes symbols containing non-letter characters (e.g. "SHOP.TO"),
# so the symbol is matched with optional surrounding quotes that are not
# captured in the group.
_POSTING_RE = re.compile(
    r'(-?[\d.]+)\s+"?([^"\s]+)"?\s+@@\s+[A-Z]{3}\s+(-?[\d.]+)'
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
