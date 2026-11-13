"""pair captable — ownership, instruments and round versions (captable pack)."""

import sys
from datetime import date
from decimal import Decimal, InvalidOperation

import yaml

from lib.helpers import parse_global_flags, get_entity_dir, get_active_entity, slugify
from lib import captable as C


# ─── Store ───────────────────────────────────────────────────────────────────

def cap_dir(entity_dir=None):
    return (entity_dir or get_entity_dir()) / 'captable'


def load_register(entity_dir=None):
    path = cap_dir(entity_dir) / 'register.yaml'
    return C.normalise(yaml.safe_load(path.read_text()) if path.exists() else None)


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def save_register(reg, entity_dir=None):
    path = cap_dir(entity_dir) / 'register.yaml'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(yaml.dump(_plain(reg), default_flow_style=False, sort_keys=False))
    tmp.replace(path)


def list_versions(entity_dir=None):
    d = cap_dir(entity_dir) / 'versions'
    return sorted(p.stem for p in d.glob('*.yaml')) if d.exists() else []


def load_version(slug, entity_dir=None):
    path = cap_dir(entity_dir) / 'versions' / f'{slug}.yaml'
    return yaml.safe_load(path.read_text()) if path.exists() else None


def save_version(slug, data, entity_dir=None):
    path = cap_dir(entity_dir) / 'versions' / f'{slug}.yaml'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(_plain(data), default_flow_style=False, sort_keys=False))


def delete_version(slug, entity_dir=None):
    path = cap_dir(entity_dir) / 'versions' / f'{slug}.yaml'
    if path.exists():
        path.unlink()
        return True
    return False


def ensure_holder(reg, holder_id, name=None, group='investor'):
    if not any(h['id'] == holder_id for h in reg['holders']):
        reg['holders'].append({'id': holder_id, 'name': name or holder_id, 'group': group})


def apply_change(reg, change):
    """Record a real change: holder, issue, pool, grant, safe, note."""
    kind = change.get('type')
    if kind == 'holder':
        hid = change.get('id') or slugify(change['name'])
        if change.get('group', 'founder') not in C.GROUPS:
            raise ValueError(f"group must be one of {', '.join(C.GROUPS)}")
        ensure_holder(reg, hid, change['name'], change.get('group', 'founder'))
        h = next(x for x in reg['holders'] if x['id'] == hid)
        for k in ('investor_type', 'contact', 'email'):
            if change.get(k):
                h[k] = change[k]
        return reg
    if kind == 'class':
        cid = change.get('id') or slugify(change.get('name', ''))
        if not cid:
            raise ValueError("A class needs an id or name")
        cl = next((c for c in reg['classes'] if c['id'] == cid), None)
        if not cl:
            cl = {'id': cid, 'name': change.get('name') or cid.title(), 'kind': change.get('kind', 'preferred')}
            reg['classes'].append(cl)
        for k in ('name', 'kind'):
            if change.get(k):
                cl[k] = change[k]
        for k in C.CLASS_TERMS:
            if k in change and change[k] not in (None, ''):
                cl[k] = bool(change[k]) if k == 'participating' and not isinstance(change[k], str) else (
                    change[k] in ('yes', 'true', True) if k == 'participating' else float(change[k]))
        if C.D(cl.get('liq_pref', 1)) < 0 or C.D(cl.get('participation_cap', 0)) < 0:
            raise ValueError("preference and cap are zero or more")
        return reg
    if kind == 'issue':
        cls = change.get('class') or 'common'
        if not any(c['id'] == cls for c in reg['classes']):
            reg['classes'].append({'id': cls, 'name': change.get('class_name') or cls.title(),
                                   'kind': 'common' if cls == 'common' else 'preferred'})
        ensure_holder(reg, change['holder'], change.get('holder_name'), change.get('group', 'investor'))
        h = next(x for x in reg['holders'] if x['id'] == change['holder'])
        for k in ('investor_type', 'contact'):
            if change.get(k) and not h.get(k):
                h[k] = change[k]
        shares = Decimal(str(change['shares']))
        if shares <= 0:
            raise ValueError("shares must be positive")
        issue = {'date': str(change.get('date') or date.today().isoformat()),
                 'holder': change['holder'], 'class': cls, 'shares': float(shares),
                 'price': float(Decimal(str(change.get('price') or 0)))}
        if change.get('vesting'):
            issue['vesting'] = _vesting(change['vesting'], issue['date'])
        reg['issuances'].append(issue)
        return reg
    if kind == 'pool':
        size = Decimal(str(change['size']))
        if size < sum(C.granted(reg).values(), Decimal('0')):
            raise ValueError("pool cannot be smaller than the options already granted")
        reg['pool']['size'] = float(size)
        return reg
    if kind in ('grant', 'safe', 'note'):
        step = {**change, 'type': kind}
        if kind == 'grant' and change.get('vesting'):
            step['vesting'] = _vesting(change['vesting'], change.get('date'))
        reg, _ = C.apply_steps(reg, [step])
        return reg
    raise ValueError(f"unknown change {kind}")


