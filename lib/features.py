"""Feature packs — optional groups of commands and web views.

The baseline (books, reports, contacts, budgets…) is always on. Extra packs
are switched on per install in global.yaml and can be overridden per entity
in that entity's config.yaml:

    # global.yaml (per install)
    features: [scenarios, runway]

    # entities/<slug>/config.yaml (per company; wins over global)
    features:
      captable: true
      runway: false
"""

from lib.helpers import load_global_config, save_global_config


PACKS = {
    'scenarios': {
        'title': 'Scenarios',
        'description': 'What-if expenses, revenue and funding kept outside the real books',
        'commands': ['scenario'],
    },
    'runway': {
        'title': 'Runway',
        'description': 'Cash, burn and runway from the books plus a scenario; raise planner',
        'commands': ['runway'],
        'requires': ['scenarios'],
    },
    'executive': {
        'title': 'Executive',
        'description': 'Company profile and company/product/founder metrics',
        'commands': ['profile', 'kpi'],
    },
    'captable': {
        'title': 'Cap table & fundraising',
        'description': 'Rounds, investor pipeline, commitments, cap table and versions',
        'commands': ['round', 'investor', 'captable'],
    },
    'growth': {
        'title': 'Growth',
        'description': 'Acquisition channels, funnel, cohort retention and unit economics',
        'commands': ['growth'],
        'requires': ['scenarios'],
    },
}


def _as_overrides(value):
    """Normalise a features value (list or mapping) to {pack: bool}."""
    if isinstance(value, dict):
        return {k: bool(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return {k: True for k in value}
    return {}


def resolve(global_cfg, entity_cfg=None):
    """Return {pack: enabled} for an install's global config and an entity config.

    Global sets the default for every entity; the entity's own `features`
    entries win. Packs whose required packs are off are off too.
    """
    state = {name: False for name in PACKS}
    for name, on in _as_overrides((global_cfg or {}).get('features')).items():
        if name in state:
            state[name] = on
    for name, on in _as_overrides((entity_cfg or {}).get('features')).items():
        if name in state:
            state[name] = on
    for name, pack in PACKS.items():
        if state[name] and not all(state.get(r) for r in pack.get('requires', [])):
            state[name] = False
    return state


# Web API roots owned by each pack (checked by the web middleware). A root
# matches itself and anything below it ("/api/scenario" covers
# "/api/scenario/x/rule" but not "/api/scenarios" — list each root).
# Baseline roots such as /api/metrics (dashboard) must never appear here.
PACK_PATHS = {
    '/api/scenario': 'scenarios', '/api/scenarios': 'scenarios',
    '/api/runway': 'runway',
    '/api/profile': 'executive', '/api/kpi': 'executive', '/api/kpis': 'executive',
    '/api/portrait': 'executive',
    '/api/round': 'captable', '/api/rounds': 'captable',
    '/api/investor': 'captable', '/api/investors': 'captable',
    '/api/captable': 'captable',
    '/api/growth': 'growth',
}


def pack_for_path(path):
    for root, name in PACK_PATHS.items():
        if path == root or path.startswith(root + '/'):
            return name
    return None


def pack_for_command(command):
    for name, pack in PACKS.items():
        if command in pack['commands']:
            return name
    return None


def _entity_config():
    from lib.helpers import get_config_file
    import yaml
    path = get_config_file()
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def enabled_packs():
    """Packs on for the active entity of this install."""
    return resolve(load_global_config(), _entity_config())


def describe():
    """Per pack: effective state, install setting and company override (None = inherit)."""
    g = _as_overrides(load_global_config().get('features'))
    e = _as_overrides(_entity_config().get('features'))
    state = resolve(load_global_config(), _entity_config())
    return [{'name': n, 'title': p['title'], 'description': p['description'],
             'requires': p.get('requires', []), 'enabled': state[n],
             'install': g.get(n, False), 'company': e.get(n)}
            for n, p in PACKS.items()]


def is_enabled(name):
    return enabled_packs().get(name, False)


def set_pack(name, on, scope='global'):
    """Switch a pack on/off in global.yaml or the active entity's config.yaml.

    Turning a pack on also turns on the packs it requires (same scope).
    """
    if name not in PACKS:
        raise KeyError(name)
    names = [name] + (PACKS[name].get('requires', []) if on else [])
    if on is None:
        names = [name]
    if scope == 'entity':
        from lib.helpers import save_config
        cfg = _entity_config()
        current = _as_overrides(cfg.get('features'))
        for n in names:
            if on is None:
                current.pop(n, None)  # inherit the install setting again
            else:
                current[n] = on
        cfg['features'] = current
        save_config(cfg)
        return
    cfg = load_global_config()
    current = [n for n, v in _as_overrides(cfg.get('features')).items() if v]
    for n in names:
        if on and n not in current:
            current.append(n)
        if not on and n in current:
            current.remove(n)
    cfg['features'] = current
    save_global_config(cfg)


def gate_message(name):
    return (f"The '{name}' pack is not enabled. "
            f"Turn it on with: pair features enable {name}   (add --entity for this company only)")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def dispatch(args):
    if not args or args[0] in ('list', 'ls'):
        cmd_list()
        return
    action, rest = args[0], args[1:]
    scope = 'entity' if '--entity' in rest else 'global'
    names = [a for a in rest if not a.startswith('--')]
    if action == 'inherit' and names:
        for n in names:
            set_pack(n, None, 'entity')
        print(f"This company now follows the install setting for {', '.join(names)}.")
        cmd_list()
        return
    if action in ('enable', 'disable', 'on', 'off') and names:
        on = action in ('enable', 'on')
        for n in names:
            if n not in PACKS:
                print(f"Unknown pack: {n}. Packs: {', '.join(PACKS)}")
                return
            set_pack(n, on, scope)
        where = 'this company' if scope == 'entity' else 'this install'
        print(f"{'Enabled' if on else 'Disabled'} {', '.join(names)} for {where}.")
        cmd_list()
        return
    print_help()


def cmd_list():
    state = enabled_packs()
    g = _as_overrides(load_global_config().get('features'))
    e = _as_overrides(_entity_config().get('features'))
    print("Feature packs (baseline is always on):\n")
    for name, pack in PACKS.items():
        mark = 'on ' if state[name] else 'off'
        src = 'company' if name in e else ('install' if name in g else 'default')
        req = f"  needs {', '.join(pack['requires'])}" if pack.get('requires') else ''
        print(f"  [{mark}] {name:<10} {pack['description']}  ({src}){req}")


def print_help():
    print("""pair features — optional feature packs

  pair features                     list packs and whether they are on
  pair features enable <pack>...    turn on for this install (global.yaml)
  pair features disable <pack>...   turn off for this install
  ... --entity                      only for the active company (config.yaml wins)
  pair features inherit <pack>...   drop the company override

Packs: """ + ', '.join(PACKS))


def prompt_packs():
    """Ask which packs to enable (used by pair init). Returns a list."""
    print("\nOptional feature packs (you can change these later with 'pair features'):")
    chosen = []
    for name, pack in PACKS.items():
        ans = input(f"  Enable {pack['title']} — {pack['description']}? [y/N]: ").strip().lower()
        if ans in ('y', 'yes'):
            chosen.append(name)
    for name in list(chosen):
        for r in PACKS[name].get('requires', []):
            if r not in chosen:
                chosen.append(r)
    return chosen
