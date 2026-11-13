"""pair kpi — company, product and founder metrics (executive pack)."""

import sys
from datetime import date
from decimal import Decimal, InvalidOperation

from lib.helpers import (load_config, parse_global_flags, get_entity_dir, get_active_entity,
                         expand_path, slugify)
from lib import kpi as K
from lib.runway import add_months, months_between, month_key


def ledger_series(config):
    """{query: {YYYY-MM: Decimal}} for ledger metrics: revenue, expenses, cogs, cash."""
    from lib.runway import actual_months, _tidy
    journal = config.get('journal_file')
    journal = expand_path(journal) if journal else None
    currency = config.get('pair', {}).get('currency', 'CAD')
    out = {'revenue': {}, 'expenses': {}, 'cash': {}, 'cogs': {}}
    try:
        months = actual_months(journal, config, currency)
    except RuntimeError:
        return out
    for m, v in months.items():
        out['revenue'][m] = v['revenue']
        out['expenses'][m] = v['expense']
        if v.get('cash_end') is not None:
            out['cash'][m] = v['cash_end']
    if months:
        try:
            for r in _tidy([journal], ['^Expenses:(COGS|Cost of Goods)']):
                if r['commodity'] == currency:
                    k = r['start_date'][:7]
                    out['cogs'][k] = out['cogs'].get(k, Decimal('0')) + Decimal(r['value'].replace(',', ''))
        except RuntimeError:
            pass
    return out


def window(end=None, months=12):
    end = end or month_key(date.today())
    return months_between(add_months(end, -(int(months) - 1)), end)


def build(config, entity_dir=None, end=None, months=12, project=0):
    """Data for the CLI and web: definitions, buckets, months and cells."""
    entity_dir = entity_dir or get_entity_dir()
    defs = K.load_definitions(entity_dir)
    values, notes = K.load_values(entity_dir)
    projections = K.load_projections(entity_dir)
    ms = window(end, months)
    future = [add_months(ms[-1], i) for i in range(1, int(project) + 1)]
    feeds = ledger_series(config)
    from lib.features import is_enabled
    if is_enabled('captable'):
        from modules.fundraise import load_deals
        from lib.fundraising import momentum
        feeds.update(momentum(load_deals(entity_dir), config))
    cells = K.grid(defs, values, feeds, ms, projections, future)
    return {'defs': defs, 'months': ms, 'future': future, 'cells': cells, 'notes': notes,
            'projections': projections, 'buckets': K.BUCKETS}


def has_data(cells, mid):
    return any(c['value'] is not None for c in cells[mid].values())


def fmt(v, unit):
    if v is None:
        return ''
    v = float(v)
    if unit == 'percent':
        return f"{v * 100:.1f}%"
    if unit in ('money',):
        return f"{v:,.0f}"
    if unit in ('ratio', 'months'):
        return f"{v:,.2f}"
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def dispatch(args):
    flags, rest = parse_global_flags(args)
    if flags['help'] or (rest and rest[0] == 'help'):
        print_help()
        return
    if rest and not rest[0].startswith('--'):
        action, rest = rest[0], rest[1:]
    else:
        action = 'show'
    config = load_config()
    entity_dir = get_entity_dir()
    defs = K.load_definitions(entity_dir)

    def flag(name, default=None):
        return rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else default

    positional = [a for i, a in enumerate(rest) if not a.startswith('--')
                  and (i == 0 or not rest[i - 1].startswith('--'))]

    if action in ('show', 'list'):
        show(config, flag('--bucket'), int(flag('--months', 6)), int(flag('--project', 0)),
             '--all' in rest, action == 'list')
    elif action == 'set':
        if len(positional) < 2:
            print("  Usage: pair kpi set <metric> <value> [--month YYYY-MM] [--note TEXT]")
            sys.exit(1)
        mid, value = positional[0], positional[1]
        if mid not in defs:
            print(f"  Unknown metric '{mid}'. See 'pair kpi list'.")
            sys.exit(1)
        if defs[mid]['source'] == 'derived' and '--force' not in rest:
            print(f"  '{mid}' is worked out ({defs[mid]['formula']}); add --force to override a month.")
            sys.exit(1)
        month = flag('--month', month_key(date.today()))
        try:
            v = None if value in ('-', 'none') else _parse(value, defs[mid]['unit'])
        except (InvalidOperation, ValueError):
            print(f"  Not a number: {value}")
            sys.exit(1)
        K.set_value(entity_dir, mid, month, v, flag('--note'))
        print(f"  {defs[mid]['name']} {month}: {value if v is not None else '(cleared)'}")
    elif action == 'add':
        name = ' '.join(positional) or flag('--name')
        if not name:
            print("  Usage: pair kpi add <name> --bucket B [--unit U] [--formula F] [--id ID]")
            sys.exit(1)
        d = define(entity_dir, name, flag('--bucket', 'momentum'), flag('--unit', 'count'),
                   flag('--formula'), flag('--id'), flag('--type', 'flow'))
        print(f"  Added metric {d['id']} ({d['bucket']}, {d['unit']}, {d['source']}).")
    elif action == 'remove' and positional:
        if K.remove_custom(entity_dir, positional[0]):
            print(f"  Removed metric {positional[0]} (its values stay in values.csv).")
        else:
            print(f"  '{positional[0]}' is not a custom metric.")
    elif action == 'project' and positional:
        key = positional[0]
        if key not in defs and not key.startswith('bucket:'):
            print("  Give a metric id or bucket:<id>.")
            sys.exit(1)
        g = positional[1] if len(positional) > 1 else None
        K.save_projection(entity_dir, key, None if g in (None, '-', 'none') else float(g))
        print(f"  Projection for {key}: {'removed' if g in (None, '-', 'none') else f'{float(g) * 100:g}% per month'}")
    elif action == 'buckets':
        for bid, label, desc in K.BUCKETS:
            n = sum(1 for d in defs.values() if d['bucket'] == bid)
            print(f"  {bid:<12} {label:<28} {n:>3}  {desc}")
    else:
        print_help()