def _vesting(v, default_start=None):
    """Normalise a vesting block: dict, or text like '48/12' (months/cliff)."""
    if isinstance(v, str):
        months, _, cliff = v.partition('/')
        v = {'months': int(months or 48), 'cliff': int(cliff or 0)}
    out = {'start': str(v.get('start') or default_start or date.today().isoformat()),
           'months': int(v.get('months') or 48), 'cliff': int(v.get('cliff') or 0)}
    if out['months'] <= 0 or out['cliff'] < 0 or out['cliff'] > out['months']:
        raise ValueError("vesting needs months > 0 and 0 <= cliff <= months")
    return out


def exit_result(value, version=None, vested_only=False, on=None, entity_dir=None):
    """Waterfall for the current table or a version's end state."""
    from lib.waterfall import payout
    reg = load_register(entity_dir)
    if version:
        v = load_version(version, entity_dir)
        if not v:
            raise ValueError(f"no version {version}")
        reg, _ = version_result(v, entity_dir)
    return payout(reg, value, vested_only, on)


def version_result(version, entity_dir=None):
    base = load_register(entity_dir)
    reg, steps = C.apply_steps(base, version.get('steps') or [])
    return reg, steps


def compare(slugs, entity_dir=None):
    """Side-by-side end state of the current table and each version."""
    out = [{'slug': '', 'name': 'Current', 'groups': C.by_group(load_register(entity_dir)),
            **_end(load_register(entity_dir))}]
    for s in slugs:
        v = load_version(s, entity_dir)
        if not v:
            continue
        reg, steps = version_result(v, entity_dir)
        out.append({'slug': s, 'name': v.get('name', s), 'groups': C.by_group(reg), **_end(reg),
                    'raised': sum((st.get('investment', Decimal('0')) for st in steps), Decimal('0'))})
    return out


def _end(reg):
    t = C.table(reg)
    return {'price': t['price'], 'value': t['value'], 'fully_diluted': t['fully_diluted'],
            'open_instruments': len(t['instruments'])}


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _flags(rest):
    out, pos, i = {}, [], 0
    while i < len(rest):
        if rest[i].startswith('--') and i + 1 < len(rest) and not rest[i + 1].startswith('--'):
            out[rest[i][2:].replace('-', '_')] = rest[i + 1]
            i += 2
        elif rest[i].startswith('--'):
            out[rest[i][2:].replace('-', '_')] = True
            i += 1
        else:
            pos.append(rest[i])
            i += 1
    return out, pos


def _num(v):
    return float(Decimal(str(v).replace(',', '')))


def dispatch(args):
    flags, rest = parse_global_flags(args)
    if flags['help'] or (rest and rest[0] == 'help'):
        print_help()
        return
    action = rest[0] if rest else 'show'
    f, pos = _flags(rest[1:])
    if flags.get('date'):            # the global parser takes --date first
        f['date'] = flags['date']
    reg = load_register()
    try:
        if action == 'show':
            show_table(reg)
        elif action == 'holder' and pos:
            save_register(apply_change(reg, {'type': 'holder', 'name': ' '.join(pos), 'id': f.get('id'),
                                             'group': f.get('group', 'founder'), 'investor_type': f.get('investor_type'),
                                             'contact': f.get('contact')}))
            print(f"  Saved holder {' '.join(pos)}.")
        elif action == 'class' and pos:
            change = {'type': 'class', 'id': pos[0], 'name': f.get('name'), 'kind': f.get('kind')}
            for k in C.CLASS_TERMS:
                if f.get(k) is not None:
                    change[k] = f[k] if k == 'participating' else _num(f[k])
            save_register(apply_change(reg, change))
            cl = next(c for c in load_register()['classes'] if c['id'] == pos[0])
            print(f"  Class {cl['id']}: " + ', '.join(f"{k}={cl[k]}" for k in ('kind', *C.CLASS_TERMS) if k in cl))
        elif action == 'exit' and pos:
            show_exit(exit_result(_num(pos[0]), f.get('version'), bool(f.get('vested')), f.get('date')))
        elif action == 'issue' and len(pos) >= 2:
            save_register(apply_change(reg, {'type': 'issue', 'holder': pos[0], 'shares': _num(pos[1]),
                                             'class': f.get('class', 'common'), 'price': f.get('price', 0),
                                             'date': f.get('date'), 'vesting': f.get('vesting')}))
            print(f"  Issued {pos[1]} {f.get('class', 'common')} shares to {pos[0]}.")
        elif action == 'pool' and pos:
            save_register(apply_change(reg, {'type': 'pool', 'size': _num(pos[0])}))
            print(f"  Option pool set to {pos[0]}.")
        elif action == 'grant' and len(pos) >= 2:
            save_register(apply_change(reg, {'type': 'grant', 'holder': pos[0], 'shares': _num(pos[1]),
                                             'strike': f.get('strike'), 'date': f.get('date', date.today().isoformat()),
                                             'vesting': f.get('vesting')}))
            print(f"  Granted {pos[1]} options to {pos[0]}.")
        elif action in ('safe', 'note') and len(pos) >= 2:
            save_register(apply_change(reg, {'type': action, 'holder': pos[0], 'amount': _num(pos[1]),
                                             'cap': f.get('cap'), 'discount': f.get('discount'),
                                             'interest': f.get('interest'), 'date': f.get('date'),
                                             'post_money': f.get('post_money', action == 'safe') not in ('no', 'false', False)}))
            print(f"  Recorded {action} from {pos[0]}.")
        elif action == 'version':
            cmd_version(pos, f)
        elif action == 'compare':
            show_compare(compare(pos or list_versions()))
        else:
            print_help()
    except (ValueError, InvalidOperation, KeyError) as e:
        print(f"  {e}")
        sys.exit(1)


