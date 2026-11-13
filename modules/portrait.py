"""Company portrait — one page telling the company's story from live modules.

Who we are (profile) -> traction (KPIs) -> money (cash, burn, runway) ->
plan (the chosen scenario) -> fundraising (open rounds) -> ownership
(cap table). Sections whose pack is off say so instead of guessing.
"""

from datetime import date
from decimal import Decimal

from lib.features import enabled_packs
from lib.helpers import get_entity_dir

KEY_METRICS = ['mrr', 'arr', 'revenue', 'paying_customers', 'total_users', 'mau', 'nps', 'net_burn', 'cash',
               'runway_months', 'headcount', 'signed_value', 'pipeline_value']
MOMENTUM = ['investor_connections', 'investor_meetings', 'investors_converted', 'customer_interviews', 'demos']


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def build(config, scenario=None):
    packs = enabled_packs()
    from lib.profile import load as load_profile
    profile = load_profile(config)
    scenario = scenario or profile.get('plan_scenario') or ''
    out = {'name': config.get('pair', {}).get('name', ''), 'currency': config.get('pair', {}).get('currency', ''),
           'profile': profile, 'packs': packs, 'today': date.today().isoformat(), 'scenario': scenario}

    # Traction: latest value of key metrics, change vs 3 months earlier, momentum last 3 months
    from modules.kpi import build as kpi_build
    k = kpi_build(config, months=6)
    latest = []
    others = [m for m, d in k['defs'].items() if m not in KEY_METRICS and m not in MOMENTUM
              and d['bucket'] not in ('profile',) and any(c['value'] is not None for c in k['cells'][m].values())]
    for mid in (KEY_METRICS + others)[:len(KEY_METRICS) + 6]:
        d = k['defs'].get(mid)
        if not d:
            continue
        vals = [(m, k['cells'][mid][m]['value']) for m in k['months'] if k['cells'][mid][m]['value'] is not None]
        if not vals:
            continue
        if len(latest) >= 10:
            break
        m, v = vals[-1]
        prev = next((pv for pm, pv in reversed(vals[:-1]) if pm <= k['months'][max(0, k['months'].index(m) - 3)]), None)
        latest.append({'id': mid, 'name': d['name'], 'unit': d['unit'], 'month': m, 'value': _f(v),
                       'change': _f((v - prev) / abs(prev)) if prev not in (None, 0) else None})
    recent = k['months'][-3:]
    momentum = []
    for mid in MOMENTUM:
        d = k['defs'].get(mid)
        total = sum((k['cells'][mid][m]['value'] or 0 for m in recent), 0)
        if total:
            momentum.append({'id': mid, 'name': d['name'], 'last_3_months': _f(total)})
    out['traction'] = {'metrics': latest, 'momentum': momentum}

    if packs.get('runway'):
        from modules.runway import build as runway_build
        from lib.runway import to_json
        try:
            data = runway_build(config, scenario or None, 18, 'add')
            _, summary = to_json(data['rows'], data['summary'])
            out['money'] = {'summary': summary, 'books': data['books']}
        except (RuntimeError, ValueError) as e:
            out['money'] = {'error': str(e)}
    if packs.get('scenarios') and scenario:
        from modules.scenario import load_scenario, scenario_monthly
        meta = load_scenario(scenario)
        if meta:
            months, _ = scenario_monthly(scenario, config)
            ahead = {m: v for m, v in months.items() if m >= f"{date.today():%Y-%m}"}
            nxt = list(ahead.items())[:12]
            out['plan'] = {'name': meta.get('name', scenario), 'description': meta.get('description', ''),
                           'rules': len(meta.get('rules') or []), 'growth': bool(meta.get('growth')),
                           'layers': meta.get('layers') or [],
                           'next_12': {'revenue': _f(sum((v['revenue'] for _, v in nxt), Decimal('0'))),
                                       'expense': _f(sum((v['expense'] for _, v in nxt), Decimal('0'))),
                                       'funding': _f(sum((v['funding'] for _, v in nxt), Decimal('0')))}}
    if packs.get('captable'):
        from modules.fundraise import load_rounds, load_deals
        from lib import fundraising as F
        deals = load_deals()
        out['fundraising'] = [{'name': r['name'], 'status': r.get('status', 'planned'), 'instrument': r.get('instrument'),
                               **{kk: _f(vv) for kk, vv in F.progress(r, deals, config).items()}}
                              for r in load_rounds() if r.get('status') != 'closed']
        from modules.captable import load_register
        from lib import captable as C
        reg = load_register()
        t = C.table(reg)
        out['ownership'] = {'groups': {g: _f(v) for g, v in C.by_group(reg).items()},
                            'fully_diluted': _f(t['fully_diluted']), 'price': _f(t['price']),
                            'value': _f(t['value']), 'open_instruments': len(t['instruments'])}
    return out
