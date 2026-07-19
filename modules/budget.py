"""pair budget — budget creation, comparison, and variance reporting."""

import sys
import re
import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import yaml

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_slug, validate_date, validate_positive_number,
    parse_global_flags, get_entity_dir, get_active_entity, slugify
)


BUDGET_DIR_NAME = "budgets"

SHOW_FILTERS = {
    'all': None,
    'expenses': 'Expenses:',
    'income': 'Income:',
    'liabilities': 'Liabilities:',
    'assets': 'Assets:',
    'operating': ('Expenses:Operating:', 'Income:Operating:'),
    'non-operating': ('Expenses:Non-Operating:', 'Income:Non-Operating:'),
}

PERIOD_TYPES = ['monthly', 'weekly', 'biweekly', 'quarterly', 'annual', 'custom']
SCENARIOS = ['baseline', 'conservative', 'aggressive', 'custom']


def _budget_dir():
    return get_entity_dir() / BUDGET_DIR_NAME


def _load_budget(slug):
    path = _budget_dir() / f"{slug}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def _save_budget(slug, data):
    d = _budget_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{slug}.yaml"
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _list_budgets():
    d = _budget_dir()
    if not d.exists():
        return []
    return sorted([p.stem for p in d.glob("*.yaml")])


def dispatch(args):
    """Route budget subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    if not remaining or remaining[0] == 'menu':
        cmd_menu(flags)
    elif remaining[0] == 'create':
        cmd_create(flags, remaining[1:])
    elif remaining[0] == 'list':
        cmd_list(flags, remaining[1:])
    elif remaining[0] == 'show':
        cmd_show(flags, remaining[1:])
    elif remaining[0] == 'edit':
        cmd_edit(flags, remaining[1:])
    elif remaining[0] == 'compare':
        cmd_compare(flags, remaining[1:])
    elif remaining[0] == 'vs':
        cmd_vs(flags, remaining[1:])
    elif remaining[0] == 'forecast':
        cmd_forecast(flags, remaining[1:])
    elif remaining[0] == 'remove':
        cmd_remove(flags, remaining[1:])
    elif remaining[0] == 'activate':
        cmd_activate(flags, remaining[1:])
    elif remaining[0] == 'set':
        # Legacy compat — quick set
        cmd_quick_set(flags, remaining[1:])
    else:
        print(f"Unknown budget action: {remaining[0]}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair budget — budget creation, comparison, and variance reporting

Actions:
  (no args)           Interactive menu
  create              Create a new budget (guided)
  list                List all budgets
  show <slug>         Display a budget table
  edit <slug>         Modify budget amounts
  compare             Compare two budgets side-by-side
  vs                  Compare budget vs actual
  forecast            Project year-end based on actuals
  remove              Remove budget(s)
  activate <slug>     Set a budget as active for its year
  set                 Quick set: one account, one amount

Flags:
  --show FILTER       Filter accounts: expenses|income|liabilities|assets|operating|all
  --division DIV      Scope to division
  --project PROJ      Scope to project
  --ytd               Year-to-date comparison
  --months RANGE      Rolling window (e.g. Jul-Sep, Q2)
  --forecast          Include year-end projection
  --vertical          Narrow terminal layout
  --format csv        Export as CSV
  --from SLUG         Copy from existing budget (create)
  --year YYYY         Budget year
""")


# ─── Interactive menu ────────────────────────────────────────────────────────

def cmd_menu(flags):
    """Interactive budget management menu."""
    co = get_active_entity() or "entity"
    print(f"\n  [{co}] Budget Management\n")
    print("  1. Create a new budget")
    print("  2. List budgets")
    print("  3. Show a budget")
    print("  4. Edit a budget")
    print("  5. Compare budgets")
    print("  6. Budget vs Actual")
    print("  7. Forecast")
    print("  8. Remove budget(s)")
    print("  9. Activate a budget")
    print()

    choice = prompt("Choice [1-9]")

    if choice == '1':
        cmd_create(flags, [])
    elif choice == '2':
        cmd_list(flags, [])
    elif choice == '3':
        slug = _pick_budget("Show which budget?")
        if slug:
            show_filter = _pick_filter()
            cmd_show(flags, [slug, '--show', show_filter])
    elif choice == '4':
        slug = _pick_budget("Edit which budget?")
        if slug:
            cmd_edit(flags, [slug])
    elif choice == '5':
        cmd_compare_interactive(flags)
    elif choice == '6':
        cmd_vs_interactive(flags)
    elif choice == '7':
        cmd_forecast(flags, [])
    elif choice == '8':
        cmd_remove_interactive(flags)
    elif choice == '9':
        slug = _pick_budget("Activate which budget?")
        if slug:
            cmd_activate(flags, [slug])
    else:
        print("Invalid choice.")


