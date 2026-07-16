"""pair contact — client, vendor, employee, and lender management."""

import sys

from lib.helpers import (
    load_config, prompt, prompt_choice, confirm,
    validate_slug, parse_global_flags
)
from lib.yaml_store import (
    load_entity, save_entity, list_entities, entity_exists, delete_entity
)


MODULE = "contacts"

ROLES = ['client', 'vendor', 'employee', 'lender', 'entity']


def dispatch(args):
    """Route contact subcommands."""
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
    elif action == 'edit':
        cmd_edit(flags, action_args)
    elif action == 'remove':
        cmd_remove(flags, action_args)
    else:
        print(f"Unknown contact action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair contact — contact management

Actions:
  add                 Add a new contact
  list                List all contacts
  show <slug>         Show contact details
  edit <slug>         Edit a contact
  remove <slug>       Remove a contact

Flags:
  --role ROLE         Filter by role (list)

Roles: client, vendor, employee, lender, entity
""")


# ─── pair contact add ─────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Add a new contact."""
    print("Add a contact\n")

    name = prompt("Name")

    from lib.helpers import slugify
    default_slug = slugify(name)
    slug = prompt("Slug (identifier)", default=default_slug, validator=validate_slug)

    if entity_exists(MODULE, slug):
        print(f"  Contact '{slug}' already exists.")
        sys.exit(1)

    role = prompt_choice("Role", ROLES)
    company = prompt("Company/organization (optional)", required=False)
    email = prompt("Email (optional)", required=False)
    phone = prompt("Phone (optional)", required=False)

    address = None
    if confirm("Add address?", default_yes=False):
        print("  Enter address (blank line to finish):")
        lines = []
        while True:
            line = input("  ")
            if not line:
                break
            lines.append(line)
        if lines:
            address = "\n".join(lines)

    payment_terms = prompt("Payment terms (optional, e.g. 'Net 30 days')", required=False)
    notes = prompt("Notes (optional)", required=False)

    # Build contact data
    contact_data = {
        'name': name,
        'slug': slug,
        'role': role,
    }

    if company:
        contact_data['pair'] = company
    if email:
        contact_data['email'] = email
    if phone:
        contact_data['phone'] = phone
    if address:
        contact_data['address'] = address
    if payment_terms:
        contact_data['payment_terms'] = payment_terms
    if notes:
        contact_data['notes'] = notes

    # For entity role, ask for billing details
    if role == 'entity':
        print("\nBilling identity details:")
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        bn = prompt("Business number (optional)", required=False)
        tax = prompt("Default tax %", default="13")
        prefix = prompt("Invoice prefix (optional, e.g. 'CLR-')", required=False)

        contact_data['billing'] = {
            'business_number': bn or None,
            'currency': currency,
            'tax': float(tax),
            'invoice_prefix': prefix or "",
            'next_invoice': f"{__import__('datetime').date.today().year}-001",
            'template': None,
            'accounts': {
                'receivable': 'Assets:Current:Accounts Receivable',
                'income': 'Income:Operating:Consulting',
                'tax_liability': 'Liabilities:Current:HST Payable',
                'bank': config.get('accounts', {}).get('bank', 'Assets:Current:Chequing'),
            },
        }

    save_entity(MODULE, slug, contact_data)
    print(f"\n  Saved: contacts/{slug}.yaml")


# ─── pair contact list ────────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all contacts."""
    role_filter = None
    for i, a in enumerate(args):
        if a == '--role' and i + 1 < len(args):
            role_filter = args[i + 1]

    slugs = list_entities(MODULE)
    if not slugs:
        print("No contacts recorded. Use 'pair contact add' to start.")
        return

    print(f"\n{'Name':<30} {'Role':<10} {'Company':<20} {'Email':<25}")
    print("─" * 88)

    count = 0
    for slug in slugs:
        contact = load_entity(MODULE, slug)
        if not contact:
            continue
        if role_filter and contact.get('role') != role_filter:
            continue

        count += 1
        print(f"{contact['name']:<30} {contact.get('role', ''):<10} "
              f"{contact.get('pair', ''):<20} {contact.get('email', ''):<25}")

    print(f"\n  {count} contact(s)")
    print()


# ─── pair contact show ────────────────────────────────────────────────────

def cmd_show(flags, args):
    """Show details for a specific contact."""
    if not args:
        print("Usage: pair contact show <slug>")
        sys.exit(1)

    slug = args[0]
    contact = load_entity(MODULE, slug)
    if not contact:
        print(f"Contact '{slug}' not found.")
        sys.exit(1)

    print(f"\n  {contact['name']}")
    print(f"  {'─' * 50}")
    print(f"  Slug:           {slug}")
    print(f"  Role:           {contact.get('role', 'N/A')}")
    if contact.get('pair'):
        print(f"  Company:        {contact['pair']}")
    if contact.get('email'):
        print(f"  Email:          {contact['email']}")
    if contact.get('phone'):
        print(f"  Phone:          {contact['phone']}")
    if contact.get('address'):
        print(f"  Address:")
        for line in contact['address'].split('\n'):
            print(f"                  {line}")
    if contact.get('payment_terms'):
        print(f"  Payment terms:  {contact['payment_terms']}")
    if contact.get('notes'):
        print(f"  Notes:          {contact['notes']}")

    # Billing identity details
    billing = contact.get('billing')
    if billing:
        print(f"\n  Billing Identity:")
        if billing.get('business_number'):
            print(f"    Business #:     {billing['business_number']}")
        print(f"    Currency:       {billing.get('currency', 'CAD')}")
        print(f"    Tax rate:       {billing.get('tax', 0)}%")
        print(f"    Invoice prefix: {billing.get('invoice_prefix', '')}")
        print(f"    Next invoice:   {billing.get('next_invoice', 'N/A')}")
        accounts = billing.get('accounts', {})
        if accounts:
            print(f"    Accounts:")
            for k, v in accounts.items():
                print(f"      {k}: {v}")

    # Show references from other modules
    _show_references(slug)
    print()


def _show_references(slug):
    """Show where this contact is referenced by other entities."""
    refs = []

    # Check assets
    for asset_slug in list_entities('assets'):
        asset = load_entity('assets', asset_slug)
        if asset and asset.get('vendor') == slug:
            refs.append(f"  asset: {asset['name']} (vendor)")

    # Check liabilities
    for liab_slug in list_entities('liabilities'):
        liab = load_entity('liabilities', liab_slug)
        if liab and liab.get('lender') == slug:
            refs.append(f"  liability: {liab['name']} (lender)")

    # Check contracts
    for contract_slug in list_entities('contracts'):
        contract = load_entity('contracts', contract_slug)
        if contract:
            for party in contract.get('parties', []):
                if party.get('contact') == slug:
                    refs.append(f"  contract: {contract['name']} ({party.get('role', 'party')})")

    if refs:
        print(f"\n  Referenced by:")
        for ref in refs:
            print(f"    {ref}")


# ─── pair contact edit ────────────────────────────────────────────────────

def cmd_edit(flags, args):
    """Edit a contact interactively."""
    if not args:
        print("Usage: pair contact edit <slug>")
        sys.exit(1)

    slug = args[0]
    contact = load_entity(MODULE, slug)
    if not contact:
        print(f"Contact '{slug}' not found.")
        sys.exit(1)

    print(f"\nEditing: {contact['name']} ({slug})")
    print("Press enter to keep current value.\n")

    contact['name'] = prompt("Name", default=contact['name'])
    contact['role'] = prompt_choice("Role", ROLES, default=contact.get('role'))
    contact['pair'] = prompt("Company", default=contact.get('pair', ''),
                                required=False) or None
    contact['email'] = prompt("Email", default=contact.get('email', ''),
                              required=False) or None
    contact['phone'] = prompt("Phone", default=contact.get('phone', ''),
                              required=False) or None
    new_terms = prompt("Payment terms", default=contact.get('payment_terms', ''),
                       required=False)
    if new_terms:
        contact['payment_terms'] = new_terms
    new_notes = prompt("Notes", default=contact.get('notes', ''), required=False)
    if new_notes:
        contact['notes'] = new_notes

    # Clean up None values
    contact = {k: v for k, v in contact.items() if v is not None}

    save_entity(MODULE, slug, contact)
    print(f"\n  Updated: contacts/{slug}.yaml")


# ─── pair contact remove ──────────────────────────────────────────────────

def cmd_remove(flags, args):
    """Remove a contact."""
    if not args:
        print("Usage: pair contact remove <slug>")
        sys.exit(1)

    slug = args[0]
    contact = load_entity(MODULE, slug)
    if not contact:
        print(f"Contact '{slug}' not found.")
        sys.exit(1)

    # Check for references
    _show_references(slug)

    if not flags.get('yes'):
        if not confirm(f"\n  Remove contact '{contact['name']}'?", default_yes=False):
            print("  Cancelled.")
            return

    delete_entity(MODULE, slug)
    print(f"  Removed: contacts/{slug}.yaml")
