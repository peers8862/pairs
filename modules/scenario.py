"""pair scenario — what-if expenses kept outside the real books.

A scenario is a folder under the entity: scenarios/<slug>/ holding
scenario.yaml (name, description) and expenses.journal (dated entries tagged
scenario:<slug>). No include file ever references scenarios/, so real ledgers,
reports and totals never see these entries. Reports load the real journal and
the scenario journal together, so they show actuals, the scenario, and both.
"""

import calendar
import csv
import shutil
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

import yaml

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm, slugify,
    validate_slug, validate_date, validate_positive_number,
    parse_global_flags, get_entity_dir, get_active_entity, expand_path,
)
from lib.journal import format_entry
from modules.expense import CATEGORIES, CATEGORY_ACCOUNTS, PAYMENT_METHODS


SCENARIO_DIR_NAME = 'scenarios'
JOURNAL_NAME = 'expenses.journal'
META_NAME = 'scenario.yaml'


# ─── Paths ───────────────────────────────────────────────────────────────────

def scenario_dir(slug, entity_dir=None):
    return (entity_dir or get_entity_dir()) / SCENARIO_DIR_NAME / slug


def scenario_journal(slug, entity_dir=None):
    return scenario_dir(slug, entity_dir) / JOURNAL_NAME


def load_scenario(slug):
    path = scenario_dir(slug) / META_NAME
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f) or {}


def list_scenarios():
    root = get_entity_dir() / SCENARIO_DIR_NAME
    if not root.exists():
        return []
    return sorted(p.parent.name for p in root.glob(f'*/{META_NAME}'))


def real_journal(config):
    journal_file = config.get('journal_file')
    return expand_path(journal_file) if journal_file else None


# ─── Entries ─────────────────────────────────────────────────────────────────

def step_month(d, n, anchor_day):
    """Move d forward n months, keeping anchor_day where the month allows it."""
    m = d.month - 1 + n
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


FREQUENCIES = {'weekly': 0, 'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'annual': 12}
REVENUE_PREFIXES = ('Income', 'Revenue')
MAX_ENTRIES = 600


def is_revenue(account):
    return account.startswith(REVENUE_PREFIXES)


def occurrence_dates(start, every='monthly', repeat=None, months=None):
    """Dates for an item: `repeat` occurrences, or every occurrence before
    start + `months` months. Monthly-based steps keep the start day where the
    month allows it; weekly steps are 7 days."""
    if every not in FREQUENCIES:
        raise ValueError(f"every must be one of: {', '.join(FREQUENCIES)}")
    first = date.fromisoformat(start)
    step = FREQUENCIES[every]
    nth = (lambda i: first + timedelta(days=7 * i)) if step == 0 else \
          (lambda i: step_month(first, i * step, first.day))
    if months:
        end = step_month(first, int(months), first.day)
        dates = []
        while len(dates) < MAX_ENTRIES and nth(len(dates)) < end:
            dates.append(nth(len(dates)))
        return dates
    repeat = 1 if repeat is None else int(repeat)
    if not 1 <= repeat <= MAX_ENTRIES:
        raise ValueError(f"repeat must be between 1 and {MAX_ENTRIES}")
    return [nth(i) for i in range(repeat)]


def build_scenario_entries(slug, start, description, account, amount,
                           source_account, currency, repeat=None, pair='0000',
                           category=None, every='monthly', months=None):
    """Journal entries for one scenario item. An Income/Revenue account makes
    it revenue (money in to source_account); otherwise it is an expense."""
    value = float(money(amount))
    tags = {'pair': pair, 'scenario': slug}
    if category:
        tags['category'] = category
    if every != 'monthly' or months:
        tags['every'] = every
    sign = -1 if is_revenue(account) else 1
    postings = [(account, currency, sign * value), (source_account, currency, -sign * value)]
    return [format_entry(d.isoformat(), description, postings, tags)
            for d in occurrence_dates(start, every, repeat, months)]


# ─── hledger queries ─────────────────────────────────────────────────────────

def account_balances(files, query, begin=None, end=None, currency=None):
    """Balance per account for the given journal files and hledger query."""
    cmd = ['hledger']
    for f in files:
        cmd += ['-f', str(f)]
    cmd += ['bal', *query, '--flat', '--no-total', '--layout=bare', '-O', 'csv']
    if begin:
        cmd += ['-b', begin]
    if end:
        cmd += ['-e', end]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"hledger failed: {result.stderr.strip()}")
    balances = {}
    reader = csv.reader(StringIO(result.stdout))
    next(reader, None)
    for account, commodity, amount in reader:
        if currency and commodity != currency:
            continue
        balances[account] = balances.get(account, Decimal('0')) + Decimal(amount.replace(',', ''))
    return balances