def _pick_budget(label):
    """Show numbered list, return selected slug."""
    slugs = _list_budgets()
    if not slugs:
        print("No budgets found. Use 'pair budget create' first.")
        return None
    print(f"\n  {label}\n")
    for i, slug in enumerate(slugs, 1):
        b = _load_budget(slug)
        name = b.get('name', slug) if b else slug
        active = " ✓" if b and b.get('active') else ""
        print(f"  {i}. {name}{active}")
    print()
    choice = prompt(f"Which? [1-{len(slugs)}]")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(slugs):
            return slugs[idx]
    except (ValueError, IndexError):
        pass
    print("Invalid selection.")
    return None


def _pick_filter():
    """Ask which account filter to apply."""
    print("\n  Show: (a) All  (e) Expenses  (i) Income  (l) Liabilities  (o) Operating")
    choice = prompt("Filter", default="a")
    mapping = {'a': 'all', 'e': 'expenses', 'i': 'income', 'l': 'liabilities', 'o': 'operating'}
    return mapping.get(choice.lower(), 'all')


# ─── Create ──────────────────────────────────────────────────────────────────

def cmd_create(flags, args):
    """Create a new budget."""
    co = get_active_entity() or "entity"

    # Parse flags
    copy_from = None
    year = str(date.today().year)
    division = None
    project = None
    for i, a in enumerate(args):
        if a == '--from' and i + 1 < len(args):
            copy_from = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year = args[i + 1]
        elif a == '--division' and i + 1 < len(args):
            division = args[i + 1]
        elif a == '--project' and i + 1 < len(args):
            project = args[i + 1]

    print(f"\n  [{co}] Create a budget\n")

    name = prompt("Budget name", default=f"{year} Operating Budget")
    slug = prompt("Slug", default=slugify(name), validator=validate_slug)
    year = prompt("Year", default=year)
    period_type = prompt_choice("Period type", PERIOD_TYPES, default='monthly')
    scenario = prompt_choice("Scenario", SCENARIOS, default='baseline')

    if not division:
        config = load_config()
        divisions = config.get('divisions', [])
        if divisions:
            div_choice = prompt("Division (blank for entity-wide)", required=False)
            if div_choice:
                division = div_choice

    if not project:
        proj_choice = prompt("Project scope (blank for all)", required=False)
        if proj_choice:
            project = proj_choice

    # Generate periods
    periods = _generate_periods(int(year), period_type)

    # Set as active?
    set_active = confirm("Set as active budget for this year?", default_yes=True)

    # Collect amounts
    lines = []
    if copy_from:
        source = _load_budget(copy_from)
        if source:
            lines = source.get('lines', [])
            print(f"\n  Copied {len(lines)} lines from '{copy_from}'. Adjust below.\n")
        else:
            print(f"  Budget '{copy_from}' not found. Starting fresh.\n")

    if not lines:
        lines = _guided_amount_entry(periods, period_type, division)

    # Build budget
    budget_data = {
        'name': name,
        'slug': slug,
        'year': year,
        'scenario': scenario,
        'period_type': period_type,
        'active': set_active,
        'periods': periods,
        'lines': lines,
    }
    if division:
        budget_data['scope'] = {'division': division}
    elif project:
        budget_data['scope'] = {'project': project}

    # Deactivate other budgets for same year if setting active
    if set_active:
        for existing_slug in _list_budgets():
            existing = _load_budget(existing_slug)
            if existing and existing.get('year') == year and existing.get('active'):
                existing['active'] = False
                _save_budget(existing_slug, existing)

    _save_budget(slug, budget_data)
    print(f"\n  Saved: budgets/{slug}.yaml ({len(lines)} lines, {len(periods)} periods)")