def cmd_version(pos, f):
    sub = pos[0] if pos else 'list'
    if sub == 'list':
        for s in list_versions():
            v = load_version(s)
            print(f"  {s:<20} {v.get('name', s):<28} {len(v.get('steps') or [])} step(s)")
        return
    if sub == 'new' and len(pos) >= 2:
        name = ' '.join(pos[1:])
        slug = slugify(name)
        if load_version(slug):
            raise ValueError(f"version {slug} exists")
        save_version(slug, {'name': name, 'steps': []})
        print(f"  Created version {slug}. Add steps with 'pair captable version step {slug} ...'.")
        return
    if sub == 'step' and len(pos) >= 2:
        slug, kind = pos[1], f.get('type', 'priced')
        v = load_version(slug)
        if not v:
            raise ValueError(f"no version {slug}")
        step = {'type': kind}
        for k in ('name', 'holder', 'date'):
            if f.get(k):
                step[k] = f[k]
        if f.get('pro_rata'):
            step['pro_rata'] = True
        if f.get('participating'):
            step['participating'] = f['participating'] not in ('no', 'false')
        for k in ('investment', 'pre_money', 'percent_sold', 'pool_target', 'amount', 'cap', 'discount',
                  'interest', 'shares', 'liq_pref', 'participation_cap', 'seniority'):
            if f.get(k) not in (None, True):
                step[k] = _num(f[k])
        if 'post_money' in f:
            step['post_money'] = f['post_money'] not in ('no', 'false')
        v.setdefault('steps', []).append(step)
        C.apply_steps(load_register(), v['steps'])     # validate before saving
        save_version(slug, v)
        show_version(slug)
        return
    if sub == 'show' and len(pos) >= 2:
        show_version(pos[1])
        return
    if sub == 'remove' and len(pos) >= 2:
        print(f"  {'Removed' if delete_version(pos[1]) else 'No version'} {pos[1]}.")
        return
    print_help()


def _pct(v):
    return f"{float(v) * 100:6.2f}%"


def show_table(reg):
    t = C.table(reg)
    co = get_active_entity() or 'entity'
    print(f"\n  [{co}] Cap table — fully diluted {float(t['fully_diluted']):,.0f} shares"
          + (f", last price {float(t['price']):.4f}" if t['price'] else '') + "\n")
    if not t['rows']:
        print("  No shares yet. Start with: pair captable holder \"Ana Diaz\" --group founder ; "
              "pair captable issue ana-diaz 4000000\n")
        return
    print(f"  {'Holder':<24} {'Group':<9} {'Shares':>14} {'Options':>12} {'Fully diluted':>14} {'%':>8} {'Unvested':>12}")
    for r in t['rows']:
        shares = sum(r['classes'].values(), Decimal('0'))
        print(f"  {r['name'][:24]:<24} {r['group']:<9} {float(shares):>14,.0f} {float(r['options']):>12,.0f} "
              f"{float(r['total']):>14,.0f} {_pct(r['pct']):>8} {float(r['unvested']) or 0:>12,.0f}")
    print(f"  {'Option pool (available)':<34} {'':>14} {'':>12} {float(t['pool_available']):>14,.0f} {_pct(t['pool_pct']):>8}")
    for i in t['instruments']:
        print(f"  Open {i['kind']}: {i['holder']} {i['amount']:,.0f}" + (f", cap {i['cap']:,.0f}" if i.get('cap') else '')
              + (f", discount {i['discount'] * 100:g}%" if i.get('discount') else '')
              + (' (post-money)' if i.get('post_money') else ''))
    print()