def scenario_report_rows(real_file, scen_files, slug, begin=None, end=None,
                         currency=None):
    """Rows of (account, actual, scenario, actual + scenario) for expense and
    revenue accounts; revenue is shown as a positive amount. scen_files is a
    path or a list of paths (manual entries and rule entries)."""
    if isinstance(scen_files, (str, Path)):
        scen_files = [scen_files]
    scen_files = [f for f in scen_files if Path(f).exists()]
    real_exists = real_file is not None and Path(real_file).exists()
    files = ([real_file] if real_exists else []) + scen_files
    accounts = '^(Expenses|Income|Revenue)'
    actual = (account_balances([real_file], [accounts], begin, end, currency)
              if real_exists else {})
    planned = (account_balances(files, [accounts, f'tag:scenario={slug}'],
                                begin, end, currency)
               if scen_files else {})
    zero = Decimal('0')
    rows = []
    for acct in sorted(set(actual) | set(planned)):
        sign = -1 if is_revenue(acct) else 1
        a, p = sign * actual.get(acct, zero) + zero, sign * planned.get(acct, zero) + zero
        rows.append((acct, a, p, a + p))
    return rows


def report_window(start=None, months=None, year=None):
    """(begin, end) dates: start + months, a calendar year, or (None, None)."""
    if start or months:
        first = date.fromisoformat(start) if start else date(date.today().year, 1, 1)
        return first.isoformat(), step_month(first, int(months or 12), first.day).isoformat()
    if year:
        return f'{year}-01-01', f'{int(year) + 1}-01-01'
    return None, None


def find_scenario_includes(entity_dir, extra_files=()):
    """Journal files that pull scenario entries into the real books."""
    candidates = sorted((Path(entity_dir) / 'include').glob('*.journal'))
    candidates += [Path(f) for f in extra_files if f and Path(f).exists()]
    marker = f'{SCENARIO_DIR_NAME}/'
    return [p for p in candidates
            if any(line.strip().startswith('include') and marker in line
                   for line in p.read_text().splitlines())]


def warn_if_included(config):
    leaks = find_scenario_includes(get_entity_dir(), [real_journal(config)])
    for path in leaks:
        print(f"  WARNING: {path} includes scenario entries; real totals are wrong.")
    return leaks


# ─── Store (shared by the CLI and the web UI) ────────────────────────────────

def create_scenario(name, description=''):
    """Create scenarios/<slug>/ and return the slug. ValueError if invalid or taken."""
    slug = slugify(name or '')
    error = validate_slug(slug)
    if error:
        raise ValueError(f"Invalid name '{name}': {error}")
    if load_scenario(slug) is not None:
        raise ValueError(f"Scenario '{slug}' already exists")
    d = scenario_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    meta = {'name': name, 'slug': slug, 'description': description or '',
            'created': date.today().isoformat()}
    with open(d / META_NAME, 'w') as f:
        yaml.dump(meta, f, default_flow_style=False, sort_keys=False)
    (d / JOURNAL_NAME).touch()
    return slug


def add_entries(slug, entries):
    with open(scenario_journal(slug), 'a') as f:
        f.write(''.join(entries))
    for dep in dependents(slug):
        sync_rules_journal(dep)


def _entry_blocks(text):
    """Split a scenario journal into entries (blocks separated by blank lines)."""
    return [b for b in text.split('\n\n') if b.strip()]


def read_entries(slug):
    """Entries in file order: date, description, expense account and amount."""
    journal = scenario_journal(slug)
    text = journal.read_text() if journal.exists() else ''
    items = []
    for index, block in enumerate(_entry_blocks(text)):
        lines = [l for l in block.strip('\n').splitlines() if l.strip()]
        head = lines[0].split('  ;')[0]
        entry_date, _, description = head.partition(' * ')
        account, amount = '', Decimal('0')
        for line in lines[1:]:
            parts = line.strip().rsplit(None, 2)
            if len(parts) == 3 and parts[0].startswith(('Expenses',) + REVENUE_PREFIXES):
                account, amount = parts[0], abs(Decimal(parts[2]))
                break
        items.append({'index': index, 'date': entry_date.strip(),
                      'kind': 'revenue' if is_revenue(account) else 'expense',
                      'description': description.strip(),
                      'account': account, 'amount': amount})
    return items


def remove_entry(slug, index):
    """Delete the entry at index (as numbered by read_entries)."""
    from lib.journal import write_journal_atomic
    journal = scenario_journal(slug)
    blocks = _entry_blocks(journal.read_text())
    if not 0 <= index < len(blocks):
        raise IndexError(f"No entry {index} in scenario '{slug}'")
    del blocks[index]
    write_journal_atomic(journal, ''.join(b.strip('\n') + '\n\n' for b in blocks))


