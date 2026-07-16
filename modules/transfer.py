"""company transfer — asset-to-asset moves."""

import sys
from datetime import date

from lib.helpers import (
    load_config, money, prompt,
    validate_date, validate_positive_number, parse_global_flags
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, GENERATED_DIR
)

TO_ACCOUNT_OPTIONS = {
    '1': ('Savings', 'Assets:Current:Savings'),
    '2': ('Petty Cash', 'Assets:Current:Petty Cash'),
    '3': ('Other', None),
}


def dispatch(args):
    """Route transfer commands."""
    flags, remaining = parse_global_flags(args)

    if flags['help'] or (remaining and remaining[0] == 'help'):
        print_help()
        return

    cmd_transfer(flags, remaining)


def print_help():
    print("""company transfer — asset-to-asset moves

Usage:
  company transfer              Record an asset-to-asset transfer

Flags:
  --amount NUM        Amount
  --date DATE         Transaction date
  --desc TEXT         Description/memo
  --from ACCOUNT      Source account (default: config bank)
  --to ACCOUNT        Destination account
""")


# ─── company transfer ────────────────────────────────────────────────────────

def cmd_transfer(flags, args):
    """Record asset-to-asset transfer."""
    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    amount_str = None
    transfer_date = flags.get('date')
    description = None
    from_account = None
    to_account = None

    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            transfer_date = args[i + 1]
        elif a == '--desc' and i + 1 < len(args):
            description = args[i + 1]
        elif a == '--from' and i + 1 < len(args):
            from_account = args[i + 1]
        elif a == '--to' and i + 1 < len(args):
            to_account = args[i + 1]

    if not description:
        description = prompt("Description", default="Internal transfer")
    if not amount_str:
        amount_str = prompt("Amount", validator=validate_positive_number)
    if not from_account:
        from_account = prompt("From account", default=bank)
    if not to_account:
        print("  Transfer to:")
        for key, (label, _) in TO_ACCOUNT_OPTIONS.items():
            print(f"    {key}) {label}")
        choice = prompt("Choose (1/2/3)", default="1")
        if choice in TO_ACCOUNT_OPTIONS:
            label, acct = TO_ACCOUNT_OPTIONS[choice]
            if acct:
                to_account = acct
            else:
                to_account = prompt("Enter account name")
        else:
            to_account = prompt("Enter account name")
    if not transfer_date:
        transfer_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                               validator=validate_date)

    amount = money(amount_str)

    postings = [
        (to_account, currency, float(amount)),
        (from_account, currency, float(-amount)),
    ]

    tags = {'pair': '1011'}
    entry = format_entry(transfer_date, description, postings, tags)

    year = transfer_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "transfers.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  From:     {from_account}")
        print(f"  To:       {to_account}")
        print(f"  Written to: generated/{year}/transfers.journal")
