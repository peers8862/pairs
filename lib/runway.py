"""Runway — cash, burn and runway from the real books plus a scenario plan.

Past months come from the books (actual revenue, expenses and the real cash
balance); future months come from a scenario's rules and manual entries. How
the plan meets the books is the `mode`:

    add      the business keeps running at its recent pace (average of the last
             complete months) and the scenario is added on top — for what-ifs
             such as "hire two people" or "move studios"
    replace  the scenario is the whole plan for future months — for full
             models built line by line

It also works with no books at all: give a starting cash amount.

Settings (config.yaml, all optional):

    runway:
      starting_cash: 25000        # used when the books have no cash yet
      cash_accounts: [Assets:Current:Chequing, Assets:Current:Savings]
      min_cash_months: 3          # warn below N months of expenses
      min_cash: 10000             # or a fixed floor (the larger one is used)
      buffer_months: 15           # raise planner: burn x buffer months
      trailing_months: 3          # months averaged for burn and the run rate
      burn_window: 12             # planned months averaged for burn, floor and raise target
"""

import csv
import subprocess
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

ZERO = Decimal('0')
CASH_EXCLUDE = ('Receivable', 'Prepaid', 'Inventory')


def month_key(d):
    return f'{d.year:04d}-{d.month:02d}'


def add_months(key, n):
    y, m = int(key[:4]), int(key[5:7]) - 1 + n
    return f'{y + m // 12:04d}-{m % 12 + 1:02d}'


def months_between(first, last):
    out, k = [], first
    while k <= last:
        out.append(k)
        k = add_months(k, 1)
    return out


def settings(config):
    s = dict((config or {}).get('runway') or {})
    s.setdefault('buffer_months', 15)
    s.setdefault('trailing_months', 3)
    s.setdefault('min_cash_months', 3)
    s.setdefault('burn_window', 12)
    return s


# ─── Books (hledger) ─────────────────────────────────────────────────────────

def _tidy(files, query, extra=()):
    cmd = ['hledger']
    for f in files:
        cmd += ['-f', str(f)]
    cmd += ['bal', *query, '-M', '-O', 'csv', '--layout=tidy', *extra]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip())
    rows = list(csv.DictReader(StringIO(res.stdout)))
    return rows


def cash_query(config):
    accounts = settings(config).get('cash_accounts')
    if accounts:
        return ['^(' + '|'.join(a.replace(':', ':') for a in accounts) + ')(:|$)']
    return ['^Assets:Current', 'not:(' + '|'.join(CASH_EXCLUDE) + ')']


def actual_months(journal, config, currency, end_month=None):
    """{YYYY-MM: {'revenue', 'expense', 'cash_end'}} from the real books.

    Revenue and expense are the month's totals; cash_end is the balance of the
    cash accounts at month end. Only months up to end_month (exclusive) are kept.
    """
    if not journal or not Path(journal).exists():
        return {}
    out = {}
    for r in _tidy([journal], ['^(Expenses|Income|Revenue)']):
        if r['commodity'] != currency:
            continue
        k = r['start_date'][:7]
        m = out.setdefault(k, {'revenue': ZERO, 'expense': ZERO, 'cash_end': None})
        v = Decimal(r['value'].replace(',', ''))
        if r['account'].startswith('Expenses'):
            m['expense'] += v
        else:
            m['revenue'] -= v
    for r in _tidy([journal], cash_query(config), ['-H']):
        if r['commodity'] != currency:
            continue
        k = r['start_date'][:7]
        m = out.setdefault(k, {'revenue': ZERO, 'expense': ZERO, 'cash_end': None})
        m['cash_end'] = (m['cash_end'] or ZERO) + Decimal(r['value'].replace(',', ''))
    if end_month:
        out = {k: v for k, v in out.items() if k < end_month}
    return dict(sorted(out.items()))


# ─── Projection (pure) ───────────────────────────────────────────────────────

