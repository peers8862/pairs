"""pair traction — one chart: a chosen traction metric, founder ownership
and cash over time (I54).

- Traction: any KPI metric, by month, from the KPI grid.
- Ownership: founder % of fully diluted shares over time, from the captable
  register's dated issuances and grants (lib/captable.founder_pct_by_month).
  Cap-table versions are undated what-ifs, not history, so they are not used.
- Cash: month-end cash from the runway rows (actual months from the books,
  then the plan).

Web: GET /api/chart/traction?metric=&months=&end= (the chart lives in
Company > Overview). CLI: pair traction [--metric ID] [--months N] [--end YYYY-MM].
"""

import sys

from lib.helpers import load_config, get_active_entity, get_entity_dir

DEFAULT_METRIC = 'paying_customers'


def build(config, metric=DEFAULT_METRIC, months=12, end=None, entity_dir=None):
    """{metric, months, traction, ownership, cash, metrics, has_captable}.

    traction/ownership/cash are {YYYY-MM: number or None}; metrics lists the
    KPI metrics for the picker ({id, name, unit, has_data}). Raises
    ValueError on an unknown metric.
    """
    from lib import captable as C
    from modules.kpi import build as kpi_build, window
    from modules.runway import build as runway_build
    from modules.captable import cap_dir, load_register
    entity_dir = entity_dir or get_entity_dir()
    ms = window(end, months)
    k = kpi_build(config, entity_dir, end=end, months=months)
    if metric not in k['defs']:
        raise ValueError(f"unknown metric '{metric}'")
    from modules.portrait import KEY_METRICS
    ordered = [m for m in KEY_METRICS if m in k['defs']]
    ordered += [m for m in k['defs'] if m not in ordered
                and k['defs'][m]['bucket'] != 'profile']
    metrics = [{'id': m, 'name': k['defs'][m]['name'], 'unit': k['defs'][m]['unit'],
                'has_data': any(k['cells'][m][mo]['value'] is not None for mo in ms)}
               for m in ordered]
    traction = {}
    for mo in ms:
        v = k['cells'][metric][mo]['value']
        traction[mo] = float(v) if v is not None else None
    has_captable = (cap_dir(entity_dir) / 'register.yaml').exists()
    reg = load_register(entity_dir)
    pcts = C.founder_pct_by_month(reg, ms)
    ownership = {mo: (float(v) if v is not None else None) for mo, v in pcts.items()}
    try:
        rows = runway_build(config, None, 1, 'add', start=None)['rows']
        cash = {r['month']: float(r['end']) for r in rows if r['month'] in ms and r['end'] is not None}
    except (RuntimeError, ValueError, ArithmeticError):
        cash = {}
    cash = {mo: cash.get(mo) for mo in ms}
    return {'metric': metric, 'months': ms, 'traction': traction,
            'ownership': ownership, 'cash': cash, 'metrics': metrics,
            'has_captable': has_captable}


def show(data):
    co = get_active_entity() or 'entity'
    metric = next((m for m in data['metrics'] if m['id'] == data['metric']), {})
    print(f"\n  [{co}] Traction vs ownership — {metric.get('name', data['metric'])}\n")
    print(f"  {'Month':<8} {metric.get('name', 'Traction')[:18]:>18} {'Founder':>8} {'Cash':>14}")
    print(f"  {'─' * 52}")
    for m in data['months']:
        t = data['traction'][m]
        o = data['ownership'][m]
        c = data['cash'][m]
        print(f"  {m:<8} {('—' if t is None else f'{t:,.0f}'):>18} "
              f"{('—' if o is None else f'{o * 100:.1f}%'):>8} "
              f"{('—' if c is None else f'{c:>14,.0f}')}")
    if not data['has_captable']:
        print("\n  No cap table yet: founder ownership is blank until a register exists.")
    print()


def dispatch(args):
    if args and args[0] in ('--help', '-h', 'help'):
        print_help()
        return
    def flag(name, default=None):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default
    config = load_config()
    try:
        data = build(config, flag('--metric', DEFAULT_METRIC), int(flag('--months', 12)),
                     flag('--end'), get_entity_dir())
    except (RuntimeError, ValueError, ArithmeticError) as e:
        print(f"  {e}")
        sys.exit(1)
    show(data)


def print_help():
    print("""pair traction — traction metric, founder ownership and cash over time

  pair traction                              paying customers, last 12 months
  pair traction --metric mrr --months 24     another metric, longer window
  pair traction --metric revenue --end 2026-06

Ownership comes from the captable register's dated issuances and grants;
cash is month-end cash from the runway rows. Web: Company > Overview.
""")
