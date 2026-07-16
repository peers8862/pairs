"""company equity — owner investment and draw transactions."""

import sys
from datetime import date

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_date, validate_positive_number, parse_global_flags
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, GENERATED_DIR
)
from lib.yaml_store import load_entity, list_entities


def dispatch(args):
    """Route equity subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'invest':
        cmd_invest(flags, action_args)
    elif action == 'draw':
        cmd_draw(flags, action_args)
    elif action == 'convert':
        cmd_convert(flags, action_args)
    else:
        print(f"Unknown equity action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""company equity — owner investment and draws

Actions:
  invest              Record owner investing into the business
  draw                Record owner drawing from the business
  convert             Convert a liability to equity (debt-to-equity)

Flags:
  --amount NUM        Amount
  --date DATE         Transaction date
  --desc TEXT         Description/memo
""")


# ─── company equity invest ───────────────────────────────────────────────────

def cmd_invest(flags, args):
    """Record owner investment."""
    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    amount_str = None
    invest_date = flags.get('date')
    description = None
    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            invest_date = args[i + 1]
        elif a == '--desc' and i + 1 < len(args):
            description = args[i + 1]

    if not amount_str:
        amount_str = prompt("Amount invested", validator=validate_positive_number)
    if not invest_date:
        invest_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                             validator=validate_date)
    if not description:
        description = prompt("Description", default="Owner investment", required=False) or "Owner investment"

    amount = money(amount_str)

    postings = [
        (bank, currency, float(amount)),
        ('Equity:Owner Investment', currency, float(-amount)),
    ]

    tags = {'pair': '1001'}
    entry = format_entry(invest_date, description, postings, tags)

    year = invest_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "equity.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Written to: generated/{year}/equity.journal")


# ─── company equity draw ─────────────────────────────────────────────────────

def cmd_draw(flags, args):
    """Record owner draw."""
    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    amount_str = None
    draw_date = flags.get('date')
    description = None
    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            draw_date = args[i + 1]
        elif a == '--desc' and i + 1 < len(args):
            description = args[i + 1]

    if not amount_str:
        amount_str = prompt("Amount drawn", validator=validate_positive_number)
    if not draw_date:
        draw_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                           validator=validate_date)
    if not description:
        description = prompt("Description", default="Owner draw", required=False) or "Owner draw"

    amount = money(amount_str)

    postings = [
        ('Equity:Owner Draws', currency, float(amount)),
        (bank, currency, float(-amount)),
    ]

    tags = {'pair': '1001'}
    entry = format_entry(draw_date, description, postings, tags)

    year = draw_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "equity.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Written to: generated/{year}/equity.journal")


# ─── company equity convert ──────────────────────────────────────────────────

def cmd_convert(flags, args):
    """Convert liability to equity (debt-to-equity conversion).

    Writes: DR Liability, CR Equity. Pair 1010.
    """
    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')

    # Parse args
    liability_slug = None
    amount_str = None
    convert_date = flags.get('date')
    description = None
    for i, a in enumerate(args):
        if a == '--liability' and i + 1 < len(args):
            liability_slug = args[i + 1]
        elif a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            convert_date = args[i + 1]
        elif a == '--desc' and i + 1 < len(args):
            description = args[i + 1]

    # Select liability
    if not liability_slug:
        slugs = list_entities("liabilities")
        if not slugs:
            print("No liabilities found. Add one with 'company liability add'.")
            sys.exit(1)

        if len(slugs) == 1:
            liability_slug = slugs[0]
        else:
            liability_slug = prompt_choice("Select liability to convert", slugs)

    liab = load_entity("liabilities", liability_slug)
    if not liab:
        print(f"Liability '{liability_slug}' not found.")
        sys.exit(1)

    liability_account = liab['accounts']['liability']
    currency = liab.get('currency', currency)

    print(f"\nConvert liability to equity: {liab['name']}")
    print(f"Account: {liability_account}\n")

    if not amount_str:
        amount_str = prompt("Amount to convert", validator=validate_positive_number)
    if not convert_date:
        convert_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                              validator=validate_date)
    if not description:
        description = prompt("Description",
                             default=f"Debt-to-equity conversion: {liab['name']}",
                             required=False) or f"Debt-to-equity conversion: {liab['name']}"

    amount = money(amount_str)

    if not flags.get('yes') and not confirm(
        f"\n  Convert {currency} {amount} from {liability_account} to Equity?"
    ):
        print("  Cancelled.")
        return

    # Journal entry: DR Liability (reduce), CR Equity (increase)
    postings = [
        (liability_account, currency, float(amount)),
        ('Equity:Owner Investment', currency, float(-amount)),
    ]

    tags = {'pair': '1010', 'source': f'liabilities/{liability_slug}.yaml'}
    entry = format_entry(convert_date, description, postings, tags)

    year = convert_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "equity.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  DR:       {liability_account}")
        print(f"  CR:       Equity:Owner Investment")
        print(f"  Written to: generated/{year}/equity.journal")
