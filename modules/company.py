"""pair company — multi-company management."""

import sys
import yaml
from pathlib import Path

from lib.helpers import (
    BASE_DIR, GLOBAL_CONFIG_FILE,
    load_global_config, save_global_config, get_active_company,
    prompt, validate_slug, ensure_dir, expand_path, slugify, save_config
)
from lib.journal import write_journal_atomic


# ─── Directory structure for a company ───────────────────────────────────────

COMPANY_DIRS = [
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
        print(f"Unknown company subcommand: {args[0]}")
        print("Usage: pair company [show|list|add|use <slug>]")
        sys.exit(1)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_show():
    """Display active company name and slug."""
    config = load_global_config()
    if not config:
        print("No companies configured. Run 'pair init' first.")
        return

    active = config.get('active')
    companies = config.get('companies', [])

    if not active or not companies:
        print("No active company. Run 'pair init' first.")
        return

    # Find the active company details
    for c in companies:
        if c['slug'] == active:
            print(f"Active company: {c['name']} ({c['slug']})")
            return

    print(f"Active company slug: {active} (details not found)")


def cmd_list():
    """Show all companies from global.yaml with active marker."""
    config = load_global_config()
    if not config:
        print("No companies configured. Run 'pair init' first.")
        return

    active = config.get('active')
    companies = config.get('companies', [])

    if not companies:
        print("No companies configured. Run 'pair init' first.")
        return

    print("Companies:\n")
    for c in companies:
        marker = " *" if c['slug'] == active else "  "
        print(f"  {marker} {c['name']} ({c['slug']})")

    print(f"\n  * = active")


def cmd_add():
    """Create a new company interactively."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        return

    print("pair company add — add a new company\n")

    name = prompt("Company name")
    default_slug = slugify(name)
    slug = prompt("Slug (short identifier)", default=default_slug, validator=validate_slug)

    # Check for duplicate slug
    companies = config.get('companies', [])
    for c in companies:
        if c['slug'] == slug:
            print(f"\n  Error: Company with slug '{slug}' already exists.")
            sys.exit(1)

    currency = prompt("Default currency", default="CAD")
    journal_file = prompt("Main hledger journal file", default="~/.hledger.journal")
    bank_name = prompt("Primary bank account name", default="Chequing")
    bank_account = f"Assets:Current:{bank_name}"

    # Create the company directory structure
    company_dir = BASE_DIR / 'companies' / slug
    _create_company_structure(company_dir, name, slug, currency, journal_file, bank_account)

    # Update global.yaml
    companies.append({
        'name': name,
        'slug': slug,
        'currency': currency,
        'journal_file': journal_file,
    })
    config['companies'] = companies
    save_global_config(config)
    _write_prompt_cache(config['active'])

    print(f"\n  Company '{name}' created at companies/{slug}/")
    print(f"  Switch to it with: pair switch {slug}")


def cmd_use(args):
    """Change active company in global.yaml."""
    config = load_global_config()
    if not config:
        print("No global.yaml found. Run 'pair init' first.")
        sys.exit(1)

    if not args:
        print("Usage: pair company use <slug>")
        print("       pair switch <slug>")
        sys.exit(1)

    slug = args[0]
    companies = config.get('companies', [])

    # Validate that slug exists
    found = None
    for c in companies:
        if c['slug'] == slug:
            found = c
            break

    if not found:
        print(f"No company with slug '{slug}'.")
        print("Available companies:")
        for c in companies:
            print(f"  {c['slug']} — {c['name']}")
        sys.exit(1)

    config['active'] = slug
    save_global_config(config)
    _write_prompt_cache(slug)
    print(f"Switched to: {found['name']} ({slug})")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _create_company_structure(company_dir, name, slug, currency, journal_file, bank_account):
    """Create full directory structure and config for a company."""
    # Create directories
    for d in COMPANY_DIRS:
        ensure_dir(company_dir / d)

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
    config_path = company_dir / 'config.yaml'
    ensure_dir(config_path.parent)
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  Created companies/{slug}/config.yaml")

    # Create accounts.journal
    accounts_path = company_dir / 'include' / 'accounts.journal'
    accounts_content = _default_accounts(bank_account, currency)
    write_journal_atomic(accounts_path, accounts_content)
    print(f"  Created companies/{slug}/include/accounts.journal")

    # Create company.journal (aggregator)
    company_journal_path = company_dir / 'include' / 'company.journal'
    aggregator_content = f"""; {name} — master include file
; Generated by: pair company add

include accounts.journal
"""
    write_journal_atomic(company_journal_path, aggregator_content)
    print(f"  Created companies/{slug}/include/company.journal")

    # Create or update the main journal file
    journal_path = expand_path(journal_file)
    include_line = f"include {company_dir}/include/company.journal\n"

    if not journal_path.exists():
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, 'w') as f:
            f.write(f"; {name} — main ledger\n")
            f.write(f"; Created by: pair company add\n\n")
            f.write(include_line)
        print(f"  Created {journal_file} with include line.")
    else:
        content = journal_path.read_text()
        if str(company_dir / 'include' / 'company.journal') not in content:
            print(f"\n  Add this line to {journal_file}:")
            print(f"    {include_line.strip()}")
        else:
            print(f"  {journal_file} already includes this company.")


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
    print("""pair company — manage companies

Usage:
  pair company              Show active company
  pair company show         Show active company
  pair company list         List all companies
  pair company add          Add a new company
  pair company use <slug>   Switch active company
  pair switch <slug>        Switch active company (shortcut)
""")


def _write_prompt_cache(slug):
    """Write active company to ~/.pair_prompt for shell PS1 integration."""
    prompt_file = Path.home() / '.pair_prompt'
    try:
        prompt_file.write_text(f"[{slug}] ")
    except OSError:
        pass  # non-critical
