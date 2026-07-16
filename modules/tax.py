"""pair tax — tax remittance tracking and summaries."""

import sys
import subprocess
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, prompt, confirm, validate_date,
    validate_positive_number, expand_path, parse_global_flags
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, get_generated_dir
)


def dispatch(args):
    """Route tax subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'summary':
        cmd_summary(flags, action_args)
    elif action == 'remit':
        cmd_remit(flags, action_args)
    else:
        print(f"Unknown tax action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair tax — tax remittance tracking

Actions:
  summary             Show tax collected vs paid for a period
  remit               Record a tax remittance payment

Flags for 'summary':
  --period SPEC       Period (YYYY, YYYY-QN, YYYY-MM); default: current quarter
  --year YYYY         Full year summary

Flags for 'remit':
  --amount NUM        Remittance amount
  --date DATE         Payment date
  --period SPEC       Period this remittance covers
""")


# ─── pair tax summary ─────────────────────────────────────────────────────

def cmd_summary(flags, args):
    """Show tax collected vs paid summary."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    journal_file = config.get('journal_file')

    # Parse period
    period = None
    year_only = None
    for i, a in enumerate(args):
        if a == '--period' and i + 1 < len(args):
            period = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year_only = args[i + 1]

    if not period and not year_only:
        # Default: current quarter
        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        period = f"{today.year}-Q{quarter}"

    # Try hledger first
    if journal_file and _check_hledger():
        _hledger_tax_summary(config, period or year_only, currency)
    else:
        # Fallback: scan generated journals for tax-related entries
        print(f"\n  Tax Summary — {period or year_only}")
        print(f"  {'─' * 50}")
        print(f"  (Requires hledger and configured journal for full summary)")
        print(f"  Run 'pair init' to set up journal path.")
        print()


def _hledger_tax_summary(config, period, currency):
    """Query hledger for tax account balances."""
    journal_path = str(expand_path(config['journal_file']))

    # Determine date range from period spec
    begin_date, end_date = _period_to_dates(period)

    print(f"\n  Tax Summary — {period}")
    print(f"  {'─' * 50}")
    print()

    # HST/GST Collected (liability — what you owe)
    collected = _query_balance(journal_path, 'Liabilities:Current:HST Payable',
                               begin_date, end_date)

    # HST/GST Paid (asset or expense — what you can claim back)
    # Try common account names
    paid = Decimal('0')
    for acct in ['Assets:Current:HST Receivable', 'Expenses:HST Paid',
                 'Assets:Current:Input Tax Credits']:
        bal = _query_balance(journal_path, acct, begin_date, end_date)
        paid += bal

    # Net owing
    # Collected is typically negative (credit balance in liability)
    collected_abs = abs(collected)
    net_owing = collected_abs - paid

    print(f"  HST/GST Collected (on sales):     {currency} {collected_abs:>12,.2f}")
    print(f"  HST/GST Paid (input tax credits): {currency} {paid:>12,.2f}")
    print(f"                                    {'─' * 16}")
    print(f"  Net Owing to CRA:                 {currency} {net_owing:>12,.2f}")
    print()

    if net_owing > 0:
        print(f"  Use 'pair tax remit' to record payment to CRA.")
    elif net_owing < 0:
        print(f"  You have a refund of {currency} {abs(net_owing):,.2f} to claim.")
    else:
        print(f"  Balanced — nothing owing.")
    print()


# ─── pair tax remit ───────────────────────────────────────────────────────

def cmd_remit(flags, args):
    """Record a tax remittance payment."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    amount_str = None
    remit_date = flags.get('date')
    period_desc = None
    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            remit_date = args[i + 1]
        elif a == '--period' and i + 1 < len(args):
            period_desc = args[i + 1]

    if not amount_str:
        amount_str = prompt("Remittance amount", validator=validate_positive_number)
    if not remit_date:
        remit_date = prompt("Payment date", default=date.today().strftime("%Y-%m-%d"),
                            validator=validate_date)
    if not period_desc:
        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        period_desc = prompt("Period covered", default=f"{today.year}-Q{quarter}")

    amount = money(amount_str)

    # HST remittance: debit liability (reduce what you owe), credit bank
    postings = [
        ('Liabilities:Current:HST Payable', currency, float(amount)),
        (bank, currency, float(-amount)),
    ]

    tags = {
        'pair': '1000',
        'remittance': 'hst',
        'period': period_desc,
    }

    description = f"Tax remittance: HST {period_desc}"
    entry = format_entry(remit_date, description, postings, tags)

    year = remit_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "tax.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Written to: generated/{year}/tax.journal")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _check_hledger():
    """Check if hledger is available."""
    try:
        result = subprocess.run(['hledger', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _query_balance(journal_path, account, begin_date=None, end_date=None):
    """Query a single account balance from hledger."""
    cmd = ['hledger', '-f', journal_path, 'bal', account,
           '--no-total', '--output-format=csv']
    if begin_date:
        cmd += ['-b', begin_date]
    if end_date:
        cmd += ['-e', end_date]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return Decimal('0')
        # Parse CSV
        import csv
        from io import StringIO
        reader = csv.reader(StringIO(result.stdout))
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2:
                balance_str = row[1].strip('"').replace(',', '')
                parts = balance_str.split()
                num_str = parts[-1] if parts else '0'
                try:
                    return Decimal(num_str)
                except Exception:
                    pass
        return Decimal('0')
    except (FileNotFoundError, OSError):
        return Decimal('0')


def _period_to_dates(period_spec):
    """Convert period spec to begin/end date strings."""
    import re

    # YYYY
    if re.match(r'^\d{4}$', period_spec):
        return f"{period_spec}-01-01", f"{int(period_spec) + 1}-01-01"

    # YYYY-QN
    match = re.match(r'^(\d{4})-Q(\d)$', period_spec)
    if match:
        year = match.group(1)
        q = int(match.group(2))
        start_month = (q - 1) * 3 + 1
        end_month = q * 3 + 1
        end_year = year
        if end_month > 12:
            end_month = 1
            end_year = str(int(year) + 1)
        return f"{year}-{start_month:02d}-01", f"{end_year}-{end_month:02d}-01"

    # YYYY-MM
    match = re.match(r'^(\d{4})-(\d{2})$', period_spec)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        end_month = month + 1
        end_year = year
        if end_month > 12:
            end_month = 1
            end_year = year + 1
        return f"{year}-{month:02d}-01", f"{end_year}-{end_month:02d}-01"

    return None, None