def delete_scenario(slug):
    shutil.rmtree(scenario_dir(slug))


# ─── Rules (one stored line per planned item; see lib/plan_rules.py) ─────────

RULES_JOURNAL = 'rules.journal'


def scenario_files(slug, entity_dir=None):
    """Journal files holding a scenario's entries (manual entries + rules)."""
    d = scenario_dir(slug, entity_dir)
    return [p for p in (d / JOURNAL_NAME, d / RULES_JOURNAL) if p.exists()]


def _plain(value):
    """YAML-safe copy of a rule value (Decimal -> float, date -> ISO)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if v not in (None, '')}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _save_meta(slug, meta):
    with open(scenario_dir(slug) / META_NAME, 'w') as f:
        yaml.dump(meta, f, default_flow_style=False, sort_keys=False)


def load_rules(slug):
    return list((load_scenario(slug) or {}).get('rules') or [])


def _cash_setup(config):
    config = config or load_config()
    return (config.get('pair', {}).get('currency', 'CAD'),
            config.get('accounts', {}).get('bank', 'Assets:Current:Chequing'))


def scenario_occurrences(slug, meta=None, _seen=None):
    """Dated amounts from a scenario's rules, its growth model and the
    scenarios it layers on top of (scenario.yaml `layers: [slug, ...]`)."""
    from lib.plan_rules import expand
    seen = set(_seen or ()) | {slug}
    meta = meta if meta is not None else (load_scenario(slug) or {})
    occ = expand(list(meta.get('rules') or []))
    if meta.get('growth'):
        from lib.growth import occurrences
        occ += occurrences(meta['growth'])
    for layer in meta.get('layers') or []:
        if layer in seen or load_scenario(layer) is None:
            continue
        for o in scenario_occurrences(layer, None, seen):
            occ.append({**o, 'rule': f"{layer}/{o['rule']}", 'layer': layer})
        for e in read_entries(layer):
            occ.append({'rule': f"{layer}/entry{e['index']}", 'name': e['description'], 'kind': e['kind'],
                        'account': e['account'], 'category': '', 'layer': layer,
                        'date': date.fromisoformat(e['date']), 'amount': e['amount']})
    return sorted(occ, key=lambda o: (o['date'], o['rule']))


def dependents(slug):
    """Scenarios that layer this one (directly)."""
    return [s for s in list_scenarios() if slug in ((load_scenario(s) or {}).get('layers') or [])]


def set_layers(slug, layers, config=None):
    """Set the scenarios this one builds on; refuses unknown slugs and cycles."""
    layers = [l for l in dict.fromkeys(layers or []) if l and l != slug]
    for l in layers:
        if load_scenario(l) is None:
            raise ValueError(f"No scenario '{l}'")

    def reaches(start, target, seen=()):
        for nxt in (load_scenario(start) or {}).get('layers') or []:
            if nxt == target or (nxt not in seen and reaches(nxt, target, seen + (nxt,))):
                return True
        return False
    for l in layers:
        if reaches(l, slug):
            raise ValueError(f"'{l}' already builds on '{slug}' (that would be a loop)")
    meta = load_scenario(slug) or {}
    if layers:
        meta['layers'] = layers
    else:
        meta.pop('layers', None)
    _save_meta(slug, meta)
    sync_rules_journal(slug, config)


def sync_rules_journal(slug, config=None, _done=None):
    """Regenerate rules.journal from the rules, growth model and layers in
    scenario.yaml, then the scenarios that layer this one."""
    from lib.plan_rules import journal_text
    from lib.journal import write_journal_atomic
    done = set(_done or ())
    if slug in done:
        return
    done.add(slug)
    currency, bank = _cash_setup(config)
    text = journal_text(slug, scenario_occurrences(slug), currency, bank)
    write_journal_atomic(scenario_dir(slug) / RULES_JOURNAL, text)
    for dep in dependents(slug):
        sync_rules_journal(dep, config, done)


def save_rules(slug, rules, config=None):
    meta = load_scenario(slug) or {}
    meta['rules'] = [_plain(r) for r in rules]
    _save_meta(slug, meta)
    sync_rules_journal(slug, config)


def add_rule(slug, rule, config=None):
    """Validate, give an id, store and regenerate. Returns the stored rule."""
    from lib.plan_rules import validate
    rule = _plain(dict(rule))
    problems = validate(rule)
    if problems:
        raise ValueError('; '.join(problems))
    rules = load_rules(slug)
    used = {r.get('id') for r in rules}
    n = len(rules) + 1
    while f'r{n}' in used:
        n += 1
    rule = {'id': f'r{n}', **{k: v for k, v in rule.items() if k != 'id'}}
    rules.append(rule)
    save_rules(slug, rules, config)
    return rule


def update_rule(slug, rule_id, changes, config=None):
    from lib.plan_rules import validate
    rules = load_rules(slug)
    for i, r in enumerate(rules):
        if r.get('id') == rule_id:
            merged = _plain({**r, **changes, 'id': rule_id})
            problems = validate(merged)
            if problems:
                raise ValueError('; '.join(problems))
            rules[i] = merged
            save_rules(slug, rules, config)
            return merged
    raise KeyError(rule_id)


def remove_rule(slug, rule_id, config=None):
    rules = load_rules(slug)
    kept = [r for r in rules if r.get('id') != rule_id]
    if len(kept) == len(rules):
        raise KeyError(rule_id)
    save_rules(slug, kept, config)


def scenario_monthly(slug, config=None):
    """Planned amounts by month: ({YYYY-MM: {revenue, expense, funding}},
    {YYYY-MM: {account: expense}}) from rules and manual entries."""
    from lib.plan_rules import month_key
    months, by_account = {}, {}

    def add(month, kind, account, amount):
        m = months.setdefault(month, {'revenue': Decimal('0'), 'expense': Decimal('0'),
                                      'funding': Decimal('0')})
        m[kind] += amount
        if kind == 'expense':
            a = by_account.setdefault(month, {})
            a[account] = a.get(account, Decimal('0')) + amount

    for o in scenario_occurrences(slug):
        add(month_key(o['date']), o['kind'], o['account'], o['amount'])
    for e in read_entries(slug):
        add(e['date'][:7], e['kind'], e['account'], e['amount'])
    return dict(sorted(months.items())), by_account


def save_growth(slug, model, config=None):
    """Store (or clear with None) the scenario's growth model and regenerate."""
    from lib.growth import validate
    if model is not None:
        problems = validate(model)
        if problems:
            raise ValueError('; '.join(problems))
    meta = load_scenario(slug) or {}
    if model is None:
        meta.pop('growth', None)
    else:
        meta['growth'] = _plain(model)
    _save_meta(slug, meta)
    sync_rules_journal(slug, config)


