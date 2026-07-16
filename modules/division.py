"""pair division — division management and reporting."""

import sys
import re
from pathlib import Path
from decimal import Decimal

from lib.helpers import load_config, parse_global_flags, BASE_DIR
from lib.yaml_store import list_entities, load_entity
from lib.journal import get_generated_dir


def dispatch(args):
    """Route division subcommands."""
    flags, remaining = parse_global_flags(args)

    if not remaining or flags['help']:
        print_help()
        return

    action = remaining[0]
    action_args = remaining[1:]

    if action == 'list':
        cmd_list(flags, action_args)
    else:
        print(f"Unknown division action: {action}")
        print_help()
        sys.exit(1)


def print_help():
    print("""pair division — division management

Actions:
  list              Show divisions and entity counts

Usage:
  pair division list
""")


# ─── pair division list ───────────────────────────────────────────────────

def cmd_list(flags, args):
    """Scan all YAML entities and expense journals for division tags, display a table."""
    config = load_config()
    configured = config.get('divisions', [])

    # Count divisions across entities
    division_counts = {}

    # Scan assets
    for slug in list_entities('assets'):
        entity = load_entity('assets', slug)
        if entity:
            div = entity.get('division', '')
            if div:
                division_counts.setdefault(div, {'assets': 0, 'liabilities': 0, 'expenses': 0})
                division_counts[div]['assets'] += 1

    # Scan liabilities
    for slug in list_entities('liabilities'):
        entity = load_entity('liabilities', slug)
        if entity:
            div = entity.get('division', '')
            if div:
                division_counts.setdefault(div, {'assets': 0, 'liabilities': 0, 'expenses': 0})
                division_counts[div]['liabilities'] += 1

    # Scan expense journals for division tags
    expense_divisions = _scan_expense_journals()
    for div, count in expense_divisions.items():
        division_counts.setdefault(div, {'assets': 0, 'liabilities': 0, 'expenses': 0})
        division_counts[div]['expenses'] += count

    # Include configured divisions even if empty
    for div in configured:
        division_counts.setdefault(div, {'assets': 0, 'liabilities': 0, 'expenses': 0})

    if not division_counts:
        print("No divisions configured or found.")
        print("Use 'pair init' or edit config.yaml to add divisions.")
        return

    # Display table
    print(f"\n{'Division':<20} {'Assets':>8} {'Liabilities':>13} {'Expenses':>10} {'Total':>8}")
    print("─" * 63)

    for div in sorted(division_counts.keys()):
        counts = division_counts[div]
        total = counts['assets'] + counts['liabilities'] + counts['expenses']
        configured_marker = " *" if div in configured else ""
        print(f"  {div:<18} {counts['assets']:>8} {counts['liabilities']:>13} "
              f"{counts['expenses']:>10} {total:>8}{configured_marker}")

    print()
    if configured:
        print(f"  * = configured in config.yaml")
        print()


def _scan_expense_journals():
    """Scan generated expense journals for division tags."""
    division_counts = {}

    if not get_generated_dir().exists():
        return division_counts

    for year_dir in sorted(get_generated_dir().iterdir()):
        if not year_dir.is_dir():
            continue
        expenses_file = year_dir / "expenses.journal"
        if not expenses_file.exists():
            continue

        with open(expenses_file) as f:
            for line in f:
                # Match transaction header with tags
                match = re.match(
                    r'^\d{4}-\d{2}-\d{2}\s+\*\s+.+?\s+;\s+(.*)',
                    line.rstrip()
                )
                if match:
                    tags_str = match.group(1)
                    # Look for division:value in tags
                    div_match = re.search(r'division:(\S+)', tags_str)
                    if div_match:
                        div = div_match.group(1).rstrip(',')
                        division_counts[div] = division_counts.get(div, 0) + 1

    return division_counts