def _parse(value, unit):
    value = value.replace(',', '').strip()
    if unit == 'percent' and value.endswith('%'):
        return Decimal(value[:-1]) / 100
    return Decimal(value)


def define(entity_dir, name, bucket, unit='count', formula=None, mid=None, mtype='flow'):
    buckets = {b for b, *_ in K.BUCKETS}
    if bucket not in buckets:
        raise ValueError(f"bucket must be one of {', '.join(sorted(buckets))}")
    if unit not in K.UNITS:
        raise ValueError(f"unit must be one of {', '.join(K.UNITS)}")
    if formula:
        err = K.check_formula(formula)
        if err:
            raise ValueError(f"formula: {err}")
    mid = mid or slugify(name).replace('-', '_')
    d = {'id': mid, 'name': name, 'bucket': bucket, 'unit': unit, 'type': mtype,
         'source': 'derived' if formula else 'manual'}
    if formula:
        d['formula'] = formula
    K.save_custom(entity_dir, d)
    return d


def show(config, bucket=None, months=6, project=0, show_all=False, list_only=False):
    data = build(config, months=months, project=project)
    defs, cells = data['defs'], data['cells']
    cols = data['months'] + data['future']
    co = get_active_entity() or 'entity'
    print(f"\n  [{co}] KPIs — {cols[0]} to {cols[-1]}" + (f" (last {project} projected)" if project else '') + "\n")
    for bid, label, _ in K.BUCKETS:
        if bucket and bid != bucket:
            continue
        ids = [m for m, d in defs.items() if d['bucket'] == bid and (show_all or list_only or has_data(cells, m))]
        if not ids:
            continue
        print(f"  {label}")
        if list_only:
            for m in ids:
                d = defs[m]
                extra = f"  = {d['formula']}" if d.get('formula') and d['source'] == 'derived' else ''
                print(f"    {m:<22} {d['name']:<40} {d['unit']:<8} {d['source']}{extra}")
            continue
        print(f"    {'':<34}" + ''.join(f"{c[2:]:>10}" for c in cols))
        for m in ids:
            d = defs[m]
            row = ''.join(f"{fmt(cells[m][c]['value'], d['unit']) + ('*' if cells[m][c]['kind'] == 'projected' and cells[m][c]['value'] is not None else ''):>10}" for c in cols)
            print(f"    {d['name'][:34]:<34}{row}")
        print()
    if not list_only:
        print("  * projected.  'pair kpi list' shows every metric; 'pair kpi set <id> <value>' records one.\n")


def print_help():
    print("""pair kpi — company, product and founder metrics   [executive pack]

  pair kpi [--months 6] [--project 6] [--bucket B] [--all]   grid of metrics with data
  pair kpi list [--bucket B]                 every metric (id, unit, source, formula)
  pair kpi buckets                           metric buckets
  pair kpi set <id> <value> [--month YYYY-MM] [--note TEXT]   (- clears; 12% works for percents)
  pair kpi add <name> --bucket B [--unit U] [--formula "a / b"] [--id ID]
  pair kpi remove <id>                       remove a custom metric
  pair kpi project <id|bucket:B> <growth>    carry forward by a monthly growth (0.05 = 5%); - removes

Ledger metrics (revenue, expenses, cogs, cash) fill from the books; derived ones are
worked out each month (functions: max, min, avg(x, n), growth(x, n)).
""")