def _generate_periods(year, period_type):
    """Generate period definitions."""
    periods = []
    if period_type == 'monthly':
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        for i, m in enumerate(months):
            start_month = i + 1
            end_month = i + 2
            end_year = year
            if end_month > 12:
                end_month = 1
                end_year = year + 1
            periods.append({
                'label': m,
                'from': f"{year}-{start_month:02d}-01",
                'to': f"{end_year}-{end_month:02d}-01",
            })
    elif period_type == 'quarterly':
        for q in range(1, 5):
            start_month = (q - 1) * 3 + 1
            end_month = q * 3 + 1
            end_year = year
            if end_month > 12:
                end_month = 1
                end_year = year + 1
            periods.append({
                'label': f"Q{q}",
                'from': f"{year}-{start_month:02d}-01",
                'to': f"{end_year}-{end_month:02d}-01",
            })
    elif period_type == 'weekly':
        from datetime import timedelta
        start = date(year, 1, 1)
        # Align to Monday
        start += timedelta(days=(7 - start.weekday()) % 7)
        week = 1
        while start.year == year:
            end = start + timedelta(days=7)
            periods.append({
                'label': f"W{week:02d}",
                'from': start.strftime("%Y-%m-%d"),
                'to': end.strftime("%Y-%m-%d"),
            })
            start = end
            week += 1
    elif period_type == 'annual':
        periods.append({
            'label': str(year),
            'from': f"{year}-01-01",
            'to': f"{year + 1}-01-01",
        })
    return periods


def _guided_amount_entry(periods, period_type, division=None):
    """Walk through accounts and collect amounts."""
    period_count = len(periods)
    labels = [p['label'] for p in periods]
    hint = ", ".join(labels[:6])
    if len(labels) > 6:
        hint += f"... ({len(labels)} periods)"

    print(f"\n  Periods: {hint}")
    print(f"  Enter: single number (uniform), NUMxCOUNT (run-length),")
    print(f"         comma-separated (explicit), 's' (step-through), or blank to skip.\n")

    # Common expense accounts
    accounts = [
        'Expenses:Operating:Rent',
        'Expenses:Operating:Payroll:Salaries',
        'Expenses:Operating:Software Subscriptions',
        'Expenses:Operating:Professional Fees',
        'Expenses:Operating:Travel',
        'Expenses:Operating:Meals and Entertainment',
        'Expenses:Operating:Marketing',
        'Expenses:Operating:Utilities',
        'Expenses:Operating:Insurance',
        'Expenses:Operating:Telecommunications',
        'Expenses:Operating:Office Supplies',
        'Expenses:Operating:Bank Fees',
        'Expenses:Operating:Repairs and Maintenance',
        'Expenses:Non-Operating:Interest Expense',
        'Income:Operating:Consulting',
        'Income:Operating:Services',
        'Income:Operating:Product Sales',
    ]

    lines = []
    print("  EXPENSES")
    for acct in accounts:
        if acct.startswith('Income:') and lines and not any(l['account'].startswith('Income:') for l in lines):
            print("\n  INCOME")
        short_name = acct.split(':')[-1]
        raw = prompt(f"  {short_name}", required=False)
        if not raw:
            continue
        amounts = _parse_amount_input(raw, period_count, labels)
        if amounts:
            lines.append({'account': acct, 'amounts': amounts})

    # Allow custom accounts
    print("\n  Additional accounts (blank to finish):")
    while True:
        acct = prompt("  Account name", required=False)
        if not acct:
            break
        raw = prompt(f"  Amount for {acct.split(':')[-1]}", required=False)
        if raw:
            amounts = _parse_amount_input(raw, period_count, labels)
            if amounts:
                lines.append({'account': acct, 'amounts': amounts})

    return lines


def _parse_amount_input(raw, period_count, labels):
    """Parse user amount input in various formats."""
    raw = raw.strip().lstrip('$')

    # Mode 1: Uniform — single number
    if re.match(r'^\d+\.?\d*$', raw):
        val = float(raw)
        return [val] * period_count

    # Mode 2: Run-length — e.g. "4500x6, 6000x6"
    if 'x' in raw.lower():
        amounts = []
        parts = [p.strip() for p in raw.split(',')]
        for part in parts:
            match = re.match(r'(\d+\.?\d*)\s*x\s*(\d+)', part, re.IGNORECASE)
            if match:
                val = float(match.group(1))
                count = int(match.group(2))
                amounts.extend([val] * count)
        # Pad or truncate
        if len(amounts) < period_count:
            amounts.extend([0.0] * (period_count - len(amounts)))
        return amounts[:period_count]

    # Mode 5: Comma-separated explicit
    if ',' in raw:
        parts = [p.strip().lstrip('$') for p in raw.split(',')]
        amounts = []
        for p in parts:
            try:
                amounts.append(float(p))
            except ValueError:
                amounts.append(0.0)
        if len(amounts) < period_count:
            amounts.extend([0.0] * (period_count - len(amounts)))
        return amounts[:period_count]

    # Mode 3: Step-through
    if raw.lower() in ('s', 'step'):
        return _step_through_entry(period_count, labels)

    # Mode 4: From-for — e.g. "from 6 for 1 = 4500"
    match = re.match(r'from\s+(\d+)\s+for\s+(\d+)\s*=\s*(\d+\.?\d*)', raw, re.IGNORECASE)
    if match:
        start_idx = int(match.group(1)) - 1
        count = int(match.group(2))
        val = float(match.group(3))
        amounts = [0.0] * period_count
        for i in range(start_idx, min(start_idx + count, period_count)):
            amounts[i] = val
        return amounts

    # Fallback: try as single number
    try:
        val = float(raw)
        return [val] * period_count
    except ValueError:
        print(f"    Could not parse: {raw}")
        return None


