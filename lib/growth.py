"""Growth engine — money-backed growth that feeds a scenario's revenue and spend.

Stored in a scenario's scenario.yaml under `growth:`. Channels bring new
sign-ups each month; one funnel turns sign-ups into paying customers; paying
customers form monthly cohorts that shrink by a retention curve; revenue per
customer and cost to serve turn customers into money. The results become
scenario lines (spend, revenue, cost to serve), so runway updates with them.

    growth:
      start: 2027-01            # first month
      months: 24
      channels:
        - {name: Search ads, type: paid, spend: 2000, spend_growth: 0.05, cpm: 12, ctr: 0.02, conversion: 0.08}
        - {name: Ads (CPA), type: paid_cpa, spend: 1000, cpa: 15}
        - {name: Referrals, type: viral, invites: 2, invite_conversion: 0.1}
        - {name: Content/SEO, type: organic, visitors: 2000, growth: 0.08, conversion: 0.02}
        - {name: Sales team, type: sales, reps: 1, add_rep_every: 6, deals_per_rep: 4, ramp_months: 3, cost_per_rep: 7000}
        - {name: Partners, type: partners, partners: 2, new_partners: 1, users_per_partner: 15}
      funnel: {activation: 0.6, paid_conversion: 0.15}   # sign-up -> active -> paying (sales deals are paying)
      retention: [0.80, 0.90, 0.95]                       # month-on-month; the last value repeats
      revenue:
        tiers: [{name: Basic, price: 15, share: 0.7}, {name: Pro, price: 49, share: 0.3}]
        expansion: 0.01                                  # monthly growth in revenue per retained customer
      cost_to_serve: 2.5                                 # per paying customer per month
      accounts: {revenue: Income:Operating:Sales, spend: Expenses:Operating:Marketing,
                 serve: Expenses:COGS, sales: Expenses:Operating:Payroll:Salaries}

Pure functions; months are 'YYYY-MM' keys.
"""

from datetime import date
from decimal import Decimal

ZERO = Decimal('0')
CHANNEL_TYPES = ('paid', 'paid_cpa', 'viral', 'organic', 'sales', 'partners')
DEFAULT_ACCOUNTS = {'revenue': 'Income:Operating:Sales', 'spend': 'Expenses:Operating:Marketing',
                    'serve': 'Expenses:COGS', 'sales': 'Expenses:Operating:Payroll:Salaries'}
LIFETIME_CAP = 60


def D(v, default='0'):
    return Decimal(str(v)) if v not in (None, '') else Decimal(default)


def add_months(key, n):
    y, m = int(key[:4]), int(key[5:7]) - 1 + n
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def template():
    today = date.today()
    return {'start': f'{today.year:04d}-{today.month:02d}', 'months': 24,
            'channels': [{'name': 'Paid ads', 'type': 'paid_cpa', 'spend': 1000, 'spend_growth': 0.05, 'cpa': 20}],
            'funnel': {'activation': 0.6, 'paid_conversion': 0.15},
            'retention': [0.85, 0.92],
            'revenue': {'tiers': [{'name': 'Standard', 'price': 20, 'share': 1}], 'expansion': 0},
            'cost_to_serve': 2}


def validate(model):
    problems = []
    if not model:
        return ['no growth model']
    try:
        add_months(str(model.get('start')), 0)
        int(str(model.get('start'))[5:7])
    except (ValueError, TypeError):
        problems.append('start must be YYYY-MM')
    for c in model.get('channels') or []:
        if c.get('type') not in CHANNEL_TYPES:
            problems.append(f"channel {c.get('name', '?')}: type must be one of {', '.join(CHANNEL_TYPES)}")
    for r in _curve(model):
        if not 0 <= r <= 1:
            problems.append('retention values are fractions between 0 and 1')
            break
    shares = sum((D(t.get('share')) for t in (model.get('revenue') or {}).get('tiers') or []), ZERO)
    if (model.get('revenue') or {}).get('tiers') and abs(shares - 1) > D('0.001'):
        problems.append('tier shares must add up to 1')
    f = model.get('funnel') or {}
    for k in ('activation', 'paid_conversion'):
        if f.get(k) not in (None, '') and not 0 <= D(f[k]) <= 1:
            problems.append(f'funnel {k} is a fraction between 0 and 1')
    return problems


