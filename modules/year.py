"""pair year — fiscal year management."""

import sys
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

from lib.helpers import (
    BASE_DIR, load_config, money, prompt, confirm,
    validate_date, parse_global_flags
)
from lib.journal import (
    format_entry, write_journal_atomic, ensure_year_structure,
    get_journal_dir, get_generated_dir
)


def cmd_year(args):
    """Route year subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'new':
        cmd_new(flags, action_args)
    elif action == 'close':
        cmd_close(flags, action_args)
    else:
        print(f"Unknown year action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair year — fiscal year management

Actions:
  new <YYYY>          Scaffold a new fiscal year
  close <YYYY>        Generate closing entries for a year

Closing entries zero out Income and Expense accounts into
Retained Earnings. Written to journal/<year>/closing.journal.
""")


# ─── pair year new ────────────────────────────────────────────────────────

def cmd_new(flags, args):
    """Scaffold a new fiscal year."""
    if not args:
        print("Usage: pair year new <YYYY>")
        sys.exit(1)

    year = int(args[0])
    ensure_year_structure(year)
    print(f"Year {year} scaffolded.")


# ─── pair year close ──────────────────────────────────────────────────────

def cmd_close(flags, args):
    """Generate closing entries that zero out income/expenses into Retained Earnings.

    Queries hledger for Income and Expense account totals for the year,
    writes closing entries to journal/<year>/closing.journal. Pair 1101.
    """
    if not args:
        print("Usage: pair year close <YYYY>")
        sys.exit(1)

    year_str = args[0]
    try:
        year = int(year_str)
    except ValueError:
        print(f"Invalid year: {year_str}")
        sys.exit(1)

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    close_date = f"{year}-12-31"

    print(f"\nClosing year {year}...")

    # Query hledger for income totals
    income_accounts = _query_account_balances(year, "Income")
    expense_accounts = _query_account_balances(year, "Expenses")

    if not income_accounts and not expense_accounts:
        print("  No income or expense balances found for this year.")
        print("  (Ensure hledger can read the journal files.)")
        return

    # Show summary
    total_income = sum(amt for _, amt in income_accounts)
    total_expenses = sum(amt for _, amt in expense_accounts)
    net_income = total_income - total_expenses

    print(f"\n  Year {year} Summary:")
    print(f"  Total Income:     {currency} {total_income:.2f}")
    print(f"  Total Expenses:   {currency} {total_expenses:.2f}")
    print(f"  Net Income:       {currency} {net_income:.2f}")

    if not flags.get('yes') and not confirm(
        f"\n  Generate closing entries for {year}?"
    ):
        print("  Cancelled.")
        return

    # Build closing entry postings
    # Close income accounts: DR Income accounts (zero them out)
    # Close expense accounts: CR Expense accounts (zero them out)
    # Net difference to Retained Earnings
    postings = []

    for account, amount in income_accounts:
        # Income accounts have credit (negative) balances in hledger
        # To close: debit them (positive posting)
        postings.append((account, currency, float(amount)))

    for account, amount in expense_accounts:
        # Expense accounts have debit (positive) balances in hledger
        # To close: credit them (negative posting)
        postings.append((account, currency, float(-amount)))

    # Net to retained earnings
    retained = -(total_income - total_expenses)
    if retained != 0:
        postings.append(('Equity:Retained Earnings', currency, float(retained)))

    if not postings:
        print("  No postings to generate.")
        return

    tags = {'pair': '1101', 'period': year_str}
    entry = format_entry(close_date, f"Closing entries for {year}", postings, tags)

    # Write to journal/<year>/closing.journal
    ensure_year_structure(year)
    closing_path = get_journal_dir() / year_str / "closing.journal"

    if flags.get('dry_run'):
        print(f"\n  Would write to: journal/{year_str}/closing.journal")
        print(f"\n{entry}")
        return

    write_journal_atomic(closing_path, f"; Closing entries for {year}\n\n{entry}")

    print(f"\n  Written to: journal/{year_str}/closing.journal")
    print(f"  Net income of {currency} {net_income:.2f} transferred to Retained Earnings.")


def _query_account_balances(year, account_prefix):
    """Query hledger for account balances in a given year.

    Returns list of (account_name, amount) tuples.
    Amount is positive for debits, negative for credits (hledger convention).
    """
    start_date = f"{year}-01-01"
    end_date = f"{year + 1}-01-01"

    try:
        result = subprocess.run(
            ['hledger', 'bal', account_prefix,
             '-b', start_date, '-e', end_date,
             '--flat', '--no-total', '--format', '%(total) %(account)\n'],
            capture_output=True, text=True, timeout=10,
            cwd=str(BASE_DIR)
        )
    except FileNotFoundError:
        print("  Warning: hledger not found. Install hledger to use closing entries.")
        return []
    except subprocess.TimeoutExpired:
        print("  Warning: hledger timed out.")
        return []

    if result.returncode != 0:
        # hledger may return non-zero if no matching transactions
        if not result.stdout.strip():
            return []

    accounts = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Parse format: "CAD 123.45 Account:Name" or "-123.45 Account:Name"
        parts = line.split()
        if not parts:
            continue

        # Try to find amount and account
        amount = None
        account_name = None

        # Format could be: "CAD 100.00 Income:Consulting"
        # or: "100.00 Income:Consulting"
        idx = 0
        # Skip currency code if present
        if parts[0].isalpha() and len(parts[0]) <= 4:
            idx = 1

        if idx < len(parts):
            try:
                amount = float(parts[idx].replace(',', ''))
                account_name = " ".join(parts[idx + 1:])
            except (ValueError, IndexError):
                continue

        if account_name and amount is not None and amount != 0:
            accounts.append((account_name, amount))

    return accounts
