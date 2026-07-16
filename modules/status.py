"""pair status — show include chain status and pending items."""

import sys
from datetime import date, datetime
from pathlib import Path

from lib.helpers import BASE_DIR, parse_global_flags
from lib.yaml_store import list_entities, load_entity
from lib.journal import INCLUDE_DIR, GENERATED_DIR, JOURNAL_DIR


def cmd_status(args):
    """Show system status: include chain, pending items, entity counts."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    print()
    _show_include_chain()
    _show_pending_amortization()
    _show_pending_payments()
    _show_entity_counts()


def print_help():
    print("""pair status — show include chain and pending items

Shows:
  - Include chain status (company.journal, year files)
  - Pending amortization (assets not amortized through current month)
  - Pending loan payments (liabilities with no recent payment)
  - Summary entity counts
""")


# ─── Include chain ───────────────────────────────────────────────────────────

def _show_include_chain():
    """Check include chain health."""
    company_journal = INCLUDE_DIR / "company.journal"

    print("  Include Chain")
    print("  " + "─" * 50)

    if company_journal.exists():
        print(f"  ✓ include/company.journal exists")
    else:
        print(f"  ✗ include/company.journal MISSING")
        print(f"    Run 'pair generate' to create it.")
        print()
        return

    # List year files
    year_files = sorted([
        f for f in INCLUDE_DIR.glob("*.journal")
        if f.stem.isdigit()
    ])

    if year_files:
        for yf in year_files:
            print(f"    include {yf.stem}.journal")
    else:
        print(f"    (no year files found)")

    # Check accounts.journal
    accounts_file = INCLUDE_DIR / "accounts.journal"
    if accounts_file.exists():
        print(f"  ✓ include/accounts.journal exists")
    else:
        print(f"  ✗ include/accounts.journal MISSING")

    print()


# ─── Pending amortization ────────────────────────────────────────────────────

def _show_pending_amortization():
    """Check for assets that haven't been amortized through current month."""
    slugs = list_entities("assets")
    if not slugs:
        return

    today = date.today()
    current_period = today.strftime("%Y-%m")
    pending = []

    for slug in slugs:
        asset = load_entity("assets", slug)
        if not asset:
            continue

        # Skip disposed assets
        if asset.get('disposal', {}).get('date'):
            continue

        # Check if asset has remaining life
        purchase_date = datetime.strptime(asset['purchase_date'], "%Y-%m-%d").date()
        useful_life = asset['useful_life_months']
        elapsed = (today.year - purchase_date.year) * 12 + (today.month - purchase_date.month)
        if elapsed >= useful_life:
            continue

        # Check if amortization journal has an entry for current period
        amort_current = False
        year_str = str(today.year)
        amort_file = GENERATED_DIR / year_str / "amortization.journal"
        if amort_file.exists():
            content = amort_file.read_text()
            # Look for this asset's entry in the current period
            if f"period:{current_period}" in content and slug in content:
                amort_current = True

        if not amort_current:
            pending.append(asset['name'])

    if pending:
        print("  Pending Amortization")
        print("  " + "─" * 50)
        for name in pending:
            print(f"  ⚠ {name}")
        print(f"\n    Run 'pair asset amort' to generate entries.")
        print()


# ─── Pending payments ────────────────────────────────────────────────────────

def _show_pending_payments():
    """Check for liabilities with no recent payment."""
    slugs = list_entities("liabilities")
    if not slugs:
        return

    today = date.today()
    pending = []

    for slug in slugs:
        liab = load_entity("liabilities", slug)
        if not liab:
            continue

        # Skip paid-off liabilities
        from decimal import Decimal
        principal = Decimal(str(liab['principal']))
        payments = liab.get('payments', [])
        paid_principal = sum(Decimal(str(p.get('principal', 0))) for p in payments)
        remaining = principal - paid_principal
        if remaining <= 0:
            continue

        # Check last payment date
        if payments:
            last_payment_date = max(p['date'] for p in payments)
            last_dt = datetime.strptime(last_payment_date, "%Y-%m-%d").date()
            # Consider "no recent payment" if more than 45 days since last payment
            days_since = (today - last_dt).days
            schedule = liab.get('payment_schedule', 'monthly')
            threshold = {
                'monthly': 45,
                'biweekly': 21,
                'quarterly': 105,
                'annual': 395,
            }.get(schedule, 45)

            if days_since > threshold:
                pending.append((liab['name'], f"{days_since} days since last payment"))
        else:
            # No payments at all — check if start date is in the past
            start_dt = datetime.strptime(liab['start_date'], "%Y-%m-%d").date()
            if start_dt < today:
                pending.append((liab['name'], "no payments recorded"))

    if pending:
        print("  Pending Payments")
        print("  " + "─" * 50)
        for name, reason in pending:
            print(f"  ⚠ {name} — {reason}")
        print(f"\n    Run 'pair liability pay <slug>' to record payments.")
        print()


# ─── Entity counts ───────────────────────────────────────────────────────────

def _show_entity_counts():
    """Show summary counts of all entity types."""
    modules = [
        ("assets", "Assets"),
        ("liabilities", "Liabilities"),
        ("contacts", "Contacts"),
        ("contracts", "Contracts"),
        ("projects", "Projects"),
    ]

    print("  Summary")
    print("  " + "─" * 50)

    for module_name, label in modules:
        count = len(list_entities(module_name))
        print(f"  {label:<20} {count}")

    # Count generated year directories
    gen_years = sorted([
        d.name for d in GENERATED_DIR.iterdir()
        if d.is_dir() and d.name.isdigit()
    ]) if GENERATED_DIR.exists() else []
    print(f"  {'Years':<20} {len(gen_years)} ({', '.join(gen_years) if gen_years else 'none'})")

    print()
