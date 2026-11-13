"""Cap table — who owns what, and what a round would do to it.

Register (captable/register.yaml):

    classes:     [{id: common, name: Common, kind: common}, {id: seed, name: Seed Preferred, kind: preferred}]
    holders:     [{id: ana, name: Ana Diaz, group: founder}]        # founder|employee|advisor|investor|other
    issuances:   [{date, holder, class, shares, price}]
    pool:        {size: 100000}                                    # options authorised (granted + available)
    grants:      [{date, holder, shares, strike}]
    instruments: [{id, holder, kind: safe|note, amount, date, cap, discount, interest, post_money, converted}]

Versions (captable/versions/<slug>.yaml) start from the current register and
apply steps in order:

    steps:
      - {type: safe, holder: angels, amount: 250000, cap: 5000000, discount: 0.2, post_money: true}
      - {type: priced, name: Seed, investment: 2000000, pre_money: 8000000, pool_target: 0.10}
      - {type: priced, name: A, investment: 6000000, percent_sold: 0.20, pool_target: 0.12}

Conversion rules (priced round):
  price            = pre-money / (pre-round fully diluted + pool increase + converting shares)
  pool increase    = enough unallocated options to reach pool_target of post-money fully diluted
                     (comes out of the pre-money: it dilutes existing holders, not the new money)
  note / pre-money SAFE   converts at min(price x (1 - discount), cap / pre-round fully diluted)
  post-money SAFE         converts at min(price x (1 - discount), cap / (pre-round fully diluted
                          + all converting shares)) — the SAFE owns amount / cap of that capitalisation
  notes accrue simple interest from their date to the round date.
Liquidation preferences, pro-rata rights and vesting are not modelled.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal

ZERO = Decimal('0')
GROUPS = ('founder', 'employee', 'advisor', 'investor', 'other')


def D(v):
    return Decimal(str(v)) if v not in (None, '') else ZERO


def empty_register():
    return {'classes': [{'id': 'common', 'name': 'Common', 'kind': 'common'}], 'holders': [],
            'issuances': [], 'pool': {'size': 0}, 'grants': [], 'instruments': []}


def normalise(reg):
    reg = deepcopy(reg or {})
    base = empty_register()
    for k, v in base.items():
        reg.setdefault(k, v)
    if not any(c['id'] == 'common' for c in reg['classes']):
        reg['classes'].insert(0, base['classes'][0])
    reg['pool'] = reg.get('pool') or {'size': 0}
    return reg


# ─── Current state ───────────────────────────────────────────────────────────

def holdings(reg):
    """{(holder, class): shares} from issuances."""
    out = {}
    for i in reg['issuances']:
        key = (i['holder'], i['class'])
        out[key] = out.get(key, ZERO) + D(i['shares'])
    return out


def granted(reg):
    out = {}
    for g in reg['grants']:
        out[g['holder']] = out.get(g['holder'], ZERO) + D(g['shares'])
    return out


def pool_available(reg):
    return D(reg['pool'].get('size')) - sum(granted(reg).values(), ZERO)


def fully_diluted(reg):
    """Issued shares + granted options + unallocated pool (not unconverted instruments)."""
    return sum(holdings(reg).values(), ZERO) + sum(granted(reg).values(), ZERO) + max(pool_available(reg), ZERO)


def last_price(reg):
    # conversions issue at a discounted price; the round price is the company's price
    priced = [i for i in reg['issuances'] if D(i.get('price')) and not i.get('conversion')]
    return D(sorted(priced, key=lambda i: str(i.get('date', '')))[-1]['price']) if priced else None


def open_instruments(reg):
    return [i for i in reg['instruments'] if not i.get('converted')]


def holder_group(reg, holder_id):
    h = next((h for h in reg['holders'] if h['id'] == holder_id), None)
    return (h or {}).get('group', 'investor' if holder_id else 'other')


def holder_name(reg, holder_id):
    h = next((h for h in reg['holders'] if h['id'] == holder_id), None)
    return (h or {}).get('name', holder_id)


def table(reg):
    """Rows per holder (shares by class, options, fully diluted, %) + pool row + totals."""
    hold, opts = holdings(reg), granted(reg)
    fd = fully_diluted(reg)
    price = last_price(reg)
    ids = []
    for (h, _), _v in hold.items():
        if h not in ids:
            ids.append(h)
    for h in opts:
        if h not in ids:
            ids.append(h)
    rows = []
    for h in ids:
        by_class = {c['id']: hold.get((h, c['id']), ZERO) for c in reg['classes']}
        total = sum(by_class.values(), ZERO) + opts.get(h, ZERO)
        rows.append({'holder': h, 'name': holder_name(reg, h), 'group': holder_group(reg, h),
                     'classes': by_class, 'options': opts.get(h, ZERO), 'total': total,
                     'pct': total / fd if fd else ZERO, 'value': total * price if price else None})
    rows.sort(key=lambda r: (GROUPS.index(r['group']) if r['group'] in GROUPS else 9, -r['total']))
    avail = max(pool_available(reg), ZERO)
    return {'rows': rows, 'pool_available': avail, 'pool_pct': avail / fd if fd else ZERO,
            'fully_diluted': fd, 'price': price, 'value': fd * price if price else None,
            'instruments': open_instruments(reg)}


def by_group(reg):
    t = table(reg)
    out = {g: ZERO for g in GROUPS}
    for r in t['rows']:
        out[r['group']] = out.get(r['group'], ZERO) + r['pct']
    out['pool'] = t['pool_pct']
    return out


# ─── Rounds ──────────────────────────────────────────────────────────────────

def _years(start, end):
    a = date.fromisoformat(str(start)) if start else None
    b = date.fromisoformat(str(end)) if end else None
    if not a or not b or b <= a:
        return ZERO
    return D((b - a).days) / D(365)


def _converted_amount(inst, on):
    return D(inst['amount']) * (1 + D(inst.get('interest')) * _years(inst.get('date'), on))


def priced_round(reg, step):
    """Apply a priced round; returns (new register, summary)."""
    reg = normalise(reg)
    investment = D(step['investment'])
    on = str(step.get('date') or date.today().isoformat())
    pre_fd = fully_diluted(reg)
    if pre_fd <= 0:
        raise ValueError("The cap table has no shares yet; add founder shares first")
    if step.get('pre_money'):
        pre_money = D(step['pre_money'])
    elif step.get('percent_sold'):
        pct = D(step['percent_sold'])
        if not 0 < pct < 1:
            raise ValueError("percent_sold is a fraction between 0 and 1")
        pre_money = investment / pct - investment
    else:
        raise ValueError("A priced round needs pre_money or percent_sold")
    target = D(step.get('pool_target'))
    avail = max(pool_available(reg), ZERO)
    insts = open_instruments(reg) if step.get('convert', True) else []

    inc, conv, price = ZERO, {}, ZERO
    for _ in range(200):
        conv_total = sum(conv.values(), ZERO)
        price = pre_money / (pre_fd + inc + conv_total)
        new_conv = {}
        for i in insts:
            amt = _converted_amount(i, on)
            disc_price = price * (1 - D(i.get('discount')))
            post = i.get('post_money', i.get('kind') == 'safe')
            if D(i.get('cap')):
                cap_base = pre_fd + (conv_total if post else ZERO)
                cap_price = D(i['cap']) / cap_base
                conv_price = min(disc_price, cap_price)
            else:
                conv_price = disc_price
            new_conv[i['id']] = amt / conv_price
        new_shares = investment / price
        post_fd = pre_fd + inc + sum(new_conv.values(), ZERO) + new_shares
        new_inc = max(ZERO, target * post_fd - avail) if target else ZERO
        if abs(new_inc - inc) < D('0.0001') and all(abs(new_conv[k] - conv.get(k, ZERO)) < D('0.0001') for k in new_conv):
            inc, conv = new_inc, new_conv
            break
        inc, conv = new_inc, new_conv
    price = pre_money / (pre_fd + inc + sum(conv.values(), ZERO))
    new_shares = investment / price

    cls = step.get('class') or (step.get('name') or 'preferred').lower().replace(' ', '-')
    if not any(c['id'] == cls for c in reg['classes']):
        reg['classes'].append({'id': cls, 'name': f"{step.get('name') or cls} Preferred", 'kind': 'preferred'})
    investors = step.get('investors') or [{'holder': step.get('holder') or f"{cls}-investors",
                                           'amount': investment}]
    for inv in investors:
        if not any(h['id'] == inv['holder'] for h in reg['holders']):
            reg['holders'].append({'id': inv['holder'], 'name': inv.get('name') or inv['holder'], 'group': 'investor'})
        reg['issuances'].append({'date': on, 'holder': inv['holder'], 'class': cls,
                                 'shares': float(D(inv['amount']) / price), 'price': float(price),
                                 'note': step.get('name', '')})
    for i in reg['instruments']:
        if i['id'] in conv:
            reg['issuances'].append({'date': on, 'holder': i['holder'], 'class': cls,
                                     'shares': float(conv[i['id']]), 'price': float(_converted_amount(i, on) / conv[i['id']]),
                                     'note': f"{i.get('kind', 'safe')} {i['id']} converted", 'conversion': True})
            i['converted'] = True
    if inc:
        reg['pool']['size'] = float(D(reg['pool'].get('size')) + inc)
    post_fd = fully_diluted(reg)
    summary = {'name': step.get('name', cls), 'date': on, 'investment': investment,
               'pre_money': pre_money, 'post_money': price * post_fd, 'price': price,
               'new_shares': new_shares, 'conversion_shares': sum(conv.values(), ZERO),
               'pool_increase': inc, 'pre_fd': pre_fd, 'post_fd': post_fd}
    return reg, summary


def add_instrument(reg, step):
    reg = normalise(reg)
    kind = step.get('kind') or step.get('type') or 'safe'
    if kind not in ('safe', 'note'):
        raise ValueError("instrument kind is safe or note")
    holder = step.get('holder') or f"{kind}-holders"
    if not any(h['id'] == holder for h in reg['holders']):
        reg['holders'].append({'id': holder, 'name': step.get('holder_name') or holder, 'group': 'investor'})
    n = len(reg['instruments']) + 1
    inst = {'id': step.get('id') or f"{kind}{n}", 'holder': holder, 'kind': kind,
            'amount': float(D(step['amount'])), 'date': str(step.get('date') or date.today().isoformat()),
            'cap': float(D(step.get('cap'))), 'discount': float(D(step.get('discount'))),
            'interest': float(D(step.get('interest'))),
            'post_money': bool(step.get('post_money', kind == 'safe')), 'converted': False}
    reg['instruments'].append(inst)
    return reg, {'name': step.get('name') or f"{kind.upper()} {holder}", 'date': inst['date'],
                 'investment': D(inst['amount']), 'instrument': inst}


def apply_steps(reg, steps):
    """Run a version's steps; returns (register after, [summaries with group % after each])."""
    reg = normalise(reg)
    out = []
    for step in steps:
        kind = step.get('type', 'priced')
        if kind == 'priced':
            reg, s = priced_round(reg, step)
        elif kind in ('safe', 'note'):
            reg, s = add_instrument(reg, {**step, 'kind': kind})
        elif kind == 'grant':
            reg = normalise(reg)
            if D(step['shares']) > pool_available(reg):
                raise ValueError("grant is larger than the options available")
            if not any(h['id'] == step['holder'] for h in reg['holders']):
                reg['holders'].append({'id': step['holder'], 'name': step.get('name') or step['holder'],
                                       'group': step.get('group', 'employee')})
            reg['grants'].append({'date': step.get('date', ''), 'holder': step['holder'],
                                  'shares': float(D(step['shares'])), 'strike': step.get('strike')})
            s = {'name': f"grant {step['holder']}", 'date': step.get('date', '')}
        else:
            raise ValueError(f"unknown step type {kind}")
        s['groups'] = by_group(reg)
        s['fully_diluted'] = fully_diluted(reg)
        out.append(s)
    return reg, out


def founder_pct(reg):
    return by_group(reg)['founder']
