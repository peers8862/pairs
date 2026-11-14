"""pair account — account registry with rich metadata."""

import csv
import hashlib
import io
import sys
import subprocess
import yaml
from pathlib import Path
from datetime import date
from decimal import Decimal

import lib.reconcile as R
from lib.yaml_store import load_entity, save_entity

from lib.helpers import (
    load_config, save_config, get_entity_dir, get_active_entity,
    parse_global_flags, prompt, prompt_choice, confirm, ensure_dir, slugify
)
from lib.ui import (
    get_entity_journal, get_entity_currency, require_entity,
    split_passthrough, show_menu, resolve_menu_or_direct
)


# ─── Menu Options ────────────────────────────────────────────────────────────

ACCOUNT_OPTIONS = [
    {'key': 'list',      'label': 'Browse accounts (tree or flat)'},
    {'key': 'add',       'label': 'Add a new account'},
    {'key': 'show',      'label': 'Show account detail + metadata'},
    {'key': 'edit',      'label': 'Edit account metadata'},
    {'key': 'remove',    'label': 'Remove/close an account'},
    {'key': 'tree',      'label': 'Visual account tree'},
    {'key': 'tag',       'label': 'Tag/untag accounts'},
    {'key': 'find',      'label': 'Search accounts by any field'},
    {'key': 'link',      'label': 'Link account to asset/liability/contact'},
    {'key': 'reconcile', 'label': 'Check balance against statement'},
    {'key': 'import',    'label': 'Import bank statement (CSV/OFX)'},
    {'key': 'match',     'label': 'Match statement lines to journal postings'},
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route account subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    pair_args, tool_args = split_passthrough(remaining)
    selected, extra_args = resolve_menu_or_direct(pair_args, ACCOUNT_OPTIONS)

    if selected is None and not pair_args:
        selected = show_menu("Accounts", ACCOUNT_OPTIONS)
        if selected is None:
            return
    elif selected is None:
        action = pair_args[0]
        action_args = pair_args[1:] + tool_args
        _dispatch_action(action, flags, action_args)
        return

    key = selected['key']
    all_args = extra_args + tool_args
    _dispatch_action(key, flags, all_args)


def _dispatch_action(action, flags, args):
    """Dispatch to the appropriate command function."""
    actions = {
        'list': cmd_list, 'add': cmd_add, 'show': cmd_show,
        'edit': cmd_edit, 'remove': cmd_remove, 'tree': cmd_tree,
        'tag': cmd_tag, 'find': cmd_find, 'link': cmd_link,
        'reconcile': cmd_reconcile, 'import': cmd_import,
        'match': cmd_match,
    }
    if action in actions:
        actions[action](flags, args)
    else:
        print(f"  Unknown account subcommand: {action}")
        sys.exit(1)


# ─── Data Layer ───────────────────────────────────────────────────────────────

def _accounts_file():
    """Path to accounts.yaml."""
    return get_entity_dir() / 'accounts.yaml'


def _load_accounts():
    """Load accounts.yaml. Returns list of account dicts."""
    path = _accounts_file()
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get('accounts', []) if data else []


def _save_accounts(accounts):
    """Save accounts list to accounts.yaml."""
    path = _accounts_file()
    ensure_dir(path.parent)
    with open(path, 'w') as f:
        yaml.dump({'accounts': accounts}, f, default_flow_style=False, sort_keys=False)


def _find_account(identifier, accounts=None):
    """Find account by path fragment, index (1-based), or partial match.
    Returns (account_dict, index) or (None, None)."""
    if accounts is None:
        accounts = _load_accounts()
    if not accounts:
        return None, None

    # Try as index
    try:
        idx = int(identifier) - 1
        if 0 <= idx < len(accounts):
            return accounts[idx], idx
    except (ValueError, TypeError):
        pass

    # Try exact path match (case-insensitive)
    for i, a in enumerate(accounts):
        if a['path'].lower() == identifier.lower():
            return a, i

    # Try partial match (contains)
    for i, a in enumerate(accounts):
        if identifier.lower() in a['path'].lower():
            return a, i

    return None, None


def _get_hledger_accounts():
    """Get account list from hledger (what's declared in the journal)."""
    journal = str(get_entity_journal())
    try:
        result = subprocess.run(
            ['hledger', '-f', journal, 'accounts', '--tree'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    return []


def _get_account_balance(path):
    """Get current balance of an account from hledger."""
    journal = str(get_entity_journal())
    try:
        result = subprocess.run(
            ['hledger', '-f', journal, 'bal', path, '--no-total', '-N', '--flat'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse first line: "  CAD 1234.56  Account:Path"
            line = result.stdout.strip().splitlines()[0].strip()
            return line.rsplit('  ', 1)[0].strip() if '  ' in line else line
    except Exception:
        pass
    return None


# ─── Commands: List / Show / Tree ─────────────────────────────────────────────

def cmd_list(flags, args):
    """List accounts with metadata."""
    entity = get_active_entity()
    accounts = _load_accounts()

    # If no accounts.yaml yet, offer to import from hledger
    if not accounts:
        hledger_accts = _get_hledger_accounts()
        if hledger_accts:
            print(f"\n  [{entity}] No accounts.yaml found, but {len(hledger_accts)} accounts in journal.")
            print("  Run 'pair account add' to register accounts with metadata.\n")
        else:
            print(f"\n  [{entity}] No accounts configured. Run 'pair account add'.\n")
        return

    # Apply filters
    filtered = accounts
    show_balances = '--with-balances' in args
    flat_mode = '--flat' in args

    i = 0
    while i < len(args):
        if args[i] == '--tag' and i + 1 < len(args):
            tag = args[i + 1].lower()
            filtered = [a for a in filtered if tag in [t.lower() for t in a.get('tags', [])]]
            i += 2
        elif args[i] == '--type' and i + 1 < len(args):
            t = args[i + 1].lower()
            filtered = [a for a in filtered if a.get('type', '').lower() == t]
            i += 2
        elif args[i] == '--institution' and i + 1 < len(args):
            inst = args[i + 1].lower()
            filtered = [a for a in filtered if inst in a.get('institution', '').lower()]
            i += 2
        elif not args[i].startswith('--'):
            # Filter by path prefix
            prefix = args[i]
            filtered = [a for a in filtered if a['path'].lower().startswith(prefix.lower())]
            i += 1
        else:
            i += 1

    print(f"\n  [{entity}] Accounts ({len(filtered)})")
    print(f"  {'─' * 70}")
    print(f"  {'#':<4}{'Path':<40}{'Type':<12}{'Institution':<16}{'Tags'}")
    print(f"  {'─' * 70}")

    for i, a in enumerate(filtered, 1):
        tags = ', '.join(a.get('tags', []))[:20]
        bal = ''
        if show_balances:
            bal = _get_account_balance(a['path']) or ''
        inst = a.get('institution', '')[:14]
        path_display = a['path']
        if len(path_display) > 38:
            path_display = '...' + path_display[-35:]
        print(f"  {i:<4}{path_display:<40}{a.get('type', ''):<12}{inst:<16}{tags}")

    print(f"  {'─' * 70}\n")


def cmd_show(flags, args):
    """Show detailed info for a single account."""
    entity = get_active_entity()
    accounts = _load_accounts()

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Account to show (# or path)")

    account, idx = _find_account(identifier, accounts)
    if account is None:
        print(f"  Account '{identifier}' not found.\n")
        return

    balance = _get_account_balance(account['path'])
    currency = get_entity_currency()

    print(f"\n  [{entity}] Account Detail")
    print(f"  {'─' * 50}")
    print(f"  Path:           {account['path']}")
    if account.get('institution'):
        print(f"  Institution:    {account['institution']}")
    if account.get('account_number'):
        print(f"  Account #:      {account['account_number']}")
    if account.get('type'):
        print(f"  Type:           {account['type']}")
    if account.get('currency'):
        print(f"  Currency:       {account['currency']}")
    if account.get('opened'):
        print(f"  Opened:         {account['opened']}")
    if account.get('contact'):
        print(f"  Contact:        {account['contact']}")
    if account.get('interest_rate'):
        print(f"  Interest rate:  {account['interest_rate']}")
    if account.get('notes'):
        print(f"  Notes:          {account['notes']}")
    tags = ', '.join(account.get('tags', []))
    if tags:
        print(f"  Tags:           {tags}")
    if account.get('groups'):
        print(f"  Groups:         {', '.join(account['groups'])}")
    print(f"  {'─' * 50}")
    if balance:
        print(f"  Current Balance: {balance}")

    # Check alerts
    alerts = account.get('alerts', {})
    if alerts and balance:
        try:
            # Extract numeric value from balance string
            bal_num = float(''.join(c for c in balance.split()[-1] if c in '0123456789.-'))
            if alerts.get('low_balance') and bal_num < alerts['low_balance']:
                print(f"  ⚠ Below low_balance threshold ({alerts['low_balance']})")
            if alerts.get('high_balance') and bal_num > alerts['high_balance']:
                print(f"  ⚠ Above high_balance threshold ({alerts['high_balance']})")
        except (ValueError, IndexError):
            pass

    # Show links
    links = []
    if account.get('linked_asset'):
        links.append(f"asset → {account['linked_asset']}")
    if account.get('linked_liability'):
        links.append(f"liability → {account['linked_liability']}")
    if account.get('linked_contact'):
        links.append(f"contact → {account.get('contact', account.get('linked_contact', ''))}")
    if links:
        print(f"  {'─' * 50}")
        for l in links:
            print(f"  Linked: {l}")

    print()


def cmd_tree(flags, args):
    """Show visual account tree from hledger."""
    journal = str(get_entity_journal())
    entity = get_active_entity()

    # Use hledger accounts --tree for the display
    cmd = ['hledger', '-f', journal, 'accounts', '--tree']
    if args:
        cmd.extend(args)

    print(f"\n  [{entity}] Account Tree\n")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                print(f"  {line}")
        else:
            print(f"  Error: {result.stderr.strip()}")
    except Exception as e:
        print(f"  Error: {e}")
    print()


def cmd_add(flags, args):
    """Add an account to the registry."""
    entity = get_active_entity()
    accounts = _load_accounts()
    currency = get_entity_currency()

    print(f"\n  [{entity}] Add account\n")

    # Show existing hledger accounts for reference
    hledger_accts = _get_hledger_accounts()

    # If arg provided, use as path
    if args and not args[0].startswith('--'):
        path = args[0]
    else:
        if hledger_accts:
            print("  Accounts in journal (top-level):")
            top = sorted(set(a.split(':')[0] for a in hledger_accts))
            for t in top:
                count = sum(1 for a in hledger_accts if a.startswith(t))
                print(f"    {t} ({count} sub-accounts)")
            print()
        path = prompt("  Account path (e.g. Assets:Current:Business Chequing)")

    # Check if already registered
    existing_paths = [a['path'].lower() for a in accounts]
    if path.lower() in existing_paths:
        print(f"  '{path}' is already registered. Use 'pair account edit'.\n")
        return

    institution = prompt("  Institution (e.g. TD Bank)", required=False)
    account_number = prompt("  Account number (masked, e.g. ****4521)", required=False)
    acc_type = prompt("  Type (chequing/savings/investment/credit/loan/expense/revenue/equity)",
                      required=False)
    acc_currency = prompt(f"  Currency", default=currency, required=False)
    opened = prompt("  Opened date (YYYY-MM-DD)", required=False)
    contact = prompt("  Contact (from contacts)", required=False)
    notes = prompt("  Notes", required=False)
    tags_raw = prompt("  Tags (comma-separated)", required=False)
    tags = [t.strip() for t in tags_raw.split(',') if t.strip()] if tags_raw else []

    entry = {'path': path}
    if institution:
        entry['institution'] = institution
    if account_number:
        entry['account_number'] = account_number
    if acc_type:
        entry['type'] = acc_type
    if acc_currency and acc_currency != currency:
        entry['currency'] = acc_currency
    if opened:
        entry['opened'] = opened
    if contact:
        entry['contact'] = contact
    if notes:
        entry['notes'] = notes
    if tags:
        entry['tags'] = tags

    accounts.append(entry)
    _save_accounts(accounts)

    print(f"\n  ✓ Registered: {path}\n")


# ─── Commands: Edit / Remove / Tag / Find / Link / Reconcile ──────────────────

def cmd_edit(flags, args):
    """Edit an account's metadata."""
    accounts = _load_accounts()
    if not accounts:
        print("  No accounts registered.\n")
        return

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Account to edit (# or path)")

    account, idx = _find_account(identifier, accounts)
    if account is None:
        print(f"  Account '{identifier}' not found.\n")
        return

    print(f"\n  Editing: {account['path']}")
    print(f"  {'─' * 45}")

    fields = [
        ('path', account.get('path', '')),
        ('institution', account.get('institution', '')),
        ('account_number', account.get('account_number', '')),
        ('type', account.get('type', '')),
        ('currency', account.get('currency', '')),
        ('opened', account.get('opened', '')),
        ('contact', account.get('contact', '')),
        ('notes', account.get('notes', '')),
        ('tags', ', '.join(account.get('tags', []))),
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
                    account['tags'] = [t.strip() for t in new_val.split(',') if t.strip()]
                else:
                    new_val = prompt(f"  {key}", default=old_val, required=False)
                    if new_val:
                        account[key] = new_val
                    elif key in account and key != 'path':
                        del account[key]
                fields[field_idx] = (key, new_val)
                print(f"  Updated {key}.")
        except ValueError:
            print("  Enter a number.")

    accounts[idx] = account
    _save_accounts(accounts)
    print(f"\n  ✓ Saved changes.\n")


def cmd_remove(flags, args):
    """Remove an account from the registry."""
    accounts = _load_accounts()
    if not accounts:
        print("  No accounts registered.\n")
        return

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Account to remove (# or path)")

    account, idx = _find_account(identifier, accounts)
    if account is None:
        print(f"  Account '{identifier}' not found.\n")
        return

    if not flags.get('yes'):
        if not confirm(f"  Remove '{account['path']}' from registry? (journal unchanged)"):
            print("  Cancelled.\n")
            return

    accounts.pop(idx)
    _save_accounts(accounts)
    print(f"  ✓ Removed '{account['path']}' from registry.\n")


def cmd_tag(flags, args):
    """Tag/untag accounts or list tags."""
    accounts = _load_accounts()
    if not accounts:
        print("  No accounts registered.\n")
        return

    # --list
    if '--list' in args:
        from collections import Counter
        tag_counts = Counter()
        for a in accounts:
            for t in a.get('tags', []):
                tag_counts[t] += 1
        if not tag_counts:
            print("  No tags in use.\n")
            return
        print(f"\n  Account tags:")
        for tag, count in sorted(tag_counts.items()):
            print(f"    {tag} ({count})")
        print()
        return

    # --remove
    if '--remove' in args:
        rm_idx = args.index('--remove')
        identifier = args[0] if args[0] != '--remove' else None
        tag_to_remove = args[rm_idx + 1] if rm_idx + 1 < len(args) else None
        if not identifier or not tag_to_remove:
            print("  Usage: pair account tag ACCOUNT --remove TAG")
            return
        account, idx = _find_account(identifier, accounts)
        if account is None:
            print(f"  Account '{identifier}' not found.\n")
            return
        tags = account.get('tags', [])
        if tag_to_remove in tags:
            tags.remove(tag_to_remove)
            account['tags'] = tags
            accounts[idx] = account
            _save_accounts(accounts)
            print(f"  ✓ Removed tag '{tag_to_remove}'.\n")
        else:
            print(f"  Tag '{tag_to_remove}' not on this account.\n")
        return

    # ACCOUNT TAG (add)
    if len(args) >= 2:
        identifier, new_tag = args[0], args[1]
        account, idx = _find_account(identifier, accounts)
        if account is None:
            print(f"  Account '{identifier}' not found.\n")
            return
        tags = account.get('tags', [])
        if new_tag not in tags:
            tags.append(new_tag)
            account['tags'] = tags
            accounts[idx] = account
            _save_accounts(accounts)
            print(f"  ✓ Added tag '{new_tag}' to {account['path']}.\n")
        else:
            print(f"  Tag already present.\n")
        return

    # TAG alone — show accounts with tag
    if len(args) == 1:
        tag = args[0]
        matched = [a for a in accounts if tag in a.get('tags', [])]
        if matched:
            print(f"\n  Accounts tagged '{tag}':")
            for a in matched:
                print(f"    {a['path']}")
            print()
        else:
            print(f"  No accounts tagged '{tag}'.\n")
        return

    print("  Usage: pair account tag [--list | ACCOUNT TAG | TAG | ACCOUNT --remove TAG]")


def cmd_find(flags, args):
    """Search accounts by any field."""
    accounts = _load_accounts()
    if not accounts:
        print("  No accounts registered.\n")
        return

    query = ' '.join(args) if args else prompt("  Search")
    query_lower = query.lower()

    results = []
    for a in accounts:
        searchable = ' '.join(str(v) for v in a.values() if v).lower()
        if query_lower in searchable:
            results.append(a)

    if results:
        print(f"\n  Found {len(results)} account(s) matching '{query}':\n")
        for a in results:
            tags = ', '.join(a.get('tags', []))
            inst = a.get('institution', '')
            print(f"    {a['path']}")
            if inst:
                print(f"      institution: {inst}")
            if tags:
                print(f"      tags: {tags}")
        print()
    else:
        print(f"  No accounts matching '{query}'.\n")


def cmd_link(flags, args):
    """Link an account to an asset, liability, or contact."""
    accounts = _load_accounts()
    if not accounts:
        print("  No accounts registered.\n")
        return

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Account to link (# or path)")

    account, idx = _find_account(identifier, accounts)
    if account is None:
        print(f"  Account '{identifier}' not found.\n")
        return

    # Parse link type from remaining args
    link_type = None
    link_target = None
    for i, a in enumerate(args[1:], 1):
        if a == '--asset' and i < len(args) - 1:
            link_type = 'linked_asset'
            link_target = args[i + 1]
        elif a == '--liability' and i < len(args) - 1:
            link_type = 'linked_liability'
            link_target = args[i + 1]
        elif a == '--contact' and i < len(args) - 1:
            link_type = 'linked_contact'
            link_target = args[i + 1]

    if not link_type:
        link_kind = prompt_choice("  Link to:", ['asset', 'liability', 'contact'])
        link_target = prompt(f"  {link_kind} slug/name")
        link_type = f'linked_{link_kind}'

    account[link_type] = link_target
    accounts[idx] = account
    _save_accounts(accounts)
    print(f"  ✓ Linked: {account['path']} → {link_type.replace('linked_', '')}: {link_target}\n")


def cmd_reconcile(flags, args):
    """Reconcile account balance against statement."""
    accounts = _load_accounts()
    entity = get_active_entity()
    currency = get_entity_currency()

    identifier = args[0] if args else None
    if not identifier:
        cmd_list(flags, [])
        identifier = prompt("  Account to reconcile (# or path)")

    account, idx = _find_account(identifier, accounts)
    if account is None:
        # Try direct hledger account path
        account = {'path': identifier}

    path = account['path']
    balance = _get_account_balance(path)

    print(f"\n  [{entity}] Reconcile: {path}")
    print(f"  Book balance (hledger): {balance or 'unknown'}")

    statement_bal = prompt("  Statement balance")
    as_of = prompt("  As of date", default=date.today().strftime("%Y-%m-%d"), required=False)

    # Compare
    try:
        book_num = float(''.join(c for c in balance.replace(',', '').split()[-1] if c in '0123456789.-')) if balance else 0
        stmt_num = float(statement_bal.replace(',', ''))
        diff = stmt_num - book_num

        if abs(diff) < 0.01:
            print(f"\n  ✓ Reconciled. No discrepancy.\n")
        else:
            print(f"\n  ⚠ Discrepancy: {currency} {diff:,.2f}")
            print(f"    1) Record adjustment entry")
            print(f"    2) Show recent transactions")
            print(f"    3) Skip")
            choice = prompt("  Choice", default='3', required=False)
            if choice == '2':
                journal = str(get_entity_journal())
                result = subprocess.run(
                    ['hledger', '-f', journal, 'reg', path, '-n', '10'],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    print()
                    for line in result.stdout.splitlines()[-10:]:
                        print(f"    {line}")
            print()
    except (ValueError, AttributeError):
        print("  Could not compare balances.\n")

    _print_statement_summary(path)


# ─── Bank statement import + matching (I69) ─────────────────────────────────

# Statement lines live in the YAML store, one file per account
# (statements/<slug>.yaml, slug = slugified account path). Import stores
# lines only — it never writes to the journal; matching records which
# statement line corresponds to which journal posting.
STATEMENT_MODULE = "statements"


def _flag(args, name, default=None):
    """Value after --name in args, or default."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _load_statement_store(account):
    """Statement store dict or None."""
    return load_entity(STATEMENT_MODULE, R.account_slug(account))


def _save_statement_store(account, store):
    save_entity(STATEMENT_MODULE, R.account_slug(account), store)


def _line_to_store(line, source_file):
    """Core line dict → YAML-safe stored dict (Decimal as string)."""
    return {
        "date": line["date"],
        "description": line["description"],
        "amount": str(line["amount"]),
        "fitid": line.get("fitid"),
        "source_file": source_file,
        "matched": None,
        "status": "unmatched",
    }


def _line_from_store(raw):
    """Stored dict → core line dict (Decimal amount)."""
    return {
        "date": raw["date"],
        "description": raw["description"],
        "amount": Decimal(str(raw["amount"])),
        "fitid": raw.get("fitid"),
        "source_file": raw.get("source_file", ""),
    }


def _csv_mapping_from(args):
    """Resolve the CSV column mapping: a named mapping from config.yaml
    statement_mappings: (--mapping NAME), or --col-* flags. Returns the
    mapping dict. Exits 1 with a clear message when neither is given
    or the named mapping does not exist."""
    config = load_config()
    name = _flag(args, "--mapping")
    mappings = config.get("statement_mappings") or {}
    if name:
        if name not in mappings:
            available = ", ".join(sorted(mappings)) or "(none defined)"
            print(f"  Unknown statement mapping: {name}")
            print(f"  Available mappings: {available}")
            sys.exit(1)
        return dict(mappings[name])
    mapping = {}
    for key, flag in (("date", "--col-date"),
                      ("description", "--col-desc"),
                      ("amount", "--col-amount"),
                      ("debit", "--col-debit"),
                      ("credit", "--col-credit")):
        value = _flag(args, flag)
        if value:
            mapping[key] = value
    date_format = _flag(args, "--date-format")
    if date_format:
        mapping["date_format"] = date_format
    if not mapping:
        print("  No column mapping: pass --mapping NAME (a named mapping "
              "in config.yaml statement_mappings:) or --col-date/--col-desc/"
              "--col-amount (or --col-debit/--col-credit) flags.")
        sys.exit(1)
    return mapping


def cmd_import(flags, args):
    """Import a bank statement: `pair account import <file> --account PATH
    [--mapping NAME | --col-* flags] [--format csv|ofx]`.

    Idempotent: the file's sha256 is recorded, so re-importing the same
    file is a no-op; lines already in the store (same account, date,
    amount, description, fitid) are skipped. Nothing is written to the
    journal — import only stores statement lines.
    """
    if not args:
        print("  Usage: pair account import <file> --account <path> "
              "[--mapping NAME | --col-* flags]")
        sys.exit(1)
    path = Path(args[0])
    if not path.exists():
        print(f"  Statement file not found: {path}")
        sys.exit(1)
    account = _flag(args, "--account") or prompt("  Account path")
    fmt = _flag(args, "--format")
    if fmt is None:
        suffix = path.suffix.lower()
        fmt = {"csv": "csv", ".csv": "csv",
               ".ofx": "ofx", ".qfx": "ofx"}.get(suffix)
        if fmt is None:
            print(f"  Unknown statement format for {path.name}: pass "
                  f"--format csv|ofx.")
            sys.exit(1)
    if fmt not in ("csv", "ofx"):
        print(f"  Unknown statement format: {fmt} (csv or ofx)")
        sys.exit(1)

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    store = _load_statement_store(account) or {
        "account": account, "imports": [], "lines": []}
    if any(i.get("sha256") == digest for i in store.get("imports", [])):
        print(f"  Already imported {path.name}; nothing new.")
        return
    text = data.decode("utf-8-sig", errors="replace")
    try:
        if fmt == "csv":
            mapping = _csv_mapping_from(args)
            lines = R.parse_csv_statement(text, mapping)
        else:
            lines = R.parse_ofx_statement(text)
    except ValueError as e:
        print(f"  Cannot import {path.name}: {e}")
        sys.exit(1)

    existing = {R.dedup_key(_line_from_store(raw), account)
                for raw in store.get("lines", [])}
    new_lines = []
    skipped = 0
    for line in lines:
        key = R.dedup_key(line, account)
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        new_lines.append(_line_to_store(line, path.name))
    store.setdefault("lines", []).extend(new_lines)
    store.setdefault("imports", []).append({
        "file": path.name, "sha256": digest,
        "imported_at": date.today().strftime("%Y-%m-%d"),
        "lines": len(lines),
    })
    _save_statement_store(account, store)
    print(f"  Imported {len(lines)} lines from {path.name} "
          f"({len(new_lines)} new, {skipped} duplicates skipped).")


def _journal_postings(account):
    """Journal postings on an account via hledger reg CSV.

    Returns [{date, description, amount}] or raises SystemExit with a
    clear message when the journal or hledger is unavailable. Uses the
    module-level get_entity_journal (imported from lib.ui at the top),
    which tests patch — do not re-import it locally.
    """
    journal = get_entity_journal()
    if not journal.exists():
        print("  No entity journal found.")
        sys.exit(1)
    result = subprocess.run(
        ["hledger", "-f", str(journal), "reg", account,
         "--output-format", "csv"],
        capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  Could not read postings for {account}: "
              f"{(result.stderr or result.stdout).strip()[:500]}")
        sys.exit(1)
    postings = []
    for row in csv.DictReader(io.StringIO(result.stdout)):
        raw_amount = (row.get("amount") or "").strip()
        try:
            amount = Decimal(raw_amount.rsplit(" ", 1)[-1].replace(",", ""))
        except Exception:
            continue
        postings.append({
            "date": (row.get("date") or "").strip(),
            "description": (row.get("description") or "").strip(),
            "amount": amount,
        })
    return postings


def cmd_match(flags, args):
    """Match stored statement lines to journal postings:
    `pair account match <account-path> [--window N]`.

    Only lines still unmatched are (re)matched; matched lines keep
    their match. Unmatched lines are findings, not failures: the
    command exits 0 and reports the counts.
    """
    account = args[0] if args else _flag(args, "--account")
    if not account:
        account = prompt("  Account path")
    window = _flag(args, "--window")
    try:
        window_days = int(window) if window else R.DEFAULT_WINDOW_DAYS
    except ValueError:
        print(f"  Invalid --window: {window!r}")
        sys.exit(1)
    if window_days < 0:
        print("  --window cannot be negative.")
        sys.exit(1)

    store = _load_statement_store(account)
    if not store or not store.get("lines"):
        print(f"  No imported statements for {account}. "
              f"Run `pair account import` first.")
        sys.exit(1)
    postings = _journal_postings(account)

    pending = [raw for raw in store["lines"] if not raw.get("matched")]
    results = R.match_lines([_line_from_store(raw) for raw in pending],
                            postings, window_days=window_days)
    for raw, result in zip(pending, results):
        raw["status"] = result["status"]
        if result["status"] == "matched":
            posting = result["posting"]
            raw["matched"] = {
                "date": posting["date"],
                "description": posting["description"],
                "amount": str(posting["amount"]),
            }
    _save_statement_store(account, store)

    counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for raw in store["lines"]:
        counts[raw.get("status", "unmatched")] += 1
    for raw, result in zip(pending, results):
        line = result["line"]
        mark = {"matched": "✓", "ambiguous": "?", "unmatched": "✗"}[
            result["status"]]
        detail = ""
        if result["status"] == "matched":
            p = result["posting"]
            detail = f"  -> {p['date']} {p['description']}"
        elif result["status"] == "ambiguous":
            detail = (f"  -> {len(result['candidates'])} candidates, "
                      f"no unique closest")
        print(f"  {mark} {line['date']} {line['description'][:40]:<40} "
              f"{line['amount']:>12.2f}{detail}")
    print(f"\n  {counts['matched']} matched, {counts['ambiguous']} ambiguous, "
          f"{counts['unmatched']} unmatched.")


def _print_statement_summary(path):
    """One read-only line after a reconcile, when a statement store
    exists for the account. Prints nothing otherwise, so reconcile
    behaves exactly as before for accounts with no imports."""
    store = _load_statement_store(path)
    if not store or not store.get("lines"):
        return
    counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for raw in store["lines"]:
        counts[raw.get("status", "unmatched")] += 1
    print(f"  Statement lines: {counts['matched']} matched, "
          f"{counts['unmatched']} unmatched, "
          f"{counts['ambiguous']} ambiguous. "
          f"Run `pair account match {path}` to update.")


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair account — account registry with rich metadata

Usage: pair account [COMMAND] [OPTIONS]

With no argument, shows a numbered menu.

Commands:
  list [PREFIX]         List registered accounts
  add [PATH]            Register a new account
  show [ACCOUNT]        Show account detail + balance
  edit [ACCOUNT]        Edit account metadata
  remove [ACCOUNT]      Remove from registry (journal unchanged)
  tree [PREFIX]         Visual account tree (from hledger)
  tag                   Tag management
  find [QUERY]          Search accounts by any field
  link [ACCOUNT]        Link to asset/liability/contact
  reconcile [ACCOUNT]   Check balance against statement
  import <FILE> --account PATH [--mapping NAME | --col-* flags]
                      Import a bank statement (CSV/OFX)
  match [ACCOUNT] [--window N]
                      Match statement lines to journal postings

List filters:
  --tag TAG             Filter by tag
  --type TYPE           Filter by type
  --institution NAME    Filter by institution
  --with-balances       Include current balances (slower)
  --flat                No tree, just paths

Tag usage:
  pair account tag --list                List all tags
  pair account tag ACCOUNT TAG           Add tag
  pair account tag ACCOUNT --remove TAG  Remove tag
  pair account tag TAG                   Show accounts with tag

Link usage:
  pair account link ACCOUNT --asset SLUG
  pair account link ACCOUNT --liability SLUG
  pair account link ACCOUNT --contact SLUG

Data stored in: entities/<slug>/accounts.yaml
Hledger declarations remain in: include/accounts.journal

Examples:
  pair account                           Interactive menu
  pair account list Assets               List asset accounts
  pair account show "Business Chequing"  Show detail
  pair account add                       Register new account
  pair account reconcile 1               Reconcile first account
  pair account find TD                   Search by institution
""")
