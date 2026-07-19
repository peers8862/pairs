"""pair chart — chart generation and visualization tools."""

import sys
import subprocess
import shutil
from pathlib import Path

from lib.helpers import (
    get_entity_dir, get_active_entity, parse_global_flags, prompt, ensure_dir
)
from lib.ui import (
    get_entity_journal, get_entity_currency, require_entity,
    split_passthrough, show_menu, resolve_menu_or_direct,
    launch_tool, check_tool
)


# ─── Menu Options ────────────────────────────────────────────────────────────

CHART_OPTIONS = [
    {'key': 'prices',   'label': 'Price history (all commodities)'},
    {'key': 'sankey',   'label': 'Cash flow diagram (plotly)'},
    {'key': 'bar',      'label': 'Terminal bar chart'},
    {'key': 'plot',     'label': 'Matplotlib chart (any query)'},
    {'key': 'vega',     'label': 'Vega-lite interactive HTML'},
    {'key': 'treemap',  'label': 'Expense treemap'},
]


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Route chart subcommands."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    pair_args, tool_args = split_passthrough(remaining)
    selected, extra_args = resolve_menu_or_direct(pair_args, CHART_OPTIONS)

    if selected is None and not pair_args:
        selected = show_menu("Charts", CHART_OPTIONS)
        if selected is None:
            return
    elif selected is None:
        # Try as direct command
        action = pair_args[0]
        action_args = pair_args[1:] + tool_args
        _dispatch_action(action, flags, action_args)
        return

    key = selected['key']
    all_args = extra_args + tool_args
    _dispatch_action(key, flags, all_args)


def _dispatch_action(action, flags, args):
    """Dispatch to chart command."""
    actions = {
        'prices': cmd_prices, 'sankey': cmd_sankey,
        'bar': cmd_bar, 'plot': cmd_plot,
        'vega': cmd_vega, 'treemap': cmd_treemap,
    }
    if action in actions:
        actions[action](flags, args)
    else:
        print(f"  Unknown chart type: {action}")
        print("  Options: " + ", ".join(actions.keys()))
        sys.exit(1)


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_prices(flags, args):
    """Generate price history chart from prices.journal."""
    from modules.market import cmd_chart as market_chart
    market_chart(flags, args)


def cmd_sankey(flags, args):
    """Generate sankey cash flow diagram."""
    journal = str(get_entity_journal())
    currency = get_entity_currency()
    entity = get_active_entity()

    if not check_tool('hledger-sankey'):
        print("\n  hledger-sankey not installed.")
        print("  Location: ~/.local/bin/hledger-sankey\n")
        return

    # Build command
    cmd = ['hledger-sankey', '--commodity', currency, journal]

    print(f"\n  [{entity}] Generating sankey diagram...")
    print(f"  Journal:   {journal}")
    print(f"  Currency:  {currency}")
    print(f"  (Opens in browser)\n")

    launch_tool(cmd, args)


def cmd_bar(flags, args):
    """Run hledger-bar for terminal bar charts."""
    journal = str(get_entity_journal())

    if not check_tool('hledger-bar'):
        print("\n  hledger-bar not installed.")
        print("  Location: ~/.local/bin/hledger-bar\n")
        return

    # If no args, prompt for account
    if not args:
        print("\n  What to chart?")
        print("  1) Expenses")
        print("  2) Revenue")
        print("  3) Assets")
        print("  4) Custom...\n")
        choice = prompt("  Select", default='1', required=False)
        if choice == '1':
            args = ['type:x']
        elif choice == '2':
            args = ['type:r']
        elif choice == '3':
            args = ['type:a']
        elif choice == '4':
            query = prompt("  hledger query")
            args = query.split()
        else:
            args = ['type:x']

    # hledger-bar needs to be called as: hledger bar ARGS
    # It reads LEDGER_FILE or we pass -f
    cmd = ['hledger', 'bar'] + args
    launch_tool(cmd, env_extra={'LEDGER_FILE': journal})


def cmd_plot(flags, args):
    """Run hledger-plot (matplotlib charts)."""
    journal = str(get_entity_journal())

    if not check_tool('hledger-plot'):
        print("\n  hledger-plot not installed.")
        print("  Install: pipx install hledger-utils\n")
        return

    # If no args, provide interactive selection
    if not args:
        print("\n  What to plot?")
        print("  1) Expenses (monthly)")
        print("  2) Assets (monthly)")
        print("  3) Revenue (monthly)")
        print("  4) Net worth (monthly)")
        print("  5) Income vs Expenses")
        print("  6) Custom query...\n")
        choice = prompt("  Select", default='1', required=False)
        if choice == '1':
            args = ['bal', 'type:x', '-M', '--depth', '2']
        elif choice == '2':
            args = ['bal', 'type:a', '-M']
        elif choice == '3':
            args = ['bal', 'type:r', '-M']
        elif choice == '4':
            args = ['bal', 'type:al', '-M', '-V']
        elif choice == '5':
            args = ['bal', 'type:rx', '-M']
        elif choice == '6':
            query = prompt("  hledger-plot args (e.g. bal Expenses -M --depth 2)")
            args = query.split()
        else:
            args = ['bal', 'type:x', '-M']

    cmd = ['hledger-plot', '-f', journal] + args
    launch_tool(cmd)


