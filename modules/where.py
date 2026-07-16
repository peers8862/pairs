"""pair where — find where entries/files live."""

import sys
import re
from pathlib import Path

from lib.helpers import BASE_DIR, parse_global_flags
from lib.yaml_store import list_entities, load_entity
from lib.journal import GENERATED_DIR


SEARCH_MODULES = [
    ("assets", "Asset"),
    ("liabilities", "Liability"),
    ("contacts", "Contact"),
    ("contracts", "Contract"),
]


def cmd_where(args):
    """Search for a query string across YAML and generated journals."""
    flags, remaining = parse_global_flags(args)

    if flags['help'] or not remaining:
        print_help()
        return

    query = " ".join(remaining)
    results = []

    # Search YAML filenames and content
    results.extend(_search_yaml(query))

    # Search generated journal files
    results.extend(_search_journals(query))

    if not results:
        print(f"\n  No results for '{query}'.")
        return

    # Display results
    print(f"\n  Results for '{query}'")
    print("  " + "─" * 60)

    for result in results:
        if result.get('line_num'):
            print(f"  {result['type']:<12} {result['path']}:{result['line_num']}")
            if result.get('context'):
                print(f"  {'':12} {result['context'].strip()}")
        else:
            print(f"  {result['type']:<12} {result['path']}")
            if result.get('name'):
                print(f"  {'':12} name: {result['name']}")

    print(f"\n  {len(results)} result(s) found.")
    print()


def print_help():
    print("""pair where — find where entries/files live

Usage: pair where <query>

Searches across:
  - YAML filenames in assets/, liabilities/, contacts/, contracts/
  - YAML name fields in those files
  - Generated journal descriptions (grep in generated/ files)

Output shows: entity type, file path, line number (for journals).
""")


# ─── YAML search ─────────────────────────────────────────────────────────────

def _search_yaml(query):
    """Search YAML filenames and name fields."""
    results = []
    query_lower = query.lower()

    for module_name, entity_type in SEARCH_MODULES:
        slugs = list_entities(module_name)
        for slug in slugs:
            # Filename match
            if query_lower in slug.lower():
                entity = load_entity(module_name, slug)
                name = entity.get('name', slug) if entity else slug
                results.append({
                    'type': entity_type,
                    'path': f"{module_name}/{slug}.yaml",
                    'name': name,
                    'line_num': None,
                })
                continue

            # Name field match
            entity = load_entity(module_name, slug)
            if entity and query_lower in entity.get('name', '').lower():
                results.append({
                    'type': entity_type,
                    'path': f"{module_name}/{slug}.yaml",
                    'name': entity['name'],
                    'line_num': None,
                })

    return results


# ─── Journal search ──────────────────────────────────────────────────────────

def _search_journals(query):
    """Search generated journal files for query in description lines."""
    results = []
    query_lower = query.lower()

    if not GENERATED_DIR.exists():
        return results

    for journal_file in sorted(GENERATED_DIR.rglob("*.journal")):
        try:
            lines = journal_file.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for line_num, line in enumerate(lines, 1):
            # Match transaction description lines (date followed by description)
            # Format: YYYY-MM-DD * Description
            if re.match(r'^\d{4}-\d{2}-\d{2}\s', line):
                if query_lower in line.lower():
                    rel_path = journal_file.relative_to(BASE_DIR)
                    results.append({
                        'type': 'Journal',
                        'path': str(rel_path),
                        'line_num': line_num,
                        'context': line,
                    })

    # Also search manual journal files
    journal_dir = BASE_DIR / "journal"
    if journal_dir.exists():
        for journal_file in sorted(journal_dir.rglob("*.journal")):
            try:
                lines = journal_file.read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(lines, 1):
                if re.match(r'^\d{4}-\d{2}-\d{2}\s', line):
                    if query_lower in line.lower():
                        rel_path = journal_file.relative_to(BASE_DIR)
                        results.append({
                            'type': 'Journal',
                            'path': str(rel_path),
                            'line_num': line_num,
                            'context': line,
                        })

    # Also search invoices
    invoices_dir = BASE_DIR / "invoices"
    if invoices_dir.exists():
        for journal_file in sorted(invoices_dir.glob("*.journal")):
            try:
                lines = journal_file.read_text().splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(lines, 1):
                if re.match(r'^\d{4}-\d{2}-\d{2}\s', line):
                    if query_lower in line.lower():
                        rel_path = journal_file.relative_to(BASE_DIR)
                        results.append({
                            'type': 'Invoice',
                            'path': str(rel_path),
                            'line_num': line_num,
                            'context': line,
                        })

    return results