def _curve(model):
    r = model.get('retention')
    if isinstance(r, list):
        return [D(x) for x in r] or [Decimal(1)]
    if r not in (None, ''):
        return [D(r)]
    return [Decimal(1)]


def survival(model, age):
    """Share of a cohort still paying `age` months after joining (age 0 = 1)."""
    curve = _curve(model)
    s = Decimal(1)
    for a in range(1, age + 1):
        s *= curve[min(a - 1, len(curve) - 1)]
    return s


def arpu(model):
    rev = model.get('revenue') or {}
    tiers = rev.get('tiers') or []
    if tiers:
        return sum((D(t.get('price')) * D(t.get('share')) for t in tiers), ZERO)
    return D(rev.get('price'))


def _channel_month(c, i, prev_new_users):
    """(sign-ups, paying deals, spend) for channel c in month i."""
    t = c.get('type')
    g = (1 + D(c.get('spend_growth'))) ** i
    if t == 'paid':
        spend = D(c.get('spend')) * g
        impressions = spend / D(c.get('cpm'), '1') * 1000
        return impressions * D(c.get('ctr')) * D(c.get('conversion')), ZERO, spend
    if t == 'paid_cpa':
        spend = D(c.get('spend')) * g
        return spend / D(c.get('cpa'), '1'), ZERO, spend
    if t == 'viral':
        k = D(c.get('invites')) * D(c.get('invite_conversion'))
        return prev_new_users * k, ZERO, D(c.get('spend')) * g
    if t == 'organic':
        visitors = D(c.get('visitors')) * (1 + D(c.get('growth'))) ** i
        return visitors * D(c.get('conversion')), ZERO, D(c.get('spend')) * g
    if t == 'sales':
        reps_now = D(c.get('reps'), '1') + (i // int(c['add_rep_every']) if c.get('add_rep_every') else 0)
        ramp = int(c.get('ramp_months') or 0)
        # each rep joins at month (k * add_rep_every); ramps linearly over ramp_months
        productive = ZERO
        every = int(c.get('add_rep_every') or 0)
        for r in range(int(reps_now)):
            joined = 0 if r < int(D(c.get('reps'), '1')) else (r - int(D(c.get('reps'), '1')) + 1) * every
            tenure = i - joined + 1
            productive += min(Decimal(1), D(tenure) / D(ramp)) if ramp else Decimal(1)
        deals = productive * D(c.get('deals_per_rep'))
        return ZERO, deals, D(c.get('cost_per_rep')) * reps_now + D(c.get('spend')) * g
    if t == 'partners':
        partners = D(c.get('partners')) + D(c.get('new_partners')) * i
        return partners * D(c.get('users_per_partner')), ZERO, D(c.get('spend')) * g + partners * D(c.get('cost_per_partner'))
    return ZERO, ZERO, ZERO


def run(model):
    """Month-by-month results plus unit economics.

    rows: month, signups, new_paying, paying, revenue, spend (marketing),
          sales_cost, serve, contribution, by_channel {name: (signups, spend)}
    """
    months = int(model.get('months') or 24)
    start = str(model.get('start'))
    f = model.get('funnel') or {}
    act, conv = D(f.get('activation'), '1'), D(f.get('paid_conversion'), '1')
    price = arpu(model)
    expansion = D((model.get('revenue') or {}).get('expansion'))
    serve_each = D(model.get('cost_to_serve'))
    channels = model.get('channels') or []
    cohorts = []          # new paying per month
    prev_new_users = ZERO
    rows = []
    for i in range(months):
        signups_total, paying_direct, spend, sales_cost = ZERO, ZERO, ZERO, ZERO
        by_channel = {}
        viral = [c for c in channels if c.get('type') == 'viral']
        for c in channels:
            if c in viral:
                continue
            s, p, cost = _channel_month(c, i, prev_new_users)
            by_channel[c.get('name') or c['type']] = {'signups': s, 'paying': p, 'spend': cost}
            signups_total += s
            paying_direct += p
            if c.get('type') == 'sales':
                sales_cost += cost
            else:
                spend += cost
        for c in viral:
            s, p, cost = _channel_month(c, i, prev_new_users if i else ZERO)
            by_channel[c.get('name') or 'viral'] = {'signups': s, 'paying': p, 'spend': cost}
            signups_total += s
            spend += cost
        prev_new_users = signups_total
        new_paying = signups_total * act * conv + paying_direct
        cohorts.append(new_paying)
        paying = ZERO
        revenue = ZERO
        for j, n in enumerate(cohorts):
            age = i - j
            alive = n * survival(model, age)
            paying += alive
            revenue += alive * price * (1 + expansion) ** age
        serve = paying * serve_each
        rows.append({'month': add_months(start, i), 'signups': signups_total, 'new_paying': new_paying,
                     'paying': paying, 'revenue': revenue, 'spend': spend, 'sales_cost': sales_cost,
                     'serve': serve, 'contribution': revenue - spend - sales_cost - serve,
                     'by_channel': by_channel})
    return rows, unit_economics(model, rows)


def unit_economics(model, rows):
    price = arpu(model)
    serve = D(model.get('cost_to_serve'))
    margin = (price - serve) / price if price else ZERO
    lifetime = sum((survival(model, a) for a in range(LIFETIME_CAP)), ZERO)
    expansion = D((model.get('revenue') or {}).get('expansion'))
    ltv_revenue = sum((survival(model, a) * price * (1 + expansion) ** a for a in range(LIFETIME_CAP)), ZERO)
    ltv = ltv_revenue * margin
    acq = sum((r['spend'] + r['sales_cost'] for r in rows), ZERO)
    new = sum((r['new_paying'] for r in rows), ZERO)
    cac = acq / new if new else None
    monthly_margin = price * margin
    payback = (cac / monthly_margin) if cac is not None and monthly_margin else None
    last = rows[-1] if rows else {}
    return {'arpu': price, 'gross_margin': margin, 'expected_lifetime_months': lifetime,
            'ltv': ltv, 'cac': cac, 'ltv_cac': (ltv / cac) if cac else None, 'payback_months': payback,
            'paying_end': last.get('paying', ZERO), 'mrr_end': last.get('revenue', ZERO),
            'total_spend': acq, 'total_revenue': sum((r['revenue'] for r in rows), ZERO),
            'contribution_total': sum((r['contribution'] for r in rows), ZERO),
            'contribution_positive_month': next((r['month'] for r in rows if r['contribution'] > 0), None)}


def occurrences(model):
    """Scenario lines from the model (same shape as plan_rules.expand output)."""
    if not model or validate(model):
        return []
    rows, _ = run(model)
    acc = {**DEFAULT_ACCOUNTS, **(model.get('accounts') or {})}
    cents = Decimal('0.01')
    out = []
    for r in rows:
        d = date(int(r['month'][:4]), int(r['month'][5:7]), 1)
        for kind, key, account, name in (('revenue', 'revenue', acc['revenue'], 'Growth: revenue'),
                                         ('expense', 'spend', acc['spend'], 'Growth: acquisition'),
                                         ('expense', 'sales_cost', acc['sales'], 'Growth: sales team'),
                                         ('expense', 'serve', acc['serve'], 'Growth: cost to serve')):
            amount = r[key].quantize(cents)
            if amount > 0:
                out.append({'rule': f'growth-{key}', 'name': name, 'kind': kind, 'account': account,
                            'category': '', 'date': d, 'amount': amount})
    return out
