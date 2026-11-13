"""KPIs — company, product and founder metrics beside the books.

Each metric has a definition (bucket, unit, kind, source) and monthly values.
Sources:

    manual    typed in (founder activity, users, pipeline…)
    ledger    filled automatically each month — from the books (revenue, expenses,
              cash…) or the investor pipeline (connections, meetings, conversions);
              a typed value wins, and with no feed the cell can be typed in
    derived   worked out from other metrics in the same month (formula)

Built-in definitions cover the usual early-stage set; an entity adds its own
in kpis/definitions.yaml. Values live in kpis/values.csv (metric, month, value,
note). Projections (kpis/projections.yaml) carry a metric or a whole bucket
forward from its last value by a growth factor — the "gearing" view.
"""

import ast
import csv
import operator
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

BUCKETS = [
    ('profile', 'Profile', 'Mostly static facts about the company and market'),
    ('financial', 'Financial (books)', 'Cash, revenue, costs, burn and runway'),
    ('unit', 'Unit economics', 'Recurring revenue, margins, acquisition cost and lifetime value'),
    ('usage', 'Customers & product usage', 'Users, activity, retention and satisfaction'),
    ('pipeline', 'Sales pipeline & traction', 'Contracts, letters of intent and sales speed'),
    ('marketing', 'Marketing & audience', 'Audience, leads and press'),
    ('fundraising', 'Fundraising', 'Round size, valuation and money committed'),
    ('momentum', 'Founder momentum', 'Activity counts that lead to outcomes'),
    ('delivery', 'Product delivery', 'Releases and milestones'),
    ('team', 'Team & operations', 'Headcount, hires and hours'),
    ('nondilutive', 'Non-dilutive & compliance', 'Grants, credits and filings'),
]

