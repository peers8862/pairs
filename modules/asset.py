"""pair asset — capital asset management with amortization."""

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


MODULE = "assets"

CATEGORIES = ['equipment', 'vehicle', 'furniture', 'software', 'other']
METHODS = ['straight-line', 'declining-balance']

# Default account mappings by category
DEFAULT_ACCOUNTS = {
    'equipment': {
        'asset': 'Assets:Fixed:Equipment',
        'amortization_expense': 'Expenses:Non-Operating:Amortization',
        'accumulated': 'Assets:Accumulated Amortization:Equipment',
    },
    'vehicle': {
        'asset': 'Assets:Fixed:Vehicles',
        'amortization_expense': 'Expenses:Non-Operating:Amortization',
        'accumulated': 'Assets:Accumulated Amortization:Vehicles',
    },
    'furniture': {
        'asset': 'Assets:Fixed:Furniture',
        'amortization_expense': 'Expenses:Non-Operating:Amortization',
        'accumulated': 'Assets:Accumulated Amortization:Furniture',
    },
    'software': {
        'asset': 'Assets:Fixed:Intellectual Property',
        'amortization_expense': 'Expenses:Non-Operating:Amortization',
        'accumulated': 'Assets:Accumulated Amortization:Intellectual Property',
    },
    'other': {
        'asset': 'Assets:Fixed:Other',
        'amortization_expense': 'Expenses:Non-Operating:Amortization',
        'accumulated': 'Assets:Accumulated Amortization:Other',
    },
}


