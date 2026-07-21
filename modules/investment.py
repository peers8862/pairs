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


from datetime import date as _date

from lib.helpers import (
    load_config, prompt, validate_positive_number,
)
from lib.journal import append_journal, ensure_year_structure, get_generated_dir
from lib.ui import get_entity_currency, get_entity_journal


def _to_number(raw, label):
    """Parse a CLI-supplied number, returning None with a message on bad input."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        print(f"\n  Invalid {label}: {raw!r}\n")
        return None
    return value


def _parse_flags(args):
    """Parse buy/sell flags into a dict."""
    parsed = {}
    keys = ('--qty', '--price', '--date', '--account', '--cash', '--fee')
    i = 0
    while i < len(args):
        if args[i] in keys:
            if i + 1 < len(args) and not args[i + 1].startswith('--'):
                parsed[args[i].lstrip('-')] = args[i + 1]
                i += 2
            else:
                # Flag has no usable value (followed by another flag, or is
                # the last token) — leave it unset so prompt/default applies.
                i += 1
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
    fee = _to_number(opts.get('fee', 0) or 0, 'fee')
    if fee is None:
        return None
    return {
        'date': opts.get('date') or _date.today().strftime('%Y-%m-%d'),
        'tax_account': tax_account,
        'cash_account': (opts.get('cash')
                         or accounts.get('bank', 'Assets:Current:Chequing')),
        'fee': fee,
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
    if common is None:
        return
    entity_currency = get_entity_currency()
    quote_currency = commodity.get('currency', entity_currency)

    if opts.get('qty'):
        qty = _to_number(opts['qty'], 'quantity')
        if qty is None:
            return
    else:
        qty = float(prompt("  Quantity", validator=validate_positive_number))

    if opts.get('price'):
        unit_price = _to_number(opts['price'], 'price')
        if unit_price is None:
            return
    else:
        unit_price = float(prompt(
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
    if common is None:
        return
    entity_currency = get_entity_currency()

    if opts.get('qty'):
        qty = _to_number(opts['qty'], 'quantity')
        if qty is None:
            return
    else:
        qty = float(prompt("  Quantity", validator=validate_positive_number))

    if opts.get('price'):
        unit_price = _to_number(opts['price'], 'price')
        if unit_price is None:
            return
    else:
        unit_price = float(prompt(
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
    if (common['tax_account'] in REGISTERED_ACCOUNTS
            and common['registered_gains_account'] in entry):
        print(f"  Gain booked to {common['registered_gains_account']} — "
              f"{common['tax_account'].upper()} gains are not taxable.")