# id: (bucket, name, unit, source, formula/query, flow|stock|ratio)
_B = [
    ('revenue', 'financial', 'Revenue', 'money', 'ledger', 'revenue', 'flow'),
    ('cogs', 'financial', 'Cost of goods sold', 'money', 'ledger', 'cogs', 'flow'),
    ('expenses', 'financial', 'Total expenses', 'money', 'ledger', 'expenses', 'flow'),
    ('net_burn', 'financial', 'Net burn', 'money', 'derived', 'max(expenses - revenue, 0)', 'flow'),
    ('cash', 'financial', 'Cash balance', 'money', 'ledger', 'cash', 'stock'),
    ('runway_months', 'financial', 'Runway (months)', 'months', 'derived', 'cash / avg(net_burn, 3)', 'ratio'),
    ('net_revenue', 'financial', 'Net revenue', 'money', 'derived', 'revenue - cogs', 'flow'),
    ('mrr', 'unit', 'Monthly recurring revenue (MRR)', 'money', 'manual', '', 'stock'),
    ('arr', 'unit', 'Annual recurring revenue (ARR)', 'money', 'derived', '12 * mrr', 'stock'),
    ('new_mrr', 'unit', 'New MRR', 'money', 'manual', '', 'flow'),
    ('expansion_mrr', 'unit', 'Expansion MRR', 'money', 'manual', '', 'flow'),
    ('contraction_mrr', 'unit', 'Contraction MRR', 'money', 'manual', '', 'flow'),
    ('churned_mrr', 'unit', 'Churned MRR', 'money', 'manual', '', 'flow'),
    ('net_new_mrr', 'unit', 'Net new MRR', 'money', 'derived',
     'new_mrr + expansion_mrr - contraction_mrr - churned_mrr', 'flow'),
    ('revenue_growth_3m', 'unit', 'Revenue growth (3-mo avg, monthly)', 'percent', 'derived',
     'growth(revenue, 3)', 'ratio'),
    ('gross_margin', 'unit', 'Gross margin', 'percent', 'derived', '(revenue - cogs) / revenue', 'ratio'),
    ('net_margin', 'unit', 'Net margin', 'percent', 'derived', '(revenue - expenses) / revenue', 'ratio'),
    ('avg_sale_price', 'unit', 'Average sale price', 'money', 'derived', 'revenue / sales_count', 'ratio'),
    ('sales_count', 'unit', 'Sales (count)', 'count', 'manual', '', 'flow'),
    ('take_rate', 'unit', 'Take rate', 'percent', 'manual', '', 'ratio'),
    ('new_customers', 'unit', 'New paying customers', 'count', 'manual', '', 'flow'),
    ('acquisition_spend', 'unit', 'Acquisition spend', 'money', 'manual', '', 'flow'),
    ('cac', 'unit', 'Customer acquisition cost (CAC)', 'money', 'derived',
     'acquisition_spend / new_customers', 'ratio'),
    ('ltv', 'unit', 'Customer lifetime value (LTV)', 'money', 'manual', '', 'ratio'),
    ('ltv_cac', 'unit', 'LTV : CAC', 'ratio', 'derived', 'ltv / cac', 'ratio'),
    ('cac_payback_months', 'unit', 'CAC payback (months)', 'months', 'derived',
     'cac / (revenue / paying_customers * gross_margin)', 'ratio'),
    ('paying_customers', 'usage', 'Paying customers', 'count', 'manual', '', 'stock'),
    ('total_users', 'usage', 'Total users', 'count', 'manual', '', 'stock'),
    ('mau', 'usage', 'Monthly active users', 'count', 'manual', '', 'stock'),
    ('dau', 'usage', 'Daily active users', 'count', 'manual', '', 'stock'),
    ('dau_mau', 'usage', 'DAU / MAU', 'percent', 'derived', 'dau / mau', 'ratio'),
    ('user_growth_3m', 'usage', 'User growth (3-mo avg, monthly)', 'percent', 'derived',
     'growth(total_users, 3)', 'ratio'),
    ('retention_3m', 'usage', 'User retention (3 months)', 'percent', 'manual', '', 'ratio'),
    ('churn', 'usage', 'Churn (% per month)', 'percent', 'manual', '', 'ratio'),
    ('nps', 'usage', 'Net Promoter Score', 'score', 'manual', '', 'stock'),
    ('signups', 'usage', 'Sign-ups', 'count', 'manual', '', 'flow'),
    ('signed_contracts', 'pipeline', 'Signed contracts', 'count', 'manual', '', 'stock'),
    ('signed_value', 'pipeline', 'Annual value of signed contracts', 'money', 'manual', '', 'stock'),
    ('pipeline_contracts', 'pipeline', 'Contracts in pipeline', 'count', 'manual', '', 'stock'),
    ('pipeline_value', 'pipeline', 'Annual value of pipeline', 'money', 'manual', '', 'stock'),
    ('lois', 'pipeline', 'Letters of intent signed', 'count', 'manual', '', 'flow'),
    ('sales_cycle_days', 'pipeline', 'Average sales cycle (days)', 'days', 'manual', '', 'ratio'),
    ('newsletter', 'marketing', 'Newsletter subscribers', 'count', 'manual', '', 'stock'),
    ('open_rate', 'marketing', 'Email open rate', 'percent', 'manual', '', 'ratio'),
    ('click_rate', 'marketing', 'Email click-through rate', 'percent', 'manual', '', 'ratio'),
    ('mql', 'marketing', 'Marketing-qualified leads', 'count', 'manual', '', 'flow'),
    ('sql', 'marketing', 'Sales-qualified leads', 'count', 'manual', '', 'flow'),
    ('cost_per_lead', 'marketing', 'Cost per lead', 'money', 'derived', 'acquisition_spend / mql', 'ratio'),
    ('press', 'marketing', 'Press mentions', 'count', 'manual', '', 'flow'),
    ('referrals', 'marketing', 'Referrals', 'count', 'manual', '', 'flow'),
    ('round_size', 'fundraising', 'Current round size', 'money', 'manual', '', 'stock'),
    ('round_valuation', 'fundraising', 'Valuation / cap of current round', 'money', 'manual', '', 'stock'),
    ('round_committed', 'fundraising', 'Committed to current round', 'money', 'manual', '', 'stock'),
    ('funding_secured', 'fundraising', 'Funding secured this month', 'money', 'manual', '', 'flow'),
    ('investor_connections', 'momentum', 'Investor connections made', 'count', 'ledger', 'investor_connections', 'flow'),
    ('investor_meetings', 'momentum', 'Investor meetings held', 'count', 'ledger', 'investor_meetings', 'flow'),
    ('investors_converted', 'momentum', 'Investors converted', 'count', 'ledger', 'investors_converted', 'flow'),
    ('customer_interviews', 'momentum', 'Customer discovery interviews', 'count', 'manual', '', 'flow'),
    ('demos', 'momentum', 'Demos given', 'count', 'manual', '', 'flow'),
    ('intros', 'momentum', 'Partner / advisor intros', 'count', 'manual', '', 'flow'),
    ('applications', 'momentum', 'Applications submitted (grants, programs)', 'count', 'manual', '', 'flow'),
    ('releases', 'delivery', 'Releases shipped', 'count', 'manual', '', 'flow'),
    ('milestones', 'delivery', 'Milestones hit', 'count', 'manual', '', 'flow'),
    ('headcount', 'team', 'Headcount (FTE)', 'count', 'manual', '', 'stock'),
    ('hires', 'team', 'Hires made', 'count', 'manual', '', 'flow'),
    ('hours_logged', 'team', 'Hours logged', 'hours', 'manual', '', 'flow'),
    ('grants_applied', 'nondilutive', 'Grants applied for', 'money', 'manual', '', 'flow'),
    ('grants_awarded', 'nondilutive', 'Grants awarded', 'money', 'manual', '', 'flow'),
    ('filings_due', 'nondilutive', 'Filings due', 'count', 'manual', '', 'stock'),
]
BUILTIN = {i: {'id': i, 'bucket': b, 'name': n, 'unit': u, 'source': s, 'formula': f, 'type': t,
               'builtin': True}
           for i, b, n, u, s, f, t in _B}