def scenario_to_budget(slug, year, name=None, activate=False, config=None):
    """Write a monthly budget for `year` from the scenario's planned expenses.

    Each expense account the scenario touches becomes a budget line with 12
    monthly amounts. Returns the budget slug."""
    from modules.budget import _generate_periods, _save_budget, _load_budget, _list_budgets
    meta = load_scenario(slug) or {}
    year = int(year)
    _, by_account = scenario_monthly(slug, config)
    accounts = sorted({a for m, accts in by_account.items() if m.startswith(f'{year}-') for a in accts})
    if not accounts:
        raise ValueError(f"The scenario has no planned expenses in {year}")
    lines = [{'account': a, 'amounts': [float(by_account.get(f'{year}-{m:02d}', {}).get(a, 0)) for m in range(1, 13)]}
             for a in accounts]
    bslug = slugify(f"{slug}-{year}")
    name = name or f"{meta.get('name', slug)} {year}"
    if activate:
        for other in _list_budgets():
            b = _load_budget(other)
            if b and str(b.get('year')) == str(year) and b.get('active') and other != bslug:
                b['active'] = False
                _save_budget(other, b)
    _save_budget(bslug, {'name': name, 'slug': bslug, 'year': str(year), 'scenario': 'custom',
                         'source_scenario': slug, 'period_type': 'monthly', 'active': bool(activate),
                         'periods': _generate_periods(year, 'monthly'), 'lines': lines})
    return bslug


def copy_scenario(slug, new_name, description=None):
    """New scenario with the same rules and manual entries."""
    meta = load_scenario(slug) or {}
    new_slug = create_scenario(new_name, description if description is not None
                               else meta.get('description', ''))
    src = scenario_journal(slug)
    if src.exists():
        scenario_journal(new_slug).write_text(src.read_text().replace(
            f'scenario:{slug}', f'scenario:{new_slug}'))
    if meta.get('growth'):
        save_growth(new_slug, meta['growth'])
    if meta.get('rules'):
        save_rules(new_slug, meta['rules'])
    return new_slug


