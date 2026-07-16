"""company generate — regenerate journals from YAML."""

import sys
from datetime import date
from pathlib import Path

from lib.helpers import BASE_DIR, parse_global_flags, load_config
from lib.yaml_store import list_entities, load_entity
from lib.journal import (
    GENERATED_DIR, ensure_year_structure, update_company_journal,
    generated_header, write_journal_atomic
)


def cmd_generate(args):
    """Regenerate all generated journals from YAML metadata."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    # Parse --module and --year flags
    module_filter = None
    year_filter = None
    for i, a in enumerate(remaining):
        if a == '--module' and i + 1 < len(remaining):
            module_filter = remaining[i + 1]
        elif a == '--year' and i + 1 < len(remaining):
            year_filter = remaining[i + 1]

    dry_run = flags['dry_run']
    quiet = flags.get('quiet', False)

    modules_to_run = _get_modules(module_filter)

    if not modules_to_run:
        print(f"Unknown module: {module_filter}")
        print("Available: assets, liabilities, include")
        sys.exit(1)

    if dry_run and not quiet:
        print("\n  DRY RUN — showing what would be generated:\n")

    results = []

    for module_name, gen_func in modules_to_run:
        result = gen_func(year_filter=year_filter, dry_run=dry_run, quiet=quiet)
        results.append((module_name, result))

    # Rebuild include chain (unless filtering to a specific module that isn't 'include')
    if module_filter is None or module_filter == 'include':
        if dry_run:
            if not quiet:
                print("  Would rebuild: include/company.journal")
        else:
            update_company_journal()
            if not quiet:
                print("  ✓ include/company.journal rebuilt")

    if not quiet and not dry_run:
        print("\n  Generate complete.")
    elif not quiet and dry_run:
        print("\n  (dry run — no files written)")

    print()


def print_help():
    print("""company generate — regenerate journals from YAML

Usage: company generate [flags]

Regenerates all generated journal files from YAML metadata:
  - Amortization entries from assets/*.yaml
  - Payment entries from liabilities/*.yaml
  - Rebuilds include/company.journal

Flags:
  --module <name>     Regenerate just one module (assets, liabilities, include)
  --year <YYYY>       Only regenerate for a specific year
  --dry-run           Show what would be generated without writing
  --quiet             Suppress output
""")


# ─── Module registry ─────────────────────────────────────────────────────────

def _get_modules(module_filter):
    """Return list of (name, gen_func) tuples to run."""
    all_modules = [
        ('assets', _generate_assets),
        ('liabilities', _generate_liabilities),
    ]

    if module_filter is None:
        return all_modules
    elif module_filter == 'include':
        return []  # include rebuild handled separately
    else:
        return [(name, func) for name, func in all_modules if name == module_filter]


# ─── Asset generation ─────────────────────────────────────────────────────────

def _generate_assets(year_filter=None, dry_run=False, quiet=False):
    """Regenerate amortization journals for all assets."""
    from modules.asset import _generate_amort_entries

    slugs = list_entities("assets")
    if not slugs:
        if not quiet:
            print("  No assets found.")
        return 0

    through_date = date.today().strftime("%Y-%m-%d")
    entries_by_year = {}

    for slug in slugs:
        asset = load_entity("assets", slug)
        if not asset:
            continue

        # Skip disposed assets (entries stop at disposal date)
        end_date = through_date
        disposal = asset.get('disposal', {})
        if disposal.get('date'):
            end_date = min(end_date, disposal['date'])

        new_entries = _generate_amort_entries(asset, end_date)
        for year_str, entry in new_entries:
            if year_filter and year_str != year_filter:
                continue
            entries_by_year.setdefault(year_str, []).append(entry)

    # Write journals per year
    total_entries = 0
    for year_str, entries in sorted(entries_by_year.items()):
        if dry_run:
            if not quiet:
                print(f"  Would write: generated/{year_str}/amortization.journal "
                      f"({len(entries)} entries)")
        else:
            ensure_year_structure(int(year_str))
            journal_path = GENERATED_DIR / year_str / "amortization.journal"
            header = generated_header("assets/*.yaml", "company generate --module assets")
            content = header + "".join(entries)
            write_journal_atomic(journal_path, content)
            if not quiet:
                print(f"  ✓ generated/{year_str}/amortization.journal ({len(entries)} entries)")
        total_entries += len(entries)

    return total_entries


# ─── Liability generation ─────────────────────────────────────────────────────

def _generate_liabilities(year_filter=None, dry_run=False, quiet=False):
    """Regenerate payment journals for all liabilities."""
    from modules.liability import _generate_payment_entries, _remaining_balance

    slugs = list_entities("liabilities")
    if not slugs:
        if not quiet:
            print("  No liabilities found.")
        return 0

    # Default: through end of current year
    through_date = f"{date.today().year}-12-31"
    entries_by_year = {}

    for slug in slugs:
        liab = load_entity("liabilities", slug)
        if not liab:
            continue

        # Skip paid-off liabilities
        remaining = _remaining_balance(liab)
        if remaining <= 0:
            continue

        new_entries = _generate_payment_entries(liab, through_date)
        for year_str, entry in new_entries:
            if year_filter and year_str != year_filter:
                continue
            entries_by_year.setdefault(year_str, []).append(entry)

    # Write journals per year
    total_entries = 0
    for year_str, entries in sorted(entries_by_year.items()):
        if dry_run:
            if not quiet:
                print(f"  Would write: generated/{year_str}/loan-payments.journal "
                      f"({len(entries)} entries)")
        else:
            ensure_year_structure(int(year_str))
            journal_path = GENERATED_DIR / year_str / "loan-payments.journal"
            header = generated_header("liabilities/*.yaml",
                                      "company generate --module liabilities")
            content = header + "".join(entries)
            write_journal_atomic(journal_path, content)
            if not quiet:
                print(f"  ✓ generated/{year_str}/loan-payments.journal ({len(entries)} entries)")
        total_entries += len(entries)

    return total_entries