def _step_through_entry(period_count, labels):
    """Walk through periods in groups, enter to repeat."""
    amounts = []
    last_val = 0.0
    # Group into chunks of 3
    chunk_size = 3 if period_count >= 6 else 1
    i = 0
    while i < period_count:
        chunk_end = min(i + chunk_size, period_count)
        chunk_labels = labels[i:chunk_end]
        label_str = "-".join(chunk_labels)
        raw = prompt(f"    {label_str} [${last_val:,.0f}]", required=False)
        if raw:
            try:
                last_val = float(raw.lstrip('$'))
            except ValueError:
                pass
        for _ in range(chunk_end - i):
            amounts.append(last_val)
        i = chunk_end
    return amounts


# ─── List ────────────────────────────────────────────────────────────────────

def cmd_list(flags, args):
    """List all budgets."""
    co = get_active_entity() or "entity"
    slugs = _list_budgets()
    if not slugs:
        print("No budgets found. Use 'pair budget create' to start.")
        return

    print(f"\n  [{co}] Budgets\n")
    print(f"  {'#':<3} {'Name':<30} {'Year':<6} {'Type':<10} {'Scenario':<14} {'Active':<6}")
    print(f"  {'─' * 72}")

    for i, slug in enumerate(slugs, 1):
        b = _load_budget(slug)
        if not b:
            continue
        active = "✓" if b.get('active') else ""
        scope = ""
        if b.get('scope'):
            s = b['scope']
            if 'division' in s:
                scope = f" [{s['division']}]"
            elif 'project' in s:
                scope = f" [{s['project']}]"
        print(f"  {i:<3} {b.get('name', slug):<30} {b.get('year', '?'):<6} "
              f"{b.get('period_type', '?'):<10} {b.get('scenario', '?'):<14} {active}{scope}")

    print()


# ─── Show ────────────────────────────────────────────────────────────────────

def cmd_show(flags, args):
    """Display a budget as a table."""
    if not args:
        slug = _pick_budget("Show which budget?")
        if not slug:
            return
        args = [slug]

    slug = args[0]
    show_filter = 'all'
    for i, a in enumerate(args):
        if a == '--show' and i + 1 < len(args):
            show_filter = args[i + 1]

    budget = _load_budget(slug)
    if not budget:
        print(f"Budget '{slug}' not found.")
        return

    co = get_active_entity() or "entity"
    periods = budget.get('periods', [])
    lines = budget.get('lines', [])
    labels = [p['label'] for p in periods]

    # Filter lines
    lines = _filter_lines(lines, show_filter)

    active_str = " (active)" if budget.get('active') else ""
    print(f"\n  [{co}] {budget['name']}{active_str}")
    print(f"  {budget.get('scenario', 'baseline')} | {budget.get('period_type', 'monthly')} | {budget.get('year', '?')}")
    print()

    # Table header
    acct_width = max(30, max((len(l['account'].split(':')[-1]) for l in lines), default=20) + 2)
    header = f"  {'Account':<{acct_width}}"
    for lbl in labels:
        header += f" {lbl:>7}"
    header += f" {'TOTAL':>9}"
    print(header)
    print(f"  {'─' * len(header)}")

    total_per_period = [Decimal('0')] * len(periods)
    for line in lines:
        amounts = line.get('amounts', [])
        short_name = line['account'].split(':')[-1]
        row = f"  {short_name:<{acct_width}}"
        line_total = Decimal('0')
        for j, amt in enumerate(amounts):
            row += f" {amt:>7,.0f}"
            line_total += Decimal(str(amt))
            if j < len(total_per_period):
                total_per_period[j] += Decimal(str(amt))
        row += f" {float(line_total):>9,.0f}"
        print(row)

    # Totals row
    print(f"  {'─' * len(header)}")
    totals_row = f"  {'TOTAL':<{acct_width}}"
    grand_total = Decimal('0')
    for t in total_per_period:
        totals_row += f" {float(t):>7,.0f}"
        grand_total += t
    totals_row += f" {float(grand_total):>9,.0f}"
    print(totals_row)
    print()


