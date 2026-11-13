"""Report categories — group ledger accounts into a few summary lines.

Defaults follow the usual startup cost budget (salaries, marketing, product,
legal & accounting, overhead). An entity can replace them in config.yaml:

    report_categories:
      Salaries & Benefits: [Expenses:Operating:Payroll]
      Marketing: [Expenses:Operating:Marketing, Expenses:Operating:Travel]

Each account goes to the first category whose prefix matches (longest prefix
wins); anything unmatched falls into the last category.
"""

DEFAULT_CATEGORIES = {
    'Salaries & Benefits': ['Expenses:Operating:Payroll', 'Expenses:Payroll', 'Expenses:Salaries'],
    'Marketing & Sales': ['Expenses:Operating:Marketing', 'Expenses:Operating:Meals and Entertainment',
                          'Expenses:Operating:Travel', 'Expenses:Marketing'],
    'Product & Materials': ['Expenses:Operating:Software Subscriptions', 'Expenses:COGS',
                            'Expenses:Cost of Goods Sold', 'Expenses:Product'],
    'Legal & Accounting': ['Expenses:Operating:Professional Fees', 'Expenses:Operating:Bank Fees'],
    'Overhead': ['Expenses'],
}


def categories(config=None):
    custom = (config or {}).get('report_categories')
    return custom if isinstance(custom, dict) and custom else DEFAULT_CATEGORIES


def category_for(account, config=None):
    """Name of the report category for an account."""
    cats = categories(config)
    best, best_len = None, -1
    for name, prefixes in cats.items():
        for p in prefixes or []:
            if (account == p or account.startswith(p + ':')) and len(p) > best_len:
                best, best_len = name, len(p)
    return best or list(cats)[-1]


def summarise(amounts, config=None):
    """{account: amount} -> {category: amount} in category order."""
    out = {name: 0 for name in categories(config)}
    for account, amount in amounts.items():
        name = category_for(account, config)
        out[name] = out.get(name, 0) + amount
    return out
