"""pair profile — company profile (executive pack)."""

import sys

from lib.helpers import load_config, save_config, parse_global_flags, get_active_entity
from lib.profile import FIELDS, load, update


def dispatch(args):
    flags, rest = parse_global_flags(args)
    if flags['help'] or (rest and rest[0] == 'help'):
        print_help()
        return
    config = load_config()
    if not rest or rest[0] == 'show':
        show(config)
        return
    action = rest[0]
    try:
        if action == 'set' and len(rest) >= 3:
            update(config, {rest[1]: ' '.join(rest[2:])})
        elif action == 'unset' and len(rest) == 2:
            update(config, {rest[1]: None})
        elif action == 'link' and len(rest) >= 3:
            links = load(config)['links'] + [{'label': ' '.join(rest[1:-1]), 'url': rest[-1]}]
            update(config, {'links': links})
        elif action == 'unlink' and len(rest) >= 2:
            label = ' '.join(rest[1:])
            update(config, {'links': [l for l in load(config)['links'] if l['label'] != label]})
        else:
            print_help()
            return
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    save_config(config)
    show(config)


def show(config):
    p = load(config)
    name = config.get('pair', {}).get('name', get_active_entity() or '')
    print(f"\n  {name} — company profile ({p['status']})\n")
    for key, label, kind, _ in FIELDS:
        if key == 'status' or key not in p:
            continue
        v = p[key]
        if kind == 'percent':
            v = f"{float(v) * 100:g}%"
        elif kind == 'money':
            v = f"{float(v):,.0f}"
        elif isinstance(v, list):
            v = ', '.join(v)
        print(f"  {label:<26} {v}")
    for l in p['links']:
        print(f"  {'Link: ' + l['label']:<26} {l['url']}")
    print()


def print_help():
    keys = ', '.join(k for k, *_ in FIELDS)
    print(f"""pair profile — company profile   [executive pack]

  pair profile                       show
  pair profile set <field> <value>   e.g. set stage seed ; set founders "Ana, Raj"
  pair profile unset <field>
  pair profile link <label> <url>    add a link (pitch deck, data room…)
  pair profile unlink <label>

Fields: {keys}
""")
