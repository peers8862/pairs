"""pair payroll — pay run and contractor payment recording."""

import sys
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_slug, validate_date, validate_positive_number,
    parse_global_flags
)
from lib.yaml_store import load_entity, save_entity, list_entities
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, get_generated_dir
)


def dispatch(args):
    """Route payroll subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'run':
        cmd_run(flags, action_args)
    elif action == 'list':
        cmd_list(flags, action_args)
    else:
        print(f"Unknown payroll action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair payroll — pay run and contractor payments

Actions:
  run                 Record a pay run or contractor payment
  list                List recent pay runs

Flags for 'run':
  --type TYPE         Type: employee or contractor (default: contractor)
  --contact SLUG      Contact slug for the payee
  --amount NUM        Gross pay amount
  --date DATE         Pay date
  --period SPEC       Period covered (e.g. '2026-07-01 to 2026-07-15')
""")


# ─── pair payroll run ─────────────────────────────────────────────────────

def cmd_run(flags, args):
    """Record a pay run."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse args
    pay_type = 'contractor'
    contact_slug = None
    amount_str = None
    pay_date = flags.get('date')
    period_desc = None

    for i, a in enumerate(args):
        if a == '--type' and i + 1 < len(args):
            pay_type = args[i + 1]
        elif a == '--contact' and i + 1 < len(args):
            contact_slug = args[i + 1]
        elif a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            pay_date = args[i + 1]
        elif a == '--period' and i + 1 < len(args):
            period_desc = args[i + 1]

    if not flags.get('batch'):
        print(f"Record a payroll run\n")
        if not pay_type or pay_type not in ('employee', 'contractor'):
            pay_type = prompt_choice("Type", ['contractor', 'employee'], default='contractor')
        if not contact_slug:
            contact_slug = prompt("Payee contact slug", validator=validate_slug)
        if not amount_str:
            amount_str = prompt("Gross amount", validator=validate_positive_number)
        if not pay_date:
            pay_date = prompt("Pay date", default=date.today().strftime("%Y-%m-%d"),
                              validator=validate_date)
        if not period_desc:
            period_desc = prompt("Period covered (optional)", required=False)

    amount = money(amount_str)

    # Resolve payee name
    contact = load_entity('contacts', contact_slug) if contact_slug else None
    payee_name = contact['name'] if contact else contact_slug

    if pay_type == 'contractor':
        # Simple: expense + bank
        postings = [
            ('Expenses:Operating:Payroll:Salaries', currency, float(amount)),
            (bank, currency, float(-amount)),
        ]
        tags = {
            'pair': '0000',
            'contact': contact_slug or '',
        }
        if period_desc:
            tags['period'] = period_desc

        description = f"Contractor payment: {payee_name}"
        entry = format_entry(pay_date, description, postings, tags)

    else:
        # Employee: needs deductions
        print("\n  Employee deductions:")
        cpp = money(prompt("  CPP (employee portion)", default="0",
                           validator=validate_positive_number) or "0")
        ei = money(prompt("  EI (employee portion)", default="0",
                          validator=validate_positive_number) or "0")
        tax = money(prompt("  Income tax withheld", default="0",
                           validator=validate_positive_number) or "0")

        net_pay = amount - cpp - ei - tax

        postings = [
            ('Expenses:Operating:Payroll:Salaries', currency, float(amount)),
            ('Liabilities:Current:Payroll Payable', currency, float(-net_pay)),
            ('Liabilities:Current:Income Tax Payable', currency, float(-tax)),
        ]
        if cpp > 0:
            postings.append(('Liabilities:Current:Payroll Payable', currency, float(-cpp)))
        if ei > 0:
            postings.append(('Liabilities:Current:Payroll Payable', currency, float(-ei)))

        tags = {
            'pair': '0001',
            'contact': contact_slug or '',
        }
        if period_desc:
            tags['period'] = period_desc

        description = f"Payroll: {payee_name}"
        entry = format_entry(pay_date, description, postings, tags)

    # Write
    year = pay_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "payroll.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount}")
        print(f"  Written to: generated/{year}/payroll.journal")


# ─── pair payroll list ────────────────────────────────────────────────────

def cmd_list(flags, args):
    """List recent pay runs by reading payroll journals."""
    import re

    year = str(date.today().year)
    for i, a in enumerate(args):
        if a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    journal_path = get_generated_dir() / year / "payroll.journal"
    if not journal_path.exists():
        print(f"No payroll entries for {year}.")
        return

    entries = []
    with open(journal_path) as f:
        for line in f:
            match = re.match(r'^(\d{4}-\d{2}-\d{2})\s+\*\s+(.+?)(?:\s+;.*)?$', line.rstrip())
            if match:
                entries.append({'date': match.group(1), 'description': match.group(2)})

    if not entries:
        print(f"No payroll entries for {year}.")
        return

    print(f"\n  Payroll — {year}\n")
    print(f"  {'Date':<12} {'Description':<50}")
    print(f"  {'─' * 62}")
    for entry in entries:
        print(f"  {entry['date']:<12} {entry['description']:<50}")
    print(f"\n  {len(entries)} entries")
    print()
