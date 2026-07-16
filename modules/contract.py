"""pair contract — agreement and contract management."""

import sys
from datetime import date, datetime

from lib.helpers import (
    load_config, prompt, prompt_choice, confirm,
    validate_slug, validate_date, validate_positive_number,
    parse_global_flags
)
from lib.yaml_store import (
    load_entity, save_entity, list_entities, entity_exists
)


MODULE = "contracts"

TYPES = ['service', 'lease', 'employment', 'subscription']
STATUSES = ['active', 'expired', 'terminated', 'pending']
SCHEDULES = ['monthly', 'quarterly', 'annual', 'one-time']
RENEWAL_TYPES = ['auto', 'manual', 'none']


def dispatch(args):
    """Route contract subcommands."""
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
    else:
        print(f"Unknown contract action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair contract — agreement and contract management

Actions:
  add                 Add a new contract
  list                List contracts
  show <slug>         Show contract details
  edit <slug>         Edit a contract

Flags:
  --status STATUS     Filter by status (list)
  --expiring DAYS     Show contracts expiring within N days (list)
  --type TYPE         Filter by type (list)

Types: service, lease, employment, subscription
Statuses: active, expired, terminated, pending
""")


# ─── pair contract add ────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Add a new contract."""
    print("Add a contract\n")

    name = prompt("Contract name")

    from lib.helpers import slugify
    default_slug = slugify(name)
    slug = prompt("Slug (identifier)", default=default_slug, validator=validate_slug)

    if entity_exists(MODULE, slug):
        print(f"  Contract '{slug}' already exists.")
        sys.exit(1)

    contract_type = prompt_choice("Type", TYPES)
    start_date = prompt("Start date", default=date.today().strftime("%Y-%m-%d"),
                        validator=validate_date)
    end_date = prompt("End date (optional, blank for open-ended)", required=False,
                      validator=lambda v: validate_date(v) if v else None)
    status = prompt_choice("Status", STATUSES, default='active')
    value = prompt("Total value (optional)", required=False,
                   validator=lambda v: validate_positive_number(v) if v else None)
    payment_schedule = prompt_choice("Payment schedule", SCHEDULES, default='monthly')
    payment_terms = prompt("Payment terms (optional, e.g. 'Net 30 days')", required=False)

    # Parties
    print("\nParties (enter contact slugs):")
    parties = []
    while True:
        contact_slug = prompt("  Contact slug (blank to finish)", required=False)
        if not contact_slug:
            break
        role = prompt(f"  Role of {contact_slug}")
        parties.append({'contact': contact_slug, 'role': role})

    # Renewal
    renewal = None
    if confirm("Add renewal terms?", default_yes=False):
        renewal_type = prompt_choice("Renewal type", RENEWAL_TYPES, default='auto')
        notice_days = prompt("Notice days before expiry", default="30")
        renewal = {
            'type': renewal_type,
            'notice_days': int(notice_days),
        }

    # Linked entities
    linked_assets = []
    linked_liabilities = []
    if confirm("Link to assets/liabilities?", default_yes=False):
        asset_slugs = prompt("  Asset slugs (comma-separated, or blank)", required=False)
        if asset_slugs:
            linked_assets = [s.strip() for s in asset_slugs.split(',')]
        liab_slugs = prompt("  Liability slugs (comma-separated, or blank)", required=False)
        if liab_slugs:
            linked_liabilities = [s.strip() for s in liab_slugs.split(',')]

    notes = prompt("Notes (optional)", required=False)

    # Build contract data
    contract_data = {
        'name': name,
        'slug': slug,
        'type': contract_type,
        'start_date': start_date,
        'status': status,
        'payment_schedule': payment_schedule,
    }

    if end_date:
        contract_data['end_date'] = end_date
    if value:
        contract_data['value'] = float(value)
    if payment_terms:
        contract_data['payment_terms'] = payment_terms
    if parties:
        contract_data['parties'] = parties
    if renewal:
        contract_data['renewal'] = renewal
    if linked_assets:
        contract_data['linked_assets'] = linked_assets
    if linked_liabilities:
        contract_data['linked_liabilities'] = linked_liabilities
    if notes:
        contract_data['notes'] = notes

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    contract_data['currency'] = currency

    save_entity(MODULE, slug, contract_data)
    print(f"\n  Saved: contracts/{slug}.yaml")


# ─── pair contract list ───────────────────────────────────────────────────

def cmd_list(flags, args):
    """List contracts."""
    status_filter = None
    type_filter = None
    expiring_days = None

    for i, a in enumerate(args):
        if a == '--status' and i + 1 < len(args):
            status_filter = args[i + 1]
        elif a == '--type' and i + 1 < len(args):
            type_filter = args[i + 1]
        elif a == '--expiring' and i + 1 < len(args):
            expiring_days = int(args[i + 1])

    slugs = list_entities(MODULE)
    if not slugs:
        print("No contracts recorded. Use 'pair contract add' to start.")
        return

    print(f"\n{'Name':<30} {'Type':<14} {'Status':<12} {'End Date':<12} {'Value':>12}")
    print("─" * 84)

    today = date.today()
    count = 0

    for slug in slugs:
        contract = load_entity(MODULE, slug)
        if not contract:
            continue

        if status_filter and contract.get('status') != status_filter:
            continue
        if type_filter and contract.get('type') != type_filter:
            continue

        # Expiring filter
        if expiring_days is not None:
            end_str = contract.get('end_date')
            if not end_str:
                continue
            end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
            days_until = (end_dt - today).days
            if days_until < 0 or days_until > expiring_days:
                continue

        count += 1
        end_date = contract.get('end_date', 'open')
        value_str = ""
        if contract.get('value'):
            currency = contract.get('currency', 'CAD')
            value_str = f"{currency} {contract['value']:,.2f}"

        # Mark expiring soon
        marker = ""
        if contract.get('end_date') and contract.get('status') == 'active':
            end_dt = datetime.strptime(contract['end_date'], "%Y-%m-%d").date()
            days_until = (end_dt - today).days
            if 0 <= days_until <= 30:
                marker = " ⚠"
            elif days_until < 0:
                marker = " ✗"

        print(f"{contract['name']:<30} {contract.get('type', ''):<14} "
              f"{contract.get('status', ''):<12} {end_date:<12} {value_str:>12}{marker}")

    print(f"\n  {count} contract(s)")
    print()


# ─── pair contract show ───────────────────────────────────────────────────

def cmd_show(flags, args):
    """Show details for a specific contract."""
    if not args:
        print("Usage: pair contract show <slug>")
        sys.exit(1)

    slug = args[0]
    contract = load_entity(MODULE, slug)
    if not contract:
        print(f"Contract '{slug}' not found.")
        sys.exit(1)

    currency = contract.get('currency', 'CAD')

    print(f"\n  {contract['name']}")
    print(f"  {'─' * 50}")
    print(f"  Slug:             {slug}")
    print(f"  Type:             {contract.get('type', 'N/A')}")
    print(f"  Status:           {contract.get('status', 'N/A')}")
    print(f"  Start date:       {contract.get('start_date', 'N/A')}")
    print(f"  End date:         {contract.get('end_date', 'open-ended')}")
    if contract.get('value'):
        print(f"  Value:            {currency} {contract['value']:,.2f}")
    print(f"  Payment schedule: {contract.get('payment_schedule', 'N/A')}")
    if contract.get('payment_terms'):
        print(f"  Payment terms:    {contract['payment_terms']}")

    # Parties
    parties = contract.get('parties', [])
    if parties:
        print(f"\n  Parties:")
        for party in parties:
            contact = load_entity('contacts', party.get('contact', ''))
            contact_name = contact['name'] if contact else party.get('contact', 'unknown')
            print(f"    {contact_name} ({party.get('role', 'party')})")

    # Renewal
    renewal = contract.get('renewal')
    if renewal:
        print(f"\n  Renewal:")
        print(f"    Type:           {renewal.get('type', 'none')}")
        print(f"    Notice days:    {renewal.get('notice_days', 'N/A')}")

    # Linked entities
    if contract.get('linked_assets'):
        print(f"\n  Linked assets:")
        for asset_slug in contract['linked_assets']:
            asset = load_entity('assets', asset_slug)
            name = asset['name'] if asset else asset_slug
            print(f"    {name}")

    if contract.get('linked_liabilities'):
        print(f"\n  Linked liabilities:")
        for liab_slug in contract['linked_liabilities']:
            liab = load_entity('liabilities', liab_slug)
            name = liab['name'] if liab else liab_slug
            print(f"    {name}")

    if contract.get('notes'):
        print(f"\n  Notes: {contract['notes']}")

    # Days until expiry
    if contract.get('end_date') and contract.get('status') == 'active':
        end_dt = datetime.strptime(contract['end_date'], "%Y-%m-%d").date()
        days_until = (end_dt - date.today()).days
        if days_until > 0:
            print(f"\n  Expires in {days_until} days")
        elif days_until == 0:
            print(f"\n  ⚠ Expires today")
        else:
            print(f"\n  ✗ Expired {-days_until} days ago")

    print()


# ─── pair contract edit ───────────────────────────────────────────────────

def cmd_edit(flags, args):
    """Edit a contract interactively."""
    if not args:
        print("Usage: pair contract edit <slug>")
        sys.exit(1)

    slug = args[0]
    contract = load_entity(MODULE, slug)
    if not contract:
        print(f"Contract '{slug}' not found.")
        sys.exit(1)

    print(f"\nEditing: {contract['name']} ({slug})")
    print("Press enter to keep current value.\n")

    contract['name'] = prompt("Name", default=contract['name'])
    contract['type'] = prompt_choice("Type", TYPES, default=contract.get('type'))
    contract['status'] = prompt_choice("Status", STATUSES, default=contract.get('status'))
    new_end = prompt("End date", default=contract.get('end_date', ''), required=False,
                     validator=lambda v: validate_date(v) if v else None)
    if new_end:
        contract['end_date'] = new_end
    new_value = prompt("Value", default=str(contract.get('value', '')), required=False)
    if new_value:
        contract['value'] = float(new_value)
    contract['payment_schedule'] = prompt_choice("Payment schedule", SCHEDULES,
                                                  default=contract.get('payment_schedule', 'monthly'))

    save_entity(MODULE, slug, contract)
    print(f"\n  Updated: contracts/{slug}.yaml")
