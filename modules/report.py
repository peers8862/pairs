"""pair report — passthrough to hledger for the active entity's journal."""

import sys
import subprocess
import shutil

from lib.helpers import parse_global_flags
from lib.ui import get_entity_journal, get_entity_name, require_entity


def dispatch(args):
    """Route to the report command."""
    cmd_report(args)


def cmd_report(args):
    """Pass arguments through to hledger against the active entity's journal.

    Usage:
        pair report register expenses -M
        pair report bs
        pair report is -p 2026
        pair report bal assets --tree
        pair report accounts
    """
    flags, remaining = parse_global_flags(args)

    if flags['help'] or not remaining:
        print_help()
        return

    require_entity()

    # Verify hledger is available
    if not shutil.which('hledger'):
        print("  hledger is not installed or not in PATH.")
        print("  Install: https://hledger.org/install.html")
        sys.exit(1)

    journal = str(get_entity_journal())
    entity_name = get_entity_name()

    # Fallback: older entities use company.journal instead of entity.journal
    from pathlib import Path
    if not Path(journal).exists():
        alt = Path(journal).parent / 'company.journal'
        if alt.exists():
            journal = str(alt)

    # Build the hledger command: hledger -f <journal> <remaining args...>
    cmd = ['hledger', '-f', journal] + remaining

    # Show what we're running (subtle, one line)
    print(f"  [{entity_name}] hledger {' '.join(remaining)}")
    print(flush=True)

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def print_help():
    print("""pair report — passthrough to hledger

  Runs any hledger command against the active entity's journal file.
  Saves you from remembering the path to the entity journal.

Usage:
  pair report <hledger-command> [args...]

Examples:
  pair report register              Full register
  pair report register expenses -M  Monthly expense register
  pair report bs                    Balance sheet
  pair report is                    Income statement
  pair report is -p 2026-Q2         Income statement for Q2
  pair report bal assets --tree     Asset balances as tree
  pair report accounts              List all accounts
  pair report bal -M --transpose    Monthly balances transposed
  pair report cashflow              Cash flow statement
  pair report stats                 Journal statistics

Any hledger command and flags work — this just supplies -f <journal>.
""")