UNITS = ('money', 'count', 'percent', 'ratio', 'months', 'days', 'hours', 'score', 'text')


# ─── Storage ─────────────────────────────────────────────────────────────────

def kpi_dir(entity_dir):
    return Path(entity_dir) / 'kpis'


def load_definitions(entity_dir):
    """Built-ins plus the entity's own (own entries can override a built-in)."""
    defs = {k: dict(v) for k, v in BUILTIN.items()}
    path = kpi_dir(entity_dir) / 'definitions.yaml'
    if path.exists():
        for d in (yaml.safe_load(path.read_text()) or []):
            if d.get('id'):
                defs[d['id']] = {**defs.get(d['id'], {}), **d, 'builtin': d['id'] in BUILTIN}
    return defs


def save_custom(entity_dir, definition):
    path = kpi_dir(entity_dir) / 'definitions.yaml'
    path.parent.mkdir(parents=True, exist_ok=True)
    items = (yaml.safe_load(path.read_text()) or []) if path.exists() else []
    items = [d for d in items if d.get('id') != definition['id']] + [definition]
    path.write_text(yaml.dump(items, default_flow_style=False, sort_keys=False))


def remove_custom(entity_dir, metric_id):
    path = kpi_dir(entity_dir) / 'definitions.yaml'
    if not path.exists():
        return False
    items = yaml.safe_load(path.read_text()) or []
    kept = [d for d in items if d.get('id') != metric_id]
    path.write_text(yaml.dump(kept, default_flow_style=False, sort_keys=False))
    return len(kept) != len(items)


def load_values(entity_dir):
    """{metric: {YYYY-MM: Decimal}} plus notes {(metric, month): note}."""
    path = kpi_dir(entity_dir) / 'values.csv'
    values, notes = {}, {}
    if not path.exists():
        return values, notes
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            try:
                values.setdefault(r['metric'], {})[r['month']] = Decimal(r['value'])
            except (InvalidOperation, KeyError):
                continue
            if r.get('note'):
                notes[(r['metric'], r['month'])] = r['note']
    return values, notes


def set_value(entity_dir, metric, month, value, note=None):
    """Write one value (None removes it). month is YYYY-MM."""
    path = kpi_dir(entity_dir) / 'values.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.exists():
        with open(path, newline='') as f:
            rows = [r for r in csv.DictReader(f) if not (r['metric'] == metric and r['month'] == month)]
    if value is not None and value != '':
        rows.append({'metric': metric, 'month': month, 'value': str(Decimal(str(value))),
                     'note': note or ''})
    rows.sort(key=lambda r: (r['metric'], r['month']))
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['metric', 'month', 'value', 'note'])
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load_projections(entity_dir):
    path = kpi_dir(entity_dir) / 'projections.yaml'
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def save_projection(entity_dir, key, growth):
    """key is a metric id or 'bucket:<id>'; growth is a monthly fraction (None removes)."""
    path = kpi_dir(entity_dir) / 'projections.yaml'
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_projections(entity_dir)
    if growth is None:
        data.pop(key, None)
    else:
        data[key] = {'growth': float(growth)}
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=True))


# ─── Formulas ────────────────────────────────────────────────────────────────

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class Missing(Exception):
    pass


def formula_names(formula):
    tree = ast.parse(formula, mode='eval')
    funcs = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - funcs