def project(actual, plan, start_month, months, starting_cash=None, mode='add',
            trailing=3, min_cash_months=3, min_cash=None, buffer_months=15, burn_window=12):
    """Month rows plus a summary.

    actual         {YYYY-MM: {'revenue', 'expense', 'cash_end'}} months already closed
    plan           {YYYY-MM: {'revenue', 'expense', 'funding'}} scenario amounts
    start_month    first projected month (usually the current month)
    months         how many months to project
    starting_cash  cash at the start of start_month when the books have none
    mode           'add' (recent pace + scenario) or 'replace' (scenario only)
    """
    if mode not in ('add', 'replace'):
        raise ValueError("mode must be 'add' or 'replace'")
    closed = [k for k in sorted(actual) if k < start_month]
    recent = closed[-trailing:] if trailing else []
    base_rev = sum((actual[k]['revenue'] for k in recent), ZERO) / len(recent) if recent else ZERO
    base_exp = sum((actual[k]['expense'] for k in recent), ZERO) / len(recent) if recent else ZERO

    rows = []
    cash = None
    for k in closed:
        a = actual[k]
        begin = cash
        end = a.get('cash_end')
        if end is None and begin is not None:
            end = begin + a['revenue'] - a['expense']
        other = (end - begin - a['revenue'] + a['expense']) if (begin is not None and end is not None) else ZERO
        rows.append({'month': k, 'source': 'actual', 'begin': begin, 'revenue': a['revenue'],
                     'expense': a['expense'], 'funding': other, 'end': end})
        cash = end
    if cash is None:
        cash = Decimal(str(starting_cash)) if starting_cash is not None else ZERO

    for k in months_between(start_month, add_months(start_month, months - 1)):
        p = plan.get(k, {})
        rev = p.get('revenue', ZERO) + (base_rev if mode == 'add' else ZERO)
        exp = p.get('expense', ZERO) + (base_exp if mode == 'add' else ZERO)
        fund = p.get('funding', ZERO)
        begin = cash
        cash = begin + rev - exp + fund
        rows.append({'month': k, 'source': 'plan', 'begin': begin, 'revenue': rev, 'expense': exp,
                     'funding': fund, 'end': cash})

    for r in rows:
        r['net'] = r['revenue'] - r['expense']
        r['burn'] = max(ZERO, -r['net'])
    return rows, summarise(rows, start_month, trailing, min_cash_months, min_cash, buffer_months,
                           base_rev, base_exp, mode, burn_window)


def summarise(rows, start_month, trailing, min_cash_months, min_cash, buffer_months,
              base_rev=ZERO, base_exp=ZERO, mode='add', burn_window=12):
    future = [r for r in rows if r['source'] == 'plan']
    past = [r for r in rows if r['source'] == 'actual']
    now_cash = future[0]['begin'] if future else (past[-1]['end'] if past else ZERO)
    recent = past[-trailing:] if past else []
    avg_burn_actual = (sum((r['burn'] for r in recent), ZERO) / len(recent)) if recent else None
    ahead = future[:burn_window]
    avg_burn_plan = (sum((r['burn'] for r in ahead), ZERO) / len(ahead)) if ahead else ZERO
    avg_expense_plan = (sum((r['expense'] for r in ahead), ZERO) / len(ahead)) if ahead else ZERO

    floor = max(Decimal(str(min_cash or 0)), avg_expense_plan * Decimal(str(min_cash_months or 0)))
    cash_out = next((r['month'] for r in future if r['end'] < 0), None)
    below_floor = next((r['month'] for r in future if r['end'] < floor), None) if floor else None
    breakeven = next((r['month'] for r in future if r['net'] >= 0 and r['revenue'] > 0), None)

    if cash_out:
        runway = Decimal(future.index(next(r for r in future if r['month'] == cash_out)))
        # part of the last month covered by what was left
        last = next(r for r in future if r['month'] == cash_out)
        if last['begin'] > 0 and last['begin'] - last['end'] > 0:
            runway += last['begin'] / (last['begin'] - last['end'])
        runway_text = None
    elif avg_burn_plan > 0:
        runway = None
        runway_text = 'beyond the projection'
    else:
        runway = None
        runway_text = 'not burning cash'

    raise_target = avg_burn_plan * Decimal(str(buffer_months))
    lowest = min((r['end'] for r in future), default=now_cash)
    return {
        'start_month': start_month, 'mode': mode,
        'cash_now': now_cash, 'lowest_cash': lowest,
        'avg_burn_actual': avg_burn_actual, 'avg_burn_plan': avg_burn_plan,
        'base_revenue': base_rev, 'base_expense': base_exp,
        'runway_months': runway, 'runway_text': runway_text,
        'cash_out_month': cash_out, 'floor': floor, 'below_floor_month': below_floor,
        'breakeven_month': breakeven,
        'buffer_months': buffer_months, 'burn_window': len(ahead), 'raise_target': raise_target,
        'raise_gap': max(ZERO, raise_target - max(now_cash, ZERO)),
    }


def sources_and_uses(raise_amount, plan_by_category, months):
    """Split a raise across report categories in proportion to planned spend.

    plan_by_category  {category: planned expense over the period}
    Returns [(category, share, amount)] and the months the raise covers at
    that spend.
    """
    total = sum(plan_by_category.values(), ZERO)
    raise_amount = Decimal(str(raise_amount))
    rows = []
    for name, amount in plan_by_category.items():
        share = (amount / total) if total else ZERO
        rows.append((name, share, raise_amount * share))
    monthly = total / months if months else ZERO
    covers = (raise_amount / monthly) if monthly else None
    return rows, covers


def to_json(rows, summary):
    def f(v):
        return float(v) if isinstance(v, Decimal) else v
    return ([{k: f(v) for k, v in r.items()} for r in rows],
            {k: f(v) for k, v in summary.items()})


def this_month():
    return month_key(date.today())
