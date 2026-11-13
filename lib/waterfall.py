"""Exit waterfall — who gets what when the company is sold.

Order of payment:
  1. Convertible notes still open are repaid (principal + interest), like debt.
  2. Preferred classes take their liquidation preference, most senior tier
     first (class `seniority`, higher = paid earlier; equal = pari passu, shared
     in proportion). Preference = invested amount x `liq_pref` (default 1x).
     Open SAFEs sit in the most junior preferred tier with a 1x preference.
  3. What is left is shared per share among common, converted preferred,
     participating preferred and options whose strike is below the price per
     share (net of strike).
  4. Non-participating preferred (and SAFEs) convert to common when that pays
     more than the preference. Participating preferred with a cap
     (`participation_cap`, a multiple of invested) stop at the cap, or convert
     when converting pays more.

Simplifications (shown in the UI): no dividends, no escrow or earn-outs, no
management carve-outs, options net-exercise at the exit price, the unallocated
pool is ignored, and SAFEs convert at their cap against the fully diluted count.
"""

from decimal import Decimal

from lib import captable as C

ZERO = Decimal('0')


def _positions(reg, vested_only=False, on=None):
    """[(holder, class, shares, invested)] from issuances."""
    out = {}
    for i in reg['issuances']:
        shares = C.D(i['shares'])
        if vested_only:
            shares = C.vested(i, on)
        key = (i['holder'], i['class'])
        s, inv = out.get(key, (ZERO, ZERO))
        out[key] = (s + shares, inv + C.D(i['shares']) * C.D(i.get('price')))
    return [(h, c, s, inv) for (h, c), (s, inv) in out.items() if s > 0]


def _solve_pps(amount, shares, options):
    """Price per share when `amount` is shared by `shares` plus options that
    net-exercise when the price is above their strike."""
    if amount <= 0:
        return ZERO
    opts = sorted(options, key=lambda o: o[1])
    included_n, included_strike = ZERO, ZERO
    pps = amount / shares if shares else ZERO
    for n, strike in opts:
        trial = (amount + included_strike + n * strike) / (shares + included_n + n) if shares + included_n + n else ZERO
        if trial > strike:
            included_n += n
            included_strike += n * strike
            pps = trial
        else:
            break
    return pps


