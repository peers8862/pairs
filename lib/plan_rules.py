"""Plan rules — one model for every planned money line.

A rule is stored once (in a scenario's scenario.yaml) and expanded into dated
amounts when needed. Kinds:

    expense   money out (account is an Expenses:* account)
    revenue   money in  (account is an Income:/Revenue:* account)
    funding   money in that is not profit or loss: equity, SAFE, note, debt, grant

Each rule has a timing (start, every, and end / months / repeat) and a driver
that says how the amount behaves over time:

    fixed      same amount every time                       amount
    growth     compounding change each occurrence          amount, rate (0.05 = +5%)
    step       amount changes from given dates              amount, steps [{from, amount}]
    percent    a share of the scenario's revenue that month percent (0.029), of: revenue | <rule id>
    units      units x price, units growing each time       units, price, unit_growth, unit_cost
    salary     a hire: salary/12 plus benefits, yearly raise salary, benefits (0.15), raise (0.03),
                                                            setup_cost (one-off at start)

Pure functions only — no file or hledger access — so they are easy to test
and reuse (runway, growth engine and metric projections build on them).
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

FREQUENCIES = {'weekly': 0, 'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'annual': 12, 'once': None}
KINDS = ('expense', 'revenue', 'funding')
DRIVERS = ('fixed', 'growth', 'step', 'percent', 'units', 'salary')
MAX_OCCURRENCES = 600
CENT = Decimal('0.01')

# Funding instrument -> account that balances the cash coming in.
FUNDING_ACCOUNTS = {
    'equity': 'Equity:Share Capital',
    'safe': 'Equity:SAFE',
    'note': 'Liabilities:Long-Term:Convertible Notes',
    'debt': 'Liabilities:Long-Term:Loans',
    'grant': 'Income:Other:Grants',
}
DEFAULT_ACCOUNTS = {
    'expense': 'Expenses:Operating:Other',
    'revenue': 'Income:Operating:Sales',
    'salary': 'Expenses:Operating:Payroll:Salaries',
    'cogs': 'Expenses:COGS',
    'setup': 'Expenses:Operating:Office Supplies',
}


def D(value, default='0'):
    if value is None or value == '':
        return Decimal(default)
    return Decimal(str(value))


def _cents(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def step_month(d, n, anchor_day):
    """Move d forward n months, keeping anchor_day where the month allows it."""
    m = d.month - 1 + n
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def month_key(d):
    return f'{d.year:04d}-{d.month:02d}'


# ─── Validation ──────────────────────────────────────────────────────────────

def validate(rule):
    """Return a list of problems with a rule (empty = fine)."""
    problems = []
    kind = rule.get('kind', 'expense')
    driver = rule.get('driver', 'fixed')
    if kind not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if driver not in DRIVERS:
        problems.append(f"driver must be one of {', '.join(DRIVERS)}")
    if (rule.get('every') or 'monthly') not in FREQUENCIES:
        problems.append(f"every must be one of {', '.join(FREQUENCIES)}")
    try:
        _date(rule.get('start'))
    except (TypeError, ValueError):
        problems.append('start must be a date (YYYY-MM-DD)')
    if rule.get('end'):
        try:
            if _date(rule['end']) < _date(rule.get('start')):
                problems.append('end is before start')
        except (TypeError, ValueError):
            problems.append('end must be a date (YYYY-MM-DD)')
    for key in ('rate', 'percent', 'benefits', 'raise', 'unit_growth'):
        v = rule.get(key)
        if v not in (None, '') and not (-1 < float(v) < 10):
            problems.append(f'{key} is a fraction (0.05 = 5%), got {v}')
    if driver == 'percent' and kind == 'revenue' and rule.get('of', 'revenue') == 'revenue':
        problems.append('a revenue rule cannot be a percent of revenue')
    if driver == 'salary' and kind != 'expense':
        problems.append('a hire (salary) is an expense')
    if kind == 'funding' and rule.get('instrument', 'equity') not in FUNDING_ACCOUNTS:
        problems.append(f"instrument must be one of {', '.join(FUNDING_ACCOUNTS)}")
    return problems


# ─── Timing ──────────────────────────────────────────────────────────────────

def occurrence_dates(rule):
    """Dates a rule happens on. `every: once` (or no end/months/repeat on a
    non-salary rule) gives a single date."""
    first = _date(rule['start'])
    every = rule.get('every') or 'monthly'
    if rule.get('driver') == 'salary':
        every = 'monthly'
    step = FREQUENCIES[every]
    if step is None:
        return [first]
    nth = (lambda i: first + timedelta(days=7 * i)) if step == 0 else \
          (lambda i: step_month(first, i * step, first.day))
    end = None
    if rule.get('end'):
        end = _date(rule['end']) + timedelta(days=1)          # end is inclusive
    elif rule.get('months'):
        end = step_month(first, int(rule['months']), first.day)
    if end is not None:
        out = []
        while len(out) < MAX_OCCURRENCES and nth(len(out)) < end:
            out.append(nth(len(out)))
        return out
    repeat = int(rule.get('repeat') or 1)
    return [nth(i) for i in range(min(repeat, MAX_OCCURRENCES))]


# ─── Amounts ─────────────────────────────────────────────────────────────────

def _amount_at(rule, i, d, first, base_by_month):
    driver = rule.get('driver', 'fixed')
    if driver == 'fixed':
        return D(rule.get('amount'))
    if driver == 'growth':
        return D(rule.get('amount')) * (1 + D(rule.get('rate'))) ** i
    if driver == 'step':
        amount = D(rule.get('amount'))
        for s in sorted(rule.get('steps') or [], key=lambda s: str(s['from'])):
            if _date(s['from']) <= d:
                amount = D(s['amount'])
        return amount
    if driver == 'percent':
        return D(rule.get('percent')) * base_by_month.get(month_key(d), Decimal('0'))
    if driver == 'units':
        return _units_at(rule, i) * D(rule.get('price'))
    if driver == 'salary':
        years = (d.year - first.year) * 12 + (d.month - first.month)
        raises = years // 12
        monthly = D(rule.get('salary')) / 12 * (1 + D(rule.get('benefits')))
        return monthly * (1 + D(rule.get('raise'))) ** raises
    raise ValueError(f"unknown driver {driver}")


def _units_at(rule, i):
    return D(rule.get('units')) * (1 + D(rule.get('unit_growth'))) ** i


def _account(rule):
    kind = rule.get('kind', 'expense')
    if rule.get('account'):
        return rule['account']
    if kind == 'funding':
        return FUNDING_ACCOUNTS.get(rule.get('instrument', 'equity'))
    if rule.get('driver') == 'salary':
        return DEFAULT_ACCOUNTS['salary']
    return DEFAULT_ACCOUNTS[kind]


def _occurrences_for(rule, base_by_month):
    out = []
    dates = occurrence_dates(rule)
    if not dates:
        return out
    first = dates[0]
    kind = rule.get('kind', 'expense')
    common = {'rule': rule.get('id', ''), 'name': rule.get('name', ''), 'kind': kind,
              'account': _account(rule), 'category': rule.get('category', '')}
    if kind == 'funding':
        common['instrument'] = rule.get('instrument', 'equity')
    for i, d in enumerate(dates):
        amount = _cents(_amount_at(rule, i, d, first, base_by_month))
        if amount:
            out.append({**common, 'date': d, 'amount': amount})
        if rule.get('driver') == 'units' and rule.get('unit_cost'):
            cost = _cents(_units_at(rule, i) * D(rule.get('unit_cost')))
            if cost:
                out.append({**common, 'kind': 'expense', 'date': d, 'amount': cost,
                            'account': rule.get('cogs_account') or DEFAULT_ACCOUNTS['cogs'],
                            'name': f"{common['name']} (cost)"})
    if rule.get('driver') == 'salary' and rule.get('setup_cost'):
        out.append({**common, 'date': first, 'amount': _cents(D(rule['setup_cost'])),
                    'account': rule.get('setup_account') or DEFAULT_ACCOUNTS['setup'],
                    'name': f"{common['name']} (setup)"})
    return out


def expand(rules):
    """All occurrences of a list of rules, sorted by date.

    Percent rules are worked out after the others, from the revenue (or the
    named rule) in the same calendar month.
    """
    rules = [r for r in rules if not r.get('disabled')]
    first_pass = [r for r in rules if r.get('driver') != 'percent']
    occ = []
    for r in first_pass:
        occ += _occurrences_for(r, {})
    revenue_by_month, by_rule = {}, {}
    for o in occ:
        k = month_key(o['date'])
        if o['kind'] == 'revenue':
            revenue_by_month[k] = revenue_by_month.get(k, Decimal('0')) + o['amount']
        by_rule.setdefault(o['rule'], {})
        by_rule[o['rule']][k] = by_rule[o['rule']].get(k, Decimal('0')) + o['amount']
    for r in rules:
        if r.get('driver') == 'percent':
            of = r.get('of') or 'revenue'
            base = revenue_by_month if of == 'revenue' else by_rule.get(of, {})
            occ += _occurrences_for(r, base)
    return sorted(occ, key=lambda o: (o['date'], o['rule']))


def monthly_totals(occurrences):
    """{YYYY-MM: {'expense': x, 'revenue': y, 'funding': z}}."""
    out = {}
    for o in occurrences:
        m = out.setdefault(month_key(o['date']), {'expense': Decimal('0'), 'revenue': Decimal('0'),
                                                   'funding': Decimal('0')})
        m[o['kind']] += o['amount']
    return dict(sorted(out.items()))


# ─── Journal output ──────────────────────────────────────────────────────────

def journal_text(slug, occurrences, currency, cash_account, pair='0000'):
    """hledger entries for the occurrences, tagged scenario:<slug> rule:<id>."""
    from lib.journal import format_entry
    parts = []
    for o in occurrences:
        value = float(o['amount'])
        sign = 1 if o['kind'] == 'expense' else -1      # money in: credit the account
        postings = [(o['account'], currency, sign * value), (cash_account, currency, -sign * value)]
        tags = {'pair': pair, 'scenario': slug, 'rule': o['rule'] or 'x'}
        if o.get('category'):
            tags['category'] = o['category']
        if o['kind'] == 'funding':
            tags['funding'] = o.get('instrument', 'equity')
        parts.append(format_entry(o['date'].isoformat(), o['name'] or o['rule'], postings, tags))
    return ''.join(parts)


def describe(rule):
    """One-line human summary of a rule."""
    d = rule.get('driver', 'fixed')
    every = 'monthly' if d == 'salary' else (rule.get('every') or 'monthly')
    pct = lambda v: f"{float(D(v)) * 100:g}%"
    if d == 'fixed':
        what = f"{D(rule.get('amount')):,.2f}"
    elif d == 'growth':
        what = f"{D(rule.get('amount')):,.2f}, {pct(rule.get('rate'))} change each time"
    elif d == 'step':
        steps = ', '.join(f"{D(s['amount']):,.2f} from {s['from']}" for s in rule.get('steps') or [])
        what = f"{D(rule.get('amount')):,.2f}" + (f" then {steps}" if steps else '')
    elif d == 'percent':
        what = f"{pct(rule.get('percent'))} of {rule.get('of') or 'revenue'}"
    elif d == 'units':
        what = f"{D(rule.get('units')):g} units x {D(rule.get('price')):,.2f}"
        if rule.get('unit_growth'):
            what += f", units {pct(rule.get('unit_growth'))} each time"
    else:
        what = f"salary {D(rule.get('salary')):,.0f}/yr + {pct(rule.get('benefits'))} benefits"
        if rule.get('raise'):
            what += f", {pct(rule.get('raise'))} yearly raise"
    span = ''
    if every != 'once':
        if rule.get('end'):
            span = f" until {rule['end']}"
        elif rule.get('months'):
            span = f" for {rule['months']} months"
        elif rule.get('repeat'):
            span = f" x{rule['repeat']}"
    return f"{what}, {every} from {rule.get('start')}{span}"
