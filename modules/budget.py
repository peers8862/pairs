"""company budget — budget setting and comparison."""

import sys
import subprocess
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, prompt, validate_positive_number,
    expand_path, parse_global_flags
)
from lib.yaml_store import load_entity, save_entity, entity_exists
from lib.helpers import BASE_DIR


MODULE = "budget"
BUDGET_FILE = BASE_DIR / "budget.yaml"


def dispatch(args):
    """Route budget subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'set':
        cmd_set(flags, action_args)
    elif action == 'vs':
        cmd_vs(flags, action_args)
    else:
        print(f"Unknown budget action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""company budget — budget setting and variance reporting

Actions:
  set                 Set budget amounts for accounts
  vs                  Compare actual vs budget

Flags for 'set':
  --account ACCT      Account name
  --amount NUM        Monthly budget amount
  --year YYYY         Budget year (default: current)

Flags for 'vs':
  --period SPEC       Period to compare (YYYY-MM, YYYY-QN, YYYY)
  --year YYYY         Full year comparison
""")


# ─── company budget set ──────────────────────────────────────────────────────

def cmd_set(flags, args):
    """Set budget amounts."""
    import yaml

    # Parse args
    account = None
    amount = None
    year = str(date.today().year)

    for i, a in enumerate(args):
        if a == '--account' and i + 1 < len(args):
            account = args[i + 1]
        elif a == '--amount' and i + 1 < len(args):
            amount = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    if not account:
        account = prompt("Account name (e.g. Expenses:Operating:Rent)")
    if not amount:
        amount = prompt("Monthly budget amount", validator=validate_positive_number)

    # Load existing budget
    budget = {}
    if BUDGET_FILE.exists():
        with open(BUDGET_FILE) as f:
            budget = yaml.safe_load(f) or {}

    if year not in budget:
        budget[year] = {}

    budget[year][account] = float(amount)

    with open(BUDGET_FILE, 'w') as f:
        yaml.dump(budget, f, default_flow_style=False, sort_keys=False)

    print(f"\n  Budget set: {account} = ${float(amount):,.2f}/month for {year}")


# ─── company budget vs ───────────────────────────────────────────────────────

def cmd_vs(flags, args):
    """Compare actual vs budget."""
    import yaml

    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')
    journal_file = config.get('journal_file')

    # Parse args
    period = None
    year = str(date.today().year)
    for i, a in enumerate(args):
        if a == '--period' and i + 1 < len(args):
            period = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    if not period:
        period = f"{year}-{date.today().month:02d}"

    # Load budget
    if not BUDGET_FILE.exists():
        print("No budget set. Use 'company budget set' first.")
        return

    with open(BUDGET_FILE) as f:
        budget = yaml.safe_load(f) or {}

    year_budget = budget.get(year, {})
    if not year_budget:
        print(f"No budget set for {year}.")
        return

    # Determine months in period for budget calculation
    months = _months_in_period(period)

    print(f"\n  Budget vs Actual — {period}")
    print(f"  {'─' * 68}")
    print(f"  {'Account':<35} {'Budget':>12} {'Actual':>12} {'Variance':>12}")
    print(f"  {'─' * 68}")

    for account, monthly_amount in sorted(year_budget.items()):
        budget_amount = money(Decimal(str(monthly_amount)) * months)
        actual = _get_actual(config, account, period)
        variance = budget_amount - actual

        var_indicator = "" if variance >= 0 else " ⚠"
        print(f"  {account:<35} {currency} {budget_amount:>9,.2f} "
              f"{currency} {actual:>9,.2f} {currency} {variance:>9,.2f}{var_indicator}")

    print(f"  {'─' * 68}")
    print()


def _get_actual(config, account, period):
    """Get actual balance for an account in a period."""
    journal_file = config.get('journal_file')
    if not journal_file:
        return Decimal('0')

    journal_path = str(expand_path(journal_file))
    cmd = ['hledger', '-f', journal_path, 'bal', account,
           '-p', period, '--no-total', '--output-format=csv']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return Decimal('0')
        import csv
        from io import StringIO
        reader = csv.reader(StringIO(result.stdout))
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                bal_str = row[1].strip('"').replace(',', '')
                parts = bal_str.split()
                try:
                    return abs(Decimal(parts[-1]))
                except Exception:
                    pass
        return Decimal('0')
    except (FileNotFoundError, OSError):
        return Decimal('0')


def _months_in_period(period_spec):
    """Count months in a period specification."""
    import re
    if re.match(r'^\d{4}$', period_spec):
        return 12
    if re.match(r'^\d{4}-Q\d$', period_spec):
        return 3
    if re.match(r'^\d{4}-\d{2}$', period_spec):
        return 1
    return 1
