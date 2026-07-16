"""company recurring — recurring entry automation."""

import sys
from datetime import date, datetime
from decimal import Decimal
from calendar import monthrange

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_slug, validate_date, validate_positive_number,
    parse_global_flags
)
from lib.yaml_store import load_entity, save_entity, list_entities, entity_exists
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, GENERATED_DIR
)


MODULE = "recurring"

FREQUENCIES = ['monthly', 'quarterly', 'annual', 'biweekly']


def dispatch(args):
    """Route recurring subcommands."""
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
    elif action == 'generate':
        cmd_generate(flags, action_args)
    elif action == 'remove':
        cmd_remove(flags, action_args)
    else:
        print(f"Unknown recurring action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""company recurring — recurring entry automation

Actions:
  add                 Define a new recurring entry
  list                List all recurring entries
  generate            Generate pending entries through a date
  remove <slug>       Remove a recurring entry definition

Flags for 'generate':
  --through DATE      Generate through this date (default: today)
  --entry SLUG       Generate for a specific entry only
  --dry-run           Preview without writing
""")


# ─── company recurring add ───────────────────────────────────────────────────

def cmd_add(flags, args):
    """Define a new recurring entry."""
    config = load_config()
    currency = config.get('company', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    print("Define a recurring entry\n")

    name = prompt("Description (e.g. 'Office rent')")
    slug = prompt("Slug (identifier)", validator=validate_slug)

    if entity_exists(MODULE, slug):
        print(f"  Recurring entry '{slug}' already exists.")
        sys.exit(1)

    frequency = prompt_choice("Frequency", FREQUENCIES)
    amount = prompt("Amount", validator=validate_positive_number)
    start_date = prompt("Start date (first occurrence)",
                        default=date.today().strftime("%Y-%m-%d"), validator=validate_date)
    end_date = prompt("End date (optional, blank for ongoing)", required=False,
                      validator=lambda v: validate_date(v) if v else None)

    debit_account = prompt("Debit account", default="Expenses:Operating:Rent")
    credit_account = prompt("Credit account", default=bank)
    pair = prompt("BitLedger pair", default="0000")

    notes = prompt("Notes (optional)", required=False)

    entry_data = {
        'name': name,
        'slug': slug,
        'frequency': frequency,
        'amount': float(amount),
        'start_date': start_date,
        'debit_account': debit_account,
        'credit_account': credit_account,
        'pair': pair,
        'currency': currency,
        'last_generated': None,
    }
    if end_date:
        entry_data['end_date'] = end_date
    if notes:
        entry_data['notes'] = notes

    save_entity(MODULE, slug, entry_data)
    print(f"\n  Saved: recurring/{slug}.yaml")
    print(f"  Run 'company recurring generate' to produce entries.")


# ─── company recurring list ──────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all recurring entries."""
    slugs = list_entities(MODULE)
    if not slugs:
        print("No recurring entries defined. Use 'company recurring add' to start.")
        return

    print(f"\n{'Name':<30} {'Frequency':<12} {'Amount':>12} {'Last Generated':<16}")
    print("─" * 74)

    for slug in slugs:
        entry = load_entity(MODULE, slug)
        if not entry:
            continue
        last = entry.get('last_generated', 'never')
        currency = entry.get('currency', 'CAD')
        print(f"{entry['name']:<30} {entry['frequency']:<12} "
              f"{currency} {entry['amount']:>9,.2f} {str(last):<16}")

    print()


# ─── company recurring generate ──────────────────────────────────────────────

def cmd_generate(flags, args):
    """Generate pending recurring entries."""
    config = load_config()

    # Parse args
    through_date = None
    specific_entry = None
    for i, a in enumerate(args):
        if a == '--through' and i + 1 < len(args):
            through_date = args[i + 1]
        elif a == '--entry' and i + 1 < len(args):
            specific_entry = args[i + 1]

    if not through_date:
        through_date = date.today().strftime("%Y-%m-%d")

    through_dt = datetime.strptime(through_date, "%Y-%m-%d").date()

    # Process entries
    if specific_entry:
        slugs = [specific_entry]
    else:
        slugs = list_entities(MODULE)

    if not slugs:
        print("No recurring entries defined.")
        return

    total_generated = 0

    for slug in slugs:
        entry = load_entity(MODULE, slug)
        if not entry:
            continue

        # Determine start point
        last_generated = entry.get('last_generated')
        if last_generated:
            start_from = datetime.strptime(last_generated, "%Y-%m-%d").date()
            # Advance to next occurrence
            start_from = _next_occurrence(start_from, entry['frequency'])
        else:
            start_from = datetime.strptime(entry['start_date'], "%Y-%m-%d").date()

        # Check end date
        end_date = through_dt
        if entry.get('end_date'):
            entry_end = datetime.strptime(entry['end_date'], "%Y-%m-%d").date()
            end_date = min(end_date, entry_end)

        # Generate occurrences
        current = start_from
        count = 0

        while current <= end_date:
            year = str(current.year)
            ensure_year_structure(int(year))

            currency = entry['currency']
            amount = money(entry['amount'])

            postings = [
                (entry['debit_account'], currency, float(amount)),
                (entry['credit_account'], currency, float(-amount)),
            ]

            tags = {
                'pair': entry.get('pair', '0000'),
                'recurring': slug,
            }

            journal_entry = format_entry(
                current.strftime("%Y-%m-%d"),
                entry['name'],
                postings, tags
            )

            if flags.get('dry_run'):
                print(journal_entry)
            else:
                journal_path = GENERATED_DIR / year / "recurring.journal"
                append_journal(journal_path, journal_entry)

            count += 1
            entry['last_generated'] = current.strftime("%Y-%m-%d")
            current = _next_occurrence(current, entry['frequency'])

        if count > 0 and not flags.get('dry_run'):
            save_entity(MODULE, slug, entry)
            total_generated += count
            if not flags.get('quiet'):
                print(f"  {entry['name']}: {count} entries generated")

    if not flags.get('quiet') and not flags.get('dry_run'):
        print(f"\n  Total: {total_generated} recurring entries generated.")


# ─── company recurring remove ────────────────────────────────────────────────

def cmd_remove(flags, args):
    """Remove a recurring entry definition."""
    if not args:
        print("Usage: company recurring remove <slug>")
        sys.exit(1)

    slug = args[0]
    entry = load_entity(MODULE, slug)
    if not entry:
        print(f"Recurring entry '{slug}' not found.")
        sys.exit(1)

    if not flags.get('yes'):
        if not confirm(f"Remove recurring entry '{entry['name']}'?", default_yes=False):
            print("  Cancelled.")
            return

    from lib.yaml_store import delete_entity
    delete_entity(MODULE, slug)
    print(f"  Removed: recurring/{slug}.yaml")
    print(f"  Note: Previously generated journal entries are not affected.")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _next_occurrence(current_date, frequency):
    """Calculate the next occurrence date after current_date."""
    if frequency == 'monthly':
        month = current_date.month + 1
        year = current_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(current_date.day, monthrange(year, month)[1])
        return date(year, month, day)
    elif frequency == 'quarterly':
        month = current_date.month + 3
        year = current_date.year
        while month > 12:
            month -= 12
            year += 1
        day = min(current_date.day, monthrange(year, month)[1])
        return date(year, month, day)
    elif frequency == 'annual':
        year = current_date.year + 1
        day = min(current_date.day, monthrange(year, current_date.month)[1])
        return date(year, current_date.month, day)
    elif frequency == 'biweekly':
        from datetime import timedelta
        return current_date + timedelta(weeks=2)
    return current_date
