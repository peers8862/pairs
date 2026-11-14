"""Stage bands (I53): date ranges (startup, seed, growth) to total spending
by company stage, from the books.

The bands live in config.yaml — there are no defaults, so nothing is
invented about the company's history:

    stage_bands:
      startup: {start: 2024-01, end: 2024-12}
      seed: {start: 2025-01, end: 2025-06}
      growth: {start: 2025-07}

An open band (no end) runs to the last month with spending in the books.
Spending is all Expenses:* postings in the band's months. Bands must not
overlap; bad months and start-after-end are rejected with ValueError.
"""

import re
from decimal import Decimal

from lib.runway import months_between

ZERO = Decimal('0')
_MONTH = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _check_month(value, name):
    if not isinstance(value, str) or not _MONTH.match(value):
        raise ValueError(f"stage_bands: {name} must be a YYYY-MM month, got {value!r}")
    return value


def bands(config=None):
    """[{name, start, end}] in config order; end is None for an open band."""
    raw = (config or {}).get('stage_bands') or {}
    if not isinstance(raw, dict):
        raise ValueError('stage_bands must map stage names to {start, end}')
    out = []
    for name, spec in raw.items():
        if not isinstance(spec, dict) or 'start' not in spec:
            raise ValueError(f"stage_bands: '{name}' needs a start month")
        start = _check_month(spec['start'], f"'{name}' start")
        end = spec.get('end')
        end = _check_month(end, f"'{name}' end") if end is not None else None
        if end is not None and end < start:
            raise ValueError(f"stage_bands: '{name}' ends before it starts")
        out.append({'name': name, 'start': start, 'end': end})
    for i, a in enumerate(out):
        for b in out[i + 1:]:
            if a['start'] <= (b['end'] or '9999-12') and b['start'] <= (a['end'] or '9999-12'):
                raise ValueError(f"stage_bands: '{a['name']}' and '{b['name']}' overlap")
    return out


def spending_by_band(monthly, config=None):
    """[{name, start, end, months, spending}] for {YYYY-MM: spending}.

    months is the number of calendar months in the band's span; an open band
    ends at the last month with spending (end None and months 0 when no
    spending falls after its start).
    """
    last = max(monthly) if monthly else None
    rows = []
    for band in bands(config):
        end = band['end'] or (last if last is not None and last >= band['start'] else None)
        if end is None:
            rows.append({**band, 'end': None, 'months': 0, 'spending': ZERO})
            continue
        span = months_between(band['start'], end)
        rows.append({**band, 'end': end, 'months': len(span),
                     'spending': sum((monthly.get(m, ZERO) for m in span), ZERO)})
    return rows


def monthly_spending(journal, config=None, currency='CAD'):
    """{YYYY-MM: total Expenses:*} from the books, via hledger.

    Raises RuntimeError if hledger fails. Returns {} with no journal.
    """
    from pathlib import Path
    from lib.runway import _tidy
    if not journal or not Path(journal).exists():
        return {}
    out = {}
    for r in _tidy([journal], ['^Expenses']):
        if r['commodity'] != currency:
            continue
        k = r['start_date'][:7]
        out[k] = out.get(k, ZERO) + Decimal(r['value'].replace(',', ''))
    return dict(sorted(out.items()))


def build(journal, config=None, currency='CAD'):
    """Stage bands with total spending from the books; [] with no bands."""
    return spending_by_band(monthly_spending(journal, config, currency), config)
