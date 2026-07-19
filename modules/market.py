"""pair market — commodity management, price fetching, and visualization."""

import sys
import re
import subprocess
import shutil
import json
from datetime import date, timedelta
from pathlib import Path

from lib.helpers import (
    load_config, save_config, get_entity_dir, get_active_entity,
    parse_global_flags, prompt, prompt_choice, confirm, ensure_dir,
    validate_date, validate_positive_number, slugify
)
from lib.ui import (
    get_entity_journal, get_entity_currency, require_entity,
    split_passthrough, show_menu, resolve_menu_or_direct,
    launch_tool, check_tool
)


# ─── Menu Options ────────────────────────────────────────────────────────────

MARKET_OPTIONS = [
    {'key': 'list',      'label': 'Show tracked commodities'},
    {'key': 'add',       'label': 'Add a commodity to track'},
    {'key': 'show',      'label': 'Current prices table'},
    {'key': 'edit',      'label': 'Edit a commodity'},
    {'key': 'remove',    'label': 'Remove a commodity'},
    {'key': 'fetch',     'label': 'Update all prices'},
    {'key': 'verify',    'label': 'Verify all commodities fetchable'},
    {'key': 'chart',     'label': 'Price history chart'},
    {'key': 'tag',       'label': 'Tag/untag commodities'},
    {'key': 'sources',   'label': 'Available price sources'},
    {'key': 'alert',     'label': 'Price drop alerts'},
    {'key': 'export',    'label': 'Cytoscape network export'},
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route market subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    pair_args, tool_args = split_passthrough(remaining)

    # Try direct selection
    selected, extra_args = resolve_menu_or_direct(pair_args, MARKET_OPTIONS)

    if selected is None and not pair_args:
        selected = show_menu("Market & Commodities", MARKET_OPTIONS)
        if selected is None:
            return
    elif selected is None:
        # Try legacy subcommands for backward compat
        action = pair_args[0]
        action_args = pair_args[1:] + tool_args
        if action == 'show':
            cmd_show(flags, action_args)
        elif action == 'fetch':
            cmd_fetch(flags, action_args)
        elif action == 'list':
            cmd_list(flags, action_args)
        elif action == 'add':
            cmd_add(flags, action_args)
        elif action == 'edit':
            cmd_edit(flags, action_args)
        elif action == 'remove':
            cmd_remove(flags, action_args)
        elif action == 'verify':
            cmd_verify(flags, action_args)
        elif action == 'chart':
            cmd_chart(flags, action_args)
        elif action == 'tag':
            cmd_tag(flags, action_args)
        elif action == 'sources':
            cmd_sources(flags, action_args)
        elif action == 'alert':
            _dispatch_alert(flags, action_args)
        elif action == 'export':
            cmd_export(flags, action_args)
        else:
            print(f"  Unknown market subcommand: {action}")
            print("  Run 'pair market --help' for usage.")
            sys.exit(1)
        return

    # Dispatch selected menu option
    key = selected['key']
    all_args = extra_args + tool_args
    if key == 'list':
        cmd_list(flags, all_args)
    elif key == 'add':
        cmd_add(flags, all_args)
    elif key == 'show':
        cmd_show(flags, all_args)
    elif key == 'edit':
        cmd_edit(flags, all_args)
    elif key == 'remove':
        cmd_remove(flags, all_args)
    elif key == 'fetch':
        cmd_fetch(flags, all_args)
    elif key == 'verify':
        cmd_verify(flags, all_args)
    elif key == 'chart':
        cmd_chart(flags, all_args)
    elif key == 'tag':
        cmd_tag(flags, all_args)
    elif key == 'sources':
        cmd_sources(flags, all_args)
    elif key == 'alert':
        _dispatch_alert(flags, all_args)
    elif key == 'export':
        cmd_export(flags, all_args)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_prices_journal():
    """Return path to the entity's include/prices.journal."""
    return get_entity_dir() / 'include' / 'prices.journal'


def _ensure_prices_journal():
    """Create include/prices.journal if it doesn't exist."""
    prices_file = _get_prices_journal()
    ensure_dir(prices_file.parent)
    if not prices_file.exists():
        entity = get_active_entity()
        prices_file.write_text(
            f"; {entity} — market price data\n"
            f"; Updated by: pair market fetch\n\n"
        )
    return prices_file


def _get_commodities():
    """Return list of configured commodities from entity config."""
    config = load_config()
    market = config.get('market', {})
    return market.get('commodities', [])


def _save_commodities(commodities):
    """Save commodities list back to entity config."""
    config = load_config()
    if 'market' not in config:
        config['market'] = {}
    config['market']['commodities'] = commodities
    save_config(config)


def _find_commodity(identifier):
    """Find a commodity by symbol or list index (1-based). Returns (commodity, index) or (None, None)."""
    commodities = _get_commodities()
    if not commodities:
        return None, None

    # Try as index
    try:
        idx = int(identifier) - 1
        if 0 <= idx < len(commodities):
            return commodities[idx], idx
    except (ValueError, TypeError):
        pass

    # Try as symbol (case-insensitive)
    for i, c in enumerate(commodities):
        if c['symbol'].lower() == identifier.lower():
            return c, i

    return None, None


def _filter_commodities(commodities, args):
    """Filter commodities list by --tag, --type, --sector, etc from args."""
    filtered = commodities
    i = 0
    while i < len(args):
        if args[i] == '--tag' and i + 1 < len(args):
            tag = args[i + 1].lower()
            filtered = [c for c in filtered if tag in [t.lower() for t in c.get('tags', [])]]
            i += 2
        elif args[i] == '--type' and i + 1 < len(args):
            t = args[i + 1].lower()
            filtered = [c for c in filtered if c.get('type', '').lower() == t]
            i += 2
        elif args[i] == '--sector' and i + 1 < len(args):
            s = args[i + 1].lower()
            filtered = [c for c in filtered if c.get('sector', '').lower() == s]
            i += 2
        elif args[i] == '--geography' and i + 1 < len(args):
            g = args[i + 1].lower()
            filtered = [c for c in filtered if c.get('geography', '').lower() == g]
            i += 2
        else:
            i += 1
    return filtered


def _existing_directives(prices_file):
    """Return set of existing P directive lines (stripped) from prices.journal."""
    if not prices_file.exists():
        return set()
    existing = set()
    for line in prices_file.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith('P '):
            existing.add(stripped)
    return existing


def _build_fetch_pair(commodity):
    """Build the pair/symbol argument for pricehist."""
    if 'fetch_pair' in commodity:
        return commodity['fetch_pair']
    if 'pair' in commodity:
        return commodity['pair']
    return commodity['symbol']


def _pricehist_available():
    """Check if pricehist is on PATH."""
    return shutil.which('pricehist') is not None


# ─── Commands: List / Show / Sources ──────────────────────────────────────────

def cmd_list(flags, args):
    """List configured commodities with metadata."""
    entity = get_active_entity()
    commodities = _get_commodities()

    if not commodities:
        print(f"\n  [{entity}] No commodities configured.")
        print("  Run 'pair market add' to add one.\n")
        return

    # Apply filters
    filtered = _filter_commodities(commodities, args)

    print(f"\n  [{entity}] Tracked Commodities")
    print(f"  {'─' * 65}")
    print(f"  {'#':<4}{'Symbol':<12}{'Name':<22}{'Type':<10}{'Source':<10}{'Tags'}")
    print(f"  {'─' * 65}")
    for i, c in enumerate(filtered, 1):
        tags = ', '.join(c.get('tags', []))
        print(f"  {i:<4}{c['symbol']:<12}{c.get('name', ''):<22}{c.get('type', ''):<10}{c.get('source', ''):<10}{tags}")
    print(f"  {'─' * 65}")
    print(f"  {len(filtered)} commodities tracked.\n")


def cmd_show(flags, args):
    """Show current prices with deltas."""
    entity = get_active_entity()
    prices_file = _get_prices_journal()

    if not prices_file.exists():
        print(f"\n  [{entity}] No prices.journal found.")
        print("  Run 'pair market fetch' to fetch prices.\n")
        return

    # Parse all price directives
    from collections import defaultdict
    prices = defaultdict(list)

    for line in prices_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith('P '):
            continue
        parts = stripped.split()
        p_date = parts[1]
        # Handle quoted commodity
        rest = stripped.split(None, 2)[2]
        if rest.startswith('"'):
            end_q = rest.index('"', 1)
            symbol = rest[1:end_q]
            remainder = rest[end_q + 1:].split()
        else:
            remainder = rest.split()
            symbol = remainder[0]
            remainder = remainder[1:]
        try:
            amount = float(remainder[1])
            prices[symbol].append((p_date, amount))
        except (IndexError, ValueError):
            continue

    if not prices:
        print(f"\n  [{entity}] No price directives found.\n")
        return

    currency = get_entity_currency()

    print(f"\n  [{entity}] Current Prices (base: {currency})")
    print(f"  {'─' * 55}")
    print(f"  {'Symbol':<12}{'Latest':<16}{'Date':<14}{'Entries'}")
    print(f"  {'─' * 55}")

    for symbol in sorted(prices.keys()):
        data = sorted(prices[symbol], key=lambda x: x[0])
        last_date, last_price = data[-1]
        count = len(data)
        print(f"  {symbol:<12}{currency} {last_price:<12,.2f}{last_date:<14}{count}")

    print(f"  {'─' * 55}\n")


def cmd_sources(flags, args):
    """Show available pricehist sources."""
    if not _pricehist_available():
        print("\n  pricehist is not installed. Install: pip install pricehist\n")
        return

    print("\n  Available pricehist sources:\n")
    result = subprocess.run(['pricehist', 'sources'], capture_output=True, text=True)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            print(f"  {line}")
    print()


# ─── Commands: Add (with Yahoo search) ───────────────────────────────────────

def _yahoo_search(query):
    """Search Yahoo Finance for a symbol/company name. Returns list of results."""
    try:
        from urllib.request import urlopen, Request
        from urllib.parse import urlencode
        import json as _json

        params = urlencode({'q': query, 'newsCount': 0, 'listsCount': 0, 'quotesCount': 10})
        url = f"https://query2.finance.yahoo.com/v1/finance/search?{params}"
        req = Request(url, headers={'User-Agent': 'pair/1.0'})
        resp = urlopen(req, timeout=10)
        data = _json.loads(resp.read().decode())

        results = []
        for q in data.get('quotes', []):
            results.append({
                'symbol': q.get('symbol', ''),
                'name': q.get('longname') or q.get('shortname', ''),
                'exchange': q.get('exchange', ''),
                'type': q.get('quoteType', '').lower(),
                'currency': q.get('currency', ''),
            })
        return results
    except Exception:
        return []


def cmd_add(flags, args):
    """Add a commodity with optional Yahoo search resolution."""
    entity = get_active_entity()
    base_currency = get_entity_currency()

    print(f"\n  [{entity}] Add commodity\n")

    # If args provided, use as search query
    query = ' '.join(args) if args else prompt("  Symbol or company name")

    # Try Yahoo search
    print(f"  Searching \"{query}\"...")
    results = _yahoo_search(query)

    selected_result = None

    if results:
        # Mark results matching entity currency
        print(f"\n  {'#':<4}{'Symbol':<14}{'Exchange':<10}{'Name':<30}{'Currency'}")
        print(f"  {'─' * 70}")
        for i, r in enumerate(results[:8], 1):
            star = ' ★' if r['currency'] == base_currency else ''
            print(f"  {i:<4}{r['symbol']:<14}{r['exchange']:<10}{r['name']:<30}{r['currency']}{star}")
        print(f"\n  ★ = matches entity currency ({base_currency})")

        raw = prompt("\n  Select [#], or Enter to enter manually", required=False)
        if raw:
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(results):
                    selected_result = results[idx]
            except ValueError:
                pass
    else:
        print("  No results found. Enter details manually.")

    # Build commodity entry
    if selected_result:
        symbol = selected_result['symbol']
        name = selected_result.get('name', '')
        source = 'yahoo'
        fetch_pair = symbol
        currency = selected_result.get('currency', base_currency)

        # For crypto: BTC-CAD → store as BTC
        store_symbol = symbol
        if '-' in symbol and selected_result.get('type') == 'cryptocurrency':
            store_symbol = symbol.split('-')[0]

        print(f"\n  Found: {symbol} — {name} ({currency})")
        store_symbol = prompt(f"  Store as symbol", default=store_symbol)
        name = prompt(f"  Name", default=name, required=False)
    else:
        store_symbol = prompt("  Symbol (e.g. SHOP.TO, BTC)")
        name = prompt("  Name (e.g. Shopify Inc)", required=False)
        sources = ['yahoo', 'bankofcanada', 'ecb', 'coinbasepro', 'alphavantage']
        source = prompt_choice("  Price source:", sources, default='yahoo')
        fetch_pair = prompt(f"  Fetch pair/symbol for pricehist", default=store_symbol)
        currency = prompt(f"  Quote currency", default=base_currency)

    # Optional metadata
    comm_type = prompt("  Type (equity/crypto/currency/etf/commodity)", default='equity', required=False)
    sector = prompt("  Sector (tech/health/financial/energy/...)", required=False)
    geography = prompt("  Geography (canada/us/europe/global)", required=False)
    strategy = prompt("  Strategy (growth/income/spec/hedge/core)", required=False)
    risk = prompt("  Risk (low/med/high/extreme)", required=False)
    tax_account = prompt("  Tax account (tfsa/rrsp/taxable/corporate)", required=False)
    tags_raw = prompt("  Tags (comma-separated)", required=False)
    tags = [t.strip() for t in tags_raw.split(',') if t.strip()] if tags_raw else []

    entry = {'symbol': store_symbol}
    if name:
        entry['name'] = name
    entry['source'] = source if not selected_result else 'yahoo'
    entry['fetch_pair'] = fetch_pair if not selected_result else symbol
    entry['currency'] = currency if not selected_result else selected_result.get('currency', base_currency)
    if comm_type:
        entry['type'] = comm_type
    if sector:
        entry['sector'] = sector
    if geography:
        entry['geography'] = geography
    if strategy:
        entry['strategy'] = strategy
    if risk:
        entry['risk'] = risk
    if tax_account:
        entry['tax_account'] = tax_account
    if tags:
        entry['tags'] = tags

    # Save
    commodities = _get_commodities()
    existing_symbols = [c['symbol'].lower() for c in commodities]
    if store_symbol.lower() in existing_symbols:
        if not confirm(f"  '{store_symbol}' already exists. Replace?", default_yes=False):
            print("  Cancelled.\n")
            return
        commodities = [c for c in commodities if c['symbol'].lower() != store_symbol.lower()]

    commodities.append(entry)
    _save_commodities(commodities)
    _ensure_prices_journal()

    print(f"\n  ✓ Added {store_symbol}")
    if not flags.get('batch') and confirm("  Fetch prices now?"):
        cmd_fetch(flags, ['--symbol', store_symbol, '--days', '30'])


# ─── Commands: Edit / Remove / Tag ───────────────────────────────────────────

def cmd_edit(flags, args):
    """Edit an existing commodity's metadata."""
    entity = get_active_entity()
    commodities = _get_commodities()

    if not commodities:
        print(f"\n  [{entity}] No commodities configured.\n")
        return

    # Identify which commodity
    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Commodity to edit (# or symbol)")

    commodity, idx = _find_commodity(identifier)
    if commodity is None:
        print(f"  Commodity '{identifier}' not found.\n")
        return

    print(f"\n  Editing: {commodity['symbol']} ({commodity.get('name', '')})")
    print(f"  {'─' * 45}")

    fields = [
        ('symbol', commodity.get('symbol', '')),
        ('name', commodity.get('name', '')),
        ('source', commodity.get('source', '')),
        ('fetch_pair', commodity.get('fetch_pair', '')),
        ('currency', commodity.get('currency', '')),
        ('type', commodity.get('type', '')),
        ('sector', commodity.get('sector', '')),
        ('geography', commodity.get('geography', '')),
        ('strategy', commodity.get('strategy', '')),
        ('risk', commodity.get('risk', '')),
        ('tax_account', commodity.get('tax_account', '')),
        ('tags', ', '.join(commodity.get('tags', []))),
    ]

    for i, (key, val) in enumerate(fields, 1):
        print(f"  {i:>2}) {key}: {val}")

    print(f"\n  Enter field number to edit, or Enter to finish.")

    while True:
        raw = prompt("  Field #", required=False)
        if not raw:
            break
        try:
            field_idx = int(raw) - 1
            if 0 <= field_idx < len(fields):
                key, old_val = fields[field_idx]
                if key == 'tags':
                    new_val = prompt(f"  {key}", default=old_val, required=False)
                    commodity['tags'] = [t.strip() for t in new_val.split(',') if t.strip()]
                else:
                    new_val = prompt(f"  {key}", default=old_val, required=False)
                    if new_val:
                        commodity[key] = new_val
                    elif key in commodity:
                        del commodity[key]
                fields[field_idx] = (key, new_val)
                print(f"  Updated {key}.")
        except ValueError:
            print("  Enter a number.")

    commodities[idx] = commodity
    _save_commodities(commodities)
    print(f"\n  ✓ Saved changes to {commodity['symbol']}.\n")


def cmd_remove(flags, args):
    """Remove a commodity from tracking."""
    entity = get_active_entity()
    commodities = _get_commodities()

    if not commodities:
        print(f"\n  [{entity}] No commodities configured.\n")
        return

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Commodity to remove (# or symbol)")

    commodity, idx = _find_commodity(identifier)
    if commodity is None:
        print(f"  Commodity '{identifier}' not found.\n")
        return

    if not flags.get('yes'):
        if not confirm(f"  Remove {commodity['symbol']} ({commodity.get('name', '')})? "
                       f"(price history in prices.journal is NOT deleted)"):
            print("  Cancelled.\n")
            return

    commodities.pop(idx)
    _save_commodities(commodities)
    print(f"  ✓ Removed {commodity['symbol']} from tracked commodities.\n")


def cmd_tag(flags, args):
    """Tag/untag commodities or list tags."""
    entity = get_active_entity()
    commodities = _get_commodities()

    if not commodities:
        print(f"\n  [{entity}] No commodities configured.\n")
        return

    # pair market tag --list
    if '--list' in args:
        from collections import Counter
        tag_counts = Counter()
        for c in commodities:
            for t in c.get('tags', []):
                tag_counts[t] += 1
        if not tag_counts:
            print(f"\n  [{entity}] No tags in use.\n")
            return
        print(f"\n  [{entity}] Tags in use:")
        for tag, count in sorted(tag_counts.items()):
            print(f"    {tag} ({count})")
        print()
        return

    # pair market tag SYMBOL TAG
    if '--remove' in args:
        # pair market tag SYMBOL --remove TAG
        rm_idx = args.index('--remove')
        identifier = args[0] if args[0] != '--remove' else None
        tag_to_remove = args[rm_idx + 1] if rm_idx + 1 < len(args) else None
        if not identifier or not tag_to_remove:
            print("  Usage: pair market tag SYMBOL --remove TAG")
            return
        commodity, idx = _find_commodity(identifier)
        if commodity is None:
            print(f"  Commodity '{identifier}' not found.\n")
            return
        tags = commodity.get('tags', [])
        if tag_to_remove in tags:
            tags.remove(tag_to_remove)
            commodity['tags'] = tags
            commodities[idx] = commodity
            _save_commodities(commodities)
            print(f"  ✓ Removed tag '{tag_to_remove}' from {commodity['symbol']}.\n")
        else:
            print(f"  Tag '{tag_to_remove}' not on {commodity['symbol']}.\n")
        return

    # pair market tag SYMBOL TAG (add tag)
    if len(args) >= 2:
        identifier = args[0]
        new_tag = args[1]
        commodity, idx = _find_commodity(identifier)
        if commodity is None:
            print(f"  Commodity '{identifier}' not found.\n")
            return
        tags = commodity.get('tags', [])
        if new_tag not in tags:
            tags.append(new_tag)
            commodity['tags'] = tags
            commodities[idx] = commodity
            _save_commodities(commodities)
            print(f"  ✓ Added tag '{new_tag}' to {commodity['symbol']}.\n")
        else:
            print(f"  Tag '{new_tag}' already on {commodity['symbol']}.\n")
        return

    # pair market tag TAG (show commodities with tag)
    if len(args) == 1:
        tag = args[0]
        matched = [c for c in commodities if tag in c.get('tags', [])]
        if matched:
            print(f"\n  Commodities tagged '{tag}':")
            for c in matched:
                print(f"    {c['symbol']:<12} {c.get('name', '')}")
            print()
        else:
            print(f"  No commodities tagged '{tag}'.\n")
        return

    # No args — show usage
    print("  Usage:")
    print("    pair market tag --list              List all tags")
    print("    pair market tag SYMBOL TAG          Add a tag")
    print("    pair market tag SYMBOL --remove TAG Remove a tag")
    print("    pair market tag TAG                 Show commodities with tag")
    print()


# ─── Commands: Fetch / Verify / Chart ─────────────────────────────────────────

def cmd_fetch(flags, args):
    """Fetch prices using pricehist, append to prices.journal."""
    if not _pricehist_available():
        print("\n  pricehist is not installed. Install: pip install pricehist\n")
        return

    # Parse flags
    symbol_filter = None
    days = 7
    i = 0
    while i < len(args):
        if args[i] == '--symbol' and i + 1 < len(args):
            symbol_filter = args[i + 1]
            i += 2
        elif args[i] == '--days' and i + 1 < len(args):
            try:
                days = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            # Bare arg = symbol filter
            if not args[i].startswith('--'):
                symbol_filter = args[i]
            i += 1

    commodities = _get_commodities()
    if not commodities:
        print("\n  No commodities configured. Run 'pair market add'.\n")
        return

    # Apply filters
    if symbol_filter:
        commodities = [c for c in commodities if c['symbol'].lower() == symbol_filter.lower()]
        if not commodities:
            print(f"\n  Commodity '{symbol_filter}' not found.\n")
            return
    else:
        commodities = _filter_commodities(commodities, args)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    prices_file = _ensure_prices_journal()
    existing = _existing_directives(prices_file)
    entity = get_active_entity()
    total_new = 0

    print(f"\n  [{entity}] Fetching prices ({start_str} to {end_str})...\n")

    for commodity in commodities:
        source = commodity.get('source', 'yahoo')
        pair_str = _build_fetch_pair(commodity)

        cmd = ['pricehist', 'fetch', '-o', 'ledger', '-s', start_str, '-e', end_str, source, pair_str]

        if flags.get('dry_run'):
            print(f"  Would run: {' '.join(cmd)}")
            continue

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            print(f"  ✗ {commodity['symbol']}: timeout")
            continue
        except Exception as e:
            print(f"  ✗ {commodity['symbol']}: {e}")
            continue

        if result.returncode != 0:
            print(f"  ✗ {commodity['symbol']}: {result.stderr.strip() or 'fetch failed'}")
            continue

        # Parse pricehist output and rewrite to standard hledger format
        new_lines = []
        output_symbol = commodity['symbol']
        quoted_symbol = f'"{output_symbol}"' if any(c in output_symbol for c in './-') else output_symbol

        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped.startswith('P '):
                continue
            parts = stripped.split()
            if len(parts) < 5:
                continue

            p_date = parts[1]
            idx = 3 if ':' in parts[2] else 2  # skip time field if present
            raw_price = parts[idx + 1] if idx + 1 < len(parts) else parts[idx]
            raw_currency = parts[idx + 2] if idx + 2 < len(parts) else commodity.get('currency', 'CAD')

            directive = f"P {p_date} {quoted_symbol} {raw_currency} {raw_price}"

            if directive not in existing:
                new_lines.append(directive)
                existing.add(directive)

        if new_lines:
            with open(prices_file, 'a') as f:
                for line in new_lines:
                    f.write(line + '\n')
            print(f"  ✓ {commodity['symbol']}: {len(new_lines)} new price(s)")
            total_new += len(new_lines)
        else:
            print(f"  · {commodity['symbol']}: no new prices")

    print(f"\n  Done. {total_new} new directive(s) added.\n")


def cmd_verify(flags, args):
    """Verify all commodities are fetchable and check for gaps."""
    if not _pricehist_available():
        print("\n  pricehist is not installed.\n")
        return

    commodities = _get_commodities()
    if not commodities:
        print("\n  No commodities configured.\n")
        return

    entity = get_active_entity()
    deep = '--deep' in args

    print(f"\n  [{entity}] Verifying {len(commodities)} commodities...\n")

    ok_count = 0
    fail_count = 0

    for commodity in commodities:
        source = commodity.get('source', 'yahoo')
        pair_str = _build_fetch_pair(commodity)
        symbol = commodity['symbol']

        # Try a 3-day fetch to verify connectivity
        end_date = date.today()
        start_date = end_date - timedelta(days=5)
        cmd = ['pricehist', 'fetch', '-o', 'ledger',
               '-s', start_date.strftime("%Y-%m-%d"),
               '-e', end_date.strftime("%Y-%m-%d"),
               source, pair_str]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                # Get latest price from output
                lines = [l for l in result.stdout.splitlines() if l.strip().startswith('P ')]
                if lines:
                    print(f"  {symbol:<12} ✓ fetchable   ({len(lines)} price(s) in last 5 days)")
                    ok_count += 1
                else:
                    print(f"  {symbol:<12} ⚠ no data     source: {source}, pair: {pair_str}")
                    fail_count += 1
            else:
                err = result.stderr.strip()[:60] if result.stderr else 'no data'
                print(f"  {symbol:<12} ✗ FAILED      {err}")
                fail_count += 1
        except subprocess.TimeoutExpired:
            print(f"  {symbol:<12} ✗ timeout")
            fail_count += 1
        except Exception as e:
            print(f"  {symbol:<12} ✗ error: {e}")
            fail_count += 1

        # Deep check: look at prices.journal for gaps
        if deep:
            _check_price_gaps(symbol)

    print(f"\n  {ok_count}/{len(commodities)} verified.", end='')
    if fail_count:
        print(f" {fail_count} need attention.")
    else:
        print(" All good.")
    print()


def _check_price_gaps(symbol):
    """Check prices.journal for gaps in a commodity's history."""
    from datetime import datetime
    prices_file = _get_prices_journal()
    if not prices_file.exists():
        return

    dates = []
    for line in prices_file.read_text().splitlines():
        if not line.strip().startswith('P '):
            continue
        # Check if this line is for our symbol
        if symbol in line or f'"{symbol}"' in line:
            parts = line.split()
            try:
                d = datetime.strptime(parts[1], "%Y-%m-%d")
                dates.append(d)
            except (ValueError, IndexError):
                pass

    if not dates:
        print(f"             ⚠ no price history in prices.journal")
        return

    dates.sort()
    print(f"             {len(dates)} entries ({dates[0].strftime('%Y-%m-%d')} → {dates[-1].strftime('%Y-%m-%d')})")

    # Find gaps > 5 days
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap > 5:
            print(f"             ⚠ gap: {gap} days ({dates[i-1].strftime('%Y-%m-%d')} → {dates[i].strftime('%Y-%m-%d')})")


def cmd_chart(flags, args):
    """Generate price history chart."""
    entity = get_active_entity()
    prices_file = _get_prices_journal()

    if not prices_file.exists():
        print(f"\n  [{entity}] No prices.journal found.\n")
        return

    # Optional: filter to specific commodity
    symbol_filter = None
    for a in args:
        if not a.startswith('--'):
            symbol_filter = a
            break

    # Use pair's venv python for matplotlib
    venv_python = Path(__file__).resolve().parent.parent / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        print("  matplotlib not available. Run: python3 -m venv .venv && .venv/bin/pip install matplotlib")
        return

    currency = get_entity_currency()
    out_path = f"/tmp/{entity}_prices.png"
    filter_arg = symbol_filter or ''

    script = f'''
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from collections import defaultdict

prices = defaultdict(list)
with open("{prices_file}") as f:
    for line in f:
        if not line.strip().startswith("P "):
            continue
        parts = line.split(None, 2)
        p_date = parts[1]
        rest = parts[2]
        if rest.startswith('"'):
            end_q = rest.index('"', 1)
            symbol = rest[1:end_q]
            remainder = rest[end_q + 1:].split()
        else:
            remainder = rest.split()
            symbol = remainder[0]
            remainder = remainder[1:]
        try:
            amount = float(remainder[1])
            d = datetime.strptime(p_date, "%Y-%m-%d")
            prices[symbol].append((d, amount))
        except (IndexError, ValueError):
            continue

filter_sym = "{filter_arg}"
if filter_sym:
    prices = {{k: v for k, v in prices.items() if k.lower() == filter_sym.lower()}}

if not prices:
    print("  No price data found.")
    exit(0)

n = len(prices)
fig, axes = plt.subplots(n, 1, figsize=(10, 3 * n), sharex=False)
if n == 1:
    axes = [axes]

for ax, (symbol, data) in zip(axes, sorted(prices.items())):
    data.sort()
    dates, vals = zip(*data)
    ax.plot(dates, vals, marker=".", markersize=3, linewidth=1.2)
    ax.set_title(f"{{symbol}} / {currency}")
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("{currency}")

fig.tight_layout()
plt.savefig("{out_path}", dpi=150)
plt.close()
print("  ✓ Chart saved: {out_path}")
'''

    proc = subprocess.run([str(venv_python), '-c', script], capture_output=True, text=True)
    if proc.stdout:
        print(f"\n{proc.stdout}")
    if proc.stderr:
        print(f"  Error: {proc.stderr.strip()}\n")


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair market — commodity management, price fetching, and visualization

Usage: pair market [COMMAND] [OPTIONS]

With no argument, shows a numbered menu.

Commands:
  list                  List tracked commodities
  add [QUERY]           Add a commodity (Yahoo search + interactive)
  show                  Current prices table
  edit [SYMBOL|#]       Edit commodity metadata
  remove [SYMBOL|#]     Remove a commodity from tracking
  fetch [SYMBOL]        Fetch prices for all/one commodity
  verify [--deep]       Verify all commodities are fetchable
  chart [SYMBOL]        Generate price history chart (PNG)
  tag                   Tag management (see below)
  sources               Show available pricehist sources

Fetch options:
  --symbol SYMBOL       Fetch only this commodity
  --days N              Fetch last N days (default: 7)
  --tag TAG             Fetch only commodities with this tag
  --type TYPE           Fetch only this type (equity/crypto/etc)

Tag usage:
  pair market tag --list              List all tags in use
  pair market tag SYMBOL TAG          Add a tag to a commodity
  pair market tag SYMBOL --remove TAG Remove a tag
  pair market tag TAG                 Show commodities with a tag

Filter options (list/fetch):
  --tag TAG             Filter by tag
  --type TYPE           Filter by type
  --sector SECTOR       Filter by sector
  --geography GEO       Filter by geography

Aliases:
  pair prices           Same as 'pair market show'

Examples:
  pair market                         Interactive menu
  pair market add shopify             Search + add
  pair market fetch --days 30         Fetch last 30 days
  pair market verify --deep           Check connectivity + gaps
  pair market chart BTC               Chart BTC price history
  pair market tag BTC crypto          Tag BTC as 'crypto'
  pair market list --type equity      List only equities

Alert commands (see 'pair market alert --help'):
  pair market alert add               Add price drop alert
  pair market alert list              Show configured alerts
  pair market alert check             Check alerts now
  pair market alert check --loop      Poll continuously
  pair market alert remove SYMBOL     Remove an alert
""")



# ─── Cytoscape Export ─────────────────────────────────────────────────────────

EXPORT_OPTIONS = [
    {'key': 'accounts',    'label': 'Account chart (hierarchy)'},
    {'key': 'correlation', 'label': 'Price correlation network'},
    {'key': 'temporal',    'label': 'Temporal price network'},
    {'key': 'momentum',    'label': 'Momentum state machine'},
]

TEMPORAL_LAYOUTS = ['grid', 'spiral', 'river', 'radial']


def cmd_export(flags, args):
    """Export data as Cytoscape GML network files."""
    entity = get_active_entity()
    entity_dir = get_entity_dir()
    out_dir = entity_dir / 'output'
    ensure_dir(out_dir)

    # Parse args
    export_type = None
    layout = None
    i = 0
    while i < len(args):
        if args[i] == '--layout' and i + 1 < len(args):
            layout = args[i + 1]
            i += 2
        elif not args[i].startswith('-'):
            export_type = args[i]
            i += 1
        else:
            i += 1

    # Interactive if no type given
    if not export_type:
        selected = show_menu("Cytoscape Export", EXPORT_OPTIONS)
        if selected is None:
            return
        export_type = selected['key']

    if export_type == 'accounts':
        _export_accounts(flags, entity, out_dir)
    elif export_type == 'correlation':
        _export_correlation(flags, entity, out_dir)
    elif export_type == 'temporal':
        _export_temporal(flags, entity, out_dir, layout)
    elif export_type == 'momentum':
        _export_momentum(flags, entity, out_dir)
    else:
        print(f"  Unknown export type: {export_type}")
        print("  Options: accounts, correlation, temporal, momentum")



def _write_gml(filepath, title, nodes, edges):
    """Write a GML file with embedded visual properties.

    nodes: list of dicts with keys: id, label, x, y, size, color, shape (optional)
    edges: list of dicts with keys: id, source, target, label, width, color, arrow (optional)
    """
    lines = []
    lines.append('graph [')
    lines.append(f'  directed 1')
    lines.append(f'  label "{title}"')

    for n in nodes:
        shape = n.get('shape', 'ellipse')
        lines.append(f'  node [')
        lines.append(f'    id {n["id"]}')
        lines.append(f'    label "{n["label"]}"')
        lines.append(f'    graphics [')
        lines.append(f'      x {n["x"]:.1f}')
        lines.append(f'      y {n["y"]:.1f}')
        lines.append(f'      w {n["size"]:.1f}')
        lines.append(f'      h {n["size"]:.1f}')
        lines.append(f'      type "{shape}"')
        lines.append(f'      fill "{n["color"]}"')
        lines.append(f'      outline "#333333"')
        lines.append(f'      outline_width 1.5')
        lines.append(f'    ]')
        lines.append(f'    LabelGraphics [')
        lines.append(f'      text "{n["label"]}"')
        lines.append(f'      fontSize {n.get("font_size", 10)}')
        lines.append(f'      fontName "Dialog"')
        lines.append(f'      anchor "s"')
        lines.append(f'    ]')
        lines.append(f'  ]')

    for e in edges:
        arrow = e.get('arrow', 'standard')
        lines.append(f'  edge [')
        lines.append(f'    id {e["id"]}')
        lines.append(f'    source {e["source"]}')
        lines.append(f'    target {e["target"]}')
        lines.append(f'    label "{e.get("label", "")}"')
        lines.append(f'    graphics [')
        lines.append(f'      width {e["width"]:.1f}')
        lines.append(f'      fill "{e["color"]}"')
        lines.append(f'      type "line"')
        lines.append(f'      targetArrow "{arrow}"')
        lines.append(f'    ]')
        if e.get('label'):
            lines.append(f'    LabelGraphics [')
            lines.append(f'      text "{e["label"]}"')
            lines.append(f'      fontSize 9')
            lines.append(f'      fontName "Dialog"')
            lines.append(f'    ]')
        lines.append(f'  ]')

    lines.append(']')
    Path(filepath).write_text('\n'.join(lines) + '\n')



def _parse_price_data():
    """Parse prices.journal into {symbol: {date: price}} dict."""
    from collections import defaultdict
    prices_file = _get_prices_journal()
    data = defaultdict(dict)
    if not prices_file.exists():
        return data
    for line in prices_file.read_text().splitlines():
        if not line.strip().startswith('P '):
            continue
        parts = line.split()
        p_date = parts[1]
        rest = line.split(None, 2)[2]
        if rest.startswith('"'):
            end = rest.index('"', 1)
            sym = rest[1:end]
            remainder = rest[end + 1:].split()
        else:
            toks = rest.split()
            sym = toks[0]
            remainder = toks[1:]
        try:
            price = float(remainder[1]) if len(remainder) >= 2 else float(remainder[0])
        except (ValueError, IndexError):
            continue
        data[sym][p_date] = price
    return data


def _compute_returns(data):
    """Compute daily % returns from price data. Returns {symbol: {date: pct}}."""
    returns = {}
    for sym, prices in data.items():
        sorted_dates = sorted(prices.keys())
        sym_returns = {}
        for i in range(1, len(sorted_dates)):
            prev = prices[sorted_dates[i - 1]]
            curr = prices[sorted_dates[i]]
            if prev > 0:
                sym_returns[sorted_dates[i]] = (curr - prev) / prev * 100
        returns[sym] = sym_returns
    return returns


def _pct_to_color(pct):
    """Map daily % change to green/red/grey color."""
    if pct > 0.5:
        intensity = min(pct / 5, 1.0)
        return f"#{int(80*(1-intensity)):02x}{int(150+105*intensity):02x}{int(80*(1-intensity)):02x}"
    elif pct < -0.5:
        intensity = min(abs(pct) / 5, 1.0)
        return f"#{int(150+105*intensity):02x}{int(80*(1-intensity)):02x}{int(80*(1-intensity)):02x}"
    return "#aaaaaa"



def _export_accounts(flags, entity, out_dir):
    """Export account chart as hierarchical Cytoscape GML."""
    import colorsys
    import math

    config = load_config()
    entity_name = config.get('pair', {}).get('name', entity)
    journal = get_entity_dir() / 'include' / 'entity.journal'

    if not journal.exists():
        print(f"\n  [{entity}] No entity journal found.\n")
        return

    # Get accounts and balances
    result = subprocess.run(['hledger', 'accounts', '-f', str(journal)],
                           capture_output=True, text=True)
    accounts = [l for l in result.stdout.strip().splitlines() if l.strip()]

    result = subprocess.run(
        ['hledger', 'balance', '-f', str(journal), '--flat', '--no-total', '-O', 'csv'],
        capture_output=True, text=True)
    balances = {}
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split('","')
        if len(parts) == 2:
            acct = parts[0].strip('"')
            val_str = parts[1].strip('"').replace('CAD ', '').replace(',', '')
            try:
                balances[acct] = abs(float(val_str))
            except ValueError:
                pass

    # Build tree
    nodes_set = set()
    node_meta = {}
    children = {}
    edges_list = []

    for acct in accounts:
        parts = acct.split(':')
        for i, part in enumerate(parts):
            full_path = ':'.join(parts[:i + 1])
            parent = ':'.join(parts[:i]) if i > 0 else None
            if full_path not in nodes_set:
                nodes_set.add(full_path)
                node_meta[full_path] = {
                    'short_name': part, 'depth': i + 1,
                    'account_type': parts[0], 'is_leaf': True,
                }
            if parent and parent in nodes_set:
                if (parent, full_path) not in edges_list:
                    edges_list.append((parent, full_path))
                    children.setdefault(parent, []).append(full_path)
                    node_meta[parent]['is_leaf'] = False

    # Add root
    root_id = entity_name
    nodes_set.add(root_id)
    node_meta[root_id] = {'short_name': entity_name, 'depth': 0,
                          'account_type': 'root', 'is_leaf': False}
    type_order = ['Assets', 'Liabilities', 'Equity', 'Income', 'Expenses']
    for t in type_order:
        if t in nodes_set:
            edges_list.append((root_id, t))
            children.setdefault(root_id, []).append(t)

    # Compute values (sum leaves)
    def compute_value(node):
        if node in balances:
            return balances[node]
        return sum(compute_value(k) for k in children.get(node, []))

    node_values = {n: compute_value(n) for n in nodes_set}

    # Layout
    def count_leaves(n):
        kids = children.get(n, [])
        return sum(count_leaves(k) for k in kids) if kids else 1

    positions = {}
    def layout_subtree(node, x, y, x_span):
        positions[node] = (round(x + x_span / 2, 1), round(y, 1))
        kids = sorted(children.get(node, []))
        if not kids:
            return
        child_span = x_span / len(kids)
        for i, child in enumerate(kids):
            layout_subtree(child, x + i * child_span, y + 120, child_span)

    total_width = count_leaves(root_id) * 200
    layout_subtree(root_id, 0, 0, total_width)

    # Sizing and coloring
    all_vals = [v for v in node_values.values() if v > 0]
    max_val = max(all_vals) if all_vals else 1
    type_hues = {'Assets': 0.35, 'Liabilities': 0.0, 'Equity': 0.78,
                 'Income': 0.58, 'Expenses': 0.08, 'root': 0.0}

    type_vals = {}
    for n, m in node_meta.items():
        t = m['account_type']
        if t != 'root':
            type_vals.setdefault(t, []).append(node_values.get(n, 0))
    type_ranges = {t: (min(v), max(v)) if v else (0, 1) for t, v in type_vals.items()}

    gml_nodes = []
    id_map = {}
    for idx, n in enumerate(sorted(nodes_set)):
        id_map[n] = idx
        m = node_meta[n]
        val = node_values.get(n, 0)
        # Size
        log_val = math.log1p(val)
        log_max = math.log1p(max_val)
        t = log_val / log_max if log_max > 0 else 0
        size = round(30 + t * 90, 1)
        # Color
        acct_type = m['account_type']
        if acct_type == 'root':
            color = "#333333"
        else:
            hue = type_hues.get(acct_type, 0.5)
            mn, mx = type_ranges.get(acct_type, (0, 1))
            ct = (val - mn) / (mx - mn) if mx != mn else 0.5
            s = 0.3 + ct * 0.6
            l = 0.85 - ct * 0.45
            r, g, b = colorsys.hls_to_rgb(hue, l, s)
            color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

        x, y = positions.get(n, (0, 0))
        gml_nodes.append({'id': idx, 'label': m['short_name'], 'x': x, 'y': y,
                          'size': size, 'color': color, 'font_size': 10})

    gml_edges = []
    for eid, (src, tgt) in enumerate(edges_list):
        gml_edges.append({'id': len(nodes_set) + eid, 'source': id_map[src],
                          'target': id_map[tgt], 'label': '', 'width': 1.5,
                          'color': '#888888', 'arrow': 'none'})

    out_file = out_dir / 'accounts-chart.gml'
    _write_gml(out_file, f"{entity_name} Account Chart", gml_nodes, gml_edges)
    print(f"\n  ✓ {out_file}")
    print(f"    {len(gml_nodes)} nodes, {len(gml_edges)} edges")
    print(f"    Open: File → Import → Network from File\n")



def _export_correlation(flags, entity, out_dir):
    """Export price correlation network as Cytoscape GML."""
    import math

    data = _parse_price_data()
    if not data:
        print(f"\n  [{entity}] No price data found.\n")
        return

    returns = _compute_returns(data)
    symbols = sorted(data.keys())

    def pearson(x_vals, y_vals):
        n = len(x_vals)
        if n < 3:
            return 0.0
        mx = sum(x_vals) / n
        my = sum(y_vals) / n
        num = sum((x - mx) * (y - my) for x, y in zip(x_vals, y_vals))
        dx = math.sqrt(sum((x - mx) ** 2 for x in x_vals))
        dy = math.sqrt(sum((y - my) ** 2 for y in y_vals))
        return num / (dx * dy) if dx and dy else 0.0

    # Correlations
    correlations = {}
    for i, s1 in enumerate(symbols):
        for j, s2 in enumerate(symbols):
            if j <= i:
                continue
            common = sorted(set(returns[s1].keys()) & set(returns[s2].keys()))
            x = [returns[s1][d] for d in common]
            y = [returns[s2][d] for d in common]
            correlations[(s1, s2)] = pearson(x, y) if len(common) >= 3 else 0.0

    # Node stats
    node_stats = {}
    for sym in symbols:
        prices_sorted = sorted(data[sym].items())
        first_p = prices_sorted[0][1]
        last_p = prices_sorted[-1][1]
        ytd = (last_p - first_p) / first_p * 100
        rets = list(returns[sym].values())
        mean_r = sum(rets) / len(rets) if rets else 0
        vol = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / len(rets)) if rets else 0
        node_stats[sym] = {'ytd': ytd, 'vol': vol, 'price': last_p}

    # Layout: circle
    n = len(symbols)
    radius = 250
    vols = [node_stats[s]['vol'] for s in symbols]
    min_vol, max_vol = min(vols), max(vols)

    gml_nodes = []
    for idx, sym in enumerate(symbols):
        angle = 2 * math.pi * idx / n - math.pi / 2
        x = round(radius * math.cos(angle), 1)
        y = round(radius * math.sin(angle), 1)
        stats = node_stats[sym]
        # Size by volatility
        t = (stats['vol'] - min_vol) / (max_vol - min_vol) if max_vol != min_vol else 0.5
        size = round(50 + t * 80, 1)
        # Color by YTD
        pct = max(-50, min(100, stats['ytd']))
        if pct >= 0:
            intensity = min(pct / 80, 1.0)
            color = f"#{int(50+(1-intensity)*150):02x}{int(150+intensity*105):02x}{int(50+(1-intensity)*100):02x}"
        else:
            intensity = min(abs(pct) / 40, 1.0)
            color = f"#{int(150+intensity*105):02x}{int(50+(1-intensity)*150):02x}{int(50+(1-intensity)*100):02x}"

        label = f"{sym} ${stats['price']:,.0f} YTD{stats['ytd']:+.0f}%"
        gml_nodes.append({'id': idx, 'label': label, 'x': x, 'y': y,
                          'size': size, 'color': color, 'font_size': 12})

    gml_edges = []
    eid = len(symbols)
    for (s1, s2), corr in sorted(correlations.items()):
        width = round(1 + abs(corr) * 12, 1)
        if corr >= 0:
            intensity = abs(corr)
            color = f"#{int(50*(1-intensity)):02x}{int(100+155*intensity):02x}{int(50*(1-intensity)):02x}"
        else:
            intensity = abs(corr)
            color = f"#{int(100+155*intensity):02x}{int(50*(1-intensity)):02x}{int(50*(1-intensity)):02x}"
        gml_edges.append({'id': eid, 'source': symbols.index(s1), 'target': symbols.index(s2),
                          'label': f"r={corr:.2f}", 'width': width, 'color': color, 'arrow': 'none'})
        eid += 1

    out_file = out_dir / 'price-correlation.gml'
    _write_gml(out_file, "Price Correlation Network", gml_nodes, gml_edges)
    print(f"\n  ✓ {out_file}")
    print(f"    {len(gml_nodes)} nodes, {len(gml_edges)} edges")
    print(f"    Node size=volatility, color=YTD, edge width=|correlation|")
    print(f"    Open: File → Import → Network from File\n")



def _export_temporal(flags, entity, out_dir, layout=None):
    """Export temporal price network as Cytoscape GML with layout options."""
    import math

    data = _parse_price_data()
    if not data:
        print(f"\n  [{entity}] No price data found.\n")
        return

    returns = _compute_returns(data)
    symbols = sorted(data.keys())
    all_dates = sorted(set(d for sd in data.values() for d in sd.keys()))[-30:]

    # Choose layout
    if not layout:
        if flags.get('batch'):
            layout = 'grid'
        else:
            print(f"\n  [{entity}] Temporal network layout:\n")
            for i, l in enumerate(TEMPORAL_LAYOUTS, 1):
                desc = {'grid': 'x=date, y=commodity (clean rows)',
                        'spiral': 'time spirals outward per commodity',
                        'river': 'left-to-right, Y=cumulative return',
                        'radial': 'spokes=commodities, rings=time'}[l]
                print(f"  {i}. {l:<10} {desc}")
            while True:
                raw = input(f"\n  Select [1-4]: ").strip()
                try:
                    idx = int(raw) - 1
                    if 0 <= idx < len(TEMPORAL_LAYOUTS):
                        layout = TEMPORAL_LAYOUTS[idx]
                        break
                except ValueError:
                    if raw in TEMPORAL_LAYOUTS:
                        layout = raw
                        break
                print("  Enter 1-4 or a layout name.")

    # Layout functions
    def grid_pos(sym, sym_idx, date, date_idx, pct):
        return date_idx * 100, sym_idx * 200

    def spiral_pos(sym, sym_idx, date, date_idx, pct):
        base_angle = 2 * math.pi * sym_idx / len(symbols)
        angle = base_angle + (date_idx / len(all_dates)) * 2 * math.pi * 2
        r = 80 + date_idx * 12
        return round(r * math.cos(angle), 1), round(r * math.sin(angle), 1)

    def river_pos(sym, sym_idx, date, date_idx, pct):
        x = date_idx * 80
        base_y = sym_idx * 300
        sym_dates = sorted(data[sym].keys())
        first_price = data[sym][sym_dates[0]]
        current_price = data[sym].get(date, first_price)
        cum_pct = (current_price - first_price) / first_price * 100
        return round(x, 1), round(base_y - cum_pct * 2, 1)

    def radial_pos(sym, sym_idx, date, date_idx, pct):
        angle = 2 * math.pi * sym_idx / len(symbols) - math.pi / 2
        r = 100 + date_idx * 15
        return round(r * math.cos(angle), 1), round(r * math.sin(angle), 1)

    layout_fn = {'grid': grid_pos, 'spiral': spiral_pos,
                 'river': river_pos, 'radial': radial_pos}[layout]

    # Build nodes
    node_id_map = {}
    gml_nodes = []
    nid = 0
    for sym_idx, sym in enumerate(symbols):
        for date_idx, d in enumerate(all_dates):
            if d not in data[sym]:
                continue
            key = f"{sym}:{d}"
            node_id_map[key] = nid
            pct = returns[sym].get(d, 0.0)
            x, y = layout_fn(sym, sym_idx, d, date_idx, pct)
            size = min(60, max(15, 15 + abs(pct) * 10))
            color = _pct_to_color(pct)
            gml_nodes.append({'id': nid, 'label': f"{sym} {d[-5:]}", 'x': x, 'y': y,
                              'size': round(size, 1), 'color': color, 'font_size': 8})
            nid += 1

    # Sequential edges (same commodity, day-to-day)
    gml_edges = []
    eid = nid
    for sym in symbols:
        sym_dates = sorted(d for d in all_dates if d in data[sym])
        for i in range(1, len(sym_dates)):
            src = node_id_map.get(f"{sym}:{sym_dates[i-1]}")
            tgt = node_id_map.get(f"{sym}:{sym_dates[i]}")
            if src is not None and tgt is not None:
                gml_edges.append({'id': eid, 'source': src, 'target': tgt,
                                  'label': '', 'width': 2.0, 'color': '#444444'})
                eid += 1

    # Cross-commodity same-day edges
    for d in all_dates:
        present = [sym for sym in symbols if d in data[sym]]
        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                src = node_id_map.get(f"{present[i]}:{d}")
                tgt = node_id_map.get(f"{present[j]}:{d}")
                if src is not None and tgt is not None:
                    gml_edges.append({'id': eid, 'source': src, 'target': tgt,
                                      'label': '', 'width': 0.5, 'color': '#dddddd',
                                      'arrow': 'none'})
                    eid += 1

    out_file = out_dir / f'temporal-{layout}.gml'
    _write_gml(out_file, f"Temporal Network ({layout})", gml_nodes, gml_edges)
    print(f"\n  ✓ {out_file}")
    print(f"    {len(gml_nodes)} nodes, {len(gml_edges)} edges, layout: {layout}")
    print(f"    Green=up, Red=down, Size=magnitude")
    print(f"    Open: File → Import → Network from File\n")



def _export_momentum(flags, entity, out_dir):
    """Export momentum state machine as Cytoscape GML."""
    import math
    from collections import Counter, defaultdict

    data = _parse_price_data()
    if not data:
        print(f"\n  [{entity}] No price data found.\n")
        return

    returns = _compute_returns(data)
    symbols = sorted(data.keys())

    STATES = ['breakout', 'rising', 'consolidating', 'falling', 'crash']
    STATE_COLORS = {'breakout': '#1b5e20', 'rising': '#66bb6a',
                    'consolidating': '#9e9e9e', 'falling': '#ef5350', 'crash': '#b71c1c'}

    def classify(pct):
        if pct > 3: return 'breakout'
        elif pct > 0.5: return 'rising'
        elif pct > -0.5: return 'consolidating'
        elif pct > -3: return 'falling'
        else: return 'crash'

    # Analyze each commodity
    sym_data = {}
    for sym in symbols:
        rets = sorted(returns[sym].items())
        if len(rets) < 4:
            continue
        # 3-day rolling classification
        states = []
        for i in range(len(rets)):
            window = rets[max(0, i - 2):i + 1]
            avg = sum(r for _, r in window) / len(window)
            states.append(classify(avg))

        transitions = Counter()
        for i in range(1, len(states)):
            transitions[(states[i - 1], states[i])] += 1
        state_counts = Counter(states)
        sym_data[sym] = {'transitions': transitions, 'state_counts': state_counts,
                         'total': len(states)}

    if not sym_data:
        print(f"\n  [{entity}] Insufficient data for momentum analysis.\n")
        return

    # Build GML
    gml_nodes = []
    gml_edges = []
    nid = 0
    node_ids = {}
    Y_OFFSET = 500
    radius = 150

    for sym_idx, sym in enumerate(symbols):
        if sym not in sym_data:
            continue
        sd = sym_data[sym]
        y_base = sym_idx * Y_OFFSET

        # Center label node
        gml_nodes.append({'id': nid, 'label': sym, 'x': 0.0, 'y': float(y_base),
                          'size': 40.0, 'color': '#333333', 'shape': 'rectangle',
                          'font_size': 14})
        nid += 1

        # State nodes in circle
        for si, state in enumerate(STATES):
            angle = 2 * math.pi * si / len(STATES) - math.pi / 2
            x = round(radius * math.cos(angle), 1)
            y = round(y_base + radius * math.sin(angle), 1)
            count = sd['state_counts'].get(state, 0)
            pct_time = count / sd['total'] * 100 if sd['total'] > 0 else 0
            size = max(25, min(100, 25 + pct_time * 1.5))
            label = f"{state} ({pct_time:.0f}%)"
            node_ids[(sym, state)] = nid
            gml_nodes.append({'id': nid, 'label': label, 'x': x, 'y': y,
                              'size': round(size, 1), 'color': STATE_COLORS[state],
                              'font_size': 10})
            nid += 1

    # Transition edges
    eid = nid
    for sym in symbols:
        if sym not in sym_data:
            continue
        sd = sym_data[sym]
        max_t = max(sd['transitions'].values()) if sd['transitions'] else 1
        for (fs, ts), count in sd['transitions'].items():
            src = node_ids.get((sym, fs))
            tgt = node_ids.get((sym, ts))
            if src is None or tgt is None:
                continue
            width = round(1 + (count / max_t) * 8, 1)
            intensity = count / max_t
            grey = int(200 - intensity * 150)
            color = f"#{grey:02x}{grey:02x}{grey:02x}"
            gml_edges.append({'id': eid, 'source': src, 'target': tgt,
                              'label': f"{count}x", 'width': width, 'color': color})
            eid += 1

    out_file = out_dir / 'momentum-states.gml'
    _write_gml(out_file, "Momentum State Machine", gml_nodes, gml_edges)
    print(f"\n  ✓ {out_file}")
    print(f"    {len(gml_nodes)} nodes, {len(gml_edges)} edges")
    print(f"    States: breakout/rising/consolidating/falling/crash")
    print(f"    Size=% time in state, edge thickness=transition frequency")
    print(f"    Open: File → Import → Network from File\n")


# ─── Alert Subsystem ──────────────────────────────────────────────────────────

def _dispatch_alert(flags, args):
    """Route alert subcommands."""
    if flags['help'] or not args:
        _alert_help()
        return

    action = args[0]
    action_args = args[1:]

    if action == 'add':
        cmd_alert_add(flags, action_args)
    elif action == 'list':
        cmd_alert_list(flags, action_args)
    elif action == 'remove':
        cmd_alert_remove(flags, action_args)
    elif action == 'check':
        cmd_alert_check(flags, action_args)
    elif action in ('--help', '-h'):
        _alert_help()
    else:
        print(f"Unknown alert subcommand: {action}")
        print("Run 'pair market alert --help' for usage.")
        sys.exit(1)


def _get_alerts_config():
    """Return the alerts section from entity config, or empty dict."""
    config = load_config()
    market = config.get('market', {})
    return market.get('alerts', {})


def _save_alerts_config(alerts):
    """Save alerts section back to entity config."""
    config = load_config()
    if 'market' not in config:
        config['market'] = {}
    config['market']['alerts'] = alerts
    save_config(config)


def _get_alert_rules():
    """Return list of alert rules."""
    alerts = _get_alerts_config()
    return alerts.get('rules', [])


def _get_alert_defaults():
    """Return alert defaults."""
    alerts = _get_alerts_config()
    return alerts.get('defaults', {
        'interval': '5m',
        'source': 'yfinance',
        'notify': 'desktop',
    })


def _get_alert_groups():
    """Return alert groups."""
    alerts = _get_alerts_config()
    return alerts.get('groups', [])


def _find_commodity(symbol):
    """Find a commodity entry by symbol. Returns dict or None."""
    commodities = _get_commodities()
    for c in commodities:
        if c['symbol'].upper() == symbol.upper():
            return c
    return None


def _resolve_interval(rule):
    """Resolve interval for a rule: rule > group > defaults."""
    if 'interval' in rule:
        return rule['interval']
    rule_tags = set(rule.get('tags', []))
    for group in _get_alert_groups():
        group_symbols = [s.upper() for s in group.get('symbols', [])]
        group_tags = set(group.get('tags', []))
        if rule['symbol'].upper() in group_symbols or rule_tags & group_tags:
            if 'interval' in group:
                return group['interval']
    return _get_alert_defaults().get('interval', '5m')


def _parse_interval(interval_str):
    """Parse interval string (e.g. '5m', '1m', '15m') to seconds."""
    match = re.match(r'^(\d+)\s*([msh]?)$', interval_str.strip().lower())
    if not match:
        return 300
    value = int(match.group(1))
    unit = match.group(2) or 'm'
    if unit == 'm':
        return value * 60
    elif unit == 's':
        return value
    elif unit == 'h':
        return value * 3600
    return 300


# ─── Previous Close ──────────────────────────────────────────────────────────

def _get_previous_close(symbol):
    """Get the most recent P directive price for symbol dated before today.

    Returns (price_float, date_str) or (None, None) if not found.
    """
    prices_file = _get_prices_journal()
    if not prices_file.exists():
        return None, None

    today_str = date.today().strftime("%Y-%m-%d")
    symbol_upper = symbol.upper()
    best_price = None
    best_date = None

    for line in prices_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith('P '):
            continue

        parts = stripped.split(None, 2)
        if len(parts) < 3:
            continue

        p_date = parts[1]
        if p_date >= today_str:
            continue

        rest = parts[2]
        if rest.startswith('"'):
            end_quote = rest.index('"', 1)
            commodity = rest[1:end_quote]
            remainder = rest[end_quote + 1:].split()
        else:
            tokens = rest.split()
            commodity = tokens[0]
            remainder = tokens[1:]

        if commodity.upper() != symbol_upper:
            continue

        if len(remainder) >= 2:
            try:
                price = float(remainder[1])
            except (ValueError, IndexError):
                continue
        elif len(remainder) == 1:
            try:
                price = float(remainder[0])
            except ValueError:
                continue
        else:
            continue

        if best_date is None or p_date > best_date:
            best_date = p_date
            best_price = price

    return best_price, best_date


# ─── Live Price ───────────────────────────────────────────────────────────────

def _get_live_price(commodity):
    """Fetch current/live price for a commodity using yfinance.

    Returns float price or None on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed. Install with: pip install yfinance")
        return None

    # Determine the ticker to fetch
    if 'fetch_pair' in commodity:
        ticker = commodity['fetch_pair']
    elif 'pair' in commodity:
        pair = commodity['pair']
        parts = pair.split('/')
        if len(parts) == 2:
            base, quote = parts
            ticker = f"{base}{quote}=X"
        else:
            ticker = commodity['symbol']
    else:
        ticker = commodity['symbol']

    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        price = info.get('last_price') or info.get('previous_close')
        if price and price > 0:
            return float(price)
    except Exception:
        pass

    # Fallback: try recent history
    try:
        hist = t.history(period='1d', interval='1m')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
    except Exception:
        pass

    return None


# ─── Notification ─────────────────────────────────────────────────────────────

def _notify_desktop(title, body, urgency='critical'):
    """Send desktop notification via notify-send."""
    if not shutil.which('notify-send'):
        return False
    try:
        subprocess.run(
            ['notify-send', '--urgency', urgency, '--app-name', 'pair-market', title, body],
            timeout=5,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def _notify_alert(rule, close_price, live_price, pct_drop, method='both'):
    """Send alert notification via configured method."""
    symbol = rule['symbol']
    threshold = rule['threshold']

    print(f"  ⚠ {symbol:<12} close: ${close_price:,.2f}   now: ${live_price:,.2f}   "
          f"▼ {pct_drop:.2f}%   ALERT (threshold: {threshold}%)")

    if method in ('desktop', 'both'):
        title = f"⚠ {symbol} dropped {pct_drop:.1f}%"
        body = f"Previous close: ${close_price:,.2f} → Now: ${live_price:,.2f}\nThreshold: {threshold}%"
        _notify_desktop(title, body)


# ─── Alert Commands ───────────────────────────────────────────────────────────

def cmd_alert_add(flags, args):
    """Add a new alert rule. Supports inline and interactive."""
    entity = get_active_entity()
    config = load_config()
    commodities = _get_commodities()

    # Parse inline args
    symbol = None
    threshold = None
    tags = []
    notify = None
    interval = None
    i = 0
    while i < len(args):
        if args[i] == '--threshold' and i + 1 < len(args):
            try:
                threshold = float(args[i + 1])
            except ValueError:
                print(f"  Invalid threshold: {args[i + 1]}")
                sys.exit(1)
            i += 2
        elif args[i] == '--tag' and i + 1 < len(args):
            tags.append(args[i + 1])
            i += 2
        elif args[i] == '--notify' and i + 1 < len(args):
            notify = args[i + 1]
            i += 2
        elif args[i] == '--interval' and i + 1 < len(args):
            interval = args[i + 1]
            i += 2
        elif not args[i].startswith('-'):
            symbol = args[i]
            i += 1
        else:
            i += 1

    # Interactive: pick from list if no symbol given
    if not symbol:
        if not commodities:
            print(f"\n  [{entity}] No commodities configured.")
            print("  Run 'pair market add' to add one, or specify a symbol:\n")
            print("  pair market alert add TSLA --threshold 5\n")
            return

        print(f"\n  [{entity}] Add price alert\n")
        print(f"  Available commodities:")
        for i_c, c in enumerate(commodities, 1):
            print(f"  {i_c}. {c['symbol']:<12} {c.get('name', '')}")
        print(f"  {len(commodities) + 1}. (new symbol)")

        while True:
            raw = input(f"\n  Select [1-{len(commodities) + 1}] or type symbol: ").strip()
            if not raw:
                continue
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(commodities):
                    symbol = commodities[idx]['symbol']
                    break
                elif idx == len(commodities):
                    symbol = prompt("  Symbol")
                    break
            except ValueError:
                symbol = raw
                break

    # Check if symbol is in commodities registry
    commodity = _find_commodity(symbol)
    if not commodity:
        print(f"\n  '{symbol}' is not in your commodities list.")
        if flags.get('batch'):
            print("  Add it first with 'pair market add'.")
            sys.exit(1)
        if confirm(f"  Add '{symbol}' to commodities now?"):
            name = prompt("  Name (optional)", required=False)
            entry = {
                'symbol': symbol,
                'source': 'yahoo',
                'currency': config.get('pair', {}).get('currency', 'CAD'),
            }
            if name:
                entry['name'] = name
            entry['fetch_pair'] = symbol

            if 'market' not in config:
                config['market'] = {}
            if 'commodities' not in config['market']:
                config['market']['commodities'] = []
            config['market']['commodities'].append(entry)
            save_config(config)
            print(f"  ✓ Added '{symbol}' to commodities.")
            commodity = entry
            _ensure_prices_journal()
        else:
            print("  Cancelled.")
            return

    # Get threshold
    if threshold is None:
        raw_t = prompt("  Drop threshold (%)", default="3")
        try:
            threshold = float(raw_t)
        except ValueError:
            print(f"  Invalid threshold: {raw_t}")
            sys.exit(1)

    # Get tags interactively if not provided
    if not tags and not flags.get('batch'):
        raw_tags = prompt("  Tags (comma-separated, optional)", required=False)
        if raw_tags:
            tags = [t.strip() for t in raw_tags.split(',') if t.strip()]

    # Get notify method
    if notify is None:
        notify = _get_alert_defaults().get('notify', 'desktop')

    # Build rule
    rule = {
        'symbol': symbol,
        'type': 'drop_from_close',
        'threshold': threshold,
        'enabled': True,
    }
    if tags:
        rule['tags'] = tags
    if interval:
        rule['interval'] = interval
    if notify != _get_alert_defaults().get('notify', 'desktop'):
        rule['notify'] = notify

    # Save to config
    alerts = _get_alerts_config()
    if not alerts:
        alerts = {'defaults': {'interval': '5m', 'source': 'yfinance', 'notify': 'desktop'}, 'rules': []}
    if 'rules' not in alerts:
        alerts['rules'] = []

    # Check for existing rule on same symbol
    existing_idx = None
    for idx, r in enumerate(alerts['rules']):
        if r['symbol'].upper() == symbol.upper():
            existing_idx = idx
            break

    if existing_idx is not None:
        if not flags.get('batch') and not confirm(f"  Alert for '{symbol}' already exists. Replace?", default_yes=False):
            print("  Cancelled.")
            return
        alerts['rules'][existing_idx] = rule
    else:
        alerts['rules'].append(rule)

    _save_alerts_config(alerts)
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    print(f"\n  ✓ Alert added: {symbol} drops ≥ {threshold}%{tag_str}")
    print(f"  Run 'pair market alert check' to test it.\n")


def cmd_alert_list(flags, args):
    """List alert rules with optional filtering."""
    entity = get_active_entity()
    rules = _get_alert_rules()

    if not rules:
        print(f"\n  [{entity}] No alerts configured.")
        print("  Run 'pair market alert add' to create one.\n")
        return

    # Parse filter flags
    tag_filter = None
    group_filter = None
    i = 0
    while i < len(args):
        if args[i] == '--tag' and i + 1 < len(args):
            tag_filter = args[i + 1]
            i += 2
        elif args[i] == '--group' and i + 1 < len(args):
            group_filter = args[i + 1]
            i += 2
        else:
            i += 1

    filtered = _filter_rules(rules, tag_filter=tag_filter, group_filter=group_filter)

    if not filtered:
        print(f"\n  [{entity}] No alerts match filter.")
        return

    filter_desc = ""
    if tag_filter:
        filter_desc = f" (tag: {tag_filter})"
    elif group_filter:
        filter_desc = f" (group: {group_filter})"

    print(f"\n  [{entity}] Alert rules{filter_desc}:\n")
    print(f"  {'Symbol':<12} {'Threshold':<12} {'Interval':<10} {'Tags':<20} {'Status'}")
    print(f"  {'─' * 12} {'─' * 12} {'─' * 10} {'─' * 20} {'─' * 8}")

    for rule in filtered:
        symbol = rule['symbol']
        threshold = f"{rule['threshold']}%"
        interval = _resolve_interval(rule)
        tags_str = ', '.join(rule.get('tags', [])) or '—'
        status = '✓ on' if rule.get('enabled', True) else '✗ off'
        print(f"  {symbol:<12} {threshold:<12} {interval:<10} {tags_str:<20} {status}")
    print()


def cmd_alert_remove(flags, args):
    """Remove an alert rule."""
    entity = get_active_entity()
    rules = _get_alert_rules()

    if not rules:
        print(f"\n  [{entity}] No alerts to remove.\n")
        return

    symbol = None
    tag_filter = None
    i = 0
    while i < len(args):
        if args[i] == '--tag' and i + 1 < len(args):
            tag_filter = args[i + 1]
            i += 2
        elif not args[i].startswith('-'):
            symbol = args[i]
            i += 1
        else:
            i += 1

    if tag_filter:
        before = len(rules)
        rules = [r for r in rules if tag_filter not in r.get('tags', [])]
        removed = before - len(rules)
        if removed == 0:
            print(f"\n  No alerts with tag '{tag_filter}' found.\n")
            return
        if not flags.get('batch') and not confirm(f"  Remove {removed} alert(s) with tag '{tag_filter}'?"):
            print("  Cancelled.")
            return
        alerts = _get_alerts_config()
        alerts['rules'] = rules
        _save_alerts_config(alerts)
        print(f"\n  ✓ Removed {removed} alert(s) with tag '{tag_filter}'.\n")
        return

    if not symbol:
        print(f"\n  [{entity}] Remove alert:\n")
        for i_r, r in enumerate(rules, 1):
            tags_str = f" [{', '.join(r.get('tags', []))}]" if r.get('tags') else ""
            print(f"  {i_r}. {r['symbol']} — drop ≥ {r['threshold']}%{tags_str}")

        while True:
            raw = input(f"\n  Select [1-{len(rules)}] or type symbol: ").strip()
            if not raw:
                print("  Cancelled.")
                return
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(rules):
                    symbol = rules[idx]['symbol']
                    break
            except ValueError:
                symbol = raw
                break

    before = len(rules)
    rules = [r for r in rules if r['symbol'].upper() != symbol.upper()]
    if len(rules) == before:
        print(f"\n  No alert for '{symbol}' found.\n")
        return

    alerts = _get_alerts_config()
    alerts['rules'] = rules
    _save_alerts_config(alerts)
    print(f"\n  ✓ Removed alert for '{symbol}'.\n")


def cmd_alert_check(flags, args):
    """Check alerts — one-shot or loop mode."""
    import time as _time

    entity = get_active_entity()
    rules = _get_alert_rules()

    if not rules:
        print(f"\n  [{entity}] No alerts configured.")
        print("  Run 'pair market alert add' to create one.\n")
        return

    symbol_filters = []
    tag_filter = None
    group_filter = None
    loop_mode = False
    loop_interval = None
    i = 0
    while i < len(args):
        if args[i] == '--tag' and i + 1 < len(args):
            tag_filter = args[i + 1]
            i += 2
        elif args[i] == '--group' and i + 1 < len(args):
            group_filter = args[i + 1]
            i += 2
        elif args[i] == '--loop':
            loop_mode = True
            i += 1
        elif args[i] == '--interval' and i + 1 < len(args):
            loop_interval = _parse_interval(args[i + 1])
            i += 2
        elif not args[i].startswith('-'):
            symbol_filters.append(args[i].upper())
            i += 1
        else:
            i += 1

    filtered = _filter_rules(rules, tag_filter=tag_filter, group_filter=group_filter,
                             symbol_filters=symbol_filters)

    if not filtered:
        print(f"\n  [{entity}] No alerts match filter.\n")
        return

    filtered = [r for r in filtered if r.get('enabled', True)]
    if not filtered:
        print(f"\n  [{entity}] All matching alerts are disabled.\n")
        return

    if loop_mode:
        _alert_loop(flags, filtered, entity, loop_interval)
    else:
        _alert_check_once(flags, filtered, entity)


def _alert_check_once(flags, rules, entity):
    """Run a single alert check pass."""
    from datetime import datetime

    now = datetime.now()
    print(f"\n  [{entity}] Price Alert Check — {now.strftime('%Y-%m-%d %H:%M')}\n")

    triggered = 0
    errors = 0

    for rule in rules:
        symbol = rule['symbol']
        threshold = rule['threshold']

        close_price, close_date = _get_previous_close(symbol)
        if close_price is None:
            print(f"  ? {symbol:<12} no previous close found in prices.journal")
            errors += 1
            continue

        commodity = _find_commodity(symbol)
        if not commodity:
            commodity = {'symbol': symbol, 'fetch_pair': symbol, 'currency': 'CAD'}

        live_price = _get_live_price(commodity)
        if live_price is None:
            print(f"  ? {symbol:<12} could not fetch live price")
            errors += 1
            continue

        if close_price > 0:
            pct_change = ((close_price - live_price) / close_price) * 100
        else:
            pct_change = 0.0

        notify_method = rule.get('notify', _get_alert_defaults().get('notify', 'desktop'))

        if pct_change >= threshold:
            _notify_alert(rule, close_price, live_price, pct_change, notify_method)
            triggered += 1
        else:
            direction = "▼" if pct_change > 0 else "▲"
            abs_change = abs(pct_change)
            print(f"  ✓ {symbol:<12} close: ${close_price:,.2f}   now: ${live_price:,.2f}   "
                  f"{direction} {abs_change:.2f}%   OK (threshold: {threshold}%)")

    print()
    if triggered:
        print(f"  {triggered} alert(s) triggered.")
    else:
        print(f"  All clear — no alerts triggered.")
    if errors:
        print(f"  {errors} symbol(s) could not be checked.")
    print()


def _alert_loop(flags, rules, entity, interval_override=None):
    """Run alert checks in a loop until interrupted."""
    import time as _time
    from datetime import datetime

    if interval_override:
        sleep_seconds = interval_override
    else:
        intervals = [_parse_interval(_resolve_interval(r)) for r in rules]
        sleep_seconds = min(intervals) if intervals else 300

    interval_desc = f"{sleep_seconds // 60}m" if sleep_seconds >= 60 else f"{sleep_seconds}s"
    print(f"\n  [{entity}] Alert loop started — checking every {interval_desc}")
    print(f"  Press Ctrl-C to stop.\n")

    try:
        while True:
            _alert_check_once(flags, rules, entity)
            next_check = datetime.now().strftime('%H:%M')
            print(f"  Next check in {interval_desc} (after {next_check})...")
            print()
            _time.sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("\n\n  Alert loop stopped.\n")


# ─── Alert Filtering ─────────────────────────────────────────────────────────

def _filter_rules(rules, tag_filter=None, group_filter=None, symbol_filters=None):
    """Filter rules by tag, group, or symbol list."""
    filtered = rules

    if symbol_filters:
        filtered = [r for r in filtered if r['symbol'].upper() in symbol_filters]

    if tag_filter:
        filtered = [r for r in filtered if tag_filter in r.get('tags', [])]

    if group_filter:
        groups = _get_alert_groups()
        group_symbols = set()
        for g in groups:
            if g.get('name', '').lower() == group_filter.lower():
                group_symbols = {s.upper() for s in g.get('symbols', [])}
                break
        if group_symbols:
            filtered = [r for r in filtered if r['symbol'].upper() in group_symbols]
        else:
            filtered = []

    return filtered


# ─── Alert Help ───────────────────────────────────────────────────────────────

def _alert_help():
    print("""pair market alert — price drop alerts

Usage: pair market alert <subcommand> [flags]

Subcommands:
  add [SYMBOL]            Add alert (inline or interactive)
  list                    List configured alerts
  remove [SYMBOL]         Remove an alert
  check [SYMBOL...]       Check alerts now

Check flags:
  --loop                  Poll continuously until Ctrl-C
  --interval INTERVAL     Override check interval (e.g. 1m, 5m, 15m)
  --tag TAG               Only check alerts with this tag
  --group NAME            Only check alerts in this group

Add flags:
  --threshold N           Drop percentage to trigger alert
  --tag TAG               Assign tag (repeatable)
  --notify METHOD         Notification: desktop, terminal, both
  --interval INTERVAL     Per-rule check interval override

Examples:
  pair market alert add                      Interactive
  pair market alert add SHOP.TO --threshold 3 --tag tsx
  pair market alert add BTC --threshold 5 --tag crypto
  pair market alert check                    Check all alerts now
  pair market alert check --tag crypto       Check only crypto alerts
  pair market alert check --loop             Poll continuously
  pair market alert check BTC SHOP.TO        Check specific symbols
  pair market alert list --tag equity        List filtered
  pair market alert remove SHOP.TO           Remove by symbol
  pair market alert remove --tag fx          Remove all with tag

Configuration:
  Alert rules stored in entity config.yaml under market.alerts.
  Previous close is read from include/prices.journal (most recent P before today).
  Live price fetched via yfinance (pip install yfinance).
  Desktop notifications via notify-send.
""")