# ─── Edit ────────────────────────────────────────────────────────────────────

def cmd_edit(flags, args):
    """Edit budget amounts."""
    if not args:
        slug = _pick_budget("Edit which budget?")
        if not slug:
            return
        args = [slug]

    slug = args[0]
    budget = _load_budget(slug)
    if not budget:
        print(f"Budget '{slug}' not found.")
        return

    periods = budget.get('periods', [])
    labels = [p['label'] for p in periods]
    lines = budget.get('lines', [])

    print(f"\n  Editing: {budget['name']}")
    print(f"  Periods: {', '.join(labels[:6])}{'...' if len(labels) > 6 else ''}")
    print(f"  Enter new value or press enter to keep. 'x' to remove line.\n")

    new_lines = []
    for line in lines:
        short_name = line['account'].split(':')[-1]
        current = line.get('amounts', [])
        if len(set(current)) == 1:
            hint = f"${current[0]:,.0f}/period"
        else:
            hint = f"${min(current):,.0f}-${max(current):,.0f}"

        raw = prompt(f"  {short_name} [{hint}]", required=False)
        if raw == 'x':
            continue  # remove line
        elif raw:
            amounts = _parse_amount_input(raw, len(periods), labels)
            if amounts:
                line['amounts'] = amounts
        new_lines.append(line)

    # Add new lines
    print("\n  Add accounts (blank to finish):")
    while True:
        acct = prompt("  Account name", required=False)
        if not acct:
            break
        raw = prompt(f"  Amount", required=False)
        if raw:
            amounts = _parse_amount_input(raw, len(periods), labels)
            if amounts:
                new_lines.append({'account': acct, 'amounts': amounts})

    budget['lines'] = new_lines
    _save_budget(slug, budget)
    print(f"\n  Updated: budgets/{slug}.yaml ({len(new_lines)} lines)")


# ─── Compare ─────────────────────────────────────────────────────────────────

def cmd_compare(flags, args):
    """Compare two budgets."""
    # Parse args for slugs
    slug1 = None
    slug2 = None
    show_filter = 'all'
    for i, a in enumerate(args):
        if a == '--show' and i + 1 < len(args):
            show_filter = args[i + 1]
        elif not slug1 and not a.startswith('-'):
            slug1 = a
        elif slug1 and not slug2 and not a.startswith('-'):
            slug2 = a

    if not slug1 or not slug2:
        cmd_compare_interactive(flags)
        return

    b1 = _load_budget(slug1)
    b2 = _load_budget(slug2)
    if not b1 or not b2:
        print("One or both budgets not found.")
        return

    _render_comparison(b1, b2, show_filter)


def cmd_compare_interactive(flags):
    """Interactive budget comparison."""
    slugs = _list_budgets()
    if len(slugs) < 2:
        print("Need at least 2 budgets to compare.")
        return

    print("\n  Select budgets to compare (space-separated numbers):\n")
    for i, slug in enumerate(slugs, 1):
        b = _load_budget(slug)
        name = b.get('name', slug) if b else slug
        print(f"  {i}. {name}")
    print()

    raw = prompt("Compare which? (e.g. '1 3')")
    parts = raw.split()
    if len(parts) < 2:
        print("Need two selections.")
        return

    try:
        idx1 = int(parts[0]) - 1
        idx2 = int(parts[1]) - 1
        slug1 = slugs[idx1]
        slug2 = slugs[idx2]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    show_filter = _pick_filter()

    b1 = _load_budget(slug1)
    b2 = _load_budget(slug2)
    _render_comparison(b1, b2, show_filter)


