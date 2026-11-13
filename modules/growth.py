"""pair growth — acquisition channels, funnel, retention and unit economics (growth pack)."""

import sys
from decimal import Decimal

from lib.helpers import parse_global_flags
from lib import growth as G


def _require(slug):
    from modules.scenario import load_scenario
    meta = load_scenario(slug) if slug else None
    if meta is None:
        print(f"  Scenario '{slug}' not found. See 'pair scenario list'.")
        sys.exit(1)
    return meta


def _value(text):
    if ',' in text:
        return [float(x) for x in text.split(',') if x.strip()]
    try:
        return float(text) if '.' in text or text.isdigit() else text
    except ValueError:
        return text


def dispatch(args):
    flags, rest = parse_global_flags(args)
    if flags['help'] or not rest or rest[0] == 'help':
        print_help()
        return
    from modules.scenario import save_growth
    action, pos = rest[0], rest[1:]
    if action == 'channel' and len(pos) >= 2:      # channel add|remove <scenario> ...
        pos = [pos[1], pos[0]] + pos[2:]
    slug = pos[0] if pos else None
    meta = _require(slug)
    model = meta.get('growth')
    try:
        if action == 'init':
            if model and '--force' not in pos:
                print("  This scenario already has a growth model (use --force to replace it).")
                return
            save_growth(slug, G.template())
            print(f"  Started a growth model in '{slug}'. See it with 'pair growth show {slug}'.")
        elif action == 'show':
            if not model:
                print(f"  No growth model. Start one with 'pair growth init {slug}'.")
                return
            show(model)
        elif action == 'set' and len(pos) >= 3:
            model = model or G.template()
            target = model
            keys = pos[1].split('.')
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            target[keys[-1]] = _value(pos[2])
            if keys == ['months']:
                model['months'] = int(float(pos[2]))
            save_growth(slug, model)
            print(f"  {pos[1]} = {pos[2]}")
        elif action == 'channel' and len(pos) >= 2:
            sub = pos[1]
            model = model or G.template()
            if sub == 'add':
                ch, i = {}, 2
                while i < len(pos):
                    if pos[i].startswith('--') and i + 1 < len(pos):
                        ch[pos[i][2:].replace('-', '_')] = _value(pos[i + 1])
                        i += 2
                    else:
                        i += 1
                ch.setdefault('name', ch.get('type', 'channel'))
                model.setdefault('channels', []).append(ch)
                save_growth(slug, model)
                print(f"  Added channel {ch['name']}.")
            elif sub == 'remove' and len(pos) >= 3:
                name = ' '.join(pos[2:])
                model['channels'] = [c for c in model.get('channels') or [] if c.get('name') != name]
                save_growth(slug, model)
                print(f"  Removed channel {name}.")
            else:
                print_help()
        elif action == 'clear':
            save_growth(slug, None)
            print(f"  Removed the growth model from '{slug}'.")
        else:
            print_help()
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)


def _f(v, d=0):
    return '' if v is None else f"{float(v):,.{d}f}"


def show(model):
    rows, ue = G.run(model)
    print(f"\n  Growth model from {model.get('start')} for {model.get('months')} months\n")
    print(f"  {'Month':<8} {'Sign-ups':>9} {'New paying':>11} {'Paying':>9} {'Revenue':>11} {'Acq. spend':>11} "
          f"{'Sales':>9} {'Serve':>9} {'Contribution':>13}")
    for r in rows:
        print(f"  {r['month']:<8} {_f(r['signups']):>9} {_f(r['new_paying'], 1):>11} {_f(r['paying']):>9} "
              f"{_f(r['revenue']):>11} {_f(r['spend']):>11} {_f(r['sales_cost']):>9} {_f(r['serve']):>9} "
              f"{_f(r['contribution']):>13}")
    print(f"\n  Revenue per customer {_f(ue['arpu'], 2)}/month, gross margin {float(ue['gross_margin']) * 100:.0f}%, "
          f"expected lifetime {_f(ue['expected_lifetime_months'], 1)} months")
    print(f"  LTV {_f(ue['ltv'])}   CAC {_f(ue['cac'])}   LTV:CAC {_f(ue['ltv_cac'], 2)}   "
          f"payback {_f(ue['payback_months'], 1)} months")
    print(f"  End: {_f(ue['paying_end'])} paying, {_f(ue['mrr_end'])} monthly revenue; "
          f"contribution positive from {ue['contribution_positive_month'] or 'never in this window'}\n")
    print("  These lines feed the scenario (and runway) as revenue, acquisition spend and cost to serve.\n")


def print_help():
    print("""pair growth — growth engine for a scenario   [growth pack]

  pair growth init <scenario>                start a model (template)
  pair growth show <scenario>                month by month + LTV, CAC, payback
  pair growth set <scenario> <key> <value>   e.g. start 2027-01 | months 24 | funnel.activation 0.6
                                             funnel.paid_conversion 0.15 | retention 0.8,0.9,0.95
                                             revenue.expansion 0.01 | cost_to_serve 2.5
  pair growth channel add <scenario> --type paid|paid_cpa|viral|organic|sales|partners --name N ...
      paid:      --spend 2000 --spend-growth 0.05 --cpm 12 --ctr 0.02 --conversion 0.08
      paid_cpa:  --spend 1000 --cpa 15
      viral:     --invites 2 --invite-conversion 0.1
      organic:   --visitors 2000 --growth 0.08 --conversion 0.02
      sales:     --reps 1 --add-rep-every 6 --deals-per-rep 4 --ramp-months 3 --cost-per-rep 7000
      partners:  --partners 2 --new-partners 1 --users-per-partner 15
  pair growth channel remove <scenario> <name>
  pair growth clear <scenario>

The model's revenue, acquisition spend, sales cost and cost to serve become
scenario lines, so 'pair runway --scenario <scenario>' includes them.
""")