def show_exit(res):
    print(f"\n  Exit at {float(res['exit_value']):,.0f} — common price per share {float(res['price_per_share']):.4f}\n")
    if res['notes_repaid']:
        print(f"  Notes repaid first: {float(res['notes_repaid']):,.0f}")
    for c in res['classes']:
        print(f"  {c['name']:<24} {c['decision']:<28} {float(c['total']):>14,.0f}  (invested {float(c['invested']):,.0f})")
    print(f"\n  {'Holder':<24} {'Group':<9} {'Proceeds':>14} {'% of exit':>10} {'Multiple':>9}")
    for r in res['rows']:
        mult = f"{float(r['multiple']):.2f}x" if r['multiple'] is not None else ''
        print(f"  {r['name'][:24]:<24} {r['group']:<9} {float(r['proceeds']):>14,.0f} {float(r['pct']) * 100:>9.1f}% {mult:>9}")
    if abs(res['undistributed']) > 1:
        print(f"\n  Not distributed: {float(res['undistributed']):,.0f}")
    print("\n  Simplified: no dividends, escrow or carve-outs; options net-exercise; unallocated pool ignored.\n")


def show_version(slug):
    v = load_version(slug)
    if not v:
        raise ValueError(f"no version {slug}")
    reg, steps = version_result(v)
    print(f"\n  Version '{v.get('name', slug)}'\n")
    for s in steps:
        g = s['groups']
        extra = ''
        if 'price' in s:
            extra = (f"pre {float(s['pre_money']):,.0f}  post {float(s['post_money']):,.0f}  price {float(s['price']):.4f}"
                     f"  pool +{float(s['pool_increase']):,.0f}")
        elif 'investment' in s:
            extra = f"{float(s['investment']):,.0f}"
        print(f"  {s['name']:<22} {extra}")
        print(f"  {'':<22} founders {_pct(g['founder'])}  investors {_pct(g['investor'])}  "
              f"employees {_pct(g['employee'])}  pool {_pct(g['pool'])}")
    show_table(reg)


def show_compare(rows):
    print(f"\n  {'':<22}" + ''.join(f"{r['name'][:16]:>18}" for r in rows))
    for label, key in (('Founders', 'founder'), ('Investors', 'investor'), ('Employees', 'employee'),
                       ('Advisors', 'advisor'), ('Option pool', 'pool')):
        print(f"  {label:<22}" + ''.join(f"{_pct(r['groups'].get(key, 0)):>18}" for r in rows))
    print(f"  {'Price per share':<22}" + ''.join(f"{(float(r['price']) if r['price'] else 0):>18.4f}" for r in rows))
    print(f"  {'Post-money value':<22}" + ''.join(f"{(float(r['value']) if r['value'] else 0):>18,.0f}" for r in rows))
    print(f"  {'Raised in version':<22}" + ''.join(f"{float(r.get('raised', 0)):>18,.0f}" for r in rows))
    print()


def print_help():
    print("""pair captable — ownership and round versions   [captable pack]

  pair captable                                 current table (fully diluted)
  pair captable holder <name> [--group founder|employee|advisor|investor|other]
  pair captable issue <holder> <shares> [--class common] [--price P] [--date D]
  pair captable pool <size>                     options authorised
  pair captable grant <holder> <options> [--strike P]
  pair captable safe <holder> <amount> [--cap N] [--discount 0.2] [--post-money no]
  pair captable note <holder> <amount> [--cap N] [--discount 0.2] [--interest 0.08] [--date D]
      issue/grant also take --vesting 48/12 (months/cliff; starts on --date)
  pair captable holder <name> --group investor --investor-type angel [--contact slug]
  pair captable class <id> [--liq-pref 1] [--participating yes|no] [--participation-cap 3] [--seniority 2]
  pair captable exit <value> [--version slug] [--vested]      exit waterfall: who gets what

Versions (contemplated rounds, never change the real table):
  pair captable version new <name>
  pair captable version step <slug> --type priced --name Seed --investment 2000000 --pre-money 8000000 [--pool-target 0.1]
  pair captable version step <slug> --type priced --investment 6000000 --percent-sold 0.2 [--pro-rata]
               [--liq-pref 1 --participating yes --participation-cap 3 --seniority 2]
  pair captable version step <slug> --type safe --holder angels --amount 250000 --cap 5000000 [--discount 0.2]
  pair captable version step <slug> --type grant --holder dev --shares 50000
  pair captable version show <slug> | list | remove <slug>
  pair captable compare [slug ...]              founders / investors / pool side by side
""")
