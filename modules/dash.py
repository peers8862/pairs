"""pair dash — launch TUI and web dashboard interfaces."""

import sys
from pathlib import Path

from lib.helpers import get_entity_dir, parse_global_flags
from lib.ui import (
    get_entity_journal, get_entity_name, get_entity_currency,
    require_entity, split_passthrough, show_menu, resolve_menu_or_direct,
    launch_tool, check_tool
)


# ─── Menu Options ────────────────────────────────────────────────────────────

DASH_OPTIONS = [
    {
        'key': 'tui',
        'label': 'puffin TUI dashboard',
        'tool': 'puffin',
        'needs_tty': True,
    },
    {
        'key': 'web',
        'label': 'hledger-web (browser, localhost:5000)',
        'tool': 'hledger-web',
    },
    {
        'key': 'lit',
        'label': 'hledger-lit (streamlit charts)',
        'tool': 'hledger-lit',
    },
    {
        'key': 'fava',
        'label': 'fava (beancount web UI with charts)',
        'tool': 'fava',
    },
    {
        'key': 'ui',
        'label': 'hledger-ui (curses)',
        'tool': 'hledger-ui',
        'needs_tty': True,
    },
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route dash subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    # Split at -- for passthrough
    pair_args, tool_args = split_passthrough(remaining)

    # Try direct selection from CLI args
    selected, extra_args = resolve_menu_or_direct(pair_args, DASH_OPTIONS)

    # If not resolved, show interactive menu
    if selected is None and not pair_args:
        selected = show_menu("Dashboards", DASH_OPTIONS)
        if selected is None:
            return
    elif selected is None:
        # Args were given but didn't match any option
        print(f"  Unknown dashboard: {pair_args[0]}")
        print("  Options: " + ", ".join(o['key'] for o in DASH_OPTIONS))
        sys.exit(1)

    # Launch the selected dashboard
    _launch_dashboard(selected, tool_args + extra_args)


# ─── Launchers ───────────────────────────────────────────────────────────────

def _launch_dashboard(option, extra_args):
    """Launch the selected dashboard tool pointed at the active entity."""
    tool = option['tool']
    key = option['key']

    if not check_tool(tool):
        print(f"\n  '{tool}' is not installed or not in PATH.")
        print(f"  See 'pair --help' for installation info.\n")
        return

    journal = str(get_entity_journal())
    entity_dir = get_entity_dir()
    entity_name = get_entity_name()

    if key == 'tui':
        _launch_puffin(entity_dir, journal, extra_args)
    elif key == 'web':
        _launch_hledger_web(journal, entity_name, extra_args)
    elif key == 'lit':
        _launch_hledger_lit(journal, extra_args)
    elif key == 'fava':
        _launch_fava(journal, entity_dir, extra_args)
    elif key == 'ui':
        _launch_hledger_ui(journal, extra_args)


def _launch_puffin(entity_dir, journal, extra_args):
    """Launch puffin with entity-specific config."""
    config_file = entity_dir / 'puffin.json'

    if not config_file.exists():
        _generate_puffin_config(entity_dir, journal)

    cmd = ['puffin', '-cfg', str(config_file)]
    print(f"\n  Launching puffin TUI...")
    print(f"  Journal: {journal}")
    print(f"  Config:  {config_file}\n")
    launch_tool(cmd, extra_args)


def _generate_puffin_config(entity_dir, journal):
    """Auto-generate a puffin.json for this entity."""
    import json

    config = {
        "startDate": "2026",
        "period": "monthly",
        "reports": [
            {"name": "balance sheet", "cmd": f"hledger balancesheet -f {journal}"},
            {"name": "income statement", "cmd": f"hledger incomestatement -f {journal}"},
            {"name": "assets", "cmd": f"hledger balance type:a -f {journal}"},
            {"name": "expenses", "cmd": f"hledger balance type:x -f {journal}"},
            {"name": "revenue", "cmd": f"hledger balance type:r -f {journal}"},
            {"name": "liabilities", "cmd": f"hledger balance type:l -f {journal}"},
            {"name": "register", "cmd": f"hledger register -f {journal}"},
            {"name": "accounts", "cmd": f"hledger accounts --tree -f {journal}", "locked": True},
        ]
    }

    config_file = entity_dir / 'puffin.json'
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)


def _launch_hledger_web(journal, entity_name, extra_args):
    """Launch hledger-web."""
    cmd = ['hledger-web', '-f', journal, '--serve']

    # Default port unless overridden
    if not any('--port' in a for a in extra_args):
        cmd.extend(['--port', '5000'])

    name = entity_name or 'entity'
    print(f"\n  Launching hledger-web for {name}...")
    print(f"  Journal: {journal}")
    print(f"  URL:     http://localhost:5000\n")
    launch_tool(cmd, extra_args)


def _launch_hledger_lit(journal, extra_args):
    """Launch hledger-lit (streamlit)."""
    cmd = ['hledger-lit']

    print(f"\n  Launching hledger-lit...")
    print(f"  Journal: {journal}")
    print(f"  (Streamlit will open in browser)\n")
    launch_tool(cmd, extra_args, env_extra={'LEDGER_FILE': journal})


def _launch_fava(journal, entity_dir, extra_args):
    """Export to beancount and launch fava."""
    import subprocess

    beancount_file = entity_dir / 'export.beancount'

    print(f"\n  Exporting to beancount format...")
    result = subprocess.run(
        ['hledger', '-f', journal, 'print', '-o', str(beancount_file)],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"  Export failed: {result.stderr.strip()}")
        print("  You may need to alias some account names for beancount compatibility.")
        return

    print(f"  Exported: {beancount_file}")

    cmd = ['fava', str(beancount_file)]

    # Default port unless overridden
    if not any('--port' in a for a in extra_args):
        cmd.extend(['--port', '5500'])

    print(f"  Launching fava...")
    print(f"  URL: http://localhost:5500\n")
    launch_tool(cmd, extra_args)


def _launch_hledger_ui(journal, extra_args):
    """Launch hledger-ui."""
    cmd = ['hledger-ui', '-f', journal]

    print(f"\n  Launching hledger-ui...")
    print(f"  Journal: {journal}\n")
    launch_tool(cmd, extra_args)


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair dash — launch TUI and web dashboard interfaces

Usage: pair dash [DASHBOARD] [-- TOOL_OPTIONS]

Dashboards:
  tui         puffin TUI dashboard (bubbletea)
  web         hledger-web (browser UI with register chart)
  lit         hledger-lit (streamlit dashboard with plotly charts)
  fava        fava (beancount web UI — export + launch)
  ui          hledger-ui (curses TUI)

With no argument, shows a numbered menu for selection.
Select by number or name: pair dash 1, pair dash web

Pass options to the underlying tool after --:
  pair dash web -- --port 8080
  pair dash tui -- -debug
  pair dash fava -- --port 3000

All dashboards operate on the active entity's journal.
Switch entity first with: pair switch <slug>

Examples:
  pair dash                   Interactive menu
  pair dash web               Launch hledger-web directly
  pair dash 3                 Launch option #3 (hledger-lit)
  pair dash lit -- --port 9000  Pass port to streamlit
""")
