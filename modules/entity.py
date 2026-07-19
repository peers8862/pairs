"""pair entity — multi-entity (Company/Project) management."""

import sys
import yaml
from pathlib import Path

from lib.helpers import (
    BASE_DIR, GLOBAL_CONFIG_FILE,
    load_global_config, save_global_config, get_active_entity,
    prompt, validate_slug, ensure_dir, expand_path, slugify, save_config
)
from lib.journal import write_journal_atomic


# ─── Directory structure for an entity ───────────────────────────────────────

ENTITY_DIRS = [
    'assets',
    'liabilities',
    'contacts',
    'contracts',
    'projects',
    'deferred',
    'recurring',
    'journal',
    'generated',
    'include',
    'invoices',
    'timesheets',
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route: list, add, use, show (default)."""
    if not args or args[0] == 'show':
        cmd_show()
    elif args[0] == 'list':
        cmd_list()
    elif args[0] == 'add':
        cmd_add()
    elif args[0] == 'use':
        cmd_use(args[1:])
    elif args[0] in ('--help', '-h'):
        print_help()
    else:
        print(f"Unknown entity subcommand: {args[0]}")
        print("Usage: pair entity [show|list|add|use <slug>]")
        sys.exit(1)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_show():
    """Display active entity name and slug."""
    config = load_global_config()
    if not config:
        print("No entities configured. Run 'pair init' first.")
        return

    active = config.get('active')
    entities = config.get('entities', [])

    if not active or not entities:
        print("No active entity. Run 'pair init' first.")
        return

    # Find the active entity details
    for e in entities:
        if e['slug'] == active:
            print(f"Active entity (Company/Project): {e['name']} ({e['slug']})")
            return

    print(f"Active entity slug: {active} (details not found)")


def cmd_list():
    """Show all entities from global.yaml with active marker."""
    config = load_global_config()
    if not config:
        print("No entities configured. Run 'pair init' first.")
        return

    active = config.get('active')
    entities = config.get('entities', [])

    if not entities:
        print("No entities configured. Run 'pair init' first.")
        return

    print("Entities (Company/Project):\n")
    for e in entities:
        marker = " *" if e['slug'] == active else "  "
        print(f"  {marker} {e['name']} ({e['slug']})")

    print(f"\n  * = active")


def cmd_add():
    """Create a new entity interactively."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        return

    print("pair entity add — add a new entity (Company/Project)\n")

    name = prompt("Entity name")
    default_slug = slugify(name)
    slug = prompt("Slug (short identifier)", default=default_slug, validator=validate_slug)

    # Check for duplicate slug
    entities = config.get('entities', [])
    for e in entities:
        if e['slug'] == slug:
            print(f"\n  Error: Entity with slug '{slug}' already exists.")
            sys.exit(1)

    currency = prompt("Default currency", default="CAD")
    journal_file = prompt("Main hledger journal file", default="~/.hledger.journal")
    bank_name = prompt("Primary bank account name", default="Chequing")
    bank_account = f"Assets:Current:{bank_name}"

    # Create the entity directory structure
    entity_dir = BASE_DIR / 'entities' / slug
    _create_entity_structure(entity_dir, name, slug, currency, journal_file, bank_account)

    # Update global.yaml
    entities.append({
        'name': name,
        'slug': slug,
        'currency': currency,
        'journal_file': journal_file,
    })
    config['entities'] = entities
    save_global_config(config)
    _write_prompt_cache(config['active'])

    print(f"\n  Entity '{name}' created at entities/{slug}/")
    print(f"  Switch to it with: pair switch {slug}")


def cmd_use(args):
    """Change active entity in global.yaml."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        sys.exit(1)

    if not args:
        print("Usage: pair entity use <slug>")
        print("       pair switch <slug>")
        sys.exit(1)

    slug = args[0]
    entities = config.get('entities', [])

    # Validate that slug exists
    found = None
    for e in entities:
        if e['slug'] == slug:
            found = e
            break

    if not found:
        print(f"No entity with slug '{slug}'.")
        print("Available entities:")
        for e in entities:
            print(f"  {e['slug']} — {e['name']}")
        sys.exit(1)

    config['active'] = slug
    save_global_config(config)
    _write_prompt_cache(slug)
    print(f"Switched to: {found['name']} ({slug})")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _create_entity_structure(entity_dir, name, slug, currency, journal_file, bank_account):
    """Create full directory structure and config for an entity."""
    # Create directories
    for d in ENTITY_DIRS:
        ensure_dir(entity_dir / d)

    # Create config.yaml
    config = {
        'pair': {
            'name': name,
            'slug': slug,
            'currency': currency,
        },
        'journal_file': journal_file,
        'accounts': {
            'bank': bank_account,
            'receivable': 'Assets:Current:Accounts Receivable',
            'payable': 'Liabilities:Current:Accounts Payable',
        },
        'divisions': [],
        'defaults': {
            'fiscal_year_start': 1,
        }
    }
    config_path = entity_dir / 'config.yaml'
    ensure_dir(config_path.parent)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  Created entities/{slug}/config.yaml")

    # Create accounts.journal
    accounts_path = entity_dir / 'include' / 'accounts.journal'
    accounts_content = _default_accounts(bank_account, currency)
    write_journal_atomic(accounts_path, accounts_content)
    print(f"  Created entities/{slug}/include/accounts.journal")

    # Create company.journal (aggregator — keeps filename for hledger compat)
    company_journal_path = entity_dir / 'include' / 'company.journal'
    aggregator_content = f"""; {name} — master include file
; Generated by: pair entity add

include accounts.journal
"""
    write_journal_atomic(company_journal_path, aggregator_content)
    print(f"  Created entities/{slug}/include/company.journal")

    # Create or update the main journal file
    journal_path = expand_path(journal_file)
    include_line = f"include {entity_dir}/include/company.journal\n"

    if not journal_path.exists():
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, 'w') as f:
            f.write(f"; {name} — main ledger\n")
            f.write(f"; Created by: pair entity add\n\n")
            f.write(include_line)
        print(f"\n  Created {journal_file} with include line.")
    else:
        content = journal_path.read_text()
        if str(entity_dir / 'include' / 'company.journal') not in content:
            print(f"\n  Add this line to {journal_file}:")
            print(f"    {include_line.strip()}")
        else:
            print(f"  {journal_file} already includes this entity.")


def _default_accounts(bank_account, currency):
    """Generate default accounts.journal content."""
    return f"""; pair account declarations
; Generated by: pair

; Assets — Current
account Assets:Current:Chequing                              ; type:A
account Assets:Current:Savings                               ; type:A
account Assets:Current:Petty Cash                            ; type:A
account Assets:Current:Accounts Receivable                   ; type:A
account Assets:Current:Prepaid Expenses                      ; type:A

; Assets — Fixed
account Assets:Fixed:Equipment                               ; type:A
account Assets:Fixed:Vehicles                                ; type:A
account Assets:Fixed:Furniture                               ; type:A
account Assets:Fixed:Leasehold Improvements                  ; type:A
account Assets:Fixed:Intellectual Property                   ; type:A

; Assets — Accumulated Amortization (contra)
account Assets:Accumulated Amortization:Equipment            ; type:A
account Assets:Accumulated Amortization:Vehicles             ; type:A
account Assets:Accumulated Amortization:Furniture            ; type:A
account Assets:Accumulated Amortization:Leasehold Improvements ; type:A
account Assets:Accumulated Amortization:Intellectual Property ; type:A

; Liabilities — Current
account Liabilities:Current:Accounts Payable                 ; type:L
account Liabilities:Current:Credit Card                      ; type:L
account Liabilities:Current:HST Payable                      ; type:L
account Liabilities:Current:Payroll Payable                  ; type:L
account Liabilities:Current:Income Tax Payable               ; type:L
account Liabilities:Current:Unearned Revenue                 ; type:L

; Liabilities — Long-Term
account Liabilities:Long-Term:Bank Loan                      ; type:L
account Liabilities:Long-Term:Vehicle Loan                   ; type:L
account Liabilities:Long-Term:Shareholder Loan               ; type:L

; Equity
account Equity:Owner Investment                              ; type:E
account Equity:Owner Draws                                   ; type:E
account Equity:Retained Earnings                             ; type:E

; Income — Operating
account Income:Operating:Consulting                          ; type:R
account Income:Operating:Services                            ; type:R
account Income:Operating:Product Sales                       ; type:R
account Income:Operating:Recurring Revenue                   ; type:R

; Income — Non-Operating
account Income:Non-Operating:Interest Income                 ; type:R
account Income:Non-Operating:Gain on Disposal                ; type:R
account Income:Non-Operating:Foreign Exchange Gain           ; type:R
account Income:Non-Operating:Other Income                    ; type:R

; Expenses — Operating
account Expenses:Operating:Payroll:Salaries                  ; type:X
account Expenses:Operating:Payroll:Benefits                  ; type:X
account Expenses:Operating:Payroll:Employer Contributions    ; type:X
account Expenses:Operating:Rent                              ; type:X
account Expenses:Operating:Utilities                         ; type:X
account Expenses:Operating:Insurance                         ; type:X
account Expenses:Operating:Office Supplies                   ; type:X
account Expenses:Operating:Software Subscriptions            ; type:X
account Expenses:Operating:Professional Fees                 ; type:X
account Expenses:Operating:Travel                            ; type:X
account Expenses:Operating:Meals and Entertainment           ; type:X
account Expenses:Operating:Marketing                         ; type:X
account Expenses:Operating:Telecommunications               ; type:X
account Expenses:Operating:Bank Fees                         ; type:X
account Expenses:Operating:Repairs and Maintenance           ; type:X

; Expenses — Non-Operating
account Expenses:Non-Operating:Amortization                  ; type:X
account Expenses:Non-Operating:Interest Expense              ; type:X
account Expenses:Non-Operating:Loss on Disposal              ; type:X
account Expenses:Non-Operating:Foreign Exchange Loss         ; type:X
account Expenses:Non-Operating:Income Tax Expense            ; type:X
"""


def print_help():
    print("""pair entity — manage entities (Company/Project)

Usage:
  pair entity               Show active entity
  pair entity show          Show active entity
  pair entity list          List all entities
  pair entity add           Add a new entity
  pair entity use <slug>    Switch active entity
  pair switch <slug>        Switch active entity (shortcut)
""")


def _write_prompt_cache(slug):
    """Write active entity to ~/.pair_prompt for shell PS1 integration."""
    prompt_file = Path.home() / '.pair_prompt'
    try:
        prompt_file.write_text(f"[{slug}] ")
    except OSError:
        pass  # non-critical
