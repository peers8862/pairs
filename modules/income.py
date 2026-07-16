"""pair income — non-operating income transactions."""

import sys
from datetime import date

from lib.helpers import (
    load_config, money, prompt,
    validate_date, validate_positive_number, parse_global_flags
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, GENERATED_DIR
)

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
    else:
        print(f"Unknown income action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair income — non-operating income

Actions:
  add                 Record non-operating income (interest, grants, gains, etc.)

Flags:
  --amount NUM        Amount
  --date DATE         Transaction date
  --desc TEXT         Description/memo
  --type TYPE         Income type (interest/grant/gain/insurance/other)
  --received          Mark as received (asset pair 0110)
  --accrued           Mark as accrued (liability pair 0111)
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

    tags = {'pair': pair_code, 'income-type': income_type}
    entry = format_entry(income_date, description, postings, tags)

    year = income_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "income.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        status = "received" if received else "accrued"
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Type:     {income_type} ({status})")
        print(f"  Written to: generated/{year}/income.journal")
