"""company journal — synthesized journal output for any period."""

import sys
import subprocess
import re
from datetime import date
from pathlib import Path

from lib.helpers import load_config, expand_path, parse_global_flags, BASE_DIR
from lib.journal import GENERATED_DIR, INCLUDE_DIR


def cmd_journal(args):
    """Output a synthesized journal for any date range."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    # Parse args
    from_date = None
    to_date = None
    year = None
    module_filter = None
    output_file = None
    with_accounts = False

    for i, a in enumerate(remaining):
        if a == '--from' and i + 1 < len(remaining):
            from_date = remaining[i + 1]
        elif a == '--to' and i + 1 < len(remaining):
            to_date = remaining[i + 1]
        elif a == '--year' and i + 1 < len(remaining):
            year = remaining[i + 1]
        elif a == '--module' and i + 1 < len(remaining):
            module_filter = remaining[i + 1]
        elif a == '--output' and i + 1 < len(remaining):
            output_file = remaining[i + 1]
        elif a == '--with-accounts':
            with_accounts = True

    # Default: current year
    if not from_date and not to_date and not year:
        year = str(date.today().year)

    if year and not from_date:
        from_date = f"{year}-01-01"
        to_date = f"{int(year) + 1}-01-01"

    config = load_config()
    journal_file = config.get('journal_file')

    # Try hledger first (best output)
    if journal_file and _check_hledger():
        output = _hledger_journal(config, from_date, to_date, module_filter, with_accounts)
    else:
        # Fallback: read generated files directly
        output = _direct_journal(from_date, to_date, module_filter, with_accounts)

    if not output.strip():
        print("No entries found for the specified period.")
        return

    if output_file:
        with open(output_file, 'w') as f:
            f.write(output)
        if not flags.get('quiet'):
            print(f"  Written to: {output_file}")
    else:
        print(output)


def print_help():
    print("""company journal — synthesized journal output

Produces a single, complete journal for any date range across all modules.

Usage:
  company journal                       Current year, all entries
  company journal --year 2025           Full year
  company journal --from 2025-07-01 --to 2026-09-30   Arbitrary span
  company journal --module amortization               Filter to one module
  company journal --output combined.journal           Write to file
  company journal --with-accounts                     Include account declarations

Flags:
  --from DATE         Start date (inclusive)
  --to DATE           End date (exclusive)
  --year YYYY         Shorthand for full year
  --module NAME       Filter: amortization, loan-payments, expenses, assets, payroll, revenue, recurring, equity, tax
  --output FILE       Write to file instead of stdout
  --with-accounts     Prepend account declarations
""")


def _check_hledger():
    """Check if hledger is available."""
    try:
        result = subprocess.run(['hledger', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _hledger_journal(config, from_date, to_date, module_filter, with_accounts):
    """Use hledger print to produce synthesized output."""
    journal_path = str(expand_path(config['journal_file']))

    cmd = ['hledger', '-f', journal_path, 'print']
    if from_date:
        cmd += ['-b', from_date]
    if to_date:
        cmd += ['-e', to_date]

    # Module filter: use tag query
    if module_filter:
        # Filter by source tag containing the module name
        cmd += [f'tag:source={module_filter}']

    result = subprocess.run(cmd, capture_output=True, text=True)

    output = ""
    if with_accounts:
        accounts_file = INCLUDE_DIR / "accounts.journal"
        if accounts_file.exists():
            output += accounts_file.read_text() + "\n"

    if result.returncode == 0:
        output += result.stdout

    return output


def _direct_journal(from_date, to_date, module_filter, with_accounts):
    """Read generated files directly without hledger."""
    from datetime import datetime

    output_parts = []

    # Include accounts if requested
    if with_accounts:
        accounts_file = INCLUDE_DIR / "accounts.journal"
        if accounts_file.exists():
            output_parts.append(accounts_file.read_text())
            output_parts.append("")

    # Header
    output_parts.append(f"; Synthesized journal")
    if from_date:
        output_parts.append(f"; From: {from_date}")
    if to_date:
        output_parts.append(f"; To: {to_date}")
    output_parts.append("")

    # Determine which year directories to scan
    if from_date:
        start_year = int(from_date[:4])
    else:
        start_year = 2020
    if to_date:
        end_year = int(to_date[:4])
    else:
        end_year = date.today().year

    # Determine which modules to include
    if module_filter:
        module_files = [f"{module_filter}.journal"]
    else:
        module_files = None  # all

    # Collect entries
    for year in range(start_year, end_year + 1):
        year_dir = GENERATED_DIR / str(year)
        if not year_dir.exists():
            continue

        files = sorted(year_dir.glob("*.journal"))
        for jfile in files:
            if module_files and jfile.name not in module_files:
                continue

            content = jfile.read_text()
            # Filter entries by date
            filtered = _filter_entries_by_date(content, from_date, to_date)
            if filtered.strip():
                output_parts.append(f"; --- {jfile.name} ({year}) ---")
                output_parts.append(filtered)

    # Also include invoices
    if not module_filter or module_filter == 'revenue':
        invoices_dir = BASE_DIR / "invoices"
        if invoices_dir.exists():
            for jfile in sorted(invoices_dir.glob("*.journal")):
                content = jfile.read_text()
                filtered = _filter_entries_by_date(content, from_date, to_date)
                if filtered.strip():
                    output_parts.append(f"; --- {jfile.name} ---")
                    output_parts.append(filtered)

    return "\n".join(output_parts) + "\n"


def _filter_entries_by_date(content, from_date, to_date):
    """Filter journal entries to only include those within date range."""
    if not from_date and not to_date:
        # Strip generated headers
        lines = content.split('\n')
        filtered = [l for l in lines if not l.startswith('; ═') and
                    not l.startswith('; GENERATED') and
                    not l.startswith('; Source:') and
                    not l.startswith('; Regenerate:') and
                    not l.startswith('; Last generated:')]
        return '\n'.join(filtered)

    entries = []
    current_entry = []
    include_current = False

    for line in content.split('\n'):
        # Start of a new entry
        match = re.match(r'^(\d{4}-\d{2}-\d{2})\s', line)
        if match:
            # Save previous entry if it passed filter
            if current_entry and include_current:
                entries.append('\n'.join(current_entry))

            current_entry = [line]
            entry_date = match.group(1)

            # Check date range
            include_current = True
            if from_date and entry_date < from_date:
                include_current = False
            if to_date and entry_date >= to_date:
                include_current = False
        elif line.strip() == '' and current_entry:
            current_entry.append(line)
            if include_current:
                entries.append('\n'.join(current_entry))
            current_entry = []
            include_current = False
        elif current_entry:
            current_entry.append(line)
        # Skip header comments
        elif line.startswith(';'):
            continue

    # Don't forget last entry
    if current_entry and include_current:
        entries.append('\n'.join(current_entry))

    return '\n'.join(entries)