def payout(reg, exit_value, vested_only=False, on=None):
    """Proceeds by holder and class for a sale at `exit_value`."""
    reg = C.normalise(reg)
    exit_value = C.D(exit_value)
    classes = {c['id']: c for c in reg['classes']}
    positions = _positions(reg, vested_only, on)
    options = []          # (holder, n, strike)
    for g in reg['grants']:
        n = C.vested(g, on) if vested_only else C.D(g['shares'])
        if n > 0:
            options.append((g['holder'], n, C.D(g.get('strike'))))
    fd = C.fully_diluted(reg) - max(C.pool_available(reg), ZERO)

    # 1. notes repaid first
    remaining = exit_value
    paid = {}
    notes = [i for i in C.open_instruments(reg) if i.get('kind') == 'note']
    note_total = sum((C._converted_amount(i, on or '9999-12-31') for i in notes), ZERO) if notes else ZERO
    note_paid = min(remaining, note_total)
    for i in notes:
        owed = C._converted_amount(i, on or '9999-12-31')
        share = owed / note_total * note_paid if note_total else ZERO
        paid[(i['holder'], f"note:{i['id']}")] = share
    remaining -= note_paid

    # preference-bearing units: preferred classes (per class) and SAFEs (each)
    units = {}
    pref_tiers = [C.D(c.get('seniority', 1)) for c in classes.values() if c.get('kind') == 'preferred']
    junior = min(pref_tiers) if pref_tiers else C.D(1)
    for h, c, s, inv in positions:
        cl = classes.get(c, {})
        if cl.get('kind') != 'preferred':
            continue
        u = units.setdefault(c, {'kind': 'class', 'positions': [], 'shares': ZERO, 'invested': ZERO,
                                 'mult': C.D(cl.get('liq_pref', 1)), 'participating': bool(cl.get('participating')),
                                 'cap': C.D(cl.get('participation_cap')), 'seniority': C.D(cl.get('seniority', 1))})
        u['positions'].append((h, s, inv))
        u['shares'] += s
        u['invested'] += inv
    for i in C.open_instruments(reg):
        if i.get('kind') != 'safe':
            continue
        conv_shares = (C.D(i['amount']) / (C.D(i['cap']) / fd)) if C.D(i.get('cap')) and fd else ZERO
        units[f"safe:{i['id']}"] = {'kind': 'safe', 'positions': [(i['holder'], conv_shares, C.D(i['amount']))],
                                     'shares': conv_shares, 'invested': C.D(i['amount']), 'mult': C.D(1),
                                     'participating': False, 'cap': ZERO, 'seniority': junior}
    common = [(h, s) for h, c, s, _ in positions if classes.get(c, {}).get('kind') != 'preferred']
    convert = {k: False for k in units}

    def run(convert):
        rem = remaining
        pref_paid = {}
        live = [k for k in units if not convert[k]]
        for tier in sorted({units[k]['seniority'] for k in live}, reverse=True):
            ks = [k for k in live if units[k]['seniority'] == tier]
            owed = {k: units[k]['invested'] * units[k]['mult'] for k in ks}
            total = sum(owed.values(), ZERO)
            pay = min(rem, total)
            for k in ks:
                pref_paid[k] = owed[k] / total * pay if total else ZERO
            rem -= pay
        sharing = {k for k in units if convert[k] or units[k]['participating']}
        capped = {}
        while True:
            shares = sum((s for _, s in common), ZERO) + sum((units[k]['shares'] for k in sharing if k not in capped), ZERO)
            pool = rem - sum(capped.values(), ZERO)
            pps = _solve_pps(pool, shares, [(n, st) for _, n, st in options])
            newly = False
            for k in sharing:
                u = units[k]
                if k in capped or convert[k] or not u['cap']:
                    continue
                limit = u['cap'] * u['invested'] - pref_paid.get(k, ZERO)
                if u['shares'] * pps > limit:
                    capped[k] = max(limit, ZERO)
                    newly = True
            if not newly:
                break
        part = {k: (capped[k] if k in capped else units[k]['shares'] * pps) for k in sharing}
        total = {k: pref_paid.get(k, ZERO) + part.get(k, ZERO) for k in units}
        return pps, pref_paid, part, total

    for _ in range(40):
        pps, pref_paid, part, total = run(convert)
        changed = False
        for k, u in units.items():
            if convert[k] or (u['participating'] and not u['cap']):
                continue
            as_common = u['shares'] * pps
            if as_common > total[k] + C.D('0.005'):
                trial = dict(convert, **{k: True})
                if run(trial)[3][k] > total[k]:
                    convert = trial
                    changed = True
                    break
        if not changed:
            break
    pps, pref_paid, part, total = run(convert)

    # distribute to holders
    for h, s in common:
        paid[(h, 'common')] = paid.get((h, 'common'), ZERO) + s * pps
    for k, u in units.items():
        for h, s, inv in u['positions']:
            share = (inv / u['invested']) if u['invested'] else (s / u['shares'] if u['shares'] else ZERO)
            key = (h, k)
            paid[key] = paid.get(key, ZERO) + total[k] * share
    for h, n, strike in options:
        if pps > strike:
            paid[(h, 'options')] = paid.get((h, 'options'), ZERO) + n * (pps - strike)

    invested = {}
    for h, c, s, inv in positions:
        invested[h] = invested.get(h, ZERO) + inv
    for i in C.open_instruments(reg):
        invested[i['holder']] = invested.get(i['holder'], ZERO) + C.D(i['amount'])
    holders = {}
    for (h, k), v in paid.items():
        holders[h] = holders.get(h, ZERO) + v
    rows = [{'holder': h, 'name': C.holder_name(reg, h), 'group': C.holder_group(reg, h),
             'proceeds': v, 'pct': v / exit_value if exit_value else ZERO,
             'invested': invested.get(h, ZERO),
             'multiple': (v / invested[h]) if invested.get(h) else None}
            for h, v in holders.items()]
    rows.sort(key=lambda r: -r['proceeds'])
    class_rows = [{'unit': k, 'name': classes.get(k, {}).get('name', k), 'kind': u['kind'],
                   'decision': 'converts to common' if convert[k] else ('preference + participation' if u['participating'] else 'takes preference'),
                   'preference': pref_paid.get(k, ZERO), 'participation': part.get(k, ZERO), 'total': total[k],
                   'invested': u['invested']} for k, u in units.items()]
    distributed = sum(holders.values(), ZERO)
    return {'exit_value': exit_value, 'price_per_share': pps, 'notes_repaid': note_paid,
            'rows': rows, 'classes': class_rows, 'undistributed': exit_value - distributed}


def by_group(result):
    out = {}
    for r in result['rows']:
        out[r['group']] = out.get(r['group'], ZERO) + r['proceeds']
    return out


def sweep(reg, values, vested_only=False, on=None):
    """Proceeds by group for several exit values (for a chart)."""
    return [{'exit_value': C.D(v), 'groups': by_group(payout(reg, v, vested_only, on))} for v in values]