def evaluate(formula, lookup, month, months):
    """Evaluate a formula for one month. lookup(metric, month) -> Decimal or None.

    Supports + - * /, numbers, metric names, max(a, b), min(a, b),
    avg(metric, n) (mean of the last n months) and growth(metric, n)
    (average monthly growth over the last n months).
    """
    idx = months.index(month)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            v = lookup(node.id, month)
            if v is None:
                raise Missing(node.id)
            return v
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and b == 0:
                raise Missing('division by zero')
            return _OPS[type(node.op)](a, b)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn in ('max', 'min'):
                vals = [ev(a) for a in node.args]
                return max(vals) if fn == 'max' else min(vals)
            if fn in ('avg', 'growth') and len(node.args) == 2 and isinstance(node.args[0], ast.Name):
                name, n = node.args[0].id, int(node.args[1].value)
                window = months[max(0, idx - n + (1 if fn == 'avg' else 0)):idx + 1]
                vals = [lookup(name, m) for m in window]
                vals = [v for v in vals if v is not None]
                if fn == 'avg':
                    if not vals:
                        raise Missing(name)
                    return sum(vals) / len(vals)
                if len(vals) < 2 or vals[0] <= 0:
                    raise Missing(name)
                steps = len(vals) - 1
                return (vals[-1] / vals[0]) ** (Decimal(1) / steps) - 1 if vals[-1] > 0 else Decimal(-1)
        raise ValueError(f"unsupported formula: {ast.dump(node)[:60]}")

    return ev(ast.parse(formula, mode='eval'))


def check_formula(formula):
    """Return an error string or None."""
    try:
        evaluate(formula, lambda n, m: Decimal(1), '2000-01', ['1999-12', '2000-01'])
    except Missing:
        return None
    except (SyntaxError, ValueError, TypeError) as e:
        return str(e)
    return None


# ─── Grid ────────────────────────────────────────────────────────────────────

def project_value(last, growth, steps):
    return last * (1 + Decimal(str(growth))) ** steps


def grid(defs, values, ledger, months, projections=None, project_months=()):
    """Cell values for every metric and month.

    Returns {metric: {month: {'value': Decimal|None, 'kind': manual|ledger|derived|projected}}}.
    Ledger values come from `ledger` {query: {month: Decimal}}; derived values
    are worked out in dependency order; projected months extend the last known
    value by the metric's (or its bucket's) growth.
    """
    projections = projections or {}
    all_months = list(months) + [m for m in project_months if m not in months]
    out = {mid: {} for mid in defs}

    def lookup(mid, month):
        cell = out.get(mid, {}).get(month)
        if cell is not None:
            return cell['value']
        d = defs.get(mid)
        if not d:
            return None
        return _cell(mid, month)['value']

    computing = set()

    def _cell(mid, month):
        if month in out[mid]:
            return out[mid][month]
        d = defs[mid]
        cell = {'value': None, 'kind': d['source']}
        if month in project_months:
            cell = _projected(mid, month)
        elif d['source'] == 'ledger':
            v = ledger.get(d.get('formula') or mid, {}).get(month)
            manual = values.get(mid, {}).get(month)
            cell = {'value': manual if manual is not None else v,
                    'kind': 'manual' if manual is not None else 'ledger'}
        elif d['source'] == 'derived' and d.get('formula'):
            manual = values.get(mid, {}).get(month)
            if manual is not None:
                cell = {'value': manual, 'kind': 'manual'}
            elif (mid, month) not in computing:
                computing.add((mid, month))
                try:
                    cell = {'value': evaluate(d['formula'], lookup, month, all_months), 'kind': 'derived'}
                except (Missing, ArithmeticError, ValueError):
                    cell = {'value': None, 'kind': 'derived'}
                computing.discard((mid, month))
        else:
            cell = {'value': values.get(mid, {}).get(month), 'kind': 'manual'}
        out[mid][month] = cell
        return cell

    def _projected(mid, month):
        d = defs[mid]
        rule = projections.get(mid) or projections.get(f"bucket:{d['bucket']}")
        if d['source'] == 'derived' and d.get('formula') and not projections.get(mid):
            try:
                return {'value': evaluate(d['formula'], lookup, month, all_months), 'kind': 'projected'}
            except (Missing, ArithmeticError, ValueError):
                return {'value': None, 'kind': 'projected'}
        if not rule:
            return {'value': None, 'kind': 'projected'}
        known = [(m, _cell(mid, m)['value']) for m in months]
        known = [(m, v) for m, v in known if v is not None]
        if not known:
            return {'value': None, 'kind': 'projected'}
        last_m, last_v = known[-1]
        steps = all_months.index(month) - all_months.index(last_m)
        return {'value': project_value(last_v, rule.get('growth', 0), steps), 'kind': 'projected'}

    for mid in defs:
        for m in all_months:
            _cell(mid, m)
    return out