def migrate_entries(slug, config=None):
    """Turn manual entries into rules: runs of the same description, account
    and amount at a regular monthly-based spacing become one rule. Returns
    the number of rules created; the manual journal is emptied."""
    entries = read_entries(slug)
    if not entries:
        return 0
    groups = []
    for e in entries:
        key = (e['description'], e['account'], e['amount'])
        if groups and groups[-1]['key'] == key:
            groups[-1]['dates'].append(e['date'])
        else:
            groups.append({'key': key, 'dates': [e['date']], 'kind': e['kind']})
    step_names = {v: k for k, v in FREQUENCIES.items() if v}
    rules = load_rules(slug)
    created = 0
    for g in groups:
        desc, account, amount = g['key']
        dates = [date.fromisoformat(d) for d in g['dates']]
        every = 'once'
        if len(dates) > 1:
            gaps = {(b.year - a.year) * 12 + b.month - a.month for a, b in zip(dates, dates[1:])}
            days = {(b - a).days for a, b in zip(dates, dates[1:])}
            if days == {7}:
                every = 'weekly'
            elif len(gaps) == 1 and gaps.pop() in step_names:
                every = step_names[(dates[1].year - dates[0].year) * 12 + dates[1].month - dates[0].month]
        if every == 'once' and len(dates) > 1:
            for d in dates:   # irregular: keep each as its own one-off rule
                rules.append({'name': desc, 'kind': g['kind'], 'account': account, 'driver': 'fixed',
                              'amount': float(amount), 'start': d.isoformat(), 'every': 'once'})
                created += 1
            continue
        rule = {'name': desc, 'kind': g['kind'], 'account': account, 'driver': 'fixed',
                'amount': float(amount), 'start': dates[0].isoformat(), 'every': every}
        if len(dates) > 1:
            rule['repeat'] = len(dates)
        rules.append(rule)
        created += 1
    used = {r.get('id') for r in rules}
    n = 1
    for r in rules:
        if not r.get('id'):
            while f'm{n}' in used:
                n += 1
            r['id'] = f'm{n}'
            used.add(r['id'])
    save_rules(slug, rules, config)
    scenario_journal(slug).write_text('')
    return created


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    flags, remaining = parse_global_flags(args)
    if not remaining or flags['help']:
        print_help()
        return
    action, action_args = remaining[0], remaining[1:]
    actions = {
        'new': cmd_new, 'list': cmd_list, 'add': cmd_add,
        'show': cmd_show, 'report': cmd_report, 'remove': cmd_remove,
        'rule': cmd_rule, 'rules': cmd_rule, 'copy': cmd_copy, 'migrate': cmd_migrate,
        'layer': cmd_layer, 'budget': cmd_budget, 'compare': cmd_compare,
    }
    if action not in actions:
        print(f"Unknown scenario action: {action}")
        print_help()
        sys.exit(1)
    actions[action](flags, action_args)


def print_help():
    print("""pair scenario — what-if expenses kept outside the real books

Scenario entries live in scenarios/<slug>/expenses.journal. Nothing includes
that folder, so real ledgers and totals never count them.

Actions:
  new <name>          Create a scenario
  list                List scenarios with item counts and totals
  add <slug>          Add a planned expense (optionally repeated monthly)
  show <slug>         List the scenario's entries
  report <slug>       Expenses per account: actual, scenario, actual + scenario
  remove <slug>       Delete a scenario and its entries
  rule add <slug>     Add a rule (one stored line; amounts worked out from its driver)
  rule list <slug>    List rules
  rule remove <slug> <id>
  copy <slug> <name>  New scenario with the same rules and entries
  migrate <slug>      Turn manual entries into rules
  layer <slug> [base ...]   Build on other scenarios (no names = clear), e.g. layer hire-editor base
  budget <slug> --year Y [--name N] [--activate]   Make a monthly budget from planned expenses
  compare [slug ...] [--replace] [--cash N] [--months N]   Side-by-side net, burn, runway (runway pack)

Rule flags ('rule add'):
  --name TEXT         What it is
  --kind KIND         expense | revenue | funding (default expense)
  --driver D          fixed | growth | step | percent | units | salary (default fixed)
  --amount NUM        Amount (fixed, growth, step)
  --rate F            growth: change per occurrence as a fraction (0.05 = +5%)
  --step DATE=AMOUNT  step: new amount from DATE (repeatable)
  --percent F         percent: share of revenue (0.029 = 2.9%)
  --of RULE           percent: of another rule's amount instead of revenue
  --units N --price P [--unit-growth F] [--unit-cost C]   units: units x price (+ cost)
  --salary N [--benefits F] [--raise F] [--setup-cost N]  salary: a hire
  --instrument I      funding: equity | safe | note | debt | grant
  --account ACCOUNT   Account (defaults by kind) ; --category NAME
  --start DATE --every FREQ (weekly..annual, once) and --end DATE | --months N | --repeat N

Flags for 'new':
  --desc TEXT         What the scenario is about

Flags for 'add':
  --batch             Non-interactive (requires --desc, --amount, --category or --account)
  --desc TEXT         Description
  --amount NUM        Amount per entry
  --category CAT      Expense category (same list as 'pair expense')
  --account ACCOUNT   Expense account, instead of --category
  --from METHOD       bank or credit-card
  --date DATE         First date (YYYY-MM-DD)
  --account ACCOUNT   An Income:/Revenue: account makes the item revenue
  --every FREQ        weekly | monthly | quarterly | semiannual | annual (default monthly)
  --repeat N          Number of occurrences (default 1)
  --months N          Or: every occurrence within N months of --date

Flags for 'report':
  --start DATE        Window start (with --months; default Jan 1 this year)
  --months N          Window length in months (default 12 with --start)
  --year YYYY         Or: one calendar year (default: all dates)
  --monthly           Month-by-month scenario expenses

Budgets: 'pair budget vs --scenario <slug> --full' compares a budget with
actuals plus the scenario for the whole year.
""")


