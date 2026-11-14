"""Projected statements — monthly profit & loss, balance sheet and cash flow.

Closed months come from the books by account; later months from the scenario
(and, in 'add' mode, the recent pace). Expenses are grouped by report category
(lib/categories.py); cost of goods sold and non-operating costs are separate
so gross profit and operating income read the usual way.

The balance sheet (I35, full O24/O25 driver set, D20) is DERIVED — never
hand-entered lines. The drivers live in an `assumptions:` block in the
scenario's scenario.yaml (following the `growth:` precedent); every field
defaults to off, so a scenario without assumptions behaves exactly as before.

Drivers:
- working capital: receivables = revenue x DSO/30, payables =
  (COGS + opex) x DPO/30, inventory = COGS x DIO/30 (month-end balances).
  Cash is reconciled, not assumed: the runway assumes revenue is collected
  and expenses paid immediately, so the balance-sheet cash is the runway
  cash adjusted for working-capital movements — see project_bs.
- equipment/depreciation: hires (salary rules) x equipment cost per new
  hire, straight-line over the useful life; depreciation is a P&L expense.
- debt/interest: debt rolls from opening + new debt funding - repayments
  (a negative debt funding occurrence); interest on the beginning debt
  balance and on the beginning cash balance, netted into one P&L line.
- tax loss carryforward: losses accumulate and offset later taxable profit
  at the assumption tax rate.
- credit line (I47): when cash would fall below the floor (the runway's
  cash floor, passed in by modules/runway.statements(); 0 when none is
  given), the line draws automatically up to `credit_line_limit` and repays
  when cash allows above the floor. Interest on the beginning drawn balance
  at `credit_line_rate`, in the net interest line.

Funding instruments (from the scenario occurrences): equity and SAFE are
equity funding, debt and note are debt, grant is INCOME — it lands in
retained earnings through net income, not in share capital. A funding
occurrence with a negative amount is a repayment / return of that kind.

The sheet must balance every projected month: assets == liabilities +
equity is asserted in project_bs (and in the tests). Interest and tax are
assumed paid in the month they arise (no interest/tax payable balances).
The opening credit-line balance comes from the opening buckets (a hand-built
opening can carry `credit_line`); a credit line already in the books sits
inside other liabilities/debt and is not separately tracked — the line
state here only tracks new draws. All money is Decimal, rounded to cents.
"""

from decimal import Decimal, ROUND_HALF_UP

from lib.categories import category_for, categories

ZERO = Decimal('0')
CENT = Decimal('0.01')
COGS = ('Expenses:COGS', 'Expenses:Cost of Goods')
NON_OPERATING = ('Expenses:Non-Operating',)