def _render_comparison(b1, b2, show_filter):
    """Render side-by-side budget comparison."""
    co = get_active_entity() or "entity"
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')

    lines1 = _filter_lines(b1.get('lines', []), show_filter)
    lines2 = _filter_lines(b2.get('lines', []), show_filter)

    # Build lookup by account
    totals1 = {l['account']: sum(l.get('amounts', [])) for l in lines1}
    totals2 = {l['account']: sum(l.get('amounts', [])) for l in lines2}
    all_accounts = sorted(set(list(totals1.keys()) + list(totals2.keys())))

    print(f"\n  [{co}] Budget Comparison\n")
    print(f"  {b1['name']} vs {b2['name']}\n")
    print(f"  {'Account':<35} {b1.get('scenario',''):<14} {b2.get('scenario',''):<14} {'Difference':<14}")
    print(f"  {'─' * 80}")

    total_a = Decimal('0')
    total_b = Decimal('0')

    for acct in all_accounts:
        a = Decimal(str(totals1.get(acct, 0)))
        b = Decimal(str(totals2.get(acct, 0)))
        diff = b - a
        total_a += a
        total_b += b
        short = acct.split(':')[-1]
        sign = "+" if diff >= 0 else ""
        print(f"  {short:<35} {currency} {float(a):>9,.0f}  {currency} {float(b):>9,.0f}  {sign}{currency} {float(diff):>8,.0f}")

    diff_total = total_b - total_a
    sign = "+" if diff_total >= 0 else ""
    print(f"  {'─' * 80}")
    print(f"  {'TOTAL':<35} {currency} {float(total_a):>9,.0f}  {currency} {float(total_b):>9,.0f}  {sign}{currency} {float(diff_total):>8,.0f}")
    print()


# ─── Budget vs Actual ────────────────────────────────────────────────────────

