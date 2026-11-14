"""Customer acquisition cost (CAC) from the books (I52).

A % of each report category counts as acquisition cost. The allocation lives
in config.yaml:

    cac_allocation:
      Marketing & Sales: 1.0
      Salaries & Benefits: 0.25

Unlisted categories count 0. Acquisition spend for a month is the allocated
share of that month's expenses from the books, summarised by report category
(lib.categories.summarise). The KPI `acquisition_spend` is ledger-fed from
here (a typed value still wins), so the existing derived
`cac = acquisition_spend / new_customers` is computed from the books.
No allocation configured means no feed and no behaviour change.
"""

from decimal import Decimal, InvalidOperation

from lib.categories import categories, summarise

ZERO = Decimal('0')


def allocation(config=None):
    """{category: fraction} from config, validated.

    Fractions must be numbers from 0 to 1; category names must be report
    categories (see lib.categories). Raises ValueError on bad config.
    """
    raw = (config or {}).get('cac_allocation') or {}
    if not isinstance(raw, dict):
        raise ValueError('cac_allocation must map report categories to fractions')
    known = set(categories(config))
    out = {}
    for name, fraction in raw.items():
        if name not in known:
            raise ValueError(f"cac_allocation: unknown report category '{name}'")
        try:
            f = Decimal(str(fraction))
        except InvalidOperation:
            raise ValueError(f"cac_allocation: '{name}' fraction must be a number")
        if f < 0 or f > 1:
            raise ValueError(f"cac_allocation: '{name}' fraction must be between 0 and 1")
        out[name] = f
    return out


def acquisition_spend(by_category, config=None):
    """Allocated acquisition spend from {category: amount} (pure)."""
    alloc = allocation(config)
    return sum((amount * alloc.get(name, ZERO) for name, amount in by_category.items()),
               ZERO)


def cac(spend, new_customers):
    """Acquisition spend per new customer, or None with no new customers."""
    if new_customers is None or new_customers == 0:
        return None
    return spend / Decimal(str(new_customers))


def monthly_expenses_by_category(journal, config=None, currency='CAD'):
    """{YYYY-MM: {category: expense}} from the books, via hledger.

    Raises RuntimeError if hledger fails (callers that feed the KPI grid
    catch it and report no feed). Returns {} with no journal.
    """
    from pathlib import Path
    from lib.runway import _tidy
    if not journal or not Path(journal).exists():
        return {}
    by_account = {}
    for r in _tidy([journal], ['^Expenses']):
        if r['commodity'] != currency:
            continue
        m = by_account.setdefault(r['start_date'][:7], {})
        m[r['account']] = m.get(r['account'], ZERO) + Decimal(r['value'].replace(',', ''))
    return {m: summarise(amounts, config) for m, amounts in sorted(by_account.items())}


def monthly_acquisition_spend(journal, config=None, currency='CAD'):
    """{YYYY-MM: allocated acquisition spend} from the books.

    {} with no allocation configured — the caller then feeds nothing.
    """
    if not allocation(config):
        return {}
    return {m: acquisition_spend(by_cat, config)
            for m, by_cat in monthly_expenses_by_category(journal, config, currency).items()}
