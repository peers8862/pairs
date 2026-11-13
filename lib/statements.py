"""Projected statements — monthly profit & loss and cash, actuals then plan.

Closed months come from the books by account; later months from the scenario
(and, in 'add' mode, the recent pace). Expenses are grouped by report category
(lib/categories.py); cost of goods sold and non-operating costs are separate
so gross profit and operating income read the usual way. Balance sheet
projection is not modelled.
"""

from decimal import Decimal

from lib.categories import category_for, categories

ZERO = Decimal('0')
COGS = ('Expenses:COGS', 'Expenses:Cost of Goods')
NON_OPERATING = ('Expenses:Non-Operating',)


def _bucket(account, config):
    if account.startswith(COGS):
        return 'cogs'
    if account.startswith(NON_OPERATING):
        return 'nonop'
    return category_for(account, config)


def actual_by_account(journal, currency, before):
    """{month: {account: amount}} for Expenses and {month: revenue} from the books."""
    from lib.runway import _tidy
    from pathlib import Path
    exp, rev = {}, {}
    if not journal or not Path(journal).exists():
        return exp, rev
    for r in _tidy([journal], ['^(Expenses|Income|Revenue)']):
        if r['commodity'] != currency:
            continue
        m = r['start_date'][:7]
        if m >= before:
            continue
        v = Decimal(r['value'].replace(',', ''))
        if r['account'].startswith('Expenses'):
            exp.setdefault(m, {})[r['account']] = exp.get(m, {}).get(r['account'], ZERO) + v
        else:
            rev[m] = rev.get(m, ZERO) - v
    return exp, rev


def build(runway_rows, actual_exp, plan_exp, base_expense, mode, config=None):
    """Lines for a monthly P&L + cash table.

    runway_rows  rows from lib.runway.project (month, source, revenue, expense, funding, begin, end)
    actual_exp   {month: {account: amount}} for closed months
    plan_exp     {month: {account: amount}} scenario expenses for plan months
    """
    months = [r['month'] for r in runway_rows]
    cats = list(categories(config))
    lines = {k: {} for k in ['revenue', 'cogs', 'gross', *cats, 'pace', 'opex', 'operating', 'nonop', 'net',
                             'funding', 'cash_end']}
    for r in runway_rows:
        m = r['month']
        by_acct = actual_exp.get(m, {}) if r['source'] == 'actual' else plan_exp.get(m, {})
        b = {}
        for a, v in by_acct.items():
            k = _bucket(a, config)
            b[k] = b.get(k, ZERO) + v
        pace = base_expense if (r['source'] == 'plan' and mode == 'add') else ZERO
        cogs = b.get('cogs', ZERO)
        opex = sum((b.get(c, ZERO) for c in cats), ZERO) + pace
        nonop = b.get('nonop', ZERO)
        # anything the totals know about but the breakdown missed (e.g. manual entries) goes to the last category
        gap = r['expense'] - (cogs + opex + nonop)
        if abs(gap) > Decimal('0.005'):
            b[cats[-1]] = b.get(cats[-1], ZERO) + gap
            opex += gap
        lines['revenue'][m] = r['revenue']
        lines['cogs'][m] = cogs
        lines['gross'][m] = r['revenue'] - cogs
        for c in cats:
            lines[c][m] = b.get(c, ZERO)
        lines['pace'][m] = pace
        lines['opex'][m] = opex
        lines['operating'][m] = r['revenue'] - cogs - opex
        lines['nonop'][m] = nonop
        lines['net'][m] = r['revenue'] - cogs - opex - nonop
        lines['funding'][m] = r['funding']
        lines['cash_end'][m] = r['end']
    labels = [('revenue', 'Revenue', 'revenue'), ('cogs', 'Cost of goods sold', 'line'),
              ('gross', 'Gross profit', 'subtotal')]
    labels += [(c, c, 'category') for c in cats]
    if mode == 'add':
        labels.append(('pace', 'Current pace (recent average)', 'category'))
    labels += [('opex', 'Operating expenses', 'subtotal'), ('operating', 'Operating income', 'subtotal'),
               ('nonop', 'Non-operating (interest, tax, amortization)', 'line'), ('net', 'Net income', 'total'),
               ('funding', 'Funding and other cash', 'cash'), ('cash_end', 'Cash at month end', 'cash')]
    return {'months': months, 'sources': {r['month']: r['source'] for r in runway_rows},
            'lines': [{'key': k, 'label': l, 'kind': kind, 'values': lines[k]} for k, l, kind in labels
                      if kind in ('revenue', 'subtotal', 'total', 'cash') or any(lines[k].values())]}
