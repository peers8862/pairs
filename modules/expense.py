"""pair expense — operating expense recording."""

import sys
import re
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_date, validate_positive_number, parse_global_flags, BASE_DIR
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, get_generated_dir
)


CATEGORIES = [
    'office', 'software', 'professional', 'travel', 'meals',
    'marketing', 'telecom', 'utilities', 'insurance', 'bank-fees',
    'repairs', 'rent', 'other'
]

CATEGORY_ACCOUNTS = {
    'office': 'Expenses:Operating:Office Supplies',
    'software': 'Expenses:Operating:Software Subscriptions',
    'professional': 'Expenses:Operating:Professional Fees',
    'travel': 'Expenses:Operating:Travel',
    'meals': 'Expenses:Operating:Meals and Entertainment',
    'marketing': 'Expenses:Operating:Marketing',
    'telecom': 'Expenses:Operating:Telecommunications',
    'utilities': 'Expenses:Operating:Utilities',
    'insurance': 'Expenses:Operating:Insurance',
    'bank-fees': 'Expenses:Operating:Bank Fees',
    'repairs': 'Expenses:Operating:Repairs and Maintenance',
    'rent': 'Expenses:Operating:Rent',
    'other': 'Expenses:Operating:Other',
}

PAYMENT_METHODS = ['bank', 'credit-card']


def dispatch(args):
    """Route expense subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'add':
        cmd_add(flags, action_args)
    elif action == 'list':
        cmd_list(flags, action_args)
    else:
        print(f"Unknown expense action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair expense — operating expense recording

Actions:
  add                 Record an expense
  list                List recorded expenses

Flags for 'add':
  --batch             Non-interactive (requires --desc, --amount, --category)
  --desc TEXT         Description
  --amount NUM        Amount
  --category CAT      Category
  --from METHOD       Payment method (bank or credit-card)
  --date DATE         Expense date

Flags for 'list':
  --period SPEC       Filter by period (YYYY, YYYY-MM, YYYY-QN)
  --category CAT      Filter by category
  --division DIV      Filter by division

Categories:
  office, software, professional, travel, meals, marketing,
  telecom, utilities, insurance, bank-fees, repairs, rent, other
""")


# ─── pair expense add ─────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Record an expense."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank_account = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    # Parse inline args (these survive after parse_global_flags strips --date etc.)
    batch_desc = None
    batch_amount = None
    batch_category = None
    batch_method = None
    batch_date = flags.get('date')  # --date is consumed by global flags

    i = 0
    while i < len(args):
        if args[i] == '--desc' and i + 1 < len(args):
            batch_desc = args[i + 1]; i += 2
        elif args[i] == '--amount' and i + 1 < len(args):
            batch_amount = args[i + 1]; i += 2
        elif args[i] == '--category' and i + 1 < len(args):
            batch_category = args[i + 1]; i += 2
        elif args[i] == '--from' and i + 1 < len(args):
            batch_method = args[i + 1]; i += 2
        elif args[i] == '--date' and i + 1 < len(args):
            batch_date = args[i + 1]; i += 2
        else:
            i += 1

    if flags.get('batch'):
        # All fields required in batch mode
        if not all([batch_desc, batch_amount, batch_category]):
            print("Batch mode requires: --desc, --amount, --category")
            sys.exit(1)
        description = batch_desc
        amount = batch_amount
        category = batch_category
        payment_method = batch_method or 'bank'
        expense_date = batch_date or flags.get('date') or date.today().strftime("%Y-%m-%d")
    else:
        print("Record an expense\n")
        description = prompt("Description")
        amount = prompt("Amount", validator=validate_positive_number)
        category = prompt_choice("Category", CATEGORIES)
        payment_method = prompt_choice("Paid from", PAYMENT_METHODS, default='bank')
        expense_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                              validator=validate_date)

    # Division prompt (if divisions configured)
    divisions = config.get('divisions', [])
    division = None
    if divisions and not flags.get('batch'):
        last_div = config.get('defaults', {}).get('last_division', divisions[0])
        division = prompt(f"Division", default=last_div, required=False)
        if not division:
            division = last_div
        # Save last-used division
        if 'defaults' not in config:
            config['defaults'] = {}
        config['defaults']['last_division'] = division
        from lib.helpers import save_config
        save_config(config)

    # Resolve accounts
    expense_account = CATEGORY_ACCOUNTS.get(category, CATEGORY_ACCOUNTS['other'])

    if payment_method == 'credit-card':
        source_account = 'Liabilities:Current:Credit Card'
        pair = '0001'
    else:
        source_account = bank_account
        pair = '0000'

    amount_val = money(amount)

    # Build entry
    postings = [
        (expense_account, currency, float(amount_val)),
        (source_account, currency, float(-amount_val)),
    ]

    tags = {
        'pair': pair,
        'category': category,
    }
    if division:
        tags['division'] = division

    entry = format_entry(expense_date, description, postings, tags)

    # Write to journal
    year = expense_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "expenses.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  Recorded: {description}")
        print(f"  Amount:   {currency} {amount_val}")
        print(f"  Category: {category}")
        print(f"  Written to: generated/{year}/expenses.journal")


