"""pair runway — cash, burn and runway from the books plus a scenario.

Part of the 'runway' feature pack. See lib/runway.py for the model.
"""

import sys
from decimal import Decimal

from lib.helpers import load_config, parse_global_flags, get_active_entity, expand_path
from lib import runway as rw


def build(config, scenario=None, months=18, mode='add', start=None, starting_cash=None,
          raise_amount=None, whatif=None):
    """Everything the CLI and web show: rows, summary, sources & uses.

    whatif  {'revenue_mult', 'cost_mult', 'hire_delay', 'revenue_shift'} —
            preview-only sliders (I55). Multipliers scale projected revenue /
            expense (plan + recent pace); delays shift the scenario's dated
            occurrences before they are totalled. Nothing is persisted and
            the saved scenario is never touched.
    """
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
        plan, by_account = scenario_monthly(scenario, config, whatif=whatif)
    whatif = whatif or {}
    try:
        rev_mult = Decimal(str(whatif.get('revenue_mult', 1)))
        exp_mult = Decimal(str(whatif.get('cost_mult', 1)))
    except ArithmeticError:
        raise ValueError('what-if multipliers must be numbers')
    rows, summary = rw.project(actual, plan, start, int(months),
                               starting_cash=starting_cash if not has_cash else None,
                               mode=mode, trailing=int(s['trailing_months']),
                               min_cash_months=s.get('min_cash_months'), min_cash=s.get('min_cash'),
                               buffer_months=s['buffer_months'], burn_window=int(s['burn_window']),
                               rev_mult=rev_mult, exp_mult=exp_mult)
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


def _scenario_rules(slug, seen=None):
    """A scenario's rules plus the rules of every scenario it layers on."""
    from modules.scenario import load_scenario
    seen = set(seen or ()) | {slug}
    meta = load_scenario(slug) or {}
    rules = list(meta.get('rules') or [])
    for layer in meta.get('layers') or []:
        if layer in seen or load_scenario(layer) is None:
            continue
        rules += _scenario_rules(layer, seen)
    return rules


def statements(config, scenario=None, months=18, mode='add', start=None, starting_cash=None):
    from lib import statements as ST
    from pathlib import Path
    data = build(config, scenario, months, mode, start, starting_cash)
    journal = config.get('journal_file')
    journal = expand_path(journal) if journal else None
    start_month = start or rw.this_month()
    actual_exp, _ = ST.actual_by_account(journal, data['currency'], start_month)
    plan_exp = {}
    assumptions = None
    funding_split = None
    hires = None
    if scenario:
        from modules.scenario import scenario_monthly, scenario_occurrences, load_scenario
        _, plan_exp = scenario_monthly(scenario, config)
        meta = load_scenario(scenario) or {}
        assumptions = meta.get('assumptions')
        # Funding split from the same occurrences the monthly totals are
        # built from, so the split sums to the runway funding lump exactly.
        funding_split = ST.funding_split(scenario_occurrences(scenario))
        hires = ST.hire_months(_scenario_rules(scenario))
    opening = None
    actual_bs = None
    if journal and Path(journal).exists():
        opening = ST.opening_balances(journal, data['currency'], start_month, config)
        actual_bs = ST.actual_bs(
            journal, data['currency'],
            [r['month'] for r in data['rows'] if r['source'] == 'actual'], config)
    if opening is None and actual_bs:
        # Books exist but nothing before the window: anchor on the last
        # actual balance sheet instead of the starting-cash fallback.
        opening = actual_bs[sorted(actual_bs)[-1]]
    if opening is None:
        # No books at all: the starting cash is contributed capital, so the
        # opening sheet balances (cash on one side, share capital on the other).
        cash0 = data['summary']['cash_now']
        opening = {'cash': cash0, 'share_capital': cash0}
    out = ST.build(data['rows'], actual_exp, plan_exp, data['summary']['base_expense'], mode, config,
                   assumptions=assumptions, funding_split=funding_split, hires=hires,
                   opening=opening, actual_bs=actual_bs or None,
                   floor=data['summary']['floor'])
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
    whatif = {}
    for name, key in (('--rev', 'revenue_mult'), ('--cost', 'cost_mult'),
                      ('--hire-delay', 'hire_delay'), ('--rev-shift', 'revenue_shift')):
        if flag(name) is not None:
            whatif[key] = flag(name)
    try:
        data = build(config, scenario, int(flag('--months', 18)), mode, flag('--start'),
                     Decimal(cash) if cash else None, flag('--raise'), whatif or None)
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
  --rev X         what-if only: projected revenue x X (default 1)
  --cost X        what-if only: projected costs x X (default 1)
  --hire-delay N  what-if only: hires start N months later (default 0)
  --rev-shift N   what-if only: revenue starts N months later (default 0)
  What-if flags change the preview only; nothing is saved.

Settings in config.yaml under runway: starting_cash, cash_accounts,
min_cash_months, min_cash, buffer_months (15), trailing_months (3),
burn_window (12).
""")
