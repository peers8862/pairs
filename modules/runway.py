"""pair runway — cash, burn and runway from the books plus a scenario.

Part of the 'runway' feature pack. See lib/runway.py for the model.
"""

import sys
from decimal import Decimal

from lib.helpers import load_config, parse_global_flags, get_active_entity, expand_path
from lib import runway as rw


def build(config, scenario=None, months=18, mode='add', start=None, starting_cash=None,
          raise_amount=None):
    """Everything the CLI and web show: rows, summary, sources & uses."""
    from lib.categories import summarise
    s = rw.settings(config)
    currency = config.get('pair', {}).get('currency', 'CAD')
    start = start or rw.this_month()
    journal = config.get('journal_file')
    journal = expand_path(journal) if journal else None
    actual = rw.actual_months(journal, config, currency, end_month=start)
    has_cash = any(m.get('cash_end') for m in actual.values())
    if starting_cash is None and not has_cash and s.get('starting_cash') is not None:
        starting_cash = s['starting_cash']
    plan, by_account = {}, {}
    if scenario:
        from modules.scenario import scenario_monthly
        plan, by_account = scenario_monthly(scenario, config)
    rows, summary = rw.project(actual, plan, start, int(months),
                               starting_cash=starting_cash if not has_cash else None,
                               mode=mode, trailing=int(s['trailing_months']),
                               min_cash_months=s.get('min_cash_months'), min_cash=s.get('min_cash'),
                               buffer_months=s['buffer_months'], burn_window=int(s['burn_window']))
    # Sources & uses: planned scenario spend in the window, by report category
    window = [r['month'] for r in rows if r['source'] == 'plan']
    spend = {}
    for m in window:
        for account, amount in by_account.get(m, {}).items():
            spend[account] = spend.get(account, Decimal('0')) + amount
    if mode == 'add' and summary['base_expense']:
        spend['Expenses:(current pace)'] = summary['base_expense'] * len(window)
    by_cat = {k: v for k, v in summarise(spend, config).items() if v}
    amount = Decimal(str(raise_amount)) if raise_amount else summary['raise_target']
    uses, covers = rw.sources_and_uses(amount, by_cat, len(window) or 1)
    return {
        'currency': currency, 'scenario': scenario or '', 'months': int(months),
        'rows': rows, 'summary': summary,
        'uses': {'amount': amount, 'covers_months': covers,
                 'rows': [{'category': c, 'share': sh, 'amount': a} for c, sh, a in uses]},
        'books': bool(actual), 'starting_cash_used': starting_cash if not has_cash else None,
    }


def statements(config, scenario=None, months=18, mode='add', start=None, starting_cash=None):
    from lib import statements as ST
    data = build(config, scenario, months, mode, start, starting_cash)
    journal = config.get('journal_file')
    journal = expand_path(journal) if journal else None
    actual_exp, _ = ST.actual_by_account(journal, data['currency'], start or rw.this_month())
    plan_exp = {}
    if scenario:
        from modules.scenario import scenario_monthly
        _, plan_exp = scenario_monthly(scenario, config)
    out = ST.build(data['rows'], actual_exp, plan_exp, data['summary']['base_expense'], mode, config)
    out['currency'] = data['currency']
    return out


def compare_scenarios(config, slugs, months=18, mode='add', starting_cash=None):
    """One summary row per scenario (plus 'no scenario' first)."""
    from decimal import Decimal as _D
    from modules.scenario import load_scenario
    rows = []
    for slug in [''] + list(slugs):
        data = build(config, slug or None, months, mode, None, starting_cash)
        s, plan = data['summary'], [r for r in data['rows'] if r['source'] == 'plan']
        tot = lambda k: sum((r[k] for r in plan), _D('0'))
        rows.append({'slug': slug, 'name': (load_scenario(slug) or {}).get('name', slug) if slug else 'No scenario',
                     'revenue': tot('revenue'), 'expense': tot('expense'), 'net': tot('net'),
                     'funding': tot('funding'), 'end_cash': plan[-1]['end'] if plan else s['cash_now'],
                     'lowest_cash': s['lowest_cash'], 'burn': s['avg_burn_plan'],
                     'runway': s['runway_months'] if s['runway_months'] is not None else s['runway_text'],
                     'cash_out': s['cash_out_month'], 'breakeven': s['breakeven_month'],
                     'raise_target': s['raise_target'],
                     'series': [{'month': r['month'], 'end': r['end']} for r in plan]})
    return rows