def _flag(args, name, default=None):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _require(slug):
    if not slug or load_scenario(slug) is None:
        print(f"Scenario '{slug}' not found. See 'pair scenario list'.")
        sys.exit(1)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_new(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    name = positional[0] if positional else prompt("Scenario name")
    slug = slugify(name)
    error = validate_slug(slug)
    if error:
        print(f"  Invalid name '{name}': {error}")
        sys.exit(1)
    if load_scenario(slug) is not None:
        print(f"  Scenario '{slug}' already exists.")
        sys.exit(1)
    description = _flag(args, '--desc')
    if description is None and not flags.get('batch'):
        description = prompt("Description", required=False) or ''
    if flags.get('dry_run'):
        print(f"  Would create scenarios/{slug}/")
        return
    create_scenario(name, description or '')
    print(f"  Created scenario '{slug}' (scenarios/{slug}/)")


def cmd_list(flags, args):
    slugs = list_scenarios()
    if not slugs:
        print("  No scenarios. Create one with 'pair scenario new <name>'.")
        return
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    co = get_active_entity() or "entity"
    print(f"\n  [{co}] Scenarios\n")
    print(f"  {'Slug':<24} {'Items':>5} {'Total':>14}  Description")
    print(f"  {'─' * 72}")
    for slug in slugs:
        meta = load_scenario(slug) or {}
        files = scenario_files(slug)
        text = ''.join(f.read_text() for f in files)
        items = len(load_rules(slug)) + len(read_entries(slug))
        total = sum(account_balances(files, ['^Expenses'], currency=currency).values(),
                    Decimal('0')) if text.strip() else Decimal('0')
        print(f"  {slug:<24} {items:>5} {currency} {float(total):>10,.2f}  "
              f"{meta.get('description', '')}")
    print()


def cmd_add(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    if not slug and not flags.get('batch'):
        slug = prompt_choice("Scenario", list_scenarios() or ['(none)'])
    _require(slug)

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank_account = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

    description = _flag(args, '--desc')
    amount = _flag(args, '--amount')
    category = _flag(args, '--category')
    account = _flag(args, '--account')
    method = _flag(args, '--from')
    start = _flag(args, '--date') or flags.get('date')
    repeat = _flag(args, '--repeat')
    every = _flag(args, '--every', 'monthly')
    months = _flag(args, '--months')

    if flags.get('batch'):
        if not (description and amount and (category or account)):
            print("Batch mode requires: --desc, --amount, and --category or --account")
            sys.exit(1)
    else:
        print(f"Add a planned expense to '{slug}'\n")
        description = description or prompt("Description")
        amount = amount or prompt("Amount", validator=validate_positive_number)
        if not account:
            category = category or prompt_choice("Category", CATEGORIES)
        method = method or prompt_choice("Paid from", PAYMENT_METHODS, default='bank')
        start = start or prompt("First date", default=date.today().isoformat(),
                                validator=validate_date)
        if '--every' not in args:
            every = prompt_choice("How often", list(FREQUENCIES), default='monthly')
        if not (repeat or months):
            span = prompt("Occurrences, or Nm for N months (e.g. 3 or 12m)", default='1')
            months, repeat = (span[:-1], None) if span.endswith('m') else (None, span)

    start = start or date.today().isoformat()
    if validate_date(start):
        print(f"  Invalid date: {start}")
        sys.exit(1)
    if validate_positive_number(str(amount)):
        print(f"  Invalid amount: {amount}")
        sys.exit(1)
    try:
        repeat = int(repeat) if repeat else None
        months = int(months) if months else None
    except ValueError:
        print(f"  Invalid --repeat or --months: {repeat or months}")
        sys.exit(1)
    if not account:
        if category not in CATEGORY_ACCOUNTS:
            print(f"  Unknown category: {category}")
            sys.exit(1)
        account = CATEGORY_ACCOUNTS[category]

    if method == 'credit-card':
        source_account, pair = 'Liabilities:Current:Credit Card', '0001'
    else:
        source_account, pair = bank_account, '0000'

    try:
        entries = build_scenario_entries(slug, start, description, account, amount,
                                         source_account, currency, repeat, pair, category,
                                         every, months)
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    if flags.get('dry_run'):
        print(''.join(entries))
        return
    add_entries(slug, entries)
    warn_if_included(config)
    if not flags.get('quiet'):
        total = money(amount) * len(entries)
        print(f"\n  Added to scenario '{slug}': {description}")
        print(f"  {len(entries)} {every} entr{'y' if len(entries) == 1 else 'ies'} from {start}, "
              f"{currency} {total} in total, account {account}")
        print(f"  Written to: scenarios/{slug}/{JOURNAL_NAME} (not in the real books)")


def cmd_show(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    meta = load_scenario(slug) or {}
    print(f"\n  Scenario '{slug}': {meta.get('description', '')}\n", flush=True)
    files = scenario_files(slug)
    if not any(f.read_text().strip() for f in files):
        print("  No entries yet. Add one with 'pair scenario rule add' or 'pair scenario add'.")
        return
    cmd = ['hledger']
    for f in files:
        cmd += ['-f', str(f)]
    subprocess.run(cmd + ['reg', '^(Expenses|Income|Revenue|Equity|Liabilities)'])


def cmd_report(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    real = real_journal(config)
    journal = scenario_files(slug)
    year = _flag(args, '--year')
    begin, end = report_window(_flag(args, '--start'), _flag(args, '--months'), year)

    warn_if_included(config)
    co = get_active_entity() or "entity"
    span = f"{begin} to {end}" if begin else "all dates"

    if '--monthly' in args:
        print(f"\n  [{co}] Scenario '{slug}' by month ({span})\n", flush=True)
        files = ([real] if real and real.exists() else []) + journal
        cmd = ['hledger']
        for f in files:
            cmd += ['-f', str(f)]
        cmd += ['bal', '^(Expenses|Income|Revenue)', f'tag:scenario={slug}', '-M', '--flat']
        if begin:
            cmd += ['-b', begin, '-e', end]
        subprocess.run(cmd)
        return

    rows = scenario_report_rows(real, journal, slug, begin, end, currency)
    print(f"\n  [{co}] Scenario '{slug}' — expenses and revenue ({span})\n")
    print(f"  {'Account':<40} {'Actual':>13} {'Scenario':>13} {'Actual+Scn':>13}")
    print(f"  {'─' * 82}")
    totals = {'expense': [Decimal('0')] * 3, 'revenue': [Decimal('0')] * 3}
    for account, *amounts in rows:
        kind = 'revenue' if is_revenue(account) else 'expense'
        totals[kind] = [t + a for t, a in zip(totals[kind], amounts)]
        print(f"  {account:<40} " + " ".join(f"{float(a):>13,.2f}" for a in amounts))
    print(f"  {'─' * 82}")
    net = [r - e for r, e in zip(totals['revenue'], totals['expense'])]
    for label, values in (('Expenses', totals['expense']), ('Revenue', totals['revenue']),
                          ('Net (revenue - expenses)', net)):
        print(f"  {label + ' (' + currency + ')':<40} " + " ".join(f"{float(v):>13,.2f}" for v in values))
    print("\n  Real books unchanged: scenario entries are never included in them.\n")


def cmd_remove(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    d = scenario_dir(slug)
    if flags.get('dry_run'):
        print(f"  Would delete {d}")
        return
    if not flags.get('yes') and not confirm(f"Delete scenario '{slug}' and all its entries?",
                                            default_yes=False):
        print("  Cancelled.")
        return
    delete_scenario(slug)
    print(f"  Removed scenario '{slug}'.")


# ─── Rule commands ───────────────────────────────────────────────────────────

RULE_FLAGS = {
    '--name': 'name', '--kind': 'kind', '--driver': 'driver', '--account': 'account',
    '--category': 'category', '--amount': 'amount', '--rate': 'rate', '--percent': 'percent',
    '--of': 'of', '--units': 'units', '--price': 'price', '--unit-growth': 'unit_growth',
    '--unit-cost': 'unit_cost', '--salary': 'salary', '--benefits': 'benefits',
    '--raise': 'raise', '--setup-cost': 'setup_cost', '--instrument': 'instrument',
    '--start': 'start', '--every': 'every', '--end': 'end', '--months': 'months',
    '--repeat': 'repeat', '--round': 'round',
}
NUMERIC = {'amount', 'rate', 'percent', 'units', 'price', 'unit_growth', 'unit_cost', 'salary',
           'benefits', 'raise', 'setup_cost'}


def rule_from_args(args):
    rule, steps = {}, []
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--step' and i + 1 < len(args):
            d, _, amt = args[i + 1].partition('=')
            steps.append({'from': d, 'amount': float(amt)})
            i += 2
            continue
        if a in RULE_FLAGS and i + 1 < len(args):
            key, val = RULE_FLAGS[a], args[i + 1]
            if key in NUMERIC:
                val = float(val)
            elif key in ('months', 'repeat'):
                val = int(val)
            rule[key] = val
            i += 2
            continue
        i += 1
    if steps:
        rule['steps'] = steps
        rule.setdefault('driver', 'step')
    rule.setdefault('start', date.today().isoformat())
    return rule


def cmd_rule(flags, args):
    sub = args[0] if args else 'list'
    rest = args[1:]
    positional = [a for a in rest if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    from lib.plan_rules import describe
    if sub in ('list', 'ls'):
        rules = load_rules(slug)
        if not rules:
            print(f"  No rules in '{slug}'. Add one with 'pair scenario rule add {slug} --name ...'.")
            return
        print(f"\n  Rules in '{slug}'\n")
        for r in rules:
            off = ' (off)' if r.get('disabled') else ''
            print(f"  {r['id']:<5} {r.get('kind', 'expense'):<8} {r.get('name', ''):<28} {describe(r)}{off}")
        print()
        return
    if sub == 'add':
        rule = rule_from_args(rest)
        if flags.get('dry_run'):
            from lib.plan_rules import expand, validate
            problems = validate(rule)
            if problems:
                print('  ' + '; '.join(problems))
                return
            for o in expand([rule]):
                print(f"  {o['date']}  {o['kind']:<8} {o['account']:<40} {o['amount']:>12,.2f}")
            return
        try:
            stored = add_rule(slug, rule)
        except ValueError as e:
            print(f"  {e}")
            sys.exit(1)
        warn_if_included(load_config())
        print(f"  Added rule {stored['id']} to '{slug}': {stored.get('name', '')} — {describe(stored)}")
        return
    if sub in ('remove', 'rm') and len(positional) > 1:
        try:
            remove_rule(slug, positional[1])
        except KeyError:
            print(f"  No rule {positional[1]} in '{slug}'.")
            sys.exit(1)
        print(f"  Removed rule {positional[1]} from '{slug}'.")
        return
    print_help()


def cmd_copy(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    if len(positional) < 2:
        print("  Usage: pair scenario copy <slug> <new name>")
        sys.exit(1)
    _require(positional[0])
    try:
        new_slug = copy_scenario(positional[0], positional[1])
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    print(f"  Copied '{positional[0]}' to '{new_slug}'.")


def cmd_migrate(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    n = migrate_entries(slug)
    print(f"  Turned the manual entries of '{slug}' into {n} rule(s).")


def cmd_layer(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    try:
        set_layers(slug, positional[1:])
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    layers = (load_scenario(slug) or {}).get('layers') or []
    print(f"  '{slug}' builds on: {', '.join(layers) if layers else '(nothing)'}")


def cmd_budget(flags, args):
    positional = [a for a in args if not a.startswith('--')]
    slug = positional[0] if positional else None
    _require(slug)
    year = _flag(args, '--year', str(date.today().year + 1))
    try:
        b = scenario_to_budget(slug, year, _flag(args, '--name'), '--activate' in args)
    except ValueError as e:
        print(f"  {e}")
        sys.exit(1)
    print(f"  Wrote budgets/{b}.yaml from '{slug}' for {year}"
          + (" (active)" if '--activate' in args else '') + f". Compare with: pair budget vs --full")


def cmd_compare(flags, args):
    from lib.features import is_enabled, gate_message
    if not is_enabled('runway'):
        print(gate_message('runway'))
        sys.exit(1)
    from modules.runway import compare_scenarios
    slugs = [a for i, a in enumerate(args) if not a.startswith('--') and (i == 0 or args[i - 1] not in ('--cash', '--months'))]
    slugs = slugs or list_scenarios()
    cash = _flag(args, '--cash')
    rows = compare_scenarios(load_config(), slugs, int(_flag(args, '--months', 18)),
                             'replace' if '--replace' in args else 'add', Decimal(cash) if cash else None)
    print(f"\n  {'':<20}" + ''.join(f"{r['name'][:16]:>18}" for r in rows))
    def line(label, key, fmt=lambda v: f"{float(v):,.0f}"):
        print(f"  {label:<20}" + ''.join(f"{(fmt(r[key]) if r[key] is not None else '—')[:17]:>18}" for r in rows))
    line('Revenue', 'revenue'); line('Expenses', 'expense'); line('Net', 'net'); line('Funding in', 'funding')
    line('End cash', 'end_cash'); line('Lowest cash', 'lowest_cash'); line('Burn / month', 'burn')
    line('Runway (months)', 'runway', lambda v: f"{float(v):.1f}" if isinstance(v, (int, float, Decimal))
         else {'beyond the projection': 'beyond window', 'not burning cash': 'no burn'}.get(v, str(v)))
    line('Cash runs out', 'cash_out', str); line('Break-even', 'breakeven', str); line('Raise target', 'raise_target')
    print()