def dispatch(args):
    """Route asset subcommands."""
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
    elif action == 'dispose':
        cmd_dispose(flags, action_args)
    elif action == 'amort':
        cmd_amort(flags, action_args)
    elif action == 'summary':
        cmd_summary(flags, action_args)
    elif action == 'writedown':
        cmd_writedown(flags, action_args)
    else:
        print(f"Unknown asset action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair asset — capital asset management

Actions:
  add                 Record a new capital asset
  list                List all assets
  summary             Aggregate view by category
  show <slug>         Show asset details and amortization status
  edit <slug>         Edit asset fields
  dispose <slug>      Record disposal (sale or scrap)
  amort               Generate amortization journal entries
  writedown <slug>    Record an impairment writedown

Flags for 'list':
  --all               Include disposed assets
  --category <cat>    Filter by category
  --division <div>    Filter by division
  --sort <field>      Sort by: name, cost, nbv, date (default: name)
  --detail            Show expanded columns (salvage, life, remaining)
  --format csv        Output as CSV

Flags for 'show':
  --schedule          Show full amortization schedule table

Flags for 'amort':
  --asset <slug>      Generate for specific asset
  --through <date>    Generate entries through date
""")


# ─── pair asset add ───────────────────────────────────────────────────────

def cmd_add(flags, args):
    """Add a new capital asset."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')

    print("Record a capital asset\n")

    name = prompt("Asset name")
    
    from lib.helpers import slugify
    default_slug = slugify(name)
    slug = prompt("Slug (identifier)", default=default_slug, validator=validate_slug)

    if entity_exists(MODULE, slug):
        print(f"  Asset '{slug}' already exists.")
        sys.exit(1)

    category = prompt_choice("Category", CATEGORIES)

    # Division prompt (if divisions configured)
    divisions = config.get('divisions', [])
    division = None
    if divisions:
        default_div = divisions[0]
        division = prompt(f"Division", default=default_div, required=False)
        if not division:
            division = default_div

    purchase_date = prompt("Purchase date", default=date.today().strftime("%Y-%m-%d"),
                           validator=validate_date)
    cost = prompt("Cost", validator=validate_positive_number)
    useful_life = prompt("Useful life (months)", validator=validate_positive_int)
    method = prompt_choice("Amortization method", METHODS)

    salvage = prompt("Salvage value", default="0", required=False,
                     validator=validate_non_negative_number)

    declining_rate = None
    if method == 'declining-balance':
        while True:
            declining_rate = prompt("Declining balance rate (e.g. 0.40 for 40%)",
                                    validator=validate_positive_number)
            val = float(declining_rate)
            if val > 100:
                print("  Rate cannot exceed 100%. Enter as a decimal (e.g. 0.40 for 40%).")
                continue
            if val >= 1:
                converted = val / 100
                # Adaptive display
                short = f"{converted:g}"
                print(f"  That looks like a percentage. Did you mean {converted:.2f} / {short}?")
                if confirm("  Use the converted value?", default_yes=True):
                    declining_rate = str(converted)
            break

    payment_method = prompt_choice("Payment method", ['cash', 'financed'], default='cash')
    linked_liability = None
    if payment_method == 'financed':
        linked_liability = prompt("Linked liability slug", required=False)

    # Build asset data
    accounts = DEFAULT_ACCOUNTS.get(category, DEFAULT_ACCOUNTS['other'])
    asset_data = {
        'name': name,
        'slug': slug,
        'category': category,
        'purchase_date': purchase_date,
        'cost': float(cost),
        'useful_life_months': int(useful_life),
        'amortization_method': method,
        'salvage_value': float(salvage or '0'),
        'currency': currency,
        'accounts': accounts.copy(),
    }

    if division:
        asset_data['division'] = division
    if declining_rate:
        asset_data['declining_balance_rate'] = float(declining_rate)
    if payment_method == 'financed' and linked_liability:
        asset_data['payment_method'] = 'financed'
        asset_data['linked_liability'] = linked_liability
    else:
        asset_data['payment_method'] = 'cash'

    # Save YAML
    save_entity(MODULE, slug, asset_data)
    print(f"\n  Saved: assets/{slug}.yaml")

    # Generate acquisition entry
    year = purchase_date[:4]
    ensure_year_structure(int(year))
    _write_acquisition_entry(asset_data, config)
    print(f"  Acquisition entry written to generated/{year}/assets.journal")

    print(f"\n  Run 'pair asset amort' to generate amortization entries.")


# How an asset came into the business decides what the acquisition entry
# credits, and therefore the pair code. 'cash' and 'financed' are the classic
# purchase paths; 'contributed' is the owner putting property in (equity), and
# 'recognized' books property the business already holds against opening equity.
ACQUISITION_PAIRS = {
    'cash': '1011',          # Assets ↔ Assets
    'financed': '1000',      # Assets ↔ Liabilities
    'contributed': '1001',   # Assets ↔ Equity
    'recognized': '1001',    # Assets ↔ Equity
}
ACQUISITION_DEFAULT_CREDIT = {
    'contributed': 'Equity:Owner Contributions',
    'recognized': 'Equity:Opening Balances',
}


def acquisition_mode(asset):
    """Normalize an asset's acquisition mode.

    `acquisition` is the current field; `payment_method` is what older YAML
    files carry, so both are read and 'cash' is the fallback either way.
    """
    mode = asset.get('acquisition') or asset.get('payment_method') or 'cash'
    return mode if mode in ACQUISITION_PAIRS else 'cash'


def _write_acquisition_entry(asset, config):
    """Write the acquisition journal entry."""
    currency = asset['currency']
    cost = money(asset['cost'])
    date_str = asset['purchase_date']
    year = date_str[:4]
    name = asset['name']
    slug = asset['slug']
    asset_account = asset['accounts']['asset']

    mode = acquisition_mode(asset)
    pair = ACQUISITION_PAIRS[mode]
    tags = {
        'pair': pair,
        'source': f'assets/{slug}.yaml',
        'category': asset['category'],
        'acquisition': mode,
    }

    # An explicit credit account always wins — it is what the user picked.
    credit_account = (asset.get('accounts', {}).get('credit') or '').strip()

    if mode == 'financed':
        if asset.get('linked_liability'):
            tags['liability'] = asset['linked_liability']
            if not credit_account:
                from lib.yaml_store import load_entity as load_liab
                liab = load_liab('liabilities', asset['linked_liability'])
                credit_account = (liab or {}).get('accounts', {}).get('liability', '')
        if not credit_account:
            credit_account = 'Liabilities:Long-Term:Loan'
    elif not credit_account:
        credit_account = ACQUISITION_DEFAULT_CREDIT.get(
            mode, config.get('accounts', {}).get('bank', 'Assets:Current:Chequing'))

    postings = [
        (asset_account, currency, float(cost)),
        (credit_account, currency, float(-cost)),
    ]

    entry = format_entry(date_str, f"Acquire asset: {name}", postings, tags)

    # Append to assets journal for that year
    journal_path = get_generated_dir() / year / "assets.journal"
    from lib.journal import append_journal
    append_journal(journal_path, entry)


# ─── pair asset list ──────────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all assets."""
    show_all = '--all' in args
    show_detail = '--detail' in args
    csv_format = '--format' in args and 'csv' in args
    category_filter = None
    division_filter = None
    sort_field = 'name'

    for i, a in enumerate(args):
        if a == '--category' and i + 1 < len(args):
            category_filter = args[i + 1]
        elif a == '--division' and i + 1 < len(args):
            division_filter = args[i + 1]
        elif a == '--sort' and i + 1 < len(args):
            sort_field = args[i + 1]

    slugs = list_entities(MODULE)
    if not slugs:
        print("No assets recorded. Use 'pair asset add' to start.")
        return

    # Collect asset data
    assets = []
    for slug in slugs:
        asset = load_entity(MODULE, slug)
        if not asset:
            continue

        disposed = asset.get('disposal', {}).get('date') is not None
        if disposed and not show_all:
            continue
        if category_filter and asset.get('category') != category_filter:
            continue
        if division_filter and asset.get('division') != division_filter:
            continue

        cost = money(asset['cost'])
        salvage = money(asset.get('salvage_value', 0))
        nbv = _calculate_nbv(asset)
        remaining = _remaining_months(asset)
        accum = cost - nbv

        assets.append({
            'name': asset['name'],
            'slug': slug,
            'category': asset.get('category', 'other'),
            'cost': cost,
            'salvage': salvage,
            'nbv': nbv,
            'accum': accum,
            'life': asset['useful_life_months'],
            'remaining': remaining,
            'date': asset['purchase_date'],
            'currency': asset.get('currency', 'CAD'),
            'status': 'disposed' if disposed else 'active',
        })

    if not assets:
        print("No assets match the filter.")
        return

    # Sort
    sort_keys = {
        'name': lambda a: a['name'].lower(),
        'cost': lambda a: -a['cost'],
        'nbv': lambda a: -a['nbv'],
        'date': lambda a: a['date'],
    }
    assets.sort(key=sort_keys.get(sort_field, sort_keys['name']))

    # CSV output
    if csv_format:
        _print_csv(assets, show_detail)
        return

    # Table output
    if show_detail:
        _print_detail_table(assets)
    else:
        _print_simple_table(assets)


def _print_simple_table(assets):
    """Standard asset list table."""
    print(f"\n{'Name':<30} {'Category':<12} {'Cost':>12} {'NBV':>12} {'Status':<10}")
    print("─" * 80)

    for a in assets:
        print(f"{a['name']:<30} {a['category']:<12} "
              f"{a['currency']} {a['cost']:>9,.2f} "
              f"{a['currency']} {a['nbv']:>9,.2f} {a['status']:<10}")

    # Totals
    total_cost = sum(a['cost'] for a in assets)
    total_nbv = sum(a['nbv'] for a in assets)
    currency = assets[0]['currency']
    print("─" * 80)
    print(f"{'TOTAL':<30} {len(assets)} assets   "
          f"{currency} {total_cost:>9,.2f} "
          f"{currency} {total_nbv:>9,.2f}")
    print()


def _print_detail_table(assets):
    """Detailed asset list with amortization columns."""
    print(f"\n{'Name':<25} {'Category':<11} {'Cost':>10} {'Salvage':>9} "
          f"{'Life':>5} {'Amort':>10} {'NBV':>10} {'Rem':>5}")
    print("─" * 92)

    for a in assets:
        print(f"{a['name']:<25} {a['category']:<11} "
              f"{a['currency']} {a['cost']:>7,.0f} "
              f"{a['currency']} {a['salvage']:>6,.0f} "
              f"{a['life']:>3}mo "
              f"{a['currency']} {a['accum']:>7,.0f} "
              f"{a['currency']} {a['nbv']:>7,.0f} "
              f"{a['remaining']:>3}mo")

    # Totals
    total_cost = sum(a['cost'] for a in assets)
    total_accum = sum(a['accum'] for a in assets)
    total_nbv = sum(a['nbv'] for a in assets)
    currency = assets[0]['currency']
    print("─" * 92)
    print(f"{'TOTAL':<25} {len(assets)} assets   "
          f"{currency} {total_cost:>7,.0f} "
          f"{'':>13} "
          f"{currency} {total_accum:>7,.0f} "
          f"{currency} {total_nbv:>7,.0f}")
    print()


def _print_csv(assets, detail):
    """CSV output for asset list."""
    if detail:
        print("name,slug,category,cost,salvage,life_months,accumulated,nbv,remaining_months,date,status")
        for a in assets:
            print(f"{a['name']},{a['slug']},{a['category']},{a['cost']:.2f},"
                  f"{a['salvage']:.2f},{a['life']},{a['accum']:.2f},{a['nbv']:.2f},"
                  f"{a['remaining']},{a['date']},{a['status']}")
    else:
        print("name,slug,category,cost,nbv,status")
        for a in assets:
            print(f"{a['name']},{a['slug']},{a['category']},"
                  f"{a['cost']:.2f},{a['nbv']:.2f},{a['status']}")


# ─── pair asset show ──────────────────────────────────────────────────────

def cmd_show(flags, args):
    """Show details for a specific asset."""
    if not args:
        print("Usage: pair asset show <slug>")
        sys.exit(1)

    show_schedule = '--schedule' in args
    slug = args[0] if args[0] != '--schedule' else (args[1] if len(args) > 1 else None)
    if not slug:
        print("Usage: pair asset show <slug> [--schedule]")
        sys.exit(1)

    asset = load_entity(MODULE, slug)
    if not asset:
        print(f"Asset '{slug}' not found.")
        sys.exit(1)

    cost = money(asset['cost'])
    salvage = money(asset.get('salvage_value', 0))
    nbv = _calculate_nbv(asset)
    monthly = _monthly_amount(asset)
    remaining = _remaining_months(asset)

    print(f"\n  {asset['name']}")
    print(f"  {'─' * 50}")
    print(f"  Slug:              {slug}")
    print(f"  Category:          {asset.get('category', 'other')}")
    print(f"  Purchase date:     {asset['purchase_date']}")
    print(f"  Cost:              {asset['currency']} {cost}")
    print(f"  Salvage value:     {asset['currency']} {salvage}")
    print(f"  Useful life:       {asset['useful_life_months']} months")
    print(f"  Method:            {asset['amortization_method']}")
    if asset['amortization_method'] == 'declining-balance':
        print(f"  DB rate:           {asset.get('declining_balance_rate', 'N/A')}")
    print(f"  Monthly amort:     {asset['currency']} {monthly}")
    print(f"  Net book value:    {asset['currency']} {nbv}")
    print(f"  Remaining months:  {remaining}")
    print(f"  Payment method:    {asset.get('payment_method', 'cash')}")

    disposal = asset.get('disposal', {})
    if disposal.get('date'):
        print(f"\n  DISPOSED")
        print(f"  Disposal date:     {disposal['date']}")
        print(f"  Method:            {disposal.get('method', 'N/A')}")
        print(f"  Proceeds:          {asset['currency']} {disposal.get('proceeds', 0)}")

    if show_schedule:
        _print_schedule(asset)

    print()


def _print_schedule(asset):
    """Print full amortization schedule for an asset."""
    currency = asset['currency']
    cost = money(asset['cost'])
    salvage = money(asset.get('salvage_value', 0))
    total_depreciable = cost - salvage
    useful_life = asset['useful_life_months']
    method = asset['amortization_method']

    # Use a far-future date to generate full schedule
    entries = _generate_amort_entries(asset, "2099-12-31")

    if not entries:
        print("\n  No amortization entries (fully amortized or zero depreciable amount).")
        return

    print(f"\n  Amortization Schedule")
    print(f"  {'─' * 60}")
    print(f"  {'Period':<10} {'Amount':>12} {'Accumulated':>14} {'Book Value':>14}")
    print(f"  {'─' * 60}")

    accumulated = Decimal('0')
    for _, entry_text in entries:
        # Parse the entry to extract date and amount
        entry_date = None
        amount = None
        for line in entry_text.split('\n'):
            if line and line[0].isdigit():
                entry_date = line[:7]  # YYYY-MM
            elif asset['accounts']['amortization_expense'] in line:
                parts = line.strip().split()
                try:
                    amount = money(parts[-1])
                except Exception:
                    pass
                break

        if entry_date and amount:
            accumulated += amount
            book_value = cost - accumulated
            print(f"  {entry_date:<10} {currency} {amount:>9,.2f} "
                  f"{currency} {accumulated:>11,.2f} "
                  f"{currency} {book_value:>11,.2f}")

    print(f"  {'─' * 60}")
    print(f"  {'Total':<10} {currency} {accumulated:>9,.2f} "
          f"{'':>17} {currency} {cost - accumulated:>11,.2f}")


# ─── pair asset edit ──────────────────────────────────────────────────────

def cmd_edit(flags, args):
    """Edit asset fields interactively."""
    if not args:
        print("Usage: pair asset edit <slug>")
        sys.exit(1)

    slug = args[0]
    asset = load_entity(MODULE, slug)
    if not asset:
        print(f"Asset '{slug}' not found.")
        sys.exit(1)

    print(f"\nEditing: {asset['name']} ({slug})")
    print("Press enter to keep current value.\n")

    # Safe fields — edit freely
    asset['name'] = prompt("Name", default=asset['name'])
    asset['category'] = prompt_choice("Category", CATEGORIES,
                                       default=asset.get('category'))
    asset['salvage_value'] = float(prompt("Salvage value",
                                          default=str(asset.get('salvage_value', 0)),
                                          validator=validate_non_negative_number))
    asset['useful_life_months'] = int(prompt("Useful life (months)",
                                             default=str(asset['useful_life_months']),
                                             validator=validate_positive_int))

    # Sensitive fields — changing these invalidates historical entries
    print("\n  The following fields affect historical journal entries.")
    print("  Changing them requires regenerating amortization.\n")

    new_cost = prompt(f"Cost", default=str(asset['cost']),
                      validator=validate_positive_number)
    if float(new_cost) != asset['cost']:
        if confirm("  Changing cost will invalidate past amortization entries. Proceed?",
                   default_yes=False):
            asset['cost'] = float(new_cost)
        else:
            print("  Cost unchanged.")

    new_date = prompt("Purchase date", default=asset['purchase_date'],
                      validator=validate_date)
    if new_date != asset['purchase_date']:
        if confirm("  Changing purchase date will shift the entire amortization schedule. Proceed?",
                   default_yes=False):
            asset['purchase_date'] = new_date
        else:
            print("  Purchase date unchanged.")

    new_method = prompt_choice("Amortization method", METHODS,
                                default=asset.get('amortization_method'))
    if new_method != asset.get('amortization_method'):
        if confirm("  Changing method will recalculate all amortization entries. Proceed?",
                   default_yes=False):
            asset['amortization_method'] = new_method
            if new_method == 'declining-balance' and not asset.get('declining_balance_rate'):
                rate = prompt("Declining balance rate (e.g. 0.40 for 40%)",
                              validator=validate_positive_number)
                asset['declining_balance_rate'] = float(rate)
        else:
            print("  Method unchanged.")
    elif asset.get('amortization_method') == 'declining-balance':
        new_rate = prompt("Declining balance rate",
                          default=str(asset.get('declining_balance_rate', '0.20')),
                          validator=validate_positive_number)
        if float(new_rate) != asset.get('declining_balance_rate', 0.20):
            if confirm("  Changing rate will recalculate amortization. Proceed?",
                       default_yes=False):
                asset['declining_balance_rate'] = float(new_rate)

    save_entity(MODULE, slug, asset)
    print(f"\n  Updated: assets/{slug}.yaml")
    print("  Run 'pair asset amort' to regenerate amortization entries.")


# ─── pair asset summary ───────────────────────────────────────────────────

def cmd_summary(flags, args):
    """Show aggregate asset view by category."""
    slugs = list_entities(MODULE)
    if not slugs:
        print("No assets recorded.")
        return

    # Aggregate by category
    categories = {}
    for slug in slugs:
        asset = load_entity(MODULE, slug)
        if not asset:
            continue
        # Skip disposed
        if asset.get('disposal', {}).get('date'):
            continue

        cat = asset.get('category', 'other')
        if cat not in categories:
            categories[cat] = {'count': 0, 'cost': Decimal('0'), 'nbv': Decimal('0')}

        categories[cat]['count'] += 1
        categories[cat]['cost'] += money(asset['cost'])
        categories[cat]['nbv'] += _calculate_nbv(asset)

    if not categories:
        print("No active assets.")
        return

    currency = 'CAD'  # Get from first asset
    for slug in slugs:
        asset = load_entity(MODULE, slug)
        if asset:
            currency = asset.get('currency', 'CAD')
            break

    print(f"\n  Asset Summary by Category")
    print(f"  {'─' * 60}")
    print(f"  {'Category':<20} {'Count':>6} {'Total Cost':>14} {'Total NBV':>14}")
    print(f"  {'─' * 60}")

    total_count = 0
    total_cost = Decimal('0')
    total_nbv = Decimal('0')

    for cat in sorted(categories.keys()):
        data = categories[cat]
        total_count += data['count']
        total_cost += data['cost']
        total_nbv += data['nbv']
        print(f"  {cat.title():<20} {data['count']:>6} "
              f"{currency} {data['cost']:>11,.2f} "
              f"{currency} {data['nbv']:>11,.2f}")

    print(f"  {'─' * 60}")
    print(f"  {'TOTAL':<20} {total_count:>6} "
          f"{currency} {total_cost:>11,.2f} "
          f"{currency} {total_nbv:>11,.2f}")
    print()


# ─── pair asset dispose ───────────────────────────────────────────────────

def cmd_dispose(flags, args):
    """Record asset disposal."""
    if not args:
        print("Usage: pair asset dispose <slug>")
        sys.exit(1)

    slug = args[0]
    asset = load_entity(MODULE, slug)
    if not asset:
        print(f"Asset '{slug}' not found.")
        sys.exit(1)

    if asset.get('disposal', {}).get('date'):
        print(f"Asset '{slug}' is already disposed.")
        sys.exit(1)

    config = load_config()
    print(f"\nDispose: {asset['name']}\n")

    disposal_date = prompt("Disposal date", default=date.today().strftime("%Y-%m-%d"),
                           validator=validate_date)
    method = prompt_choice("Disposal method", ['sold', 'scrapped', 'donated', 'traded-in'])
    proceeds = "0"
    if method in ('sold', 'traded-in'):
        proceeds = prompt("Proceeds received", default="0",
                          validator=validate_non_negative_number)

    # Update YAML
    asset['disposal'] = {
        'date': disposal_date,
        'method': method,
        'proceeds': float(proceeds),
    }
    save_entity(MODULE, slug, asset)

    # Generate disposal journal entry
    _write_disposal_entry(asset, config)
    year = disposal_date[:4]
    print(f"\n  Updated: assets/{slug}.yaml")
    print(f"  Disposal entry written to generated/{year}/assets.journal")


def _write_disposal_entry(asset, config):
    """Write disposal journal entry."""
    currency = asset['currency']
    cost = money(asset['cost'])
    disposal = asset['disposal']
    proceeds = money(disposal['proceeds'])
    disposal_date = disposal['date']
    year = disposal_date[:4]
    name = asset['name']
    slug = asset['slug']

    # Calculate accumulated amortization at disposal date
    accum = _accumulated_at_date(asset, disposal_date)

    book_value = cost - accum
    gain_loss = proceeds - book_value

    asset_account = asset['accounts']['asset']
    accum_account = asset['accounts']['accumulated']
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    postings = []

    # Proceeds (if any)
    if proceeds > 0:
        postings.append((bank, currency, float(proceeds)))

    # Remove accumulated amortization (debit contra-asset)
    if accum > 0:
        postings.append((accum_account, currency, float(accum)))

    # Gain or loss
    if gain_loss > 0:
        pair = '0110'
        postings.append((asset_account, currency, float(-cost)))
        postings.append(('Income:Non-Operating:Gain on Disposal', currency, float(-gain_loss)))
    elif gain_loss < 0:
        pair = '0010'
        postings.append(('Expenses:Non-Operating:Loss on Disposal', currency, float(-gain_loss)))
        postings.append((asset_account, currency, float(-cost)))
    else:
        pair = '1011'
        postings.append((asset_account, currency, float(-cost)))

    tags = {
        'pair': pair,
        'source': f'assets/{slug}.yaml',
        'disposal': disposal['method'],
        'proceeds': str(float(proceeds)),
    }

    entry = format_entry(disposal_date, f"Dispose asset: {name} ({disposal['method']})",
                         postings, tags)

    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "assets.journal"
    from lib.journal import append_journal
    append_journal(journal_path, entry)


# ─── pair asset amort ─────────────────────────────────────────────────────

def cmd_amort(flags, args):
    """Generate amortization entries."""
    config = load_config()

    # Parse args
    specific_asset = None
    through_date = None
    for i, a in enumerate(args):
        if a == '--asset' and i + 1 < len(args):
            specific_asset = args[i + 1]
        elif a == '--through' and i + 1 < len(args):
            through_date = args[i + 1]
        elif a == '--all':
            through_date = None  # generate all pending

    if not through_date:
        through_date = date.today().strftime("%Y-%m-%d")

    # Collect assets to process
    if specific_asset:
        slugs = [specific_asset]
    else:
        slugs = list_entities(MODULE)

    if not slugs:
        print("No assets found.")
        return

    # Group entries by year
    entries_by_year = {}

    for slug in slugs:
        asset = load_entity(MODULE, slug)
        if not asset:
            print(f"  Warning: {slug} not found, skipping.")
            continue

        # Skip disposed assets (entries stop at disposal date)
        end_date = through_date
        disposal = asset.get('disposal', {})
        if disposal.get('date'):
            end_date = min(end_date, disposal['date'])

        new_entries = _generate_amort_entries(asset, end_date)
        for year_str, entry in new_entries:
            entries_by_year.setdefault(year_str, []).append(entry)

    # Write journals per year (atomic replacement)
    total_entries = 0
    for year_str, entries in sorted(entries_by_year.items()):
        ensure_year_structure(int(year_str))
        journal_path = get_generated_dir() / year_str / "amortization.journal"
        header = generated_header("assets/*.yaml", "pair asset amort")
        content = header + "".join(entries)
        write_journal_atomic(journal_path, content)
        total_entries += len(entries)
        if not flags.get('quiet'):
            print(f"  generated/{year_str}/amortization.journal ({len(entries)} entries)")

    if not flags.get('quiet'):
        print(f"\n  Total: {total_entries} amortization entries generated.")


def _generate_amort_entries(asset, through_date_str):
    """Generate all amortization entries for an asset through a given date.

    Returns list of (year_str, entry_str) tuples.
    """
    currency = asset['currency']
    cost = money(asset['cost'])
    salvage = money(asset.get('salvage_value', 0))
    total_depreciable = cost - salvage
    useful_life = asset['useful_life_months']
    method = asset['amortization_method']
    name = asset['name']
    slug = asset['slug']
    expense_account = asset['accounts']['amortization_expense']
    accum_account = asset['accounts']['accumulated']

    purchase_date = datetime.strptime(asset['purchase_date'], "%Y-%m-%d").date()
    through_date = datetime.strptime(through_date_str, "%Y-%m-%d").date()

    entries = []
    accumulated = Decimal('0')
    seq = 0

    # Start from the purchase month
    current_year = purchase_date.year
    current_month = purchase_date.month

    while seq < useful_life:
        # Entry date is 1st of month (except first partial period uses purchase date)
        if seq == 0:
            entry_date = purchase_date
        else:
            entry_date = date(current_year, current_month, 1)

        # Stop if past through_date
        if entry_date > through_date:
            break

        seq += 1

        # Calculate amount
        if method == 'straight-line':
            monthly = money(total_depreciable / useful_life)

            # Partial first month
            if seq == 1 and purchase_date.day > 1:
                days_in_month = monthrange(purchase_date.year, purchase_date.month)[1]
                days_remaining = days_in_month - purchase_date.day + 1
                monthly = money(monthly * days_remaining / days_in_month)

            # Final month adjustment
            if seq == useful_life:
                monthly = total_depreciable - accumulated

            amount = monthly

        elif method == 'declining-balance':
            rate = Decimal(str(asset.get('declining_balance_rate', '0.20')))
            book_value = cost - accumulated
            monthly = money((rate / 12) * book_value)

            # Partial first month
            if seq == 1 and purchase_date.day > 1:
                days_in_month = monthrange(purchase_date.year, purchase_date.month)[1]
                days_remaining = days_in_month - purchase_date.day + 1
                monthly = money(monthly * days_remaining / days_in_month)

            # Don't amortize below salvage
            if accumulated + monthly > total_depreciable:
                monthly = total_depreciable - accumulated

            # Final month
            if seq == useful_life:
                monthly = total_depreciable - accumulated

            amount = monthly
        else:
            break

        # Skip zero amounts
        if amount <= 0:
            break

        accumulated += amount

        # Build description
        desc_parts = [f"Amortization: {name} ({seq}/{useful_life})"]
        if seq == 1 and purchase_date.day > 1:
            desc_parts[0] += " partial"
        if seq == useful_life:
            desc_parts[0] += " final"

        # Tags
        tags = {
            'pair': '0010',
            'source': f'assets/{slug}.yaml',
            'period': entry_date.strftime("%Y-%m"),
            'seq': f'{seq}/{useful_life}',
        }
        if seq == 1 and purchase_date.day > 1:
            days_in_month = monthrange(purchase_date.year, purchase_date.month)[1]
            days_remaining = days_in_month - purchase_date.day + 1
            tags['partial'] = f'{days_remaining}/{days_in_month}'
        if seq == useful_life:
            tags['final'] = 'true'

        postings = [
            (expense_account, currency, float(amount)),
            (accum_account, currency, float(-amount)),
        ]

        entry = format_entry(entry_date.strftime("%Y-%m-%d"), desc_parts[0], postings, tags)
        entries.append((str(entry_date.year), entry))

        # Advance month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return entries


# ─── Calculation helpers ─────────────────────────────────────────────────────

def _calculate_nbv(asset):
    """Calculate current net book value."""
    cost = money(asset['cost'])
    accum = _accumulated_at_date(asset, date.today().strftime("%Y-%m-%d"))
    return cost - accum


def _accumulated_at_date(asset, date_str):
    """Calculate accumulated amortization at a given date."""
    entries = _generate_amort_entries(asset, date_str)
    total = Decimal('0')
    for _, entry_text in entries:
        # Parse amount from the entry (first posting amount)
        for line in entry_text.split('\n'):
            if asset['accounts']['amortization_expense'] in line:
                parts = line.strip().split()
                # Amount is last token
                try:
                    total += money(parts[-1])
                except Exception:
                    pass
                break
    return total


def _monthly_amount(asset):
    """Get the standard monthly amortization amount."""
    cost = money(asset['cost'])
    salvage = money(asset.get('salvage_value', 0))
    useful_life = asset['useful_life_months']

    if asset['amortization_method'] == 'straight-line':
        return money((cost - salvage) / useful_life)
    else:
        rate = Decimal(str(asset.get('declining_balance_rate', '0.20')))
        return money((rate / 12) * cost)  # first month (maximum)


def _remaining_months(asset):
    """Calculate remaining months of useful life."""
    purchase_date = datetime.strptime(asset['purchase_date'], "%Y-%m-%d").date()
    today = date.today()
    elapsed = (today.year - purchase_date.year) * 12 + (today.month - purchase_date.month)
    remaining = asset['useful_life_months'] - elapsed
    return max(0, remaining)


# ─── pair asset writedown ─────────────────────────────────────────────────

def cmd_writedown(flags, args):
    """Record an impairment writedown on an asset.

    Writes: DR Expenses:Non-Operating:Impairment, CR accumulated amortization account.
    Updates YAML with writedown record. Pair 0010.
    """
    if not args:
        print("Usage: pair asset writedown <slug>")
        sys.exit(1)

    slug = args[0]
    asset = load_entity(MODULE, slug)
    if not asset:
        print(f"Asset '{slug}' not found.")
        sys.exit(1)

    if asset.get('disposal', {}).get('date'):
        print(f"Asset '{slug}' is already disposed.")
        sys.exit(1)

    config = load_config()
    currency = asset['currency']
    nbv = _calculate_nbv(asset)

    print(f"\nWritedown: {asset['name']}")
    print(f"Current net book value: {currency} {nbv}")
    print()

    # Parse from args or prompt
    amount_str = None
    writedown_date = flags.get('date')
    reason = None
    for i, a in enumerate(args[1:], 1):
        if a == '--amount' and i + 1 < len(args):
            amount_str = args[i + 1]
        elif a == '--date' and i + 1 < len(args):
            writedown_date = args[i + 1]
        elif a == '--reason' and i + 1 < len(args):
            reason = args[i + 1]

    if not amount_str:
        amount_str = prompt("Writedown amount", validator=validate_positive_number)
    if not writedown_date:
        writedown_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                                validator=validate_date)
    if not reason:
        reason = prompt("Reason for writedown", default="Impairment")

    amount = money(amount_str)

    # Validate amount doesn't exceed NBV
    if amount > nbv:
        print(f"  Warning: writedown ({currency} {amount}) exceeds net book value ({currency} {nbv}).")
        if not confirm("  Proceed anyway?", default_yes=False):
            print("  Cancelled.")
            return

    if not flags.get('yes') and not confirm(
        f"\n  Write down {asset['name']} by {currency} {amount}?"
    ):
        print("  Cancelled.")
        return

    # Journal entry: DR Impairment Expense, CR Accumulated Amortization
    accum_account = asset['accounts']['accumulated']
    postings = [
        ('Expenses:Non-Operating:Impairment', currency, float(amount)),
        (accum_account, currency, float(-amount)),
    ]

    tags = {
        'pair': '0010',
        'source': f'assets/{slug}.yaml',
        'reason': reason,
    }

    entry = format_entry(writedown_date,
                         f"Writedown: {asset['name']} — {reason}",
                         postings, tags)

    year = writedown_date[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "assets.journal"
    append_journal(journal_path, entry)

    # Update YAML — add writedown record and adjust salvage value
    if 'writedowns' not in asset:
        asset['writedowns'] = []
    asset['writedowns'].append({
        'date': writedown_date,
        'amount': float(amount),
        'reason': reason,
    })

    # Reduce salvage value by writedown amount (floor at 0)
    current_salvage = money(asset.get('salvage_value', 0))
    new_salvage = max(Decimal('0'), current_salvage - amount)
    asset['salvage_value'] = float(new_salvage)

    save_entity(MODULE, slug, asset)

    if not flags.get('quiet'):
        print(f"\n  Writedown recorded: {asset['name']}")
        print(f"  Amount:      {currency} {amount}")
        print(f"  Reason:      {reason}")
        print(f"  New salvage: {currency} {new_salvage}")
        print(f"  Written to:  generated/{year}/assets.journal")
        print(f"  Updated:     assets/{slug}.yaml")
