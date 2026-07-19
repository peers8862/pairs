"""pair liability — loan and debt management with payment scheduling."""

import sys
from datetime import date, datetime
from decimal import Decimal
from calendar import monthrange

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_slug, validate_date, validate_positive_number,
    validate_non_negative_number, validate_positive_int,
    parse_global_flags
)
from lib.yaml_store import load_entity, save_entity, list_entities, entity_exists
from lib.journal import (
    format_entry, generated_header, write_journal_atomic, append_journal,
    ensure_year_structure, get_generated_dir
)


MODULE = "liabilities"

TYPES = ['loan', 'lease', 'credit-line', 'payable']
SCHEDULES = ['monthly', 'biweekly', 'quarterly', 'annual']

# Default account mappings by type
DEFAULT_ACCOUNTS = {
    'loan': {
        'liability': 'Liabilities:Long-Term:Bank Loan',
        'interest_expense': 'Expenses:Non-Operating:Interest Expense',
        'payment_source': 'Assets:Current:Chequing',
    },
    'lease': {
        'liability': 'Liabilities:Long-Term:Lease',
        'interest_expense': 'Expenses:Non-Operating:Interest Expense',
        'payment_source': 'Assets:Current:Chequing',
    },
    'credit-line': {
        'liability': 'Liabilities:Current:Credit Line',
        'interest_expense': 'Expenses:Non-Operating:Interest Expense',
        'payment_source': 'Assets:Current:Chequing',
    },
    'payable': {
        'liability': 'Liabilities:Current:Accounts Payable',
        'interest_expense': 'Expenses:Non-Operating:Interest Expense',
        'payment_source': 'Assets:Current:Chequing',
    },
}