def _cents(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def _bucket(account, config):
    if account.startswith(COGS):
        return 'cogs'
    if account.startswith(NON_OPERATING):
        return 'nonop'
    return category_for(account, config)


# ─── Assumptions (scenario.yaml `assumptions:`) ─────────────────────────────

ASSUMPTION_FIELDS = {
    'dso_days': '0', 'dpo_days': '0', 'dio_days': '0',
    'equipment_cost_per_hire': '0', 'useful_life_years': '0',
    'interest_rate_debt': '0', 'interest_rate_cash': '0',
    'tax_rate': '0', 'tax_loss_carryforward_opening': '0',
    'credit_line_limit': '0', 'credit_line_rate': '0',
}


def assumptions_from(raw):
    """Validated assumptions: every field optional, defaults to off.

    Days and costs are plain numbers; rates are fractions (0.05 = 5%).
    Raises ValueError on unknown keys, negative days/costs, a tax rate
    outside [0, 1), or equipment cost without a useful life.
    """
    raw = raw or {}
    unknown = sorted(set(raw) - set(ASSUMPTION_FIELDS))
    if unknown:
        raise ValueError(f"unknown assumptions: {', '.join(unknown)}")
    a = {}
    for key in ASSUMPTION_FIELDS:
        try:
            a[key] = Decimal(str(raw.get(key))) if raw.get(key) not in (None, '') \
                else Decimal(ASSUMPTION_FIELDS[key])
        except Exception:
            raise ValueError(f'assumption {key} must be a number, got {raw.get(key)!r}')
    for key in ('dso_days', 'dpo_days', 'dio_days'):
        if a[key] < 0:
            raise ValueError(f'{key} must be >= 0')
    for key in ('interest_rate_debt', 'interest_rate_cash'):
        if not (-1 < a[key] < 10):
            raise ValueError(f'{key} is a fraction (0.05 = 5%), got {a[key]}')
    if not (0 <= a['credit_line_rate'] < 1):
        raise ValueError(f"credit_line_rate is a fraction in [0, 1), got {a['credit_line_rate']}")
    if a['credit_line_limit'] < 0:
        raise ValueError('credit_line_limit must be >= 0')
    if not (0 <= a['tax_rate'] < 1):
        raise ValueError(f'tax_rate is a fraction in [0, 1), got {a["tax_rate"]}')
    for key in ('equipment_cost_per_hire', 'tax_loss_carryforward_opening'):
        if a[key] < 0:
            raise ValueError(f'{key} must be >= 0')
    if a['useful_life_years'] < 0:
        raise ValueError('useful_life_years must be >= 0')
    if a['equipment_cost_per_hire'] > 0 and a['useful_life_years'] <= 0:
        raise ValueError('useful_life_years is required when equipment_cost_per_hire is set')
    return a


# ─── Funding split and hires (from scenario occurrences / rules) ────────────

def funding_split(occurrences):
    """{YYYY-MM: {equity, safe, debt, note, grant}} for funding occurrences.

    Classified by instrument when present, else by account: Equity ->
    equity, Liabilities -> debt, anything else (Income) -> grant.
    """
    out = {}
    for o in occurrences or []:
        if o.get('kind') != 'funding':
            continue
        month = str(o['date'])[:7]
        m = out.setdefault(month, {'equity': ZERO, 'safe': ZERO, 'debt': ZERO,
                                   'note': ZERO, 'grant': ZERO})
        instrument = o.get('instrument')
        if instrument in m:
            m[instrument] += Decimal(str(o['amount']))
        else:
            account = o.get('account') or ''
            if account.startswith('Equity'):
                m['equity'] += Decimal(str(o['amount']))
            elif account.startswith('Liabilities'):
                m['debt'] += Decimal(str(o['amount']))
            else:
                m['grant'] += Decimal(str(o['amount']))
    return dict(sorted(out.items()))


def hire_months(rules):
    """{YYYY-MM: number of salary rules whose first occurrence is that month}."""
    from lib.plan_rules import occurrence_dates
    out = {}
    for r in rules or []:
        if r.get('driver') != 'salary':
            continue
        dates = occurrence_dates(r)
        if not dates:
            continue
        key = dates[0].strftime('%Y-%m')
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


# ─── Opening balances from the books ────────────────────────────────────────

def _is_cash_account(account, config=None):
    """Same rule as lib.runway.cash_query: the configured cash accounts,
    else Assets:Current except Receivable / Prepaid / Inventory."""
    from lib.runway import settings
    accounts = settings(config).get('cash_accounts')
    if accounts:
        return any(account == a or account.startswith(a + ':') for a in accounts)
    if not account.startswith('Assets:Current'):
        return False
    return not any(x in account for x in ('Receivable', 'Prepaid', 'Inventory'))


def _book_balances(journal, currency, config=None, end=None):
    """{month: {account: Decimal}} month-end balances from the books.

    One `hledger bal -M -H` tidy query over balance-sheet and P&L accounts;
    `end` (YYYY-MM-DD, exclusive) limits it. hledger signs: asset/expense
    balances are positive, liability/equity/income balances negative.
    """
    from lib.runway import _tidy
    from pathlib import Path
    if not journal or not Path(journal).exists():
        return {}
    extra = ['-H']
    if end:
        extra += ['--end', end]
    rows = _tidy([journal], ['^(Assets|Liabilities|Equity|Income|Revenue|Expenses)'], extra)
    out = {}
    for r in rows:
        if r['commodity'] != currency:
            continue
        month = r['start_date'][:7]
        # NB: do not inline setdefault into the assignment target — the
        # right-hand side is evaluated before the target, so out[month]
        # would KeyError on the first row of a month.
        d = out.setdefault(month, {})
        d[r['account']] = d.get(r['account'], ZERO) + Decimal(r['value'].replace(',', ''))
    return dict(sorted(out.items()))


def buckets_from_balances(balances, config=None):
    """Map one month of book balances onto balance-sheet buckets.

    The mapping is a partition of every account, so the buckets balance
    whenever the books do: retained earnings is the accumulated P&L
    (-income balances - expense balances), and anything not otherwise
    classified lands in an `other_*` bucket, frozen at its opening value.
    """
    b = {'cash': ZERO, 'receivables': ZERO, 'inventory': ZERO, 'ppe_gross': ZERO,
         'accum_depreciation': ZERO, 'other_assets': ZERO, 'payables': ZERO,
         'debt': ZERO, 'other_liabilities': ZERO, 'share_capital': ZERO,
         'safe': ZERO, 'other_equity': ZERO, 'retained_earnings': ZERO}
    income = ZERO
    expense = ZERO
    for account, v in (balances or {}).items():
        if _is_cash_account(account, config):
            b['cash'] += v
        elif 'Receivable' in account:
            b['receivables'] += v
        elif 'Inventory' in account:
            b['inventory'] += v
        elif account.startswith('Assets:Fixed'):
            b['ppe_gross'] += v
        elif account.startswith('Assets:Accumulated Amortization'):
            b['accum_depreciation'] += -v
        elif account.startswith('Assets'):
            b['other_assets'] += v
        elif 'Payable' in account:
            b['payables'] += -v
        elif account.startswith('Liabilities') and ('Loan' in account or 'Note' in account):
            b['debt'] += -v
        elif account.startswith('Liabilities'):
            b['other_liabilities'] += -v
        elif account == 'Equity:Share Capital':
            b['share_capital'] += -v
        elif account == 'Equity:SAFE':
            b['safe'] += -v
        elif account.startswith('Equity'):
            b['other_equity'] += -v
        elif account.startswith(('Income', 'Revenue')):
            income += v
        elif account.startswith('Expenses'):
            expense += v
    b['retained_earnings'] = -income - expense
    return b


def opening_balances(journal, currency, before_month, config=None):
    """Balance-sheet buckets at the end of the month before `before_month`,
    from the books; None when there are no books (or no months before it)."""
    bals = _book_balances(journal, currency, config, end=f'{before_month}-01')
    months = [m for m in bals if m < before_month]
    if not months:
        return None
    return buckets_from_balances(bals[months[-1]], config)


def actual_bs(journal, currency, months, config=None):
    """{month: buckets} of actual balance sheets for the given months."""
    bals = _book_balances(journal, currency, config)
    return {m: buckets_from_balances(bals[m], config) for m in months if m in bals}


# ─── Balance-sheet projection (pure) ────────────────────────────────────────

OPENING_KEYS = ('cash', 'receivables', 'inventory', 'ppe_gross',
                'accum_depreciation', 'other_assets', 'payables', 'debt', 'credit_line',
                'other_liabilities', 'share_capital', 'safe', 'other_equity',
                'retained_earnings', 'tax_loss_carryforward')


def _normalise_opening(opening):
    return {k: Decimal(str((opening or {}).get(k, 0))) for k in OPENING_KEYS}


def _month_diff(a, b):
    """Months from a to b (YYYY-MM keys)."""
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


def _check(state):
    assets = (state['cash'] + state['receivables'] + state['inventory']
              + state['ppe_gross'] - state['accum_depreciation']
              + state['other_assets'])
    liabilities = (state['payables'] + state['debt'] + state['credit_line']
                   + state['other_liabilities'])
    equity = (state['share_capital'] + state['safe'] + state['other_equity']
              + state['retained_earnings'])
    return assets, liabilities, equity, assets - liabilities - equity


def project_bs(opening, monthly, assumptions=None, floor=None):
    """Roll a balance sheet forward month by month.

    opening   buckets (see buckets_from_balances) at the start; must balance.
    monthly   [{month, source, revenue, cogs, opex, nonop, funding,
                funding_split, hires, actual_bs?}] — for months with
                `actual_bs` the book balances are used as-is and the
                drivers are skipped; for the rest the sheet is derived.
                A missing funding_split means the whole funding lump is
                equity; a supplied split must sum to the funding lump.
    assumptions  scenario `assumptions:` block (see assumptions_from).
    floor     the cash floor the credit line draws to (the runway's cash
              floor); None means 0 — cash is never allowed below zero when
              a credit line is configured. With no credit_line_limit the
              floor does nothing: cash can go below it, as before.

    Returns {months, lines, pl, cash_flow, carryforward} — lines are the
    balance-sheet lines keyed bs_*, pl the derived P&L lines
    (depreciation / interest / tax / net), cash_flow the plan months'
    operating / investing / financing flows that tie cash_end to opening
    cash. Raises AssertionError if any month does not balance.
    """
    a = assumptions_from(assumptions)
    floor = Decimal(str(floor)) if floor is not None else ZERO
    state = _normalise_opening(opening)
    _, _, _, check = _check(state)
    if check != ZERO:
        raise ValueError(f'opening balance sheet does not balance (off by {check})')
    life_months = int((a['useful_life_years'] * 12).to_integral_value(rounding=ROUND_HALF_UP))
    vintages = []   # {'month', 'amount', 'life', 'depreciated'}
    # Opening loss carryforward: the opening buckets' value plus the
    # assumptions' opening value — in practice only one is ever set.
    carryforward = state['tax_loss_carryforward'] + a['tax_loss_carryforward_opening']
    lines = {k: {} for k in
             ('bs_cash', 'bs_receivables', 'bs_inventory', 'bs_ppe_net', 'bs_other_assets',
              'bs_assets', 'bs_payables', 'bs_debt', 'bs_credit_line', 'bs_other_liabilities',
              'bs_liabilities', 'bs_share_capital', 'bs_safe', 'bs_other_equity', 'bs_retained',
              'bs_equity', 'bs_check')}
    pl = {k: {} for k in ('depreciation', 'interest', 'tax', 'net')}
    cash_flow = {}
    carry = {}
    months = []
    for item in monthly:
        m = item['month']
        months.append(m)
        if item.get('actual_bs') is not None:
            b = item['actual_bs']
            state = _normalise_opening({**b, 'tax_loss_carryforward': carryforward})
            rev, cogs, opex, nonop = (Decimal(str(item.get(k, 0))) for k in
                                      ('revenue', 'cogs', 'opex', 'nonop'))
            pl['depreciation'][m] = ZERO
            pl['interest'][m] = ZERO
            pl['tax'][m] = ZERO
            pl['net'][m] = rev - cogs - opex - nonop
        else:
            rev = Decimal(str(item.get('revenue', 0)))
            cogs = Decimal(str(item.get('cogs', 0)))
            opex = Decimal(str(item.get('opex', 0)))
            nonop = Decimal(str(item.get('nonop', 0)))
            fund = Decimal(str(item.get('funding', 0)))
            split = item.get('funding_split')
            if split is None:
                split = {'equity': fund, 'safe': ZERO, 'debt': ZERO, 'note': ZERO,
                         'grant': ZERO}
            else:
                split = {k: Decimal(str(split.get(k, 0))) for k in
                         ('equity', 'safe', 'debt', 'note', 'grant')}
                if sum(split.values()) != fund:
                    raise ValueError(
                        f"funding split for {m} sums to {sum(split.values())}, "
                        f"not the funding lump {fund}")
            # Equipment: new hires x cost per hire, one vintage per month.
            equip_add = _cents(Decimal(str(item.get('hires', 0)))
                               * a['equipment_cost_per_hire'])
            if equip_add > 0:
                vintages.append({'month': m, 'amount': equip_add, 'life': life_months,
                                 'depreciated': ZERO})
            # Depreciation: straight-line per vintage; the last month of a
            # vintage's life takes the exact remainder, so PP&E nets to zero.
            dep = ZERO
            for v in vintages:
                age = _month_diff(v['month'], m)
                if age < 0 or age >= v['life']:
                    continue
                if age == v['life'] - 1:
                    d = v['amount'] - v['depreciated']
                else:
                    d = _cents(v['amount'] / v['life'])
                v['depreciated'] += d
                dep += d
            # Interest on beginning balances (avoids the cash/net circularity).
            int_debt = _cents(state['debt'] * a['interest_rate_debt'] / 12)
            int_cash = _cents(state['cash'] * a['interest_rate_cash'] / 12)
            int_cl = _cents(state['credit_line'] * a['credit_line_rate'] / 12)
            interest = int_debt - int_cash + int_cl
            # Tax: profit before tax, less any loss carryforward.
            pbt = rev - cogs - opex - nonop - dep - interest
            if pbt <= 0:
                carryforward += -pbt
                tax = ZERO
            else:
                taxable = max(ZERO, pbt - carryforward)
                carryforward = max(ZERO, carryforward - pbt)
                tax = _cents(taxable * a['tax_rate'])
            net = pbt - tax
            pl['depreciation'][m] = dep
            pl['interest'][m] = interest
            pl['tax'][m] = tax
            pl['net'][m] = net
            # Working capital (month-end balances, 30-day months).
            ar_new = _cents(rev * a['dso_days'] / 30)
            ap_new = _cents((cogs + opex) * a['dpo_days'] / 30)
            inv_new = _cents(cogs * a['dio_days'] / 30)
            # Cash, indirect method: net + depreciation (non-cash) - the
            # working-capital movements - equipment bought + funding in.
            # This is the reconciliation that replaces the runway's
            # collect-everything-immediately cash for plan months.
            cfo = net + dep - (ar_new - state['receivables']) \
                + (ap_new - state['payables']) - (inv_new - state['inventory'])
            cfi = -equip_add
            cff = fund
            cash_begin = state['cash']
            cash_pre = cash_begin + cfo + cfi + cff
            # Credit line (I47): draw to the floor when cash would fall below
            # it, repay when cash allows above it, up to the limit. Interest
            # above is on the beginning balance, so this decision cannot feed
            # back into it; the draw is a financing flow, so the sheet still
            # balances (cash and the line move together).
            draw = repay = ZERO
            if a['credit_line_limit'] > 0:
                if cash_pre < floor:
                    draw = max(ZERO, min(floor - cash_pre,
                                         a['credit_line_limit'] - state['credit_line']))
                elif cash_pre > floor and state['credit_line'] > 0:
                    repay = min(state['credit_line'], cash_pre - floor)
                state['credit_line'] += draw - repay
                cff += draw - repay
            state['cash'] = cash_pre + draw - repay
            state['receivables'] = ar_new
            state['inventory'] = inv_new
            state['payables'] = ap_new
            state['ppe_gross'] += equip_add
            state['accum_depreciation'] += dep
            state['debt'] += split['debt'] + split['note']
            state['share_capital'] += split['equity']
            state['safe'] += split['safe']
            # A grant is income, not equity: it reaches retained earnings
            # through net income's twin — the grant cash is in `fund`, and
            # net excludes it, so add it to retained earnings directly.
            state['retained_earnings'] += net + split['grant']
            cash_flow[m] = {'operating': cfo, 'investing': cfi, 'financing': cff,
                            'begin': cash_begin, 'end': state['cash'],
                            'credit_line_draw': draw - repay,
                            'credit_line': state['credit_line']}
        assets, liabilities, equity, check = _check(state)
        if check != ZERO:
            raise AssertionError(
                f'balance sheet does not balance in {m} (off by {check})')
        ppe_net = state['ppe_gross'] - state['accum_depreciation']
        for key, value in (
                ('bs_cash', state['cash']), ('bs_receivables', state['receivables']),
                ('bs_inventory', state['inventory']), ('bs_ppe_net', ppe_net),
                ('bs_other_assets', state['other_assets']), ('bs_assets', assets),
                ('bs_payables', state['payables']), ('bs_debt', state['debt']),
                ('bs_credit_line', state['credit_line']),
                ('bs_other_liabilities', state['other_liabilities']),
                ('bs_liabilities', liabilities),
                ('bs_share_capital', state['share_capital']), ('bs_safe', state['safe']),
                ('bs_other_equity', state['other_equity']),
                ('bs_retained', state['retained_earnings']), ('bs_equity', equity),
                ('bs_check', check)):
            lines[key][m] = value
        carry[m] = carryforward
    return {'months': months, 'lines': lines, 'pl': pl, 'cash_flow': cash_flow,
            'carryforward': carry}


# ─── Statements table ────────────────────────────────────────────────────────

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


def build(runway_rows, actual_exp, plan_exp, base_expense, mode, config=None,
          assumptions=None, funding_split=None, hires=None, opening=None,
          actual_bs=None, floor=None):
    """Lines for a monthly P&L + cash table, plus (when `opening` is given)
    a projected balance sheet and cash-flow reconciliation.

    runway_rows  rows from lib.runway.project (month, source, revenue, expense, funding, begin, end)
    actual_exp   {month: {account: amount}} for closed months
    plan_exp     {month: {account: amount}} scenario expenses for plan months
    assumptions  scenario `assumptions:` block (None = all drivers off)
    funding_split {month: {equity, safe, debt, note, grant}}; a month with
                 no split treats its whole funding lump as equity
    hires        {month: new hires} for the equipment driver
    opening      balance-sheet buckets at the start of the window; without
                 it (and without actual_bs) the output is exactly the old
                 P&L + cash table, with no balance-sheet keys
    actual_bs    {month: buckets} of actual balance sheets, used as-is for
                 those months
    floor        cash floor the credit line (I47) draws to; None means 0

    With a balance sheet, the cash_end line is the reconciled balance-sheet
    cash (working-capital adjusted); with all drivers off it equals the
    runway cash_end exactly, so the old numbers are unchanged.
    """
    months = [r['month'] for r in runway_rows]
    cats = list(categories(config))
    lines = {k: {} for k in ['revenue', 'cogs', 'gross', *cats, 'pace', 'opex', 'operating', 'nonop', 'net',
                             'funding', 'cash_end']}
    monthly = []
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
        monthly.append({'month': m, 'source': r['source'], 'revenue': r['revenue'],
                        'cogs': cogs, 'opex': opex, 'nonop': nonop,
                        'funding': r['funding'],
                        'funding_split': (funding_split or {}).get(m),
                        'hires': (hires or {}).get(m, 0),
                        'actual_bs': (actual_bs or {}).get(m)})
    labels = [('revenue', 'Revenue', 'revenue'), ('cogs', 'Cost of goods sold', 'line'),
              ('gross', 'Gross profit', 'subtotal')]
    labels += [(c, c, 'category') for c in cats]
    if mode == 'add':
        labels.append(('pace', 'Current pace (recent average)', 'category'))
    labels += [('opex', 'Operating expenses', 'subtotal'), ('operating', 'Operating income', 'subtotal'),
               ('nonop', 'Non-operating (interest, tax, amortization)', 'line'), ('net', 'Net income', 'total'),
               ('funding', 'Funding and other cash', 'cash'), ('cash_end', 'Cash at month end', 'cash')]
    out = {'months': months, 'sources': {r['month']: r['source'] for r in runway_rows},
           'lines': [{'key': k, 'label': l, 'kind': kind, 'values': lines[k]} for k, l, kind in labels
                     if kind in ('revenue', 'subtotal', 'total', 'cash') or any(lines[k].values())]}
    if opening is None and not actual_bs:
        return out
    bs = project_bs(opening, monthly, assumptions, floor=floor)
    for key in ('depreciation', 'interest', 'tax'):
        lines[key] = bs['pl'][key]
    lines['net'] = bs['pl']['net']
    for key, values in bs['lines'].items():
        lines[key] = values
        if key == 'bs_cash':
            lines['cash_end'] = values
    bs_labels = [('depreciation', 'Depreciation', 'line'), ('interest', 'Interest (net)', 'line'),
                 ('tax', 'Tax', 'line'),
                 ('bs_cash', 'Cash', 'line'), ('bs_receivables', 'Accounts receivable', 'line'),
                 ('bs_inventory', 'Inventory', 'line'), ('bs_ppe_net', 'Equipment (net)', 'line'),
                 ('bs_other_assets', 'Other assets', 'line'), ('bs_assets', 'Total assets', 'total'),
                 ('bs_payables', 'Accounts payable', 'line'), ('bs_debt', 'Debt', 'line'),
                 ('bs_credit_line', 'Credit line', 'line'),
                 ('bs_other_liabilities', 'Other liabilities', 'line'),
                 ('bs_liabilities', 'Total liabilities', 'total'),
                 ('bs_share_capital', 'Share capital', 'line'), ('bs_safe', 'SAFE', 'line'),
                 ('bs_other_equity', 'Other equity', 'line'),
                 ('bs_retained', 'Retained earnings', 'line'),
                 ('bs_equity', 'Total equity', 'total'),
                 ('bs_check', 'Balance check (must be 0)', 'total')]
    # Rebuild the line list with the derived lines in place: depreciation /
    # interest / tax sit between non-operating and net income, the balance
    # sheet follows cash at month end.
    by_key = {l['key']: l for l in out['lines']}
    for key, label, kind in bs_labels:
        by_key[key] = {'key': key, 'label': label, 'kind': kind, 'values': lines[key]}
    # Net income and cash at month end are derived lines too — rebind them
    # to the projected values, not the pre-projection ones above.
    by_key['net'] = {'key': 'net', 'label': 'Net income', 'kind': 'total',
                     'values': lines['net']}
    by_key['cash_end'] = {'key': 'cash_end', 'label': 'Cash at month end', 'kind': 'cash',
                          'values': lines['cash_end']}
    order = [l['key'] for l in out['lines']]
    order = [k for k in order if k != 'net']
    net_at = order.index('funding')
    order = order[:net_at] + ['depreciation', 'interest', 'tax', 'net'] + order[net_at:]
    order += [k for k, _, _ in bs_labels[3:]]
    out['lines'] = [by_key[k] for k in order
                    if by_key[k]['kind'] in ('revenue', 'subtotal', 'total', 'cash')
                    or any(by_key[k]['values'].values())]
    out['balance_sheet'] = bs['lines']
    out['cash_flow'] = bs['cash_flow']
    return out