def dispatch(args):
    flags, remaining = parse_global_flags(args)
    if flags['help'] or (remaining and remaining[0] in ('help',)):
        print_help()
        return
    def flag(name, default=None):
        return remaining[remaining.index(name) + 1] if name in remaining and \
            remaining.index(name) + 1 < len(remaining) else default
    config = load_config()
    scenario = flag('--scenario')
    if scenario:
        from modules.scenario import load_scenario
        if load_scenario(scenario) is None:
            print(f"Scenario '{scenario}' not found. See 'pair scenario list'.")
            sys.exit(1)
    mode = 'replace' if '--replace' in remaining else 'add'
    cash = flag('--cash')
    try:
        data = build(config, scenario, int(flag('--months', 18)), mode, flag('--start'),
                     Decimal(cash) if cash else None, flag('--raise'))
    except (RuntimeError, ValueError) as e:
        print(f"  {e}")
        sys.exit(1)
    show(data)


def _m(v):
    return '' if v is None else f"{float(v):>12,.0f}"


def show(data):
    s, cur = data['summary'], data['currency']
    co = get_active_entity() or 'entity'
    plan = f"scenario '{data['scenario']}'" if data['scenario'] else 'no scenario'
    how = 'recent pace + scenario' if s['mode'] == 'add' else 'scenario only'
    print(f"\n  [{co}] Runway — {plan}, {how} ({cur})\n")
    print(f"  {'Month':<8} {'':<6} {'Begin':>12} {'Revenue':>12} {'Expenses':>12} {'Funding':>12} {'End cash':>12}")
    print(f"  {'─' * 80}")
    for r in data['rows']:
        mark = '  <' if r['month'] == s['cash_out_month'] else ''
        print(f"  {r['month']:<8} {r['source']:<6} {_m(r['begin'])} {_m(r['revenue'])} {_m(r['expense'])} "
              f"{_m(r['funding'])} {_m(r['end'])}{mark}")
    print(f"  {'─' * 80}")
    runway = (f"{float(s['runway_months']):.1f} months (cash runs out {s['cash_out_month']})"
              if s['runway_months'] is not None else s['runway_text'])
    print(f"  Cash now            {float(s['cash_now']):>14,.0f}")
    print(f"  Burn (plan)         {float(s['avg_burn_plan']):>14,.0f} / month  (average of next {s['burn_window']} months)")
    if s['avg_burn_actual'] is not None:
        print(f"  Burn (actual)       {float(s['avg_burn_actual']):>14,.0f} / month")
    print(f"  Runway              {runway}")
    if s['floor']:
        below = s['below_floor_month'] or 'never in this window'
        print(f"  Cash floor          {float(s['floor']):>14,.0f}  (dips below: {below})")
    if s['breakeven_month']:
        print(f"  Break-even month    {s['breakeven_month']}")
    print(f"  Raise target        {float(s['raise_target']):>14,.0f}  "
          f"(burn x {s['buffer_months']} months; gap after cash: {float(s['raise_gap']):,.0f})")
    u = data['uses']
    if u['rows']:
        covers = f", covers {float(u['covers_months']):.1f} months of planned spend" if u['covers_months'] else ''
        print(f"\n  Uses of {float(u['amount']):,.0f}{covers}")
        for r in u['rows']:
            print(f"    {r['category']:<24} {float(r['share']) * 100:>5.1f}%  {float(r['amount']):>12,.0f}")
    if not data['books']:
        print("\n  No transactions in the books yet: starting from "
              f"{float(data['starting_cash_used'] or 0):,.0f} (--cash or runway.starting_cash).")
    print("\n  Raise target = planned burn x buffer months: founders tend to underestimate\n"
          "  costs and build time by about a third, so plan beyond 12 months.\n")


def print_help():
    print("""pair runway — cash, burn and runway   [runway pack]

  pair runway                         recent pace only, 18 months
  pair runway --scenario lean         add a scenario on top of the recent pace
  pair runway --scenario full --replace   the scenario is the whole plan
  --months N      months to project (default 18)
  --start YYYY-MM first projected month (default this month)
  --cash N        starting cash when the books have none yet
  --raise N       size of the raise for Sources & Uses (default: raise target)

Settings in config.yaml under runway: starting_cash, cash_accounts,
min_cash_months, min_cash, buffer_months (15), trailing_months (3),
burn_window (12).
""")