def cmd_vs(flags, args):
    """Compare active budget vs actual."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    journal_file = config.get('journal_file')

    # Parse flags
    show_filter = 'all'
    ytd = False
    division = None
    project = None
    fmt = None
    year = str(date.today().year)

    for i, a in enumerate(args):
        if a == '--show' and i + 1 < len(args):
            show_filter = args[i + 1]
        elif a == '--ytd':
            ytd = True
        elif a == '--division' and i + 1 < len(args):
            division = args[i + 1]
        elif a == '--project' and i + 1 < len(args):
            project = args[i + 1]
        elif a == '--format' and i + 1 < len(args):
            fmt = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    # Find active budget for the year
    budget = _get_active_budget(year)
    if not budget:
        print(f"No active budget for {year}. Use 'pair budget activate <slug>'.")
        return

    periods = budget.get('periods', [])
    lines = _filter_lines(budget.get('lines', []), show_filter)

    # Determine which periods to compare
    today = date.today()
    if ytd:
        # All periods up to current
        compare_periods = [p for p in periods if p['from'] <= today.strftime("%Y-%m-%d")]
    else:
        # Current period only
        compare_periods = []
        for p in periods:
            if p['from'] <= today.strftime("%Y-%m-%d") < p['to']:
                compare_periods = [p]
                break
        if not compare_periods and periods:
            compare_periods = [periods[-1]]

    period_indices = [periods.index(p) for p in compare_periods]
    period_label = f"{compare_periods[0]['label']}" if len(compare_periods) == 1 else f"{compare_periods[0]['label']}-{compare_periods[-1]['label']}"

    co = get_active_entity() or "entity"
    title = "YTD" if ytd else period_label
    print(f"\n  [{co}] Budget vs Actual — {title} {year}\n")
    print(f"  {'Account':<35} {'Budget':>12} {'Actual':>12} {'Variance':>12} {'%':>6}")
    print(f"  {'─' * 80}")

    total_budget = Decimal('0')
    total_actual = Decimal('0')

    for line in lines:
        amounts = line.get('amounts', [])
        budget_amt = sum(Decimal(str(amounts[i])) for i in period_indices if i < len(amounts))
        actual_amt = _get_actual_for_periods(config, line['account'], compare_periods, division)

        variance = budget_amt - actual_amt
        pct = (float(variance) / float(budget_amt) * 100) if budget_amt != 0 else 0
        indicator = " ⚠" if variance < 0 else ""

        total_budget += budget_amt
        total_actual += actual_amt

        short = line['account'].split(':')[-1]
        print(f"  {short:<35} {currency} {float(budget_amt):>9,.2f} "
              f"{currency} {float(actual_amt):>9,.2f} "
              f"{currency} {float(variance):>9,.2f} {pct:>5.0f}%{indicator}")

    total_var = total_budget - total_actual
    total_pct = (float(total_var) / float(total_budget) * 100) if total_budget != 0 else 0
    print(f"  {'─' * 80}")
    print(f"  {'TOTAL':<35} {currency} {float(total_budget):>9,.2f} "
          f"{currency} {float(total_actual):>9,.2f} "
          f"{currency} {float(total_var):>9,.2f} {total_pct:>5.0f}%")
    print()


def cmd_vs_interactive(flags):
    """Interactive budget vs actual menu."""
    print("\n  Period: (m) Current month  (q) Current quarter  (y) YTD  (c) Custom")
    period_choice = prompt("Period", default="m")

    show_filter = _pick_filter()

    print("  Scope: (a) All  (d) By division  (p) By project")
    scope_choice = prompt("Scope", default="a")

    args = ['--show', show_filter]
    if period_choice == 'y':
        args.append('--ytd')
    if scope_choice == 'd':
        div = prompt("Division")
        args += ['--division', div]
    elif scope_choice == 'p':
        proj = prompt("Project")
        args += ['--project', proj]

    cmd_vs(flags, args)


# ─── Forecast ────────────────────────────────────────────────────────────────

def cmd_forecast(flags, args):
    """Project year-end based on actuals so far."""
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    year = str(date.today().year)

    for i, a in enumerate(args):
        if a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    budget = _get_active_budget(year)
    if not budget:
        print(f"No active budget for {year}.")
        return

    periods = budget.get('periods', [])
    lines = budget.get('lines', [])
    today = date.today()

    # Count elapsed and remaining periods
    elapsed = [p for p in periods if p['to'] <= today.strftime("%Y-%m-%d")]
    remaining = len(periods) - len(elapsed)
    elapsed_count = len(elapsed)

    if elapsed_count == 0:
        print("No completed periods yet — can't forecast.")
        return

    co = get_active_entity() or "entity"
    print(f"\n  [{co}] Forecast — {year} ({elapsed_count} of {len(periods)} periods elapsed)\n")
    print(f"  {'Account':<35} {'Budget(yr)':>11} {'Actual(ytd)':>12} {'Projected':>11} {'vs Budget':>11}")
    print(f"  {'─' * 83}")

    total_budget_yr = Decimal('0')
    total_projected = Decimal('0')

    elapsed_indices = list(range(elapsed_count))

    for line in lines:
        amounts = line.get('amounts', [])
        budget_yr = sum(Decimal(str(a)) for a in amounts)
        actual_ytd = _get_actual_for_periods(config, line['account'], elapsed, None)

        # Project: actual rate * full year
        if elapsed_count > 0:
            rate_per_period = actual_ytd / elapsed_count
            projected = rate_per_period * len(periods)
        else:
            projected = Decimal('0')

        diff = projected - budget_yr
        sign = "+" if diff >= 0 else ""

        total_budget_yr += budget_yr
        total_projected += projected

        short = line['account'].split(':')[-1]
        print(f"  {short:<35} {currency} {float(budget_yr):>8,.0f} "
              f"{currency} {float(actual_ytd):>9,.0f} "
              f"{currency} {float(projected):>8,.0f} "
              f"{sign}{currency} {float(diff):>7,.0f}")

    total_diff = total_projected - total_budget_yr
    sign = "+" if total_diff >= 0 else ""
    print(f"  {'─' * 83}")
    print(f"  {'TOTAL':<35} {currency} {float(total_budget_yr):>8,.0f} "
          f"{'':>15} "
          f"{currency} {float(total_projected):>8,.0f} "
          f"{sign}{currency} {float(total_diff):>7,.0f}")
    print()


# ─── Remove ──────────────────────────────────────────────────────────────────

def cmd_remove(flags, args):
    """Remove budgets."""
    if args and not args[0].startswith('-'):
        # Direct slug
        slug = args[0]
        b = _load_budget(slug)
        if not b:
            print(f"Budget '{slug}' not found.")
            return
        if confirm(f"Remove '{b['name']}'?", default_yes=False):
            (_budget_dir() / f"{slug}.yaml").unlink()
            print(f"  Removed.")
        return

    cmd_remove_interactive(flags)


def cmd_remove_interactive(flags):
    """Interactive removal with multi-select."""
    slugs = _list_budgets()
    if not slugs:
        print("No budgets to remove.")
        return

    print("\n  Select budgets to remove (space-separated numbers):\n")
    for i, slug in enumerate(slugs, 1):
        b = _load_budget(slug)
        name = b.get('name', slug) if b else slug
        print(f"  {i}. {name}")
    print()

    raw = prompt("Remove which?")
    indices = []
    for part in raw.split():
        try:
            indices.append(int(part) - 1)
        except ValueError:
            pass

    removed = 0
    for idx in indices:
        if 0 <= idx < len(slugs):
            slug = slugs[idx]
            b = _load_budget(slug)
            name = b.get('name', slug) if b else slug
            if confirm(f"  Remove '{name}'?", default_yes=False):
                (_budget_dir() / f"{slug}.yaml").unlink()
                removed += 1

    print(f"  Removed {removed} budget(s).")


# ─── Activate ────────────────────────────────────────────────────────────────

def cmd_activate(flags, args):
    """Set a budget as active for its year."""
    if not args:
        slug = _pick_budget("Activate which budget?")
        if not slug:
            return
    else:
        slug = args[0]

    budget = _load_budget(slug)
    if not budget:
        print(f"Budget '{slug}' not found.")
        return

    year = budget.get('year')

    # Deactivate others for same year
    for other_slug in _list_budgets():
        other = _load_budget(other_slug)
        if other and other.get('year') == year and other.get('active'):
            other['active'] = False
            _save_budget(other_slug, other)

    budget['active'] = True
    _save_budget(slug, budget)
    print(f"  Activated: {budget['name']} for {year}")


# ─── Quick set (legacy compat) ───────────────────────────────────────────────

def cmd_quick_set(flags, args):
    """Quick set: one account, one amount on active budget."""
    config = load_config()
    year = str(date.today().year)
    account = None
    amount = None

    for i, a in enumerate(args):
        if a == '--account' and i + 1 < len(args):
            account = args[i + 1]
        elif a == '--amount' and i + 1 < len(args):
            amount = args[i + 1]
        elif a == '--year' and i + 1 < len(args):
            year = args[i + 1]

    if not account:
        account = prompt("Account name")
    if not amount:
        amount = prompt("Monthly budget amount", validator=validate_positive_number)

    budget = _get_active_budget(year)
    if not budget:
        print(f"No active budget for {year}. Create one with 'pair budget create'.")
        return

    periods = budget.get('periods', [])
    amt_float = float(amount)
    amounts = [amt_float] * len(periods)

    # Update or add line
    lines = budget.get('lines', [])
    found = False
    for line in lines:
        if line['account'] == account:
            line['amounts'] = amounts
            found = True
            break
    if not found:
        lines.append({'account': account, 'amounts': amounts})

    budget['lines'] = lines
    _save_budget(budget['slug'], budget)
    print(f"\n  Budget set: {account} = ${amt_float:,.2f}/period for {year}")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_active_budget(year):
    """Find the active budget for a given year."""
    for slug in _list_budgets():
        b = _load_budget(slug)
        if b and b.get('year') == str(year) and b.get('active'):
            return b
    return None


def _filter_lines(lines, show_filter):
    """Filter budget lines by account type."""
    if show_filter == 'all' or show_filter not in SHOW_FILTERS:
        return lines
    prefix = SHOW_FILTERS[show_filter]
    if prefix is None:
        return lines
    if isinstance(prefix, tuple):
        return [l for l in lines if any(l['account'].startswith(p) for p in prefix)]
    return [l for l in lines if l['account'].startswith(prefix)]


def _get_actual_for_periods(config, account, periods, division=None):
    """Query hledger for actual balance across specified periods."""
    from lib.helpers import expand_path
    journal_file = config.get('journal_file')
    if not journal_file:
        return Decimal('0')

    journal_path = str(expand_path(journal_file))
    if not periods:
        return Decimal('0')

    begin = periods[0]['from']
    end = periods[-1]['to']

    cmd = ['hledger', '-f', journal_path, 'bal', account,
           '-b', begin, '-e', end, '--no-total', '--output-format=csv']
    if division:
        cmd += [f'tag:division={division}']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return Decimal('0')
        import csv
        from io import StringIO
        reader = csv.reader(StringIO(result.stdout))
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                bal_str = row[1].strip('"').replace(',', '')
                parts = bal_str.split()
                try:
                    return abs(Decimal(parts[-1]))
                except Exception:
                    pass
        return Decimal('0')
    except (FileNotFoundError, OSError):
        return Decimal('0')
