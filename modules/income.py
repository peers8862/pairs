"""pair income — non-operating income transactions."""

import shutil
import subprocess
import sys
from datetime import date

from lib.helpers import (
    load_config, money, prompt,
    validate_date, validate_positive_number, parse_global_flags,
    validate_division
)
from lib.journal import (
    build_tags, format_entry, append_journal, ensure_year_structure, get_generated_dir
)
from lib.ui import get_entity_journal, require_entity

INCOME_TYPES = ['interest', 'grant', 'gain', 'insurance', 'other']


def dispatch(args):
    """Route income subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'add':
        cmd_add(flags, action_args)
    elif action == 'statement':
        cmd_statement(flags, action_args)
    else:
        print(f"Unknown income action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair income — non-operating income

Actions:
  add                 Record non-operating income (interest, grants, gains, etc.)
  statement           Income statement, optionally for one division

Flags for 'add':
  --amount NUM        Amount
  --date DATE         Transaction date
  --desc TEXT         Description/memo
  --type TYPE         Income type (interest/grant/gain/insurance/other)
  --received          Mark as received (asset pair 0110)
  --accrued           Mark as accrued (liability pair 0111)

Flags for 'statement':
  --division DIV      Only transactions tagged with this division
  --period SPEC       hledger period (e.g. 2026, 2026-01)

A division statement counts only transactions tagged with that division;
entries without a division tag are excluded from it (but included
entity-wide, with no --division flag).
""")


# ─── pair income add ──────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Record non-operating income."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    amount_str = None
    income_date = flags.get('date')
    description = None
    income_type = None
    received = None

    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            income_date = args[i + 1]
        elif a == '--desc' and i + 1 < len(args):
            description = args[i + 1]
        elif a == '--type' and i + 1 < len(args):
            income_type = args[i + 1]
        elif a == '--received':
            received = True
        elif a == '--accrued':
            received = False

    if not description:
        description = prompt("Description", default="Non-operating income")
    if not amount_str:
        amount_str = prompt("Amount", validator=validate_positive_number)
    if not income_type:
        type_choices = '/'.join(INCOME_TYPES)
        income_type = prompt(f"Type ({type_choices})", default="other")
        if income_type not in INCOME_TYPES:
            income_type = 'other'
    if not income_date:
        income_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                             validator=validate_date)
    if received is None:
        answer = prompt("Received? (yes=cash in bank, no=accrued)", default="yes")
        received = answer.lower() in ('yes', 'y')

    amount = money(amount_str)
    income_account = f"Revenue:Other Income:{income_type.title()}"

    if received:
        # Pair 0110: asset increases, revenue increases
        postings = [
            (bank, currency, float(amount)),
            (income_account, currency, float(-amount)),
        ]
        pair_code = '0110'
    else:
        # Pair 0111: liability increases (accrued receivable), revenue increases
        receivable = config.get('accounts', {}).get('receivable', 'Assets:Current:Accounts Receivable')
        postings = [
            (receivable, currency, float(amount)),
            (income_account, currency, float(-amount)),
        ]
        pair_code = '0111'

    tags = build_tags(pair_code, **{'income-type': income_type})
    entry = format_entry(income_date, description, postings, tags)

    year = income_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "income.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        status = "received" if received else "accrued"
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Type:     {income_type} ({status})")
        print(f"  Written to: generated/{year}/income.journal")


# ─── pair income statement ────────────────────────────────────────────────

def cmd_statement(flags, args):
    """Print the income statement, optionally for one division (I73).

    Runs hledger's own income statement against the entity journal, so
    the figures are the same ones `pair report is` shows. With --division
    only transactions tagged with that division count; entries without a
    division tag are excluded from a division statement.
    """
    config = load_config()

    division = None
    period = None
    for i, a in enumerate(args):
        if a == '--division' and i + 1 < len(args):
            division = args[i + 1]
        elif a == '--period' and i + 1 < len(args):
            period = args[i + 1]

    try:
        division = validate_division(config, division)
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)

    require_entity()
    journal = get_entity_journal()
    if not journal.exists():
        print(f"  No journal found at {journal}.")
        sys.exit(1)
    if not shutil.which('hledger'):
        print("  hledger is not installed or not in PATH.")
        print("  Install: https://hledger.org/install.html")
        sys.exit(1)

    cmd = ['hledger', '-f', str(journal), 'is']
    if period:
        cmd += ['-p', period]
    if division:
        cmd += [f'tag:division={division}']
    title = "  Income statement"
    if division:
        title += f" — division '{division}'"
    if period:
        title += f" ({period})"
    print(title)
    # Capture and re-print (rather than inheriting stdout) so the statement
    # is testable with capsys and behaves the same in pipes and terminals.
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='')
    sys.exit(result.returncode)
