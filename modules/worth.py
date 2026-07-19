"""pair worth — net worth reporting."""

import sys
import subprocess
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, expand_path, parse_global_flags, BASE_DIR
)
from lib.yaml_store import load_entity, list_entities


def dispatch(args):
    """Route worth subcommands or show default report."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    # Check for sub-actions
    if remaining and remaining[0] == 'breakdown':
        cmd_breakdown(flags, remaining[1:])
    elif remaining and remaining[0] == 'trend':
        cmd_trend(flags, remaining[1:])
    else:
        cmd_worth(flags, remaining)


def print_help():
    print("""pair worth — net worth reporting

Usage:
  pair worth                     Current net worth
  pair worth --period DATE       Net worth as of a date
  pair worth --monthly           Monthly trend (current year)
  pair worth --quarterly         Quarterly trend
  pair worth --detail            Full account breakdown
  pair worth --raw               Pass through to hledger bs

Flags:
  --period <date>     As-of date (YYYY-MM-DD)
  --monthly           Show month-by-month change
  --quarterly         Show quarter-by-quarter change
  --detail            Show full account tree
  --division <div>    Filter by division
  --raw               Direct hledger bs output
""")


# ─── pair worth (main report) ────────────────────────────────────────────

def cmd_worth(flags, args):
    """Show entity net worth."""
    config = load_config()
    entity_name = config.get('pair', {}).get('name', 'Entity')
    currency = config.get('pair', {}).get('currency', 'CAD')

    # Parse period/flags from remaining args
    period_end = None
    show_monthly = False
    show_quarterly = False
    show_detail = False
    show_raw = False
    division_filter = None

    for i, a in enumerate(args):
        if a == '--period' and i + 1 < len(args):
            period_end = args[i + 1]
        elif a == '--monthly':
            show_monthly = True
        elif a == '--quarterly':
            show_quarterly = True
        elif a == '--detail':
            show_detail = True
        elif a == '--raw':
            show_raw = True
        elif a == '--division' and i + 1 < len(args):
            division_filter = args[i + 1]

    # If hledger is available and journals exist, use hledger
    journal_file = config.get('journal_file')
    hledger_available = _check_hledger() and journal_file

    if show_raw and hledger_available:
        _run_hledger_bs(config, period_end)
        return

    if show_monthly or show_quarterly:
        _show_periodic(config, 'monthly' if show_monthly else 'quarterly', period_end)
        return

    # Compute from YAML data (works without hledger)
    assets_data = _compute_assets(division_filter=division_filter)
    liabilities_data = _compute_liabilities(division_filter=division_filter)

    # Also try hledger for current assets (bank balances, receivables)
    current_assets_hledger = {}
    if hledger_available:
        current_assets_hledger = _query_current_assets(config, period_end, division_filter=division_filter)

    # Render report
    as_of = period_end or date.today().strftime("%Y-%m-%d")

    print()
    print("══════════════════════════════════════════════════════════════")
    print(f"  Entity Net Worth — {entity_name}")
    print(f"  As of {as_of}")
    print("══════════════════════════════════════════════════════════════")
    print()

    # ─── Assets ───
    print("  ASSETS")
    print("  ──────────────────────────────────────────────────────────")
    print()

    # Current assets (from hledger if available)
    total_current = Decimal('0')
    if current_assets_hledger:
        print("  Current Assets")
        for account, balance in sorted(current_assets_hledger.items()):
            short_name = account.split(':')[-1]
            total_current += balance
            print(f"    {short_name:<40} {currency} {balance:>12,.2f}")
        print(f"                                             {'─' * 16}")
        print(f"    {'Total Current Assets':<40} {currency} {total_current:>12,.2f}")
        print()

    # Fixed assets (from YAML)
    total_fixed = Decimal('0')
    if assets_data:
        if show_detail:
            print("  Fixed Assets                          Cost        Amort         NBV")
        else:
            print("  Fixed Assets (net book value)")

        for asset in assets_data:
            if show_detail:
                print(f"    {asset['name']:<30} {currency} {asset['cost']:>9,.2f}"
                      f"  ({currency} {asset['amort']:>9,.2f})"
                      f"  {currency} {asset['nbv']:>9,.2f}")
            else:
                print(f"    {asset['name']:<40} {currency} {asset['nbv']:>12,.2f}")
            total_fixed += asset['nbv']

        print(f"                                             {'─' * 16}")
        print(f"    {'Total Fixed Assets':<40} {currency} {total_fixed:>12,.2f}")
        print()

    total_assets = total_current + total_fixed
    print(f"                                             {'─' * 16}")
    print(f"  {'TOTAL ASSETS':<42} {currency} {total_assets:>12,.2f}")
    print()
    print()

    # ─── Liabilities ───
    print("  LIABILITIES")
    print("  ──────────────────────────────────────────────────────────")
    print()

    total_liabilities = Decimal('0')
    long_term = []
    short_term = []

    for liab in liabilities_data:
        if liab['term_type'] == 'long-term':
            long_term.append(liab)
        else:
            short_term.append(liab)

    if long_term:
        print("  Long-term")
        for liab in long_term:
            print(f"    {liab['name']:<40} {currency} {liab['balance']:>12,.2f}")
            total_liabilities += liab['balance']
        print()

    if short_term:
        print("  Short-term")
        for liab in short_term:
            print(f"    {liab['name']:<40} {currency} {liab['balance']:>12,.2f}")
            total_liabilities += liab['balance']
        print()

    # Add hledger liabilities (payables, HST, etc.) if available
    hledger_liabilities = {}
    if hledger_available:
        hledger_liabilities = _query_hledger_liabilities(config, period_end, division_filter=division_filter)
        if hledger_liabilities:
            # Don't double-count liabilities already in YAML
            yaml_accounts = {liab.get('account', '') for liab in liabilities_data}
            for account, balance in sorted(hledger_liabilities.items()):
                if account not in yaml_accounts and balance != 0:
                    short_name = account.split(':')[-1]
                    print(f"    {short_name:<40} {currency} {abs(balance):>12,.2f}")
                    total_liabilities += abs(balance)

    print(f"                                             {'─' * 16}")
    print(f"  {'TOTAL LIABILITIES':<42} {currency} {total_liabilities:>12,.2f}")
    print()
    print()

    # ─── Net Worth ───
    net_worth = total_assets - total_liabilities
    print("  ══════════════════════════════════════════════════════════")
    print(f"  {'NET WORTH (Equity)':<42} {currency} {net_worth:>12,.2f}")
    print("  ══════════════════════════════════════════════════════════")
    print()


# ─── Periodic trend ──────────────────────────────────────────────────────────

def _show_periodic(config, frequency, period_end):
    """Show net worth trend over time."""
    entity_name = config.get('pair', {}).get('name', 'Entity')
    currency = config.get('pair', {}).get('currency', 'CAD')
    journal_file = config.get('journal_file')

    if not journal_file or not _check_hledger():
        print("Periodic reports require hledger and a configured journal file.")
        print("Run 'pair init' to configure, or use 'pair worth' for a point-in-time report.")
        return

    journal_path = str(expand_path(journal_file))

    # Use hledger to get periodic balance sheet
    period_flag = '--monthly' if frequency == 'monthly' else '--quarterly'
    cmd = [
        'hledger', '-f', journal_path, 'bs',
        period_flag, '--output-format=csv'
    ]
    if period_end:
        cmd += ['-e', period_end]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"hledger error: {result.stderr.strip()}")
        return

    # Parse and display
    if result.stdout.strip():
        print(f"\n  Net Worth — {frequency.title()} ({entity_name})\n")
        print(result.stdout)
    else:
        print("  No data available for the specified period.")


# ─── Data computation from YAML ──────────────────────────────────────────────

def _compute_assets(division_filter=None):
    """Compute asset values from YAML files."""
    slugs = list_entities('assets')
    assets = []

    for slug in slugs:
        asset = load_entity('assets', slug)
        if not asset:
            continue
        # Skip disposed assets
        if asset.get('disposal', {}).get('date'):
            continue
        # Filter by division
        if division_filter and asset.get('division') != division_filter:
            continue

        cost = money(asset['cost'])
        # Calculate accumulated amortization
        amort = _asset_accumulated_amort(asset)
        nbv = cost - amort

        assets.append({
            'name': asset['name'],
            'slug': slug,
            'category': asset.get('category', 'other'),
            'cost': cost,
            'amort': amort,
            'nbv': nbv,
        })

    return assets


def _asset_accumulated_amort(asset):
    """Calculate accumulated amortization for an asset as of today."""
    from datetime import datetime
    from calendar import monthrange

    cost = Decimal(str(asset['cost']))
    salvage = Decimal(str(asset.get('salvage_value', 0)))
    total_depreciable = cost - salvage
    useful_life = asset['useful_life_months']
    method = asset['amortization_method']
    purchase_date = datetime.strptime(asset['purchase_date'], "%Y-%m-%d").date()
    today = date.today()

    if purchase_date >= today:
        return Decimal('0')

    accumulated = Decimal('0')

    # Count months elapsed
    current_year = purchase_date.year
    current_month = purchase_date.month

    for seq in range(useful_life):
        if seq == 0:
            entry_date = purchase_date
        else:
            entry_date = date(current_year, current_month, 1)

        if entry_date > today:
            break

        if method == 'straight-line':
            monthly = money(total_depreciable / useful_life)
            # Partial first month
            if seq == 0 and purchase_date.day > 1:
                days_in_month = monthrange(purchase_date.year, purchase_date.month)[1]
                days_remaining = days_in_month - purchase_date.day + 1
                monthly = money(monthly * days_remaining / days_in_month)
            # Final month
            if seq == useful_life - 1:
                monthly = total_depreciable - accumulated
            amount = monthly

        elif method == 'declining-balance':
            rate = Decimal(str(asset.get('declining_balance_rate', '0.20')))
            book_value = cost - accumulated
            monthly = money((rate / 12) * book_value)
            if seq == 0 and purchase_date.day > 1:
                days_in_month = monthrange(purchase_date.year, purchase_date.month)[1]
                days_remaining = days_in_month - purchase_date.day + 1
                monthly = money(monthly * days_remaining / days_in_month)
            if accumulated + monthly > total_depreciable:
                monthly = total_depreciable - accumulated
            amount = monthly
        else:
            break

        if amount <= 0:
            break

        accumulated += amount

        # Advance month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

    return accumulated


def _compute_liabilities(division_filter=None):
    """Compute liability balances from YAML files."""
    slugs = list_entities('liabilities')
    liabilities = []

    for slug in slugs:
        liab = load_entity('liabilities', slug)
        if not liab:
            continue
        # Filter by division
        if division_filter and liab.get('division') != division_filter:
            continue

        principal = money(liab['principal'])
        # Subtract principal payments made
        payments = liab.get('payments', [])
        paid_principal = sum(money(p.get('principal', 0)) for p in payments)
        remaining = principal - paid_principal

        if remaining <= 0:
            continue

        # Classify as long-term or short-term
        liab_type = liab.get('type', 'loan')
        if liab_type in ('loan', 'lease') and liab.get('term_months', 0) > 12:
            term_type = 'long-term'
        else:
            term_type = 'short-term'

        liabilities.append({
            'name': liab['name'],
            'slug': slug,
            'type': liab_type,
            'term_type': term_type,
            'balance': remaining,
            'account': liab.get('accounts', {}).get('liability', ''),
        })

    return liabilities


# ─── hledger queries ─────────────────────────────────────────────────────────

def _check_hledger():
    """Check if hledger is available."""
    try:
        result = subprocess.run(['hledger', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _query_current_assets(config, period_end=None, division_filter=None):
    """Query hledger for current asset balances."""
    journal_file = config.get('journal_file')
    if not journal_file:
        return {}

    journal_path = str(expand_path(journal_file))
    cmd = [
        'hledger', '-f', journal_path, 'bal',
        'Assets:Current', '--no-total', '--output-format=csv'
    ]
    if period_end:
        cmd += ['-e', period_end]
    if division_filter:
        cmd += [f'tag:division={division_filter}']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}
        return _parse_hledger_csv(result.stdout)
    except (FileNotFoundError, OSError):
        return {}


def _query_hledger_liabilities(config, period_end=None, division_filter=None):
    """Query hledger for liability balances not tracked in YAML."""
    journal_file = config.get('journal_file')
    if not journal_file:
        return {}

    journal_path = str(expand_path(journal_file))
    cmd = [
        'hledger', '-f', journal_path, 'bal',
        'Liabilities', '--no-total', '--output-format=csv'
    ]
    if period_end:
        cmd += ['-e', period_end]
    if division_filter:
        cmd += [f'tag:division={division_filter}']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {}
        return _parse_hledger_csv(result.stdout)
    except (FileNotFoundError, OSError):
        return {}


def _run_hledger_bs(config, period_end=None):
    """Run hledger bs directly (--raw mode)."""
    journal_file = config.get('journal_file')
    if not journal_file:
        print("No journal file configured.")
        return

    journal_path = str(expand_path(journal_file))
    cmd = ['hledger', '-f', journal_path, 'bs']
    if period_end:
        cmd += ['-e', period_end]

    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        print("hledger not found. Install from https://hledger.org/install.html")


def _parse_hledger_csv(csv_output):
    """Parse hledger CSV balance output into {account: Decimal} dict."""
    import csv
    from io import StringIO

    result = {}
    if not csv_output.strip():
        return result

    reader = csv.reader(StringIO(csv_output))
    header = next(reader, None)  # skip header row

    for row in reader:
        if len(row) >= 2:
            account = row[0].strip('"')
            balance_str = row[1].strip('"').replace(',', '')
            # Remove currency prefix if present
            parts = balance_str.split()
            if len(parts) == 2:
                balance_str = parts[1]
            elif len(parts) == 1:
                balance_str = parts[0]
            try:
                result[account] = Decimal(balance_str)
            except Exception:
                pass

    return result


# ─── Subcommands ─────────────────────────────────────────────────────────────

def cmd_breakdown(flags, args):
    """Detailed breakdown by category."""
    # For now, same as --detail
    cmd_worth(flags, ['--detail'] + args)


def cmd_trend(flags, args):
    """Trend over time."""
    cmd_worth(flags, ['--monthly'] + args)