# ─── pair expense list ────────────────────────────────────────────────────

def cmd_list(flags, args):
    """List recorded expenses."""
    # Parse filters
    period_filter = None
    category_filter = None
    division_filter = None

    for i, a in enumerate(args):
        if a == '--period' and i + 1 < len(args):
            period_filter = args[i + 1]
        elif a == '--category' and i + 1 < len(args):
            category_filter = args[i + 1]
        elif a == '--division' and i + 1 < len(args):
            division_filter = args[i + 1]

    # Determine which files to read
    if period_filter:
        years = _years_from_period(period_filter)
    else:
        # Default: current year
        years = [str(date.today().year)]

    entries = []
    for year in years:
        journal_path = get_generated_dir() / year / "expenses.journal"
        if journal_path.exists():
            entries.extend(_parse_expense_journal(journal_path, period_filter, category_filter, division_filter))

    if not entries:
        print("No expenses found for the specified period.")
        return

    # Display
    total = Decimal('0')
    print(f"\n{'Date':<12} {'Description':<35} {'Category':<14} {'Amount':>12}")
    print("─" * 77)

    for entry in entries:
        print(f"{entry['date']:<12} {entry['description']:<35} "
              f"{entry['category']:<14} {entry['currency']} {entry['amount']:>9,.2f}")
        total += entry['amount']

    print("─" * 77)
    print(f"{'Total':<12} {'':<35} {'':<14} {entries[0]['currency'] if entries else 'CAD'} {total:>9,.2f}")
    print()


# ─── Parsing helpers ─────────────────────────────────────────────────────────

def _parse_expense_journal(path, period_filter=None, category_filter=None, division_filter=None):
    """Parse expense entries from a journal file."""
    entries = []
    current_entry = None

    with open(path) as f:
        for line in f:
            # Match transaction header: YYYY-MM-DD * Description  ; tags
            match = re.match(
                r'^(\d{4}-\d{2}-\d{2})\s+\*\s+(.+?)(?:\s+;\s+(.*))?$',
                line.rstrip()
            )
            if match:
                if current_entry:
                    entries.append(current_entry)
                entry_date = match.group(1)
                description = match.group(2)
                tags_str = match.group(3) or ''

                # Parse tags
                tags = {}
                if tags_str:
                    for pair in tags_str.split(','):
                        pair = pair.strip()
                        if ':' in pair:
                            k, v = pair.split(':', 1)
                            tags[k.strip()] = v.strip()

                current_entry = {
                    'date': entry_date,
                    'description': description,
                    'category': tags.get('category', 'other'),
                    'division': tags.get('division', ''),
                    'amount': Decimal('0'),
                    'currency': 'CAD',
                }
                continue

            # Match posting line (first posting is the expense amount)
            if current_entry and current_entry['amount'] == 0:
                posting_match = re.match(
                    r'^\s+\S+.*\s+([A-Z]{3})\s+([\d,.]+)\s*$',
                    line.rstrip()
                )
                if posting_match:
                    current_entry['currency'] = posting_match.group(1)
                    amount_str = posting_match.group(2).replace(',', '')
                    try:
                        current_entry['amount'] = Decimal(amount_str)
                    except Exception:
                        pass

    # Don't forget the last entry
    if current_entry:
        entries.append(current_entry)

    # Apply filters
    if period_filter:
        entries = [e for e in entries if _matches_period(e['date'], period_filter)]
    if category_filter:
        entries = [e for e in entries if e['category'] == category_filter]
    if division_filter:
        entries = [e for e in entries if e.get('division') == division_filter]

    return entries


def _matches_period(entry_date, period_spec):
    """Check if an entry date matches a period specification."""
    # YYYY
    if re.match(r'^\d{4}$', period_spec):
        return entry_date.startswith(period_spec)
    # YYYY-MM
    if re.match(r'^\d{4}-\d{2}$', period_spec):
        return entry_date.startswith(period_spec)
    # YYYY-QN
    match = re.match(r'^(\d{4})-Q(\d)$', period_spec)
    if match:
        year = match.group(1)
        quarter = int(match.group(2))
        month = int(entry_date[5:7])
        q_start = (quarter - 1) * 3 + 1
        q_end = quarter * 3
        return entry_date.startswith(year) and q_start <= month <= q_end
    return True


def _years_from_period(period_spec):
    """Extract year(s) from a period specification."""
    match = re.match(r'^(\d{4})', period_spec)
    if match:
        return [match.group(1)]
    return [str(date.today().year)]
