"""pair export — export journal data in various formats."""

import sys
import subprocess
from pathlib import Path

from lib.helpers import get_entity_dir, get_active_entity, parse_global_flags, prompt
from lib.ui import (
    get_entity_journal, get_entity_currency, require_entity,
    split_passthrough, show_menu, resolve_menu_or_direct,
    launch_tool, check_tool
)


# ─── Menu Options ────────────────────────────────────────────────────────────

EXPORT_OPTIONS = [
    {'key': 'csv',       'label': 'Balance report as CSV'},
    {'key': 'beancount', 'label': 'Full journal as Beancount format'},
    {'key': 'psql',      'label': 'Push to PostgreSQL (hledger2psql)'},
    {'key': 'json',      'label': 'Journal as JSON'},
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route export subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    pair_args, tool_args = split_passthrough(remaining)
    selected, extra_args = resolve_menu_or_direct(pair_args, EXPORT_OPTIONS)

    if selected is None and not pair_args:
        selected = show_menu("Export", EXPORT_OPTIONS)
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
    """Dispatch to export command."""
    actions = {
        'csv': cmd_csv, 'beancount': cmd_beancount,
        'psql': cmd_psql, 'json': cmd_json,
    }
    if action in actions:
        actions[action](flags, args)
    else:
        print(f"  Unknown export format: {action}")
        print("  Options: " + ", ".join(actions.keys()))
        sys.exit(1)


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_csv(flags, args):
    """Export balance report as CSV."""
    journal = str(get_entity_journal())
    entity = get_active_entity()
    entity_dir = get_entity_dir()

    # Default: balance sheet as CSV
    out_file = args[0] if args and not args[0].startswith('-') else str(entity_dir / f'{entity}-export.csv')

    cmd = ['hledger', '-f', journal, 'bal', '--layout', 'bare', '-N', '-O', 'csv']
    # Add any extra hledger args
    extra = [a for a in args if a.startswith('-')]
    cmd.extend(extra)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error: {result.stderr.strip()}\n")
        return

    Path(out_file).write_text(result.stdout)
    lines = len(result.stdout.splitlines()) - 1
    print(f"\n  [{entity}] Exported {lines} rows to: {out_file}\n")


def cmd_beancount(flags, args):
    """Export full journal as Beancount format."""
    journal = str(get_entity_journal())
    entity = get_active_entity()
    entity_dir = get_entity_dir()

    out_file = args[0] if args and not args[0].startswith('-') else str(entity_dir / f'{entity}.beancount')

    cmd = ['hledger', '-f', journal, 'print', '-o', out_file]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error: {result.stderr.strip()}\n")
        return

    size = Path(out_file).stat().st_size
    print(f"\n  [{entity}] Exported to: {out_file} ({size:,} bytes)")
    print(f"  Use with: fava {out_file}\n")


def cmd_psql(flags, args):
    """Export to PostgreSQL via hledger2psql."""
    journal = str(get_entity_journal())
    entity = get_active_entity()

    if not check_tool('hledger2psql'):
        print("\n  hledger2psql not installed.")
        print("  Install: pipx install hledger2psql\n")
        return

    cmd = ['hledger2psql']
    print(f"\n  [{entity}] Launching hledger2psql...")
    print(f"  Journal: {journal}")
    print(f"  (Requires PostgreSQL connection configured)\n")
    launch_tool(cmd, args, env_extra={'LEDGER_FILE': journal})


def cmd_json(flags, args):
    """Export journal as JSON."""
    journal = str(get_entity_journal())
    entity = get_active_entity()
    entity_dir = get_entity_dir()

    out_file = args[0] if args and not args[0].startswith('-') else str(entity_dir / f'{entity}-export.json')

    cmd = ['hledger', '-f', journal, 'print', '-O', 'json']

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error: {result.stderr.strip()}\n")
        return

    Path(out_file).write_text(result.stdout)
    size = Path(out_file).stat().st_size
    print(f"\n  [{entity}] Exported to: {out_file} ({size:,} bytes)\n")


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair export — export journal data in various formats

Usage: pair export [FORMAT] [OUTPUT_FILE] [-- HLEDGER_OPTIONS]

With no argument, shows a numbered menu.

Formats:
  csv [FILE]            Balance report as CSV
  beancount [FILE]      Full journal in Beancount format
  psql                  Push to PostgreSQL (hledger2psql)
  json [FILE]           Full journal as JSON

Default output files are written to the entity directory.

Pass extra hledger options after --:
  pair export csv -- -M --depth 2       Monthly, depth 2
  pair export csv -- type:x             Expenses only

Examples:
  pair export                            Interactive menu
  pair export csv                        Balance CSV to entity dir
  pair export beancount                  Export for fava
  pair export json /tmp/data.json        Custom output path
  pair export csv -- type:x -M           Monthly expense CSV
""")