def cmd_vega(flags, args):
    """Generate vega-lite interactive charts."""
    if not check_tool('hledger-vega'):
        print("\n  hledger-vega not installed.")
        print("  Location: ~/.local/share/hledger-vega/\n")
        return

    journal = str(get_entity_journal())
    entity = get_active_entity()

    print(f"\n  [{entity}] hledger-vega generates HTML charts using vega-lite.")
    print(f"  Source: ~/.local/share/hledger-vega/src/")
    print(f"  Configure report files in that directory, then run:\n")
    print(f"    cd ~/.local/share/hledger-vega/src && make\n")
    print(f"  See: https://github.com/Xitian9/hledger-vega\n")


def cmd_treemap(flags, args):
    """Generate expense treemap using matplotlib from pair's venv."""
    journal = str(get_entity_journal())
    currency = get_entity_currency()
    entity = get_active_entity()

    # Get expense data from hledger
    cmd = ['hledger', '-f', journal, 'bal', 'type:x', '--depth', '3',
           '-N', '--no-total', '--layout', 'bare', '-O', 'csv']
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  Error: {result.stderr.strip()}\n")
        return

    lines = result.stdout.strip().splitlines()
    if len(lines) < 2:
        print("  No expense data to chart.\n")
        return

    # Use pair's venv python for matplotlib
    venv_python = Path(__file__).resolve().parent.parent / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        print("  matplotlib not available. Run: python3 -m venv .venv && .venv/bin/pip install matplotlib")
        return

    out_path = f"/tmp/{entity}_expenses_treemap.png"
    csv_data = result.stdout

    # Write a temp script for the venv python to execute
    script = f'''
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys

csv_data = sys.stdin.read()
lines = csv_data.strip().splitlines()
entries = []
for line in lines[1:]:
    parts = line.split(",")
    if len(parts) >= 3:
        account = parts[0].strip('"').replace("Expenses:", "")
        try:
            amount = abs(float(parts[2].strip('"')))
            if amount > 0:
                entries.append((account, amount))
        except ValueError:
            continue

if not entries:
    print("  No expense data to chart.")
    sys.exit(0)

entries.sort(key=lambda x: x[1], reverse=True)
labels = [e[0] for e in entries[:15]]
values = [e[1] for e in entries[:15]]

fig, ax = plt.subplots(figsize=(10, 6))
ax.barh(labels[::-1], values[::-1])
ax.set_xlabel("{currency}")
ax.set_title("{entity} — Expenses by Category")
ax.grid(True, alpha=0.3, axis="x")
fig.tight_layout()
plt.savefig("{out_path}", dpi=150)
plt.close()
print("  ✓ Chart saved: {out_path}")
'''

    proc = subprocess.run(
        [str(venv_python), '-c', script],
        input=csv_data, capture_output=True, text=True
    )
    if proc.stdout:
        print(f"\n{proc.stdout}")
    if proc.stderr:
        print(f"  Error: {proc.stderr.strip()}\n")


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair chart — chart generation and visualization

Usage: pair chart [TYPE] [ARGS] [-- TOOL_OPTIONS]

With no argument, shows a numbered menu.

Chart types:
  prices [SYMBOL]       Price history (from prices.journal)
  sankey                Cash flow sankey diagram (plotly, opens browser)
  bar [QUERY]           Terminal bar chart (hledger-bar)
  plot [QUERY]          Matplotlib chart (hledger-plot, saves PNG)
  vega                  Vega-lite interactive HTML charts
  treemap               Expense category breakdown (bar chart PNG)

Interactive mode:
  pair chart plot       → prompts for scope (expenses/assets/revenue/custom)
  pair chart bar        → prompts for what to chart

Direct mode:
  pair chart bar type:x -M               Monthly expenses
  pair chart plot bal Expenses -M --depth 2
  pair chart prices BTC                  Just BTC prices
  pair chart sankey                      Full flow diagram

Pass options to underlying tool after --:
  pair chart plot -- --stacked --xkcd
  pair chart sankey -- --debug

All charts operate on the active entity's journal.

Examples:
  pair chart                              Interactive menu
  pair chart 1                            Prices chart
  pair chart sankey                       Sankey flow diagram
  pair chart bar revenue                  Revenue bar chart
  pair chart treemap                      Expense breakdown
  pair chart plot bal Assets -M -V        Asset value over time
""")
