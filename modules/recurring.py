"""pair recurring — recurring entry automation."""

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
    format_entry, append_journal, ensure_year_structure, get_generated_dir
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
    elif action == 'pay':
        cmd_pay(flags, action_args)
    elif action == 'due':
        cmd_due(flags, action_args)
    elif action == 'remove':
        cmd_remove(flags, action_args)
    else:
        print(f"Unknown recurring action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair recurring — recurring entry automation

Actions:
  add                 Define a new recurring entry
  list                List all recurring entries
  generate            Generate pending entries through a date
  pay [SLUG] [--amount N]  Record a payment at its real amount
  due                      Upcoming items + active reminders
  remove <slug>       Remove a recurring entry definition

Flags for 'generate':
  --through DATE      Generate through this date (default: today)
  --entry SLUG       Generate for a specific entry only
  --dry-run           Preview without writing
""")


# ─── pair recurring add ───────────────────────────────────────────────────

def cmd_add(flags, args):
    """Define a new recurring entry."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
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
    print(f"  Run 'pair recurring generate' to produce entries.")


# ─── pair recurring list ──────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all recurring entries."""
    slugs = list_entities(MODULE)
    if not slugs:
        print("No recurring entries defined. Use 'pair recurring add' to start.")
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


# ─── pair recurring generate ──────────────────────────────────────────────

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
            # User-assigned tags ride along on every generated entry.
            for t in entry.get('tags', []) or []:
                if isinstance(t, str) and ':' in t:
                    k, _, v = t.partition(':')
                    tags[k.strip()] = v.strip()
                elif isinstance(t, str) and t.strip():
                    tags[t.strip()] = ''

            journal_entry = format_entry(
                current.strftime("%Y-%m-%d"),
                entry['name'],
                postings, tags
            )

            if flags.get('dry_run'):
                print(journal_entry)
            else:
                journal_path = get_generated_dir() / year / "recurring.journal"
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


# ─── pair recurring remove ────────────────────────────────────────────────

def cmd_remove(flags, args):
    """Remove a recurring entry definition."""
    if not args:
        print("Usage: pair recurring remove <slug>")
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


# ─── Due dates, reminders, and variable-amount payment ───────────────────────

def due_info(entry, today=None):
    """Next due date, days until, and whether a reminder is active.

    Variable bills (utilities, telecom) are the reason `reminder_days` exists:
    you want warning before the charge lands so the real amount can be entered.
    """
    from datetime import date as _d, timedelta
    today = today or _d.today()
    day = int(entry.get('day') or 1)

    def _on(year, month):
        # Clamp to month length (a 31st becomes the 30th/28th where needed).
        import calendar
        return _d(year, month, min(day, calendar.monthrange(year, month)[1]))

    freq = (entry.get('frequency') or 'monthly').lower()
    nxt = _on(today.year, today.month)
    if nxt < today:
        if freq == 'monthly':
            nxt = _on(today.year + (today.month // 12), (today.month % 12) + 1)
        elif freq in ('yearly', 'annual', 'annually'):
            nxt = _on(today.year + 1, today.month)
        elif freq == 'weekly':
            nxt = today + timedelta(days=7)
        else:
            nxt = _on(today.year + (today.month // 12), (today.month % 12) + 1)

    days_until = (nxt - today).days
    reminder = entry.get('reminder_days')
    return {
        'next_due': nxt.strftime('%Y-%m-%d'),
        'days_until': days_until,
        'reminder_days': reminder,
        'reminder_active': reminder is not None and days_until <= int(reminder),
    }


def apply_amount_policy(entry, actual, policy):
    """Return the new expected amount for a recurring entry after a payment.

    policy: 'adopt'   — the actual becomes the new expected
            'average' — mean of previous expected and actual
            'anomaly' — keep the previous expected (default)
    """
    expected = float(entry.get('amount') or 0)
    actual = float(actual)
    if policy == 'adopt':
        return round(actual, 2)
    if policy == 'average':
        return round((expected + actual) / 2, 2)
    return round(expected, 2)


def record_payment(slug, actual, pay_date=None, policy='anomaly', note=''):
    """Record a payment at its real amount and update the expected amount.

    Returns a dict describing the variance so callers (CLI and web) can report
    it identically.
    """
    from datetime import date as _d
    entry = load_entity(MODULE, slug)
    if not entry:
        return None

    expected = float(entry.get('amount') or 0)
    actual = float(actual)
    diff = round(actual - expected, 2)
    pay_date = pay_date or _d.today().strftime('%Y-%m-%d')

    history = entry.get('history', []) or []
    history.append({'date': pay_date, 'amount': round(actual, 2),
                    'expected': round(expected, 2), 'variance': diff,
                    'policy': policy, **({'note': note} if note else {})})
    entry['history'] = history[-24:]

    new_amount = apply_amount_policy(entry, actual, policy)
    entry['amount'] = new_amount
    entry['last_paid'] = pay_date
    save_entity(MODULE, slug, entry)

    return {
        'slug': slug, 'date': pay_date,
        'expected': round(expected, 2), 'actual': round(actual, 2),
        'variance': diff,
        'pct': round((diff / expected * 100), 1) if expected else 0.0,
        'policy': policy, 'new_amount': new_amount,
        'changed': new_amount != round(expected, 2),
    }


def cmd_pay(flags, args):
    """Record a payment at its real amount, then report the variance."""
    slug = args[0] if args else prompt("  Recurring slug")
    entry = load_entity(MODULE, slug)
    if not entry:
        print(f"\n  No recurring entry '{slug}'\n")
        return

    expected = float(entry.get('amount') or 0)
    currency = entry.get('currency', 'CAD')
    print(f"\n  {entry.get('name', slug)} — expected {currency} {expected:.2f}")

    actual_raw = None
    for i, a in enumerate(args):
        if a == '--amount' and i + 1 < len(args):
            actual_raw = args[i + 1]
    if actual_raw is None:
        actual_raw = prompt(f"  Actual amount", default=f"{expected:.2f}")
    try:
        actual = float(str(actual_raw).replace(',', ''))
    except ValueError:
        print(f"\n  Invalid amount: {actual_raw!r}\n")
        return

    diff = round(actual - expected, 2)
    # Report the variance before asking what to do about it.
    if diff == 0:
        print(f"  Matches the expected amount.")
        policy = 'anomaly'
    else:
        sign = '+' if diff > 0 else ''
        pct = f" ({sign}{diff / expected * 100:.1f}%)" if expected else ''
        print(f"  Difference: {sign}{currency} {diff:.2f}{pct} vs expected {currency} {expected:.2f}")
        print("\n    a) adopt   — use this amount going forward")
        print("    v) average — average of expected and actual")
        print("    k) keep    — anomaly, keep the previous amount")
        choice = prompt("  Choose (a/v/k)", default='k').strip().lower()[:1]
        policy = {'a': 'adopt', 'v': 'average'}.get(choice, 'anomaly')

    result = record_payment(slug, actual, policy=policy)
    print(f"\n  ✓ Recorded {currency} {result['actual']:.2f} on {result['date']}")
    if result['changed']:
        print(f"  Expected amount updated to {currency} {result['new_amount']:.2f} ({policy})")
    else:
        print(f"  Expected amount unchanged at {currency} {result['new_amount']:.2f}")
    print()


def cmd_due(flags, args):
    """Show upcoming recurring items and active reminders."""
    slugs = list_entities(MODULE)
    if not slugs:
        print("\n  No recurring entries.\n")
        return
    rows = []
    for slug in slugs:
        e = load_entity(MODULE, slug)
        if not e:
            continue
        rows.append((due_info(e), e, slug))
    rows.sort(key=lambda r: r[0]['days_until'])

    print("\n  Upcoming recurring items:\n")
    for info, e, slug in rows:
        bell = ' 🔔' if info['reminder_active'] else ''
        cur = e.get('currency', 'CAD')
        print(f"    {info['next_due']}  in {info['days_until']:>3}d  "
              f"{cur} {float(e.get('amount') or 0):>10.2f}  {e.get('name', slug)}{bell}")
    print()
