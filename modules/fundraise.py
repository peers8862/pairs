"""pair round / pair investor — rounds, investor pipeline and commitments (captable pack)."""

import sys
from datetime import date
from decimal import Decimal

import yaml

from lib.helpers import load_config, parse_global_flags, get_entity_dir, get_active_entity, slugify
from lib import fundraising as F


# ─── Store ───────────────────────────────────────────────────────────────────

def _path(name, entity_dir=None):
    return (entity_dir or get_entity_dir()) / 'fundraising' / f'{name}.yaml'


def _load(name, entity_dir=None):
    p = _path(name, entity_dir)
    return list(yaml.safe_load(p.read_text()) or []) if p.exists() else []


def _save(name, items, entity_dir=None):
    p = _path(name, entity_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(yaml.dump(items, default_flow_style=False, sort_keys=False))
    tmp.replace(p)


def load_rounds(entity_dir=None):
    return _load('rounds', entity_dir)


def load_deals(entity_dir=None):
    return _load('pipeline', entity_dir)


def save_rounds(items, entity_dir=None):
    _save('rounds', items, entity_dir)


def save_deals(items, entity_dir=None):
    _save('pipeline', items, entity_dir)


def _unique(base, used):
    slug, n = base, 2
    while slug in used:
        slug, n = f'{base}-{n}', n + 1
    return slug


def _clean(d):
    out = {}
    for k, v in d.items():
        if v in (None, ''):
            continue
        out[k] = float(v) if isinstance(v, Decimal) else v
    return out


def add_round(data, entity_dir=None):
    rounds = load_rounds(entity_dir)
    if not data.get('name'):
        raise ValueError("A round needs a name")
    if data.get('type', 'seed') not in F.ROUND_TYPES:
        raise ValueError(f"type must be one of {', '.join(F.ROUND_TYPES)}")
    if data.get('instrument', 'equity') not in F.INSTRUMENTS:
        raise ValueError(f"instrument must be one of {', '.join(F.INSTRUMENTS)}")
    rid = _unique(slugify(data['name']), {r['id'] for r in rounds})
    r = _clean({'id': rid, 'name': data['name'], 'type': data.get('type', 'seed'),
                'instrument': data.get('instrument', 'equity'), 'status': data.get('status', 'planned'),
                **{k: data.get(k) for k in ('target', 'close_date', 'pre_money', 'price', 'cap', 'discount',
                                            'interest', 'post_money', 'notes')}})
    rounds.append(r)
    save_rounds(rounds, entity_dir)
    return r


def update_round(rid, changes, entity_dir=None):
    rounds = load_rounds(entity_dir)
    for r in rounds:
        if r['id'] == rid:
            r.update({k: v for k, v in changes.items() if k != 'id'})
            for k in [k for k, v in r.items() if v in (None, '')]:
                r.pop(k)
            save_rounds(rounds, entity_dir)
            return r
    raise KeyError(rid)


def add_deal(data, entity_dir=None, config=None):
    deals = load_deals(entity_dir)
    if not data.get('investor'):
        raise ValueError("An investor name is needed")
    stage = data.get('stage') or F.stages(config)[0]
    did = _unique(slugify(data['investor']), {d['id'] for d in deals})
    today = date.today().isoformat()
    deal = _clean({'id': did, 'investor': data['investor'], 'created': today,
                   **{k: data.get(k) for k in ('email', 'organization', 'investor_type', 'referral', 'round',
                                               'amount', 'first_meeting', 'last_meeting', 'next_step')}})
    deal['stage'] = None
    F.set_stage(deal, stage, data.get('first_meeting') or today, config)
    deal['notes'] = []
    if data.get('create_contact') or data.get('contact'):
        try:
            c = link_contact({**deal, 'contact': data.get('contact')}, create=bool(data.get('create_contact')))
            if c:
                deal['contact'] = c
        except Exception:          # contacts are optional; the deal still saves
            pass
    deals.append(deal)
    save_deals(deals, entity_dir)
    return deal


def update_deal(did, changes, entity_dir=None, config=None):
    deals = load_deals(entity_dir)
    for d in deals:
        if d['id'] == did:
            if changes.get('stage') and changes['stage'] != d.get('stage'):
                F.set_stage(d, changes['stage'], changes.get('date'), config)
            for k, v in changes.items():
                if k in ('stage', 'date', 'id', 'history', 'notes'):
                    continue
                if v in (None, ''):
                    d.pop(k, None)
                else:
                    d[k] = v
            if changes.get('note'):
                d.setdefault('notes', []).append({'date': changes.get('date') or date.today().isoformat(),
                                                  'text': changes['note'], 'meeting': bool(changes.get('meeting'))})
                d.pop('note', None)
                d.pop('meeting', None)
                if changes.get('meeting'):
                    d['last_meeting'] = changes.get('date') or date.today().isoformat()
            save_deals(deals, entity_dir)
            return d
    raise KeyError(did)


def link_contact(deal, create=False):
    """Find or create a contacts/ record (role investor) for a deal. Returns the slug."""
    from lib.yaml_store import load_entity, save_entity, list_entities
    slug = deal.get('contact') or slugify(deal['investor'])
    existing = load_entity('contacts', slug)
    if existing:
        return slug
    if not create:
        for other in list_entities('contacts'):
            c = load_entity('contacts', other) or {}
            if deal.get('email') and c.get('email') == deal.get('email'):
                return other
        return None
    data = {'name': deal['investor'], 'slug': slug, 'role': 'investor'}
    if deal.get('email'):
        data['email'] = deal['email']
    if deal.get('organization'):
        data['pair'] = deal['organization']
    if deal.get('investor_type'):
        data['notes'] = f"Investor type: {deal['investor_type']}"
    save_entity('contacts', slug, data)
    return slug


def updates_list(entity_dir=None):
    """Everyone talked to (including those who passed), for progress updates."""
    out = []
    for d in load_deals(entity_dir):
        notes = d.get('notes') or []
        last_contact = max([n.get('date', '') for n in notes if n.get('text') != 'Progress update sent']
                           + [d.get('last_meeting') or '', d.get('first_meeting') or '', d.get('created') or ''])
        out.append({'id': d['id'], 'investor': d['investor'], 'email': d.get('email', ''),
                    'organization': d.get('organization', ''), 'stage': d.get('stage', ''),
                    'round': d.get('round', ''), 'last_contact': last_contact,
                    'last_update': d.get('last_update', ''), 'updates_off': bool(d.get('updates_off'))})
    return sorted(out, key=lambda x: (x['updates_off'], x['last_update'] or '', x['investor']))


def mark_update_sent(ids, on=None, entity_dir=None):
    on = on or date.today().isoformat()
    deals = load_deals(entity_dir)
    n = 0
    for d in deals:
        if not ids or d['id'] in ids:
            if d.get('updates_off'):
                continue
            d['last_update'] = on
            d.setdefault('notes', []).append({'date': on, 'text': 'Progress update sent', 'meeting': False})
            n += 1
    save_deals(deals, entity_dir)
    return n


def remove_deal(did, entity_dir=None):
    deals = load_deals(entity_dir)
    kept = [d for d in deals if d['id'] != did]
    if len(kept) == len(deals):
        raise KeyError(did)
    save_deals(kept, entity_dir)


def receive(did, on=None, config=None, entity_dir=None, write=True):
    """Money from a commitment arrived: write the cash entry in the books and the
    cap-table change, and move the deal to the last stage. Returns a summary."""
    from lib.journal import format_entry, append_journal, ensure_year_structure, get_generated_dir
    from modules.captable import load_register, save_register, apply_change
    config = config or load_config()
    on = on or date.today().isoformat()
    deal = next((d for d in load_deals(entity_dir) if d['id'] == did), None)
    if not deal:
        raise KeyError(did)
    if deal.get('received'):
        raise ValueError(f"{did} was already recorded as received on {deal['received']}")
    round_ = next((r for r in load_rounds(entity_dir) if r['id'] == deal.get('round')), None)
    if not round_:
        raise ValueError("Link the commitment to a round first (its instrument decides the accounts)")
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')
    currency = config.get('pair', {}).get('currency', 'CAD')
    postings, tags, desc = F.funding_entry(deal, round_, bank, currency, on)
    entry = format_entry(on, desc, postings, tags)
    step = F.captable_step(deal, round_, on)
    if step:
        for k in ('investor_type', 'contact'):
            if deal.get(k):
                step[k] = deal[k]
    summary = {'entry': entry, 'captable': step, 'journal': f"generated/{on[:4]}/equity.journal"}
    if not write:
        return summary
    ensure_year_structure(int(on[:4]))
    append_journal(get_generated_dir() / on[:4] / 'equity.journal', entry)
    if step:
        reg = load_register(entity_dir)
        reg = apply_change(reg, step)
        save_register(reg, entity_dir)
    update_deal(did, {'stage': F.stages(config)[-1], 'date': on, 'received': on}, entity_dir, config)
    return summary


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _flags(rest):
    from modules.captable import _flags as f
    return f(rest)


def dispatch(args):
    """Entry for both `pair round` and `pair investor` (MODULE_MAP points both here)."""
    command = sys.argv[1] if len(sys.argv) > 1 else 'round'
    flags, rest = parse_global_flags(args)
    if flags['help'] or (rest and rest[0] == 'help'):
        print_help()
        return
    config = load_config()
    action = rest[0] if rest else 'list'
    f, pos = _flags(rest[1:])
    if flags.get('date'):            # the global parser takes --date first
        f['date'] = flags['date']
    try:
        if command == 'round':
            round_cmd(action, f, pos, config)
        else:
            investor_cmd(action, f, pos, config, flags)
    except (ValueError, KeyError) as e:
        print(f"  {e}")
        sys.exit(1)


def _money(v):
    return f"{float(v):,.0f}"


def round_cmd(action, f, pos, config):
    if action == 'list':
        deals = load_deals()
        rounds = load_rounds()
        if not rounds:
            print("  No rounds. Add one: pair round add \"Pre-seed 2027\" --type pre-seed --instrument safe --target 500000")
            return
        print(f"\n  {'Round':<24} {'Type':<9} {'Instr.':<7} {'Status':<8} {'Target':>12} {'Soft':>12} {'Signed':>12} {'Received':>12}")
        for r in rounds:
            p = F.progress(r, deals, config)
            print(f"  {r['name'][:24]:<24} {r.get('type', ''):<9} {r.get('instrument', ''):<7} {r.get('status', ''):<8} "
                  f"{_money(p['target']):>12} {_money(p['soft']):>12} {_money(p['signed']):>12} {_money(p['received']):>12}")
        print()
    elif action == 'add' and pos:
        data = {'name': ' '.join(pos), **{k: v for k, v in f.items() if v is not True}}
        for k in ('target', 'pre_money', 'price', 'cap', 'discount', 'interest'):
            if k in data:
                data[k] = float(str(data[k]).replace(',', ''))
        if 'post_money' in f:
            data['post_money'] = f['post_money'] not in ('no', 'false')
        r = add_round(data)
        print(f"  Added round {r['id']}.")
    elif action == 'set' and len(pos) >= 1:
        changes = {k: v for k, v in f.items() if v is not True}
        for k in ('target', 'pre_money', 'price', 'cap', 'discount', 'interest'):
            if k in changes:
                changes[k] = float(str(changes[k]).replace(',', ''))
        update_round(pos[0], changes)
        print(f"  Updated round {pos[0]}.")
    else:
        print_help()


def investor_cmd(action, f, pos, config, flags):
    if action == 'list':
        deals = load_deals()
        rnd = f.get('round')
        print(f"\n  {'Investor':<24} {'Org':<18} {'Round':<14} {'Stage':<20} {'Amount':>11}  Next step")
        for d in deals:
            if rnd and d.get('round') != rnd:
                continue
            print(f"  {d['investor'][:24]:<24} {d.get('organization', '')[:18]:<18} {d.get('round', '')[:14]:<14} "
                  f"{d.get('stage', ''):<20} {_money(d.get('amount') or 0):>11}  {d.get('next_step', '')}")
        print(f"\n  Stages: {' > '.join(F.stages(config))} (or {F.CLOSED_LOST})\n")
    elif action == 'add' and pos:
        data = {'investor': ' '.join(pos), **{k: v for k, v in f.items() if v is not True}}
        data['create_contact'] = bool(f.get('create_contact'))
        if 'amount' in data:
            data['amount'] = float(str(data['amount']).replace(',', ''))
        d = add_deal(data, config=config)
        print(f"  Added {d['investor']} ({d['id']}) at '{d['stage']}'.")
    elif action in ('stage', 'move') and len(pos) >= 2:
        d = update_deal(pos[0], {'stage': ' '.join(pos[1:]), 'date': f.get('date')}, config=config)
        print(f"  {d['investor']} is now at '{d['stage']}'.")
    elif action == 'set' and pos:
        changes = {k: v for k, v in f.items() if v is not True}
        if 'amount' in changes:
            changes['amount'] = float(str(changes['amount']).replace(',', ''))
        update_deal(pos[0], changes, config=config)
        print(f"  Updated {pos[0]}.")
    elif action in ('note', 'meeting') and len(pos) >= 2:
        update_deal(pos[0], {'note': ' '.join(pos[1:]), 'meeting': action == 'meeting', 'date': f.get('date')},
                    config=config)
        print(f"  {'Meeting' if action == 'meeting' else 'Note'} added for {pos[0]}.")
    elif action == 'receive' and pos:
        s = receive(pos[0], f.get('date'), config, write=not flags.get('dry_run'))
        print(("  Would write:\n" if flags.get('dry_run') else "  Recorded in the books:\n") + s['entry'])
        if s['captable']:
            print(f"  Cap table: {s['captable']['type']} for {s['captable']['holder']}")
        else:
            print("  Cap table: no change (equity round without a price; add the issuance with 'pair captable issue')")
    elif action == 'remove' and pos:
        remove_deal(pos[0])
        print(f"  Removed {pos[0]}.")
    elif action == 'updates':
        if f.get('sent'):
            n = mark_update_sent(pos, f.get('date'))
            print(f"  Marked an update sent to {n} investor(s).")
            return
        rows = updates_list()
        if f.get('emails'):
            print(', '.join(r['email'] for r in rows if r['email'] and not r['updates_off']))
            return
        print(f"\n  {'Investor':<24} {'Email':<28} {'Stage':<18} {'Last contact':<13} {'Last update':<12}")
        for r in rows:
            off = ' (no updates)' if r['updates_off'] else ''
            print(f"  {r['investor'][:24]:<24} {r['email'][:28]:<28} {r['stage'][:18]:<18} {r['last_contact']:<13} {r['last_update'] or '—':<12}{off}")
        print("\n  'pair investor updates --emails' prints the address list; '--sent' records an update for all\n"
              "  (or name ids). Keep people who passed: progress updates bring investors back later.\n")
    elif action == 'contact' and pos:
        deals = load_deals()
        d = next((x for x in deals if x['id'] == pos[0]), None)
        if not d:
            raise KeyError(pos[0])
        slug = link_contact(d, create=True)
        update_deal(pos[0], {'contact': slug}, config=config)
        print(f"  {d['investor']} linked to contact '{slug}' (role investor).")
    else:
        print_help()


def print_help():
    print("""pair round / pair investor — fundraising   [captable pack]

Rounds:
  pair round                                       rounds with target, soft, signed, received
  pair round add <name> --type seed --instrument safe|note|equity --target N
               [--close-date D] [--cap N] [--discount 0.2] [--interest 0.08] [--pre-money N] [--price P]
  pair round set <id> --status open|closed --target N ...

Investor pipeline:
  pair investor [--round R]                        list
  pair investor add <name> [--organization O] [--investor-type VC] [--referral R] [--create-contact]
                [--round R] [--amount N] [--first-meeting D] [--next-step TEXT]
  pair investor stage <id> <stage>                 1st call ... capital received, or passed
  pair investor meeting <id> <text> [--date D]     log a meeting (counts in KPIs)
  pair investor note <id> <text>
  pair investor set <id> --amount N --next-step TEXT ...
  pair investor contact <id>                       create/link a contact record (role investor)
  pair investor updates [--emails] [--sent [ids]]  everyone to send progress updates to
  pair investor receive <id> [--date D] [--dry-run]
        money arrived: writes the cash entry to the books AND the cap-table
        change (SAFE/note instrument, or shares at the round price)
""")
