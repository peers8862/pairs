"""pair stages — total spending by company stage (I53).

Reads the stage_bands date ranges from config.yaml and totals Expenses:*
from the books in each band. See lib/stages.py for the config shape.
"""

import sys

from lib.helpers import load_config, get_active_entity, expand_path


def build(config):
    """[{name, start, end, months, spending}] for the active entity."""
    from lib.stages import build as _build
    journal = config.get('journal_file')
    journal = expand_path(journal) if journal else None
    currency = config.get('pair', {}).get('currency', 'CAD')
    return _build(journal, config, currency)


def show(rows):
    co = get_active_entity() or 'entity'
    print(f"\n  [{co}] Spending by company stage\n")
    print(f"  {'Stage':<14} {'From':<8} {'To':<8} {'Months':>6} {'Spending':>14}")
    print(f"  {'─' * 56}")
    total = 0
    for r in rows:
        total += r['spending']
        print(f"  {r['name']:<14} {r['start']:<8} {r['end'] or '—':<8} {r['months']:>6} "
              f"{float(r['spending']):>14,.0f}")
    print(f"  {'─' * 56}")
    print(f"  {'Total':<14} {'':<8} {'':<8} {'':>6} {float(total):>14,.0f}\n")


def dispatch(args):
    if args and args[0] in ('--help', '-h', 'help'):
        print_help()
        return
    config = load_config()
    try:
        rows = build(config)
    except (RuntimeError, ValueError) as e:
        print(f"  {e}")
        sys.exit(1)
    if not rows:
        print("  No stage bands configured yet. Add stage_bands to config.yaml:\n"
              "    stage_bands:\n"
              "      startup: {start: 2024-01, end: 2024-12}\n"
              "      seed: {start: 2025-01, end: 2025-06}\n"
              "      growth: {start: 2025-07}")
        return
    show(rows)


def print_help():
    print("""pair stages — total spending by company stage   [stages]

  pair stages            spending in each stage band, from the books

Stage bands come from config.yaml (no defaults):

  stage_bands:
    startup: {start: 2024-01, end: 2024-12}
    seed: {start: 2025-01, end: 2025-06}
    growth: {start: 2025-07}

An open band (no end) runs to the last month with spending. Spending is
all Expenses:* postings in the band's months.
""")