def dispatch(args):
    """Route liability subcommands."""
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
    elif action == 'show':
        cmd_show(flags, action_args)
    elif action == 'pay':
        cmd_pay(flags, action_args)
    elif action == 'payments':
        cmd_payments(flags, action_args)
    elif action == 'reclassify':
        cmd_reclassify(flags, action_args)
    else:
        print(f"Unknown liability action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair liability — loan and debt management

Actions:
  add                 Record a new liability (loan, lease, credit line)
  list                List all liabilities
  show <slug>         Show liability details and payment status
  pay <slug>          Record a payment
  payments            Generate scheduled payment entries
  reclassify <slug>   Reclassify liability to a different account

Flags:
  --all               Include paid-off liabilities (list)
  --liability <slug>  Generate for specific liability (payments)
  --through <date>    Generate entries through date (payments)
  --type <type>       Filter by type (list)
""")


# ─── pair liability add ───────────────────────────────────────────────────

def cmd_add(flags, args):
    """Add a new liability."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')

    print("Record a liability\n")

    name = prompt("Name (e.g. 'Vehicle Loan - Honda CR-V')")

    from lib.helpers import slugify
    default_slug = slugify(name)
    slug = prompt("Slug (identifier)", default=default_slug, validator=validate_slug)

    if entity_exists(MODULE, slug):
        print(f"  Liability '{slug}' already exists.")
        sys.exit(1)

    liab_type = prompt_choice("Type", TYPES)
    principal = prompt("Principal amount", validator=validate_positive_number)
    interest_rate = prompt("Annual interest rate (%)", default="0",
                           validator=validate_non_negative_number)
    term_months = prompt("Term (months)", validator=validate_positive_int)
    start_date = prompt("Start date", default=date.today().strftime("%Y-%m-%d"),
                        validator=validate_date)
    schedule = prompt_choice("Payment schedule", SCHEDULES, default='monthly')

    # Calculate or ask for payment amount
    payment_amount = None
    rate = Decimal(interest_rate)
    if rate > 0:
        calculated = _calculate_payment(Decimal(principal), rate, int(term_months), schedule)
        use_calc = confirm(f"Calculated payment: {currency} {calculated:.2f}. Use this?")
        if use_calc:
            payment_amount = float(calculated)
        else:
            payment_amount = float(prompt("Payment amount", validator=validate_positive_number))
    else:
        # Zero interest — simple division
        periods = _periods_count(int(term_months), schedule)
        simple = money(Decimal(principal) / periods)
        use_simple = confirm(f"Payment (no interest): {currency} {simple:.2f}. Use this?")
        if use_simple:
            payment_amount = float(simple)
        else:
            payment_amount = float(prompt("Payment amount", validator=validate_positive_number))

    lender = prompt("Lender contact slug (optional)", required=False)

    # Account overrides
    defaults = DEFAULT_ACCOUNTS.get(liab_type, DEFAULT_ACCOUNTS['loan'])
    accounts = defaults.copy()

    # Customize liability account name
    if liab_type in ('loan', 'lease'):
        accounts['liability'] = f"Liabilities:Long-Term:{name}"
    elif liab_type == 'credit-line':
        accounts['liability'] = f"Liabilities:Current:{name}"
    else:
        accounts['liability'] = f"Liabilities:Current:{name}"

    # Use bank from config
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')
    accounts['payment_source'] = bank

    # Build liability data
    liab_data = {
        'name': name,
        'slug': slug,
        'type': liab_type,
        'principal': float(principal),
        'interest_rate': float(interest_rate),
        'term_months': int(term_months),
        'start_date': start_date,
        'payment_schedule': schedule,
        'payment_amount': payment_amount,
        'currency': currency,
        'accounts': accounts,
    }

    if lender:
        liab_data['lender'] = lender

    # Save YAML
    save_entity(MODULE, slug, liab_data)
    print(f"\n  Saved: liabilities/{slug}.yaml")

    # Generate creation entry
    year = start_date[:4]
    ensure_year_structure(int(year))
    _write_creation_entry(liab_data, config)
    print(f"  Creation entry written to generated/{year}/liabilities.journal")

    print(f"\n  Run 'pair liability payments' to generate payment schedule.")


def _write_creation_entry(liab, config):
    """Write the liability creation journal entry."""
    currency = liab['currency']
    principal = money(liab['principal'])
    date_str = liab['start_date']
    year = date_str[:4]
    name = liab['name']
    slug = liab['slug']
    liability_account = liab['accounts']['liability']
    bank = liab['accounts']['payment_source']

    tags = {
        'pair': '1000',
        'source': f'liabilities/{slug}.yaml',
        'type': liab['type'],
        'term': str(liab['term_months']),
    }

    # For loans/credit-lines: cash received, liability created
    # For leases: asset created, liability created (handled by asset module linking)
    postings = [
        (bank, currency, float(principal)),
        (liability_account, currency, float(-principal)),
    ]

    entry = format_entry(date_str, f"New liability: {name}", postings, tags)

    journal_path = get_generated_dir() / year / "liabilities.journal"
    append_journal(journal_path, entry)


# ─── pair liability list ──────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all liabilities."""
    show_all = '--all' in args
    type_filter = None
    for i, a in enumerate(args):
        if a == '--type' and i + 1 < len(args):
            type_filter = args[i + 1]

    slugs = list_entities(MODULE)
    if not slugs:
        print("No liabilities recorded. Use 'pair liability add' to start.")
        return

    print(f"\n{'Name':<35} {'Type':<12} {'Principal':>12} {'Remaining':>12} {'Status':<10}")
    print("─" * 85)

    for slug in slugs:
        liab = load_entity(MODULE, slug)
        if not liab:
            continue

        if type_filter and liab.get('type') != type_filter:
            continue

        principal = money(liab['principal'])
        remaining = _remaining_balance(liab)
        paid_off = remaining <= 0

        if paid_off and not show_all:
            continue

        status = "paid off" if paid_off else "active"

        print(f"{liab['name']:<35} {liab.get('type', ''):<12} "
              f"{liab['currency']} {principal:>9} "
              f"{liab['currency']} {remaining:>9} {status:<10}")

    print()


# ─── pair liability show ──────────────────────────────────────────────────

def cmd_show(flags, args):
    """Show details for a specific liability."""
    if not args:
        print("Usage: pair liability show <slug>")
        sys.exit(1)

    slug = args[0]
    liab = load_entity(MODULE, slug)
    if not liab:
        print(f"Liability '{slug}' not found.")
        sys.exit(1)

    principal = money(liab['principal'])
    remaining = _remaining_balance(liab)
    payment = money(liab.get('payment_amount', 0))
    total_interest = _total_interest(liab)
    payments_made = _payments_made_count(liab)
    total_payments = _periods_count(liab['term_months'], liab.get('payment_schedule', 'monthly'))

    print(f"\n  {liab['name']}")
    print(f"  {'─' * 50}")
    print(f"  Slug:              {slug}")
    print(f"  Type:              {liab.get('type', 'loan')}")
    print(f"  Principal:         {liab['currency']} {principal}")
    print(f"  Interest rate:     {liab['interest_rate']}% annual")
    print(f"  Term:              {liab['term_months']} months")
    print(f"  Start date:        {liab['start_date']}")
    print(f"  Schedule:          {liab.get('payment_schedule', 'monthly')}")
    print(f"  Payment amount:    {liab['currency']} {payment}")
    print(f"  Remaining balance: {liab['currency']} {remaining}")
    print(f"  Payments made:     {payments_made}/{total_payments}")
    print(f"  Total interest:    {liab['currency']} {total_interest}")
    if liab.get('lender'):
        print(f"  Lender:            {liab['lender']}")
    print(f"\n  Accounts:")
    for key, val in liab.get('accounts', {}).items():
        print(f"    {key}: {val}")
    print()


# ─── pair liability pay ───────────────────────────────────────────────────

def cmd_pay(flags, args):
    """Record a single payment on a liability."""
    if not args:
        print("Usage: pair liability pay <slug>")
        sys.exit(1)

    slug = args[0]
    liab = load_entity(MODULE, slug)
    if not liab:
        print(f"Liability '{slug}' not found.")
        sys.exit(1)

    config = load_config()
    currency = liab['currency']
    payment_amount = money(liab.get('payment_amount', 0))

    print(f"\nPayment: {liab['name']}\n")

    # Allow override of amount and date
    amount_str = prompt(f"Payment amount", default=str(payment_amount),
                        validator=validate_positive_number)
    payment_date = prompt("Payment date", default=date.today().strftime("%Y-%m-%d"),
                          validator=validate_date)

    amount = money(amount_str)

    # Calculate principal/interest split
    remaining = _remaining_balance(liab)
    rate = Decimal(str(liab['interest_rate']))

    if rate > 0:
        # Monthly interest on remaining balance
        monthly_rate = rate / Decimal('1200')
        interest_portion = money(remaining * monthly_rate)
        principal_portion = amount - interest_portion

        # Ensure we don't overpay principal
        if principal_portion > remaining:
            principal_portion = remaining
            interest_portion = amount - principal_portion
    else:
        interest_portion = Decimal('0')
        principal_portion = min(amount, remaining)

    print(f"\n  Principal: {currency} {principal_portion:.2f}")
    print(f"  Interest:  {currency} {interest_portion:.2f}")
    print(f"  Total:     {currency} {amount:.2f}")

    if not flags.get('yes') and not confirm("\n  Record this payment?"):
        print("  Cancelled.")
        return

    # Determine payment sequence number
    payments_made = _payments_made_count(liab) + 1
    total_payments = _periods_count(liab['term_months'], liab.get('payment_schedule', 'monthly'))

    # Write journal entry
    year = payment_date[:4]
    ensure_year_structure(int(year))

    liability_account = liab['accounts']['liability']
    interest_account = liab['accounts']['interest_expense']
    bank = liab['accounts']['payment_source']

    postings = []
    if principal_portion > 0:
        postings.append((liability_account, currency, float(principal_portion)))
    if interest_portion > 0:
        postings.append((interest_account, currency, float(interest_portion)))
    postings.append((bank, currency, float(-amount)))

    tags = {
        'pair': '1000',
        'source': f'liabilities/{slug}.yaml',
        'seq': f'{payments_made}/{total_payments}',
    }

    entry = format_entry(payment_date,
                         f"Payment: {liab['name']} ({payments_made}/{total_payments})",
                         postings, tags)

    journal_path = get_generated_dir() / year / "loan-payments.journal"
    append_journal(journal_path, entry)

    # Track payment in YAML
    if 'payments' not in liab:
        liab['payments'] = []
    liab['payments'].append({
        'date': payment_date,
        'amount': float(amount),
        'principal': float(principal_portion),
        'interest': float(interest_portion),
    })
    save_entity(MODULE, slug, liab)

    print(f"\n  Payment recorded in generated/{year}/loan-payments.journal")
    new_balance = remaining - principal_portion
    print(f"  Remaining balance: {currency} {new_balance:.2f}")


# ─── pair liability payments ──────────────────────────────────────────────

def cmd_payments(flags, args):
    """Generate scheduled payment entries."""
    config = load_config()

    # Parse args
    specific_liability = None
    through_date = None
    for i, a in enumerate(args):
        if a == '--liability' and i + 1 < len(args):
            specific_liability = args[i + 1]
        elif a == '--through' and i + 1 < len(args):
            through_date = args[i + 1]

    if not through_date:
        # Default: through end of current year
        through_date = f"{date.today().year}-12-31"

    # Collect liabilities to process
    if specific_liability:
        slugs = [specific_liability]
    else:
        slugs = list_entities(MODULE)

    if not slugs:
        print("No liabilities found.")
        return

    # Group entries by year
    entries_by_year = {}

    for slug in slugs:
        liab = load_entity(MODULE, slug)
        if not liab:
            print(f"  Warning: {slug} not found, skipping.")
            continue

        # Skip if already paid off
        remaining = _remaining_balance(liab)
        if remaining <= 0:
            continue

        new_entries = _generate_payment_entries(liab, through_date)
        for year_str, entry in new_entries:
            entries_by_year.setdefault(year_str, []).append(entry)

    # Write journals per year (atomic replacement)
    total_entries = 0
    for year_str, entries in sorted(entries_by_year.items()):
        ensure_year_structure(int(year_str))
        journal_path = get_generated_dir() / year_str / "loan-payments.journal"
        header = generated_header("liabilities/*.yaml", "pair liability payments")
        content = header + "".join(entries)
        write_journal_atomic(journal_path, content)
        total_entries += len(entries)
        if not flags.get('quiet'):
            print(f"  generated/{year_str}/loan-payments.journal ({len(entries)} entries)")

    if not flags.get('quiet'):
        print(f"\n  Total: {total_entries} payment entries generated.")


def _generate_payment_entries(liab, through_date_str):
    """Generate payment entries from start through a given date.

    Returns list of (year_str, entry_str) tuples.
    """
    currency = liab['currency']
    principal = Decimal(str(liab['principal']))
    rate = Decimal(str(liab['interest_rate']))
    term = liab['term_months']
    payment_amount = money(liab.get('payment_amount', 0))
    schedule = liab.get('payment_schedule', 'monthly')
    name = liab['name']
    slug = liab['slug']
    liability_account = liab['accounts']['liability']
    interest_account = liab['accounts']['interest_expense']
    bank = liab['accounts']['payment_source']

    start_date = datetime.strptime(liab['start_date'], "%Y-%m-%d").date()
    through_date = datetime.strptime(through_date_str, "%Y-%m-%d").date()

    entries = []
    remaining_principal = principal
    total_payments = _periods_count(term, schedule)

    # Determine payment dates
    payment_dates = _payment_dates(start_date, total_payments, schedule)

    for seq, pdate in enumerate(payment_dates, 1):
        if pdate > through_date:
            break
        if remaining_principal <= 0:
            break

        # Calculate interest/principal split
        if rate > 0:
            monthly_rate = rate / Decimal('1200')
            interest_portion = money(remaining_principal * monthly_rate)
            principal_portion = payment_amount - interest_portion

            if principal_portion < 0:
                # Negative amortization: payment doesn't cover interest.
                # Full payment goes to interest; unpaid interest capitalizes.
                capitalized_interest = -principal_portion
                interest_portion = payment_amount
                principal_portion = Decimal('0')
                remaining_principal += capitalized_interest
                actual_payment = payment_amount
            elif principal_portion > remaining_principal:
                # Last payment adjustment
                principal_portion = remaining_principal
                actual_payment = principal_portion + interest_portion
            else:
                actual_payment = payment_amount

            remaining_principal -= principal_portion
        else:
            interest_portion = Decimal('0')
            principal_portion = min(payment_amount, remaining_principal)
            actual_payment = principal_portion
            remaining_principal -= principal_portion

        # Build entry
        postings = []
        if principal_portion > 0:
            postings.append((liability_account, currency, float(principal_portion)))
        if interest_portion > 0:
            postings.append((interest_account, currency, float(interest_portion)))
        postings.append((bank, currency, float(-actual_payment)))

        tags = {
            'pair': '1000',
            'source': f'liabilities/{slug}.yaml',
            'seq': f'{seq}/{total_payments}',
        }

        entry = format_entry(
            pdate.strftime("%Y-%m-%d"),
            f"Payment: {name} ({seq}/{total_payments})",
            postings, tags
        )
        entries.append((str(pdate.year), entry))

    return entries


# ─── Calculation helpers ─────────────────────────────────────────────────────

def _calculate_payment(principal, annual_rate, term_months, schedule='monthly'):
    """Calculate fixed payment amount using amortization formula."""
    periods = _periods_count(term_months, schedule)

    if annual_rate == 0:
        return money(principal / periods)

    # Convert annual rate to per-period rate
    if schedule == 'monthly':
        r = annual_rate / Decimal('1200')
    elif schedule == 'biweekly':
        r = annual_rate / Decimal('2600')
    elif schedule == 'quarterly':
        r = annual_rate / Decimal('400')
    elif schedule == 'annual':
        r = annual_rate / Decimal('100')
    else:
        r = annual_rate / Decimal('1200')

    # PMT formula: P * r * (1+r)^n / ((1+r)^n - 1)
    factor = (1 + r) ** periods
    payment = principal * r * factor / (factor - 1)
    return money(payment)


def _periods_count(term_months, schedule):
    """How many payment periods in the term."""
    if schedule == 'monthly':
        return term_months
    elif schedule == 'biweekly':
        return int(term_months * Decimal('26') / Decimal('12'))
    elif schedule == 'quarterly':
        return term_months // 3
    elif schedule == 'annual':
        return term_months // 12
    return term_months


def _payment_dates(start_date, count, schedule):
    """Generate a list of payment dates."""
    dates = []
    current = start_date

    for i in range(count):
        if schedule == 'monthly':
            # Same day each month
            month = current.month + i
            year = current.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            day = min(start_date.day, monthrange(year, month)[1])
            dates.append(date(year, month, day))
        elif schedule == 'biweekly':
            from datetime import timedelta
            dates.append(start_date + timedelta(weeks=2 * i))
        elif schedule == 'quarterly':
            month = current.month + (i * 3)
            year = current.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            day = min(start_date.day, monthrange(year, month)[1])
            dates.append(date(year, month, day))
        elif schedule == 'annual':
            year = current.year + i
            day = min(start_date.day, monthrange(year, current.month)[1])
            dates.append(date(year, current.month, day))

    return dates


def _remaining_balance(liab):
    """Calculate remaining balance based on recorded payments."""
    principal = money(liab['principal'])
    payments = liab.get('payments', [])
    paid_principal = sum(money(p.get('principal', 0)) for p in payments)
    return principal - paid_principal


def _payments_made_count(liab):
    """Count payments already recorded."""
    return len(liab.get('payments', []))


def _total_interest(liab):
    """Total interest paid so far."""
    payments = liab.get('payments', [])
    return sum(money(p.get('interest', 0)) for p in payments)


# ─── pair liability reclassify ────────────────────────────────────────────

def cmd_reclassify(flags, args):
    """Reclassify a liability from one account to another.

    Writes: DR old liability account, CR new liability account. Pair 1100.
    """
    if not args:
        print("Usage: pair liability reclassify <slug>")
        sys.exit(1)

    slug = args[0]
    liab = load_entity(MODULE, slug)
    if not liab:
        print(f"Liability '{slug}' not found.")
        sys.exit(1)

    config = load_config()
    currency = liab['currency']
    old_account = liab['accounts']['liability']

    print(f"\nReclassify: {liab['name']}")
    print(f"Current account: {old_account}\n")

    # Prompts
    new_account = prompt("New liability account")
    amount_str = prompt("Amount to reclassify",
                        default=str(liab['principal']),
                        validator=validate_positive_number)
    reclass_date = flags.get('date') or prompt(
        "Date", default=date.today().strftime("%Y-%m-%d"),
        validator=validate_date
    )

    amount = money(amount_str)

    if not flags.get('yes') and not confirm(
        f"\n  Reclassify {currency} {amount} from\n"
        f"    {old_account}\n"
        f"  to\n"
        f"    {new_account}\n"
        f"  Proceed?"
    ):
        print("  Cancelled.")
        return

    # Journal entry: DR old liability (reduces it), CR new liability (increases it)
    postings = [
        (old_account, currency, float(amount)),
        (new_account, currency, float(-amount)),
    ]

    tags = {
        'pair': '1100',
        'source': f'liabilities/{slug}.yaml',
    }

    entry = format_entry(reclass_date,
                         f"Reclassify liability: {liab['name']}",
                         postings, tags)

    year = reclass_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "loan-payments.journal"
    append_journal(journal_path, entry)

    # Update YAML account
    liab['accounts']['liability'] = new_account
    save_entity(MODULE, slug, liab)

    if not flags.get('quiet'):
        print(f"\n  Reclassified: {liab['name']}")
        print(f"  Old account:  {old_account}")
        print(f"  New account:  {new_account}")
        print(f"  Amount:       {currency} {amount}")
        print(f"  Written to:   generated/{year}/loan-payments.journal")
