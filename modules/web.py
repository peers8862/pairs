"""pair web — PWA server for progressive entry assembly.

Starts a local FastAPI server serving the link-mode PWA.
"""

import sys
import os
import subprocess
import shlex
import webbrowser
from pathlib import Path
from datetime import date
from decimal import Decimal

# Ensure we can import from the project
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from lib.helpers import (
    load_config, money, parse_global_flags, get_active_entity, get_entity_dir
)
from lib.ui import get_entity_journal, get_entity_name, get_entity_currency, require_entity
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, get_generated_dir
)


# ─── Pair definitions (shared with dot.py / link.py) ─────────────────────────

PAIRS = {
    '<': {'num': 1, 'name': 'OpExp / Asset', 'desc': 'Paid operating expense',
          'first_filter': ['Assets:Current'], 'second_filter': ['Expenses:Operating'],
          'first_prompt': 'paid from?', 'second_prompt': 'for what?', 'first_is_credit': True},
    '>': {'num': 2, 'name': 'OpExp / Liability', 'desc': 'Expense on credit',
          'first_filter': ['Liabilities:Current', 'Liabilities:Credit'], 'second_filter': ['Expenses:Operating'],
          'first_prompt': 'charged to?', 'second_prompt': 'for what?', 'first_is_credit': True},
    '<<': {'num': 3, 'name': 'NonOpExp / Asset', 'desc': 'Amortization / write-down',
           'first_filter': ['Assets:Fixed', 'Assets:Accumulated'], 'second_filter': ['Expenses:Non-Operating'],
           'first_prompt': 'which asset?', 'second_prompt': 'expense type?', 'first_is_credit': True},
    '>>': {'num': 4, 'name': 'NonOpExp / Liability', 'desc': 'Interest accrued',
           'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current'], 'second_filter': ['Expenses:Non-Operating'],
           'first_prompt': 'which debt?', 'second_prompt': 'expense type?', 'first_is_credit': True},
    '<.': {'num': 5, 'name': 'OpIncome / Asset', 'desc': 'Revenue received',
           'first_filter': ['Assets:Current'], 'second_filter': ['Income:Operating'],
           'first_prompt': 'received into?', 'second_prompt': 'income type?', 'first_is_credit': False},
    '>.': {'num': 6, 'name': 'OpIncome / Liability', 'desc': 'Deferred revenue recognized',
           'first_filter': ['Liabilities:Current', 'Liabilities:Deferred'], 'second_filter': ['Income:Operating'],
           'first_prompt': 'from which liability?', 'second_prompt': 'income type?', 'first_is_credit': False},
    '<<.': {'num': 7, 'name': 'NonOpIncome / Asset', 'desc': 'Non-op income received',
            'first_filter': ['Assets:Current'], 'second_filter': ['Income:Non-Operating'],
            'first_prompt': 'received into?', 'second_prompt': 'income type?', 'first_is_credit': False},
    '>>.': {'num': 8, 'name': 'NonOpIncome / Liability', 'desc': 'Debt forgiveness',
            'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current'], 'second_filter': ['Income:Non-Operating'],
            'first_prompt': 'which liability?', 'second_prompt': 'income type?', 'first_is_credit': False},
    '<.>': {'num': 9, 'name': 'Asset / Liability', 'desc': 'Received loan proceeds',
            'first_filter': ['Assets:Current'], 'second_filter': ['Liabilities:Long-Term', 'Liabilities:Current'],
            'first_prompt': 'cash into?', 'second_prompt': 'which debt?', 'first_is_credit': False},
    '<..': {'num': 10, 'name': 'Asset / Equity', 'desc': 'Owner invested',
            'first_filter': ['Assets:Current', 'Assets:Fixed'], 'second_filter': ['Equity'],
            'first_prompt': 'received into?', 'second_prompt': 'equity type?', 'first_is_credit': False},
    '>..': {'num': 11, 'name': 'Liability / Equity', 'desc': 'Dividend declared',
            'first_filter': ['Equity'], 'second_filter': ['Liabilities:Current', 'Liabilities:Dividends'],
            'first_prompt': 'from equity?', 'second_prompt': 'to which liability?', 'first_is_credit': False},
    '..<': {'num': 12, 'name': 'Asset / Asset', 'desc': 'Internal transfer',
            'first_filter': ['Assets:Current', 'Assets:Fixed'], 'second_filter': ['Assets:Current', 'Assets:Fixed'],
            'first_prompt': 'receiving account?', 'second_prompt': 'sending account?', 'first_is_credit': False},
    '..>': {'num': 13, 'name': 'Liability / Liability', 'desc': 'Refinance / consolidate',
            'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current', 'Liabilities:Credit'],
            'second_filter': ['Liabilities:Long-Term', 'Liabilities:Current', 'Liabilities:Credit'],
            'first_prompt': 'old debt?', 'second_prompt': 'new debt?', 'first_is_credit': False},
    '..': {'num': 14, 'name': 'Equity / Equity', 'desc': 'Reclassify / year-end close',
           'first_filter': ['Equity'], 'second_filter': ['Equity'],
           'first_prompt': 'from bucket?', 'second_prompt': 'to bucket?', 'first_is_credit': False},
}

KNOWN_PREFIXES = [
    'Assets:Accumulated Amortization:',
    'Assets:Current:', 'Assets:Fixed:',
    'Liabilities:Long-Term:', 'Liabilities:Current:', 'Liabilities:',
    'Expenses:Non-Operating:', 'Expenses:Operating:',
    'Income:Non-Operating:', 'Income:Operating:',
    'Equity:',
]

# Sort priority: lower = appears first in autocomplete lists
PREFIX_SORT_ORDER = {
    'Assets:Current:': 10,
    'Assets:Fixed:': 20,
    'Assets:Accumulated Amortization:': 30,
    'Expenses:Operating:': 40,
    'Expenses:Non-Operating:': 50,
    'Income:Operating:': 60,
    'Income:Non-Operating:': 70,
    'Liabilities:Current:': 80,
    'Liabilities:Long-Term:': 90,
    'Liabilities:': 95,
    'Equity:': 100,
}

PREFIX_HINTS = {
    'Assets:Accumulated Amortization:': 'Accum Amort',
    'Assets:Current:': 'Current', 'Assets:Fixed:': 'Fixed',
    'Liabilities:Long-Term:': 'Long-Term', 'Liabilities:Current:': 'Current', 'Liabilities:': 'Liab',
    'Expenses:Non-Operating:': 'Non-Op', 'Expenses:Operating:': 'Op',
    'Income:Non-Operating:': 'Non-Op', 'Income:Operating:': 'Op',
    'Equity:': 'Equity',
}


# ─── Helper functions ────────────────────────────────────────────────────────

def _get_accounts():
    """Get account list from hledger."""
    journal = str(get_entity_journal())
    if not Path(journal).exists():
        alt = Path(journal).parent / 'company.journal'
        if alt.exists():
            journal = str(alt)
    try:
        result = subprocess.run(
            ['hledger', '-f', journal, 'accounts', '--flat'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return []
        accounts = [a.split(';')[0].strip() for a in result.stdout.strip().split('\n') if a.strip()]
        seen = set()
        return [a for a in accounts if not (a in seen or seen.add(a))]
    except Exception:
        return []


def _leaf_display(account):
    """Return (short_name, hint, sort_order) for an account."""
    for prefix in KNOWN_PREFIXES:
        if account.startswith(prefix):
            short = account[len(prefix):]
            hint = PREFIX_HINTS.get(prefix, '')
            sort_order = PREFIX_SORT_ORDER.get(prefix, 50)
            # Contra accounts: prefix to disambiguate from the asset they offset
            if 'Accumulated' in prefix or 'Allowance' in prefix or 'Depreciation' in prefix:
                # Use the category as prefix (e.g., "Amort: Equipment")
                category = prefix.rstrip(':').split(':')[-1]
                # Shorten common categories
                short_prefixes = {'Accumulated Amortization': 'Amort', 'Accumulated Depreciation': 'Depr', 'Allowance': 'Allow'}
                cat_short = short_prefixes.get(category, category)
                short = cat_short + ': ' + short
            return short, hint, sort_order
    return account, '', 50


def _filter_accounts(accounts, prefixes):
    """Filter accounts matching any prefix."""
    return [a for a in accounts if any(a.startswith(p) for p in prefixes)]


# ─── FastAPI app ─────────────────────────────────────────────────────────────

def create_app():
    """Create and configure the FastAPI application."""
    from fastapi import FastAPI, HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from pydantic import BaseModel

    app = FastAPI(title="Pairs", docs_url=None, redoc_url=None)

    static_dir = BASE_DIR / 'web' / 'static'

    # Serve static files
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ─── Models ──────────────────────────────────────────────────────────

    class EntryRequest(BaseModel):
        expr: str
        first_account: str
        second_account: str
        amount: float
        description: str = ''
        reversal: bool = False
        entry_date: str = ''

    class AssetRequest(BaseModel):
        name: str
        slug: str = ''
        category: str = 'equipment'
        purchase_date: str = ''
        cost: float = 0
        useful_life_months: int = 12
        amortization_method: str = 'straight-line'
        rate: float = 0.30
        salvage_value: float = 0
        description: str = ''
        payment_method: str = 'cash'
        linked_liability: str = ''

    class LiabilityRequest(BaseModel):
        name: str
        slug: str = ''
        type: str = 'loan'
        principal: float = 0
        interest_rate: float = 0
        term_months: int = 12
        start_date: str = ''
        payment_schedule: str = 'monthly'
        payment_amount: float = 0
        lender: str = ''
        description: str = ''

    class TransferRequest(BaseModel):
        amount: float
        from_account: str
        to_account: str
        date: str = ''
        description: str = ''

    class TaxRemitRequest(BaseModel):
        amount: float
        date: str = ''
        period: str = ''

    class ConfigRequest(BaseModel):
        name: str = ''
        currency: str = ''
        divisions: list = []

    class CommodityRequest(BaseModel):
        symbol: str
        name: str = ''
        source: str = ''
        fetch_pair: str = ''
        currency: str = ''
        type: str = ''
        sector: str = ''
        geography: str = ''
        strategy: str = ''
        risk: str = ''
        tax_account: str = ''
        tags: list = []

    class FetchRequest(BaseModel):
        symbol: str = ''
        days: int = 7
        tag: str = ''
        type: str = ''

    class EntryFields(BaseModel):
        """Structured entry fields. Serialization happens server-side via
        lib.entry.serialize_entry so there is exactly one serializer — a JS
        copy would risk reintroducing the two-space delimiter bug."""
        date: str = ''
        status: str = ''
        code: str = ''
        payee: str = ''
        note: str = ''
        tags: str = ''
        postings: list = []
        pair: str = ''
        # Raw escape hatch, mirroring the search box: hand-edited journal text
        # wins over the composed fields when raw is set.
        journal_text: str = ''
        raw: bool = False

    class BuyRequest(BaseModel):
        symbol: str
        qty: float
        price: float
        account: str = ''
        fee: float = 0.0
        fx: float = 1.0
        date: str = ''

    class SellRequest(BaseModel):
        symbol: str
        qty: float
        price: float
        account: str = ''
        fee: float = 0.0
        date: str = ''

    # ─── Routes ──────────────────────────────────────────────────────────

    @app.get("/")
    async def index():
        return FileResponse(str(BASE_DIR / 'web' / 'index.html'))

    @app.get("/manifest.json")
    async def manifest():
        return FileResponse(str(BASE_DIR / 'web' / 'manifest.json'))

    @app.get("/sw.js")
    async def service_worker():
        return FileResponse(str(BASE_DIR / 'web' / 'sw.js'), media_type='application/javascript')

    @app.get("/api/status")
    async def status():
        entity = get_active_entity()
        name = get_entity_name() if entity else None
        config = load_config() if entity else {}
        currency = config.get('pair', {}).get('currency', 'CAD')
        return {
            'entity': entity,
            'name': name,
            'currency': currency,
            'today': date.today().isoformat(),
        }

    @app.get("/api/pairs")
    async def pairs():
        return {k: {'num': v['num'], 'name': v['name'], 'desc': v['desc'],
                    'first_prompt': v['first_prompt'], 'second_prompt': v['second_prompt']}
                for k, v in PAIRS.items()}

    @app.get("/api/accounts")
    async def accounts(expr: str = ''):
        all_accounts = _get_accounts()
        if not all_accounts:
            raise HTTPException(status_code=404, detail="No accounts found")

        result = []
        for acct in all_accounts:
            short, hint, sort_order = _leaf_display(acct)
            result.append({'full': acct, 'short': short, 'hint': hint, 'sort': sort_order})

        # Sort: Fixed before Accum, Operating before Non-Operating
        result.sort(key=lambda a: a['sort'])

        if expr and expr in PAIRS:
            pair = PAIRS[expr]
            first = [a for a in result if any(a['full'].startswith(p) for p in pair['first_filter'])]
            second = [a for a in result if any(a['full'].startswith(p) for p in pair['second_filter'])]
            return {'all': result, 'first': first, 'second': second}

        return {'all': result, 'first': result, 'second': result}

    class AccountAddRequest(BaseModel):
        parent: str = ''
        name: str = ''

    @app.post("/api/account/add")
    async def add_account(req: AccountAddRequest):
        """Append an account declaration to include/accounts.journal."""
        import re
        parent = (req.parent or '').strip().strip(':')
        name = (req.name or '').strip().strip(':')
        if not parent or not name:
            raise HTTPException(status_code=400, detail="Parent and name are required")
        full = f"{parent}:{name}"
        # Allow letters, digits, spaces, &, -, and colons only
        if not re.fullmatch(r'[A-Za-z0-9 &:\-]+', full):
            raise HTTPException(status_code=400, detail="Invalid account name")

        type_map = {'Assets': 'A', 'Liabilities': 'L', 'Equity': 'E',
                    'Income': 'R', 'Revenue': 'R', 'Expenses': 'X'}
        acct_type = type_map.get(full.split(':')[0], 'A')

        accounts_file = get_entity_dir() / 'include' / 'accounts.journal'
        existing = accounts_file.read_text() if accounts_file.exists() else ''
        if re.search(rf'^account {re.escape(full)}\b', existing, re.M):
            return {'status': 'exists', 'full': full, 'message': f"'{full}' already declared"}

        from lib.journal import append_journal
        append_journal(accounts_file, f"account {full}  ; type:{acct_type}\n")
        return {'status': 'ok', 'full': full, 'type': acct_type, 'message': f"Added {full}"}

    @app.post("/api/entry")
    async def create_entry(req: EntryRequest):
        if req.expr not in PAIRS:
            raise HTTPException(status_code=400, detail=f"Unknown expression: {req.expr}")

        pair = PAIRS[req.expr]
        entry_date = req.entry_date or date.today().isoformat()
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        amount = money(req.amount)
        desc = req.description or req.second_account.split(':')[-1]

        # Determine debit/credit
        if pair['first_is_credit']:
            debit_account = req.second_account
            credit_account = req.first_account
        else:
            debit_account = req.first_account
            credit_account = req.second_account

        if req.reversal:
            debit_account, credit_account = credit_account, debit_account

        postings = [
            (debit_account, currency, float(amount)),
            (credit_account, currency, float(-amount)),
        ]

        tags = {'mode': 'link', 'pair': str(pair['num']), 'expr': req.expr}
        if req.reversal:
            tags['reversal'] = 'true'

        entry = format_entry(entry_date, desc, postings, tags)

        # Write
        year = entry_date[:4]
        ensure_year_structure(int(year))
        journal_path = get_generated_dir() / year / "links.journal"
        append_journal(journal_path, entry)

        # Ensure links.journal is included in the year file
        from lib.journal import get_include_dir
        include_dir = get_include_dir()
        year_include = include_dir / f"{year}.journal"
        if year_include.exists():
            include_line = f"include ../generated/{year}/links.journal"
            content = year_include.read_text()
            if include_line not in content:
                with open(year_include, 'a') as f:
                    f.write(f"\n{include_line}\n")

        return {
            'ok': True,
            'entry': entry.strip(),
            'path': f"generated/{year}/links.journal",
        }

    def _ensure_year_include(year, fname):
        """Ensure generated/<year>/<fname> is pulled in by the year include file."""
        from lib.journal import get_include_dir
        year_include = get_include_dir() / f"{year}.journal"
        if year_include.exists():
            line = f"include ../generated/{year}/{fname}"
            if line not in year_include.read_text():
                with open(year_include, 'a') as f:
                    f.write(f"\n{line}\n")

    @app.post("/api/transfer")
    async def create_transfer(req: TransferRequest):
        """Record an asset-to-asset transfer (pair 1011)."""
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')
        if req.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than zero")
        if not req.from_account.strip() or not req.to_account.strip():
            raise HTTPException(status_code=400, detail="From and To accounts are required")

        entry_date = req.date or date.today().isoformat()
        amt = money(req.amount)
        desc = req.description.strip() or "Internal transfer"
        postings = [
            (req.to_account.strip(), currency, float(amt)),
            (req.from_account.strip(), currency, float(-amt)),
        ]
        entry = format_entry(entry_date, desc, postings, {'pair': '1011'})
        year = entry_date[:4]
        ensure_year_structure(int(year))
        append_journal(get_generated_dir() / year / "transfers.journal", entry)
        _ensure_year_include(year, "transfers.journal")
        return {'status': 'ok', 'message': f"Transfer recorded: {currency} {amt}"}

    @app.get("/api/transfers")
    async def list_transfers():
        """Recent transfers parsed from generated/*/transfers.journal."""
        import re
        entity_dir = get_entity_dir()
        gen = entity_dir / 'generated'
        items = []
        if gen.exists():
            for jf in sorted(gen.glob('*/transfers.journal')):
                lines = jf.read_text().splitlines()
                cur = None
                for ln in lines:
                    m = re.match(r'^(\d{4}-\d{2}-\d{2})\s+\*?\s*(.*?)(\s+;.*)?$', ln)
                    if m and not ln.startswith(' '):
                        cur = {'date': m.group(1), 'description': m.group(2).strip(), 'postings': []}
                        items.append(cur)
                    elif cur is not None and ln.startswith(' ') and ln.strip():
                        parts = ln.strip().rsplit('  ', 1)
                        if len(parts) == 2:
                            cur['postings'].append({'account': parts[0].strip(), 'amount': parts[1].strip()})
        items.sort(key=lambda x: x['date'], reverse=True)
        return {'items': items[:50]}

    # ─── Dashboard endpoints ─────────────────────────────────────────────

    @app.get("/api/worth")
    async def worth():
        """Net worth summary via hledger."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")

        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        # Get balance sheet data from hledger
        try:
            result = subprocess.run(
                ['hledger', '-f', journal, 'bal', '--flat', '-N',
                 'assets', 'liabilities', '--output-format', 'csv'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return {'currency': currency, 'assets': 0, 'liabilities': 0, 'net_worth': 0, 'accounts': []}

            accounts = []
            total_assets = 0
            total_liabilities = 0

            for line in result.stdout.strip().split('\n')[1:]:  # skip header
                if not line.strip():
                    continue
                parts = line.split('","')
                if len(parts) >= 2:
                    acct = parts[0].strip('"')
                    amt_str = parts[1].strip('"').replace(currency, '').strip().replace(',', '')
                    try:
                        amt = float(amt_str)
                    except (ValueError, IndexError):
                        amt = 0

                    accounts.append({'account': acct, 'amount': amt})
                    if acct.startswith('Assets:'):
                        total_assets += amt
                    elif acct.startswith('Liabilities:'):
                        total_liabilities += amt

            return {
                'currency': currency,
                'assets': round(total_assets, 2),
                'liabilities': round(abs(total_liabilities), 2),
                'net_worth': round(total_assets + total_liabilities, 2),
                'accounts': accounts,
            }
        except Exception as e:
            return {'currency': currency, 'assets': 0, 'liabilities': 0, 'net_worth': 0, 'accounts': [], 'error': str(e)}

    @app.get("/api/recent")
    async def recent(limit: int = 100, offset: int = 0, query: str = ''):
        """Journal register entries with optional search filter."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")

        try:
            cmd = ['hledger', '-f', journal, 'register', '--output-format', 'csv']
            terms = []
            if query:
                terms, err = _safe_query_terms(query)
                if err:
                    return {'entries': [], 'total': 0, 'error': err}
                # Bare terms match account names in hledger.
                # To also match descriptions, we pass both as an OR query.
                cmd += terms + ['or', 'desc:' + query]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # If OR query fails (older hledger), fall back to simple account match
                cmd2 = ['hledger', '-f', journal, 'register', '--output-format', 'csv'] + terms
                result = subprocess.run(cmd2, capture_output=True, text=True)
                if result.returncode != 0:
                    return {'entries': [], 'total': 0}

            lines = result.stdout.strip().split('\n')
            if len(lines) <= 1:
                return {'entries': [], 'total': 0}

            # CSV header: "txnidx","date","code","description","account","amount","total"
            # Group by txnidx
            txns = {}
            txn_order = []
            for line in lines[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 6:
                    idx = parts[0]
                    if idx not in txns:
                        txns[idx] = {
                            'id': idx,
                            'date': parts[1],
                            'description': parts[3],
                            'postings': [],
                        }
                        txn_order.append(idx)
                    txns[idx]['postings'].append({
                        'account': parts[4],
                        'amount': parts[5],
                    })

            # Return in reverse chronological order with pagination
            txn_order.reverse()
            total = len(txn_order)
            page = txn_order[offset:offset + limit]
            entries = [txns[idx] for idx in page]
            return {'entries': entries, 'total': total, 'offset': offset, 'limit': limit}
        except Exception as e:
            return {'entries': [], 'total': 0, 'error': str(e)}

    # ─── Advanced search ──────────────────────────────────────────────────
    # Query terms are passed to hledger as argv (never through a shell), so the
    # full query language works verbatim: acct: amt: cur: date: desc: note:
    # payee: code: status: type: tag: depth: real: not: and boolean expr:/any:/all:

    def _safe_query_terms(query):
        """Split a user query into hledger argv terms. Returns (terms, error).

        Argument injection guard: hledger parses any argv item beginning with
        '-' as a FLAG, not a query term. Passing args as a list prevents *shell*
        injection but not this. A smuggled --output-file= turns a read-only
        report into an arbitrary file write, and -f repoints it at any file on
        disk. No legitimate query term starts with '-', so reject them.
        Callers additionally pass '--' before these terms.
        """
        try:
            terms = shlex.split(query) if query else []
        except ValueError as e:
            return [], f"Unbalanced quotes: {e}"
        bad = [t for t in terms if t.startswith('-')]
        if bad:
            return [], f"Query terms cannot start with '-': {', '.join(bad)}"
        return terms, ''

    class SearchRequest(BaseModel):
        query: str = ''          # raw hledger query (full parity)
        fields: dict = {}        # structured builder fields
        mode: str = 'register'   # register (postings) | print (transactions)
        limit: int = 200

    def _compose_query(fields):
        """Build an hledger query string from structured builder fields.

        One-way by design: fields compose into a query the user can see and
        then edit by hand. Parsing an arbitrary hledger query back into fields
        would need hledger's own grammar and would drift.
        """
        terms = []

        def add(prefix, value, negate=False):
            value = (value or '').strip()
            if not value:
                return
            # Quote terms containing spaces so shlex keeps them as one argv item.
            term = f"{prefix}{value}" if prefix else value
            if ' ' in value:
                term = f"{prefix}'{value}'" if prefix else f"'{value}'"
            terms.append(f"not:{term}" if negate else term)

        neg = fields.get('negate') or {}
        for key, prefix in (('acct', 'acct:'), ('desc', 'desc:'), ('payee', 'payee:'),
                            ('note', 'note:'), ('code', 'code:'), ('cur', 'cur:'),
                            ('date', 'date:'), ('date2', 'date2:')):
            add(prefix, fields.get(key), bool(neg.get(key)))

        amount = (fields.get('amt') or '').strip()
        if amount:
            op = (fields.get('amt_op') or '').strip()
            terms.append(f"amt:'{op}{amount}'" if op else f"amt:{amount}")

        status = (fields.get('status') or '').strip()
        if status in ('unmarked', 'pending', 'cleared'):
            terms.append({'unmarked': 'status:', 'pending': 'status:!', 'cleared': 'status:*'}[status])

        types = ''.join(t for t in (fields.get('type') or '') if t.upper() in 'ALERXCVG')
        if types:
            terms.append(f"type:{types.upper()}")

        tag_name = (fields.get('tag_name') or '').strip()
        if tag_name:
            tag_value = (fields.get('tag_value') or '').strip()
            add('tag:', f"{tag_name}={tag_value}" if tag_value else tag_name, bool(neg.get('tag')))

        depth = str(fields.get('depth') or '').strip()
        if depth.isdigit():
            terms.append(f"depth:{depth}")

        if fields.get('real'):
            terms.append('real:')

        expr = (fields.get('expr') or '').strip()
        if expr:
            terms.append(f"expr:'{expr}'")

        return ' '.join(terms)

    @app.post("/api/search")
    async def search(req: SearchRequest):
        """Run an hledger query. Read-only.

        A raw query wins if given; otherwise the structured fields compose one.
        hledger's own error is returned verbatim on a malformed query rather
        than silently yielding zero results.
        """
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")

        query = (req.query or '').strip() or _compose_query(req.fields or {})

        terms, err = _safe_query_terms(query)
        if err:
            return {'ok': False, 'query': query, 'error': err, 'entries': [], 'total': 0}

        mode = req.mode if req.mode in ('register', 'print') else 'register'
        # NB: do not add a '--' separator here. hledger stops parsing prefix:
        # query syntax after '--', so amt:/type:/expr: silently match nothing.
        # The leading-dash rejection in _safe_query_terms is the guard.
        cmd = ['hledger', '-f', journal, mode, '--output-format', 'csv'] + terms

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            return {'ok': False, 'query': query, 'error': 'hledger is not installed',
                    'entries': [], 'total': 0}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'query': query, 'error': 'Search timed out',
                    'entries': [], 'total': 0}

        if result.returncode != 0:
            return {'ok': False, 'query': query,
                    'error': (result.stderr or result.stdout).strip()[:2000],
                    'entries': [], 'total': 0}

        rows = _parse_csv_rows(result.stdout)
        entries = _group_search_rows(rows, mode)
        total = len(entries)
        return {'ok': True, 'query': query, 'mode': mode, 'error': '',
                'entries': entries[:req.limit], 'total': total}

    def _parse_csv_rows(text):
        import csv, io
        try:
            return list(csv.DictReader(io.StringIO(text)))
        except Exception:
            return []

    def _group_search_rows(rows, mode):
        """Group hledger CSV output into transactions with their postings."""
        txns, order = {}, []
        for row in rows:
            idx = row.get('txnidx') or row.get('txn') or str(len(order))
            if idx not in txns:
                txns[idx] = {'id': idx, 'date': row.get('date', ''),
                             'description': row.get('description', ''),
                             'code': row.get('code', ''), 'postings': []}
                order.append(idx)
            txns[idx]['postings'].append({
                'account': row.get('account', ''),
                'amount': row.get('amount', ''),
                'total': row.get('total', ''),
            })
        order.reverse()
        return [txns[i] for i in order]

    @app.get("/api/entities")
    async def entities():
        """List all entities."""
        from lib.helpers import load_global_config
        config = load_global_config()
        active = config.get('active', '')
        entity_list = config.get('entities', [])
        return {
            'active': active,
            'entities': entity_list,
        }

    class EntityCreateRequest(BaseModel):
        kind: str = 'entity'      # entity | project
        parent: str = ''          # owned projects only
        name: str = ''
        slug: str = ''
        path: str = ''
        currency: str = 'CAD'
        bank: str = 'Chequing'

    @app.get("/api/entity/default-path")
    async def entity_default_path(kind: str = 'entity', parent: str = '', slug: str = ''):
        """The default folder for a new entity/project — mirrors the CLI."""
        from modules.entity import ENTITIES_BASE, PROJECTS_BASE
        from lib.helpers import entity_dir_for
        slug = (slug or 'new').strip() or 'new'
        if kind == 'project' and parent.strip():
            base = entity_dir_for(parent.strip()) / 'projects' / slug
        elif kind == 'project':
            base = PROJECTS_BASE / slug
        else:
            base = ENTITIES_BASE / slug
        return {'path': str(base)}

    @app.get("/api/entity/scan")
    async def entity_scan(path: str = ''):
        """Inspect a destination: is there a journal to adopt, which folders exist.

        Powers the registration fork — the same detection the CLI does, so the
        web and CLI agree on what counts as an existing ledger.
        """
        from modules.entity import _find_journal_file, _scan_structure, ENTITY_DIRS
        from lib.helpers import expand_path
        raw = (path or '').strip()
        if not raw:
            return {'exists': False, 'journal': '', 'found': [], 'missing': ENTITY_DIRS}
        folder = expand_path(raw)
        if not folder.exists():
            return {'exists': False, 'journal': '', 'found': [], 'missing': ENTITY_DIRS}
        journal = _find_journal_file(folder)
        found, missing = _scan_structure(folder)
        return {
            'exists': True,
            'journal': str(journal.relative_to(folder)) if journal else '',
            'found': found,
            'missing': missing,
        }

    @app.post("/api/entity/create")
    async def entity_create(req: EntityCreateRequest):
        """Create or register an entity/project. Mirrors `pair create`."""
        import re as _re
        from modules.entity import (
            ENTITIES_BASE, PROJECTS_BASE, _find_journal_file,
            _create_entity_structure, _register_missing,
        )
        from lib.helpers import (
            load_global_config, save_global_config, expand_path, entity_dir_for, slugify,
        )

        name = (req.name or '').strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        slug = (req.slug or '').strip() or slugify(name)
        if not _re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug):
            raise HTTPException(status_code=400,
                                detail="Slug must be lowercase letters, digits and hyphens")

        kind = 'project' if req.kind == 'project' else 'entity'
        parent = (req.parent or '').strip()

        config = load_global_config()
        entities = config.get('entities', []) or []
        if any(e.get('slug') == slug for e in entities):
            raise HTTPException(status_code=400, detail=f"'{slug}' already exists")
        if parent and not any(e.get('slug') == parent for e in entities):
            raise HTTPException(status_code=400, detail=f"No entity with slug '{parent}'")

        if req.path.strip():
            dest = expand_path(req.path.strip())
        elif kind == 'project' and parent:
            dest = entity_dir_for(parent) / 'projects' / slug
        elif kind == 'project':
            dest = PROJECTS_BASE / slug
        else:
            dest = ENTITIES_BASE / slug
        dest = dest.resolve()

        existing = _find_journal_file(dest)
        registering = existing is not None
        journal_file = str(existing) if existing else str(dest / 'include' / 'company.journal')
        bank_account = f"Assets:Current:{(req.bank or 'Chequing').strip()}"
        currency = (req.currency or 'CAD').strip()

        try:
            if registering:
                _register_missing(dest, name, slug, currency, journal_file, bank_account)
            else:
                _create_entity_structure(dest, name, slug, currency, journal_file, bank_account)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not create folder: {e}")

        entry = {'name': name, 'slug': slug, 'currency': currency,
                 'kind': kind, 'journal_file': journal_file}
        if parent:
            entry['parent'] = parent
        if dest != (BASE_DIR / 'entities' / slug).resolve():
            entry['path'] = str(dest)
        entities.append(entry)
        config['entities'] = entities
        save_global_config(config)

        return {'status': 'ok', 'slug': slug, 'path': str(dest),
                'registered': registering, 'kind': kind,
                'message': f"{name} {'registered' if registering else 'created'} at {dest}"}

    @app.post("/api/switch")
    async def switch_entity(slug: str):
        """Switch active entity."""
        from lib.helpers import load_global_config, save_global_config
        config = load_global_config()
        entity_list = config.get('entities', [])

        # Verify entity exists
        found = any(e.get('slug') == slug for e in entity_list)
        if not found:
            raise HTTPException(status_code=404, detail=f"Entity not found: {slug}")

        config['active'] = slug
        save_global_config(config)

        # Find name
        name = slug
        for e in entity_list:
            if e.get('slug') == slug:
                name = e.get('name', slug)
                break

        return {'ok': True, 'active': slug, 'name': name}

    @app.get("/api/report")
    async def report(cmd: str = 'bs', period: str = '', args: str = ''):
        """Run hledger report and return output."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")

        # Whitelist of allowed commands
        allowed = ['bs', 'balancesheet', 'is', 'incomestatement', 'bal',
                   'register', 'cashflow', 'accounts', 'stats']
        if cmd not in allowed:
            raise HTTPException(status_code=400, detail=f"Command not allowed: {cmd}")

        hledger_cmd = ['hledger', '-f', journal, cmd]
        if period:
            hledger_cmd += ['-p', period]
        if args:
            arg_list = args.split()
            if any(a.startswith('-') for a in arg_list):
                raise HTTPException(status_code=400, detail="Report args cannot start with '-'")
            hledger_cmd += arg_list

        try:
            result = subprocess.run(hledger_cmd, capture_output=True, text=True)
            return {
                'cmd': cmd,
                'output': result.stdout,
                'error': result.stderr if result.returncode != 0 else '',
            }
        except Exception as e:
            return {'cmd': cmd, 'output': '', 'error': str(e)}

    # ─── YAML data endpoints ─────────────────────────────────────────────

    @app.get("/api/assets")
    async def assets():
        """List all assets from YAML."""
        return {'items': _load_yaml_dir('assets')}

    @app.post("/api/asset")
    async def create_or_update_asset(req: AssetRequest):
        """Create or update an asset YAML file."""
        import yaml
        import re
        from lib.yaml_store import save_entity, entity_exists

        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        # Slugify
        slug = req.slug.strip() if req.slug else ''
        if slug:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', slug):
                raise HTTPException(status_code=400, detail="Invalid slug")
        else:
            slug = re.sub(r'[^a-z0-9]+', '-', req.name.lower().strip()).strip('-') or 'untitled'

        # Category → accounts mapping
        DEFAULT_ACCOUNTS = {
            'equipment': {
                'asset': 'Assets:Fixed:Equipment',
                'amortization_expense': 'Expenses:Non-Operating:Amortization',
                'accumulated': 'Assets:Accumulated Amortization:Equipment',
            },
            'vehicle': {
                'asset': 'Assets:Fixed:Vehicles',
                'amortization_expense': 'Expenses:Non-Operating:Amortization',
                'accumulated': 'Assets:Accumulated Amortization:Vehicles',
            },
            'furniture': {
                'asset': 'Assets:Fixed:Furniture',
                'amortization_expense': 'Expenses:Non-Operating:Amortization',
                'accumulated': 'Assets:Accumulated Amortization:Furniture',
            },
            'software': {
                'asset': 'Assets:Fixed:Intellectual Property',
                'amortization_expense': 'Expenses:Non-Operating:Amortization',
                'accumulated': 'Assets:Accumulated Amortization:Intellectual Property',
            },
            'other': {
                'asset': 'Assets:Fixed:Other',
                'amortization_expense': 'Expenses:Non-Operating:Amortization',
                'accumulated': 'Assets:Accumulated Amortization:Other',
            },
        }

        category = req.category if req.category in DEFAULT_ACCOUNTS else 'other'
        accounts = DEFAULT_ACCOUNTS[category]
        purchase_date = req.purchase_date or date.today().isoformat()

        asset_data = {
            'name': req.name,
            'slug': slug,
            'category': category,
            'purchase_date': purchase_date,
            'cost': req.cost,
            'useful_life_months': req.useful_life_months,
            'amortization_method': req.amortization_method,
            'salvage_value': req.salvage_value,
            'currency': currency,
            'accounts': accounts.copy(),
        }

        if req.description:
            asset_data['description'] = req.description
        if req.amortization_method == 'declining-balance' and req.rate > 0:
            asset_data['rate'] = req.rate
            asset_data['declining_balance_rate'] = req.rate
        if req.payment_method == 'financed':
            asset_data['payment_method'] = 'financed'
            if req.linked_liability:
                asset_data['linked_liability'] = req.linked_liability
        else:
            asset_data['payment_method'] = 'cash'

        # Save
        save_entity('assets', slug, asset_data)

        # Write acquisition entry
        year = purchase_date[:4]
        ensure_year_structure(int(year))
        from modules.asset import _write_acquisition_entry
        _write_acquisition_entry(asset_data, config)

        return {'status': 'ok', 'slug': slug, 'message': f"Asset '{req.name}' saved"}

    @app.delete("/api/asset/{slug}")
    async def delete_asset(slug: str):
        """Delete an asset."""
        import re
        from lib.yaml_store import delete_entity, entity_exists
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', slug):
            raise HTTPException(status_code=400, detail="Invalid slug")
        if not entity_exists('assets', slug):
            raise HTTPException(status_code=404, detail=f"Asset '{slug}' not found")
        delete_entity('assets', slug)
        return {'status': 'ok', 'message': f"Asset '{slug}' deleted'"}

    @app.get("/api/liabilities")
    async def liabilities():
        """List all liabilities from YAML."""
        return {'items': _load_yaml_dir('liabilities')}

    @app.post("/api/liability")
    async def create_or_update_liability(req: LiabilityRequest):
        """Create or update a liability YAML file (+ creation entry on first save).

        Reuses modules.liability for payment maths and account/journal logic so the
        web path stays identical to `pair liability add`.
        """
        import re
        from decimal import Decimal
        from lib.yaml_store import save_entity, entity_exists, load_entity
        from lib.helpers import money
        from modules import liability as liab_mod

        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        slug = req.slug.strip() if req.slug else ''
        if slug:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', slug):
                raise HTTPException(status_code=400, detail="Invalid slug")
        else:
            slug = re.sub(r'[^a-z0-9]+', '-', req.name.lower().strip()).strip('-') or 'untitled'

        principal = float(req.principal)
        if principal <= 0:
            raise HTTPException(status_code=400, detail="Principal must be greater than zero")

        liab_type = req.type if req.type in liab_mod.TYPES else 'loan'
        schedule = req.payment_schedule if req.payment_schedule in liab_mod.SCHEDULES else 'monthly'
        term_months = int(req.term_months) if req.term_months else 12
        start_date = req.start_date or date.today().isoformat()
        rate = Decimal(str(req.interest_rate or 0))

        # Payment: an explicit client value wins; otherwise compute like cmd_add
        if req.payment_amount and req.payment_amount > 0:
            payment_amount = float(req.payment_amount)
        elif rate > 0:
            payment_amount = float(liab_mod._calculate_payment(
                Decimal(str(principal)), rate, term_months, schedule))
        else:
            periods = liab_mod._periods_count(term_months, schedule)
            payment_amount = float(money(Decimal(str(principal)) / periods)) if periods else 0.0

        # Accounts (mirror liability.cmd_add naming)
        accounts = liab_mod.DEFAULT_ACCOUNTS.get(liab_type, liab_mod.DEFAULT_ACCOUNTS['loan']).copy()
        if liab_type in ('loan', 'lease'):
            accounts['liability'] = f"Liabilities:Long-Term:{req.name}"
        else:
            accounts['liability'] = f"Liabilities:Current:{req.name}"
        accounts['payment_source'] = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')

        is_new = not entity_exists('liabilities', slug)
        existing = load_entity('liabilities', slug) or {} if not is_new else {}

        liab_data = {
            'name': req.name,
            'slug': slug,
            'type': liab_type,
            'principal': principal,
            'interest_rate': float(req.interest_rate or 0),
            'term_months': term_months,
            'start_date': start_date,
            'payment_schedule': schedule,
            'payment_amount': payment_amount,
            'currency': currency,
            'accounts': accounts,
        }
        if req.lender:
            liab_data['lender'] = req.lender.strip()
        if req.description:
            liab_data['notes'] = req.description
        # Preserve any recorded payments across edits
        if existing.get('payments'):
            liab_data['payments'] = existing['payments']

        save_entity('liabilities', slug, liab_data)

        # Only write the creation entry for a brand-new liability (avoid duplicates on edit)
        if is_new:
            ensure_year_structure(int(start_date[:4]))
            liab_mod._write_creation_entry(liab_data, config)

        return {'status': 'ok', 'slug': slug, 'payment_amount': round(payment_amount, 2),
                'message': f"Liability '{req.name}' saved"}

    @app.delete("/api/liability/{slug}")
    async def delete_liability(slug: str):
        """Delete a liability YAML file (journal entries are left intact)."""
        import re
        from lib.yaml_store import delete_entity, entity_exists
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', slug):
            raise HTTPException(status_code=400, detail="Invalid slug")
        if not entity_exists('liabilities', slug):
            raise HTTPException(status_code=404, detail=f"Liability '{slug}' not found")
        delete_entity('liabilities', slug)
        return {'status': 'ok', 'message': f"Liability '{slug}' deleted"}

    @app.get("/api/contacts")
    async def contacts():
        """List all contacts from YAML."""
        return {'items': _load_yaml_dir('contacts')}

    @app.get("/api/contracts")
    async def contracts():
        """List all contracts from YAML."""
        return {'items': _load_yaml_dir('contracts')}

    @app.get("/api/recurring")
    async def recurring():
        """List all recurring entries from YAML."""
        return {'items': _load_yaml_dir('recurring')}

    @app.get("/api/expenses")
    async def expenses(period: str = ''):
        """Expense breakdown from hledger."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        cmd = ['hledger', '-f', journal, 'bal', 'expenses', '--flat', '--no-total', '--output-format', 'csv']
        if period:
            cmd += ['-p', period]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return {'items': []}
            config = load_config()
            currency = config.get('pair', {}).get('currency', 'CAD')
            items = []
            for line in result.stdout.strip().split('\n')[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    acct = parts[0]
                    amt_str = parts[1].replace(currency, '').strip().replace(',', '')
                    try:
                        amt = float(amt_str)
                    except ValueError:
                        amt = 0
                    short, hint, _ = _leaf_display(acct)
                    items.append({'account': acct, 'short': short, 'hint': hint, 'amount': amt})
            items.sort(key=lambda x: -abs(x['amount']))
            return {'items': items, 'currency': currency}
        except Exception as e:
            return {'items': [], 'error': str(e)}

    @app.get("/api/equity")
    async def equity(period: str = ''):
        """Equity accounts from hledger."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        cmd = ['hledger', '-f', journal, 'bal', 'equity', '--flat', '--no-total', '--output-format', 'csv']
        if period:
            cmd += ['-p', period]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return {'items': []}
            config = load_config()
            currency = config.get('pair', {}).get('currency', 'CAD')
            items = []
            for line in result.stdout.strip().split('\n')[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    acct = parts[0]
                    amt_str = parts[1].replace(currency, '').strip().replace(',', '')
                    try:
                        amt = float(amt_str)
                    except ValueError:
                        amt = 0
                    short, hint, _ = _leaf_display(acct)
                    items.append({'account': acct, 'short': short, 'hint': hint, 'amount': amt})
            items.sort(key=lambda x: -abs(x['amount']))
            return {'items': items, 'currency': currency}
        except Exception as e:
            return {'items': [], 'error': str(e)}

    @app.get("/api/income")
    async def income(period: str = ''):
        """Income accounts from hledger."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        cmd = ['hledger', '-f', journal, 'bal', 'income', '--flat', '--no-total', '--output-format', 'csv']
        if period:
            cmd += ['-p', period]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return {'items': []}
            config = load_config()
            currency = config.get('pair', {}).get('currency', 'CAD')
            items = []
            for line in result.stdout.strip().split('\n')[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    acct = parts[0]
                    amt_str = parts[1].replace(currency, '').strip().replace(',', '')
                    try:
                        amt = float(amt_str)
                    except ValueError:
                        amt = 0
                    short, hint, _ = _leaf_display(acct)
                    items.append({'account': acct, 'short': short, 'hint': hint, 'amount': abs(amt)})
            items.sort(key=lambda x: -abs(x['amount']))
            return {'items': items, 'currency': currency}
        except Exception as e:
            return {'items': [], 'error': str(e)}

    @app.get("/api/commodities")
    async def commodities():
        """List commodities with latest prices."""
        import yaml
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')
        market_config = config.get('market', {})
        commodity_list = market_config.get('commodities', [])

        # Get latest prices from prices.journal
        entity_dir = get_entity_dir()
        prices_file = entity_dir / 'include' / 'prices.journal'
        latest_prices = {}
        if prices_file.exists():
            with open(prices_file) as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith('P '):
                        continue
                    parts = line.split()
                    if len(parts) >= 5:
                        pdate = parts[1]
                        symbol = parts[2].strip('"')
                        try:
                            price = float(parts[-1])
                        except ValueError:
                            continue
                        latest_prices[symbol] = {'date': pdate, 'price': price}

        # Merge config + prices
        items = []
        for c in commodity_list:
            sym = c.get('symbol', '')
            latest = latest_prices.get(sym, {})
            items.append({
                'symbol': sym,
                'name': c.get('name', sym),
                'source': c.get('source', ''),
                'currency': c.get('currency', currency),
                'tax_account': c.get('tax_account', ''),
                'tags': c.get('tags', []),
                'latest_price': latest.get('price'),
                'latest_date': latest.get('date', ''),
            })

        return {'items': items, 'currency': currency}

    @app.get("/api/market/sources")
    async def market_sources():
        """Supported price sources."""
        return {'sources': ['yahoo', 'bankofcanada', 'ecb', 'coinbasepro', 'alphavantage']}

    @app.post("/api/commodity")
    async def create_or_update_commodity(req: CommodityRequest):
        """Create or update a commodity in the entity's market config (merges to keep extra fields)."""
        import re
        from lib.helpers import save_config
        symbol = req.symbol.strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="Symbol is required")
        if not re.fullmatch(r'[A-Za-z0-9.\-]+', symbol):
            raise HTTPException(status_code=400, detail="Invalid symbol")

        config = load_config()
        market = config.setdefault('market', {})
        commodities = market.get('commodities', []) or []

        entry = next((c for c in commodities if c.get('symbol', '').lower() == symbol.lower()), None)
        if entry is None:
            entry = {'symbol': symbol}
            commodities.append(entry)

        entry['symbol'] = symbol
        # Only overwrite fields the caller actually filled in, so metadata set
        # from the CLI (sector, risk, ...) survives an edit from the web form.
        for field in ('name', 'source', 'fetch_pair', 'currency', 'type',
                      'sector', 'geography', 'strategy', 'risk', 'tax_account'):
            value = getattr(req, field, '').strip()
            if value:
                entry[field] = value
        tags = [t.strip() for t in req.tags if isinstance(t, str) and t.strip()]
        if tags:
            entry['tags'] = tags
        elif 'tags' in entry:
            del entry['tags']

        market['commodities'] = commodities
        save_config(config)
        return {'status': 'ok', 'symbol': symbol, 'message': f"Saved {symbol}"}

    @app.delete("/api/commodity/{symbol}")
    async def delete_commodity(symbol: str):
        """Remove a commodity from the market config."""
        from lib.helpers import save_config
        config = load_config()
        market = config.get('market', {})
        commodities = market.get('commodities', []) or []
        new_list = [c for c in commodities if c.get('symbol', '').lower() != symbol.lower()]
        if len(new_list) == len(commodities):
            raise HTTPException(status_code=404, detail=f"Commodity '{symbol}' not found")
        market['commodities'] = new_list
        config['market'] = market
        save_config(config)
        return {'status': 'ok', 'message': f"Removed {symbol}"}

    # Yahoo's search endpoint returns an empty `currency` for every quote, so
    # infer it from the symbol suffix / exchange code instead.
    EXCHANGE_CURRENCY = {
        'TOR': 'CAD', 'NEO': 'CAD', 'VAN': 'CAD', 'CNQ': 'CAD',
        'NMS': 'USD', 'NYQ': 'USD', 'NGM': 'USD', 'PCX': 'USD', 'ASE': 'USD',
        'BTS': 'USD', 'NAS': 'USD', 'CCC': 'USD', 'CME': 'USD',
        'LSE': 'GBP', 'GER': 'EUR', 'PAR': 'EUR', 'AMS': 'EUR', 'MIL': 'EUR',
        'SAO': 'BRL', 'TYO': 'JPY', 'HKG': 'HKD', 'ASX': 'AUD',
    }

    def _infer_currency(result):
        """Best-effort quote currency for a Yahoo search hit."""
        if result.get('currency'):
            return result['currency']
        symbol = result.get('symbol', '')
        # Crypto/FX pairs carry their quote currency in the symbol: BTC-CAD.
        if '-' in symbol:
            quote = symbol.rsplit('-', 1)[-1]
            if len(quote) == 3 and quote.isalpha():
                return quote.upper()
        return EXCHANGE_CURRENCY.get(result.get('exchange', ''), '')

    @app.get("/api/market/search")
    async def market_search(q: str = ''):
        """Search Yahoo Finance for symbols. Mirrors `pair market add QUERY`."""
        from modules.market import _yahoo_search
        query = q.strip()
        if not query:
            return {'results': [], 'currency': ''}

        base_currency = get_entity_currency()
        tracked = {c.get('symbol', '').lower()
                   for c in (load_config().get('market', {}).get('commodities', []) or [])}

        results = []
        for r in _yahoo_search(query)[:10]:
            symbol = r.get('symbol', '')
            # Crypto arrives as BTC-CAD; the CLI stores BTC and fetches BTC-CAD.
            # Suggest that split but let the user confirm it in the form.
            store_symbol = symbol
            if '-' in symbol and r.get('type') == 'cryptocurrency':
                store_symbol = symbol.split('-')[0]
            currency = _infer_currency(r)
            results.append({
                **r,
                'currency': currency,
                'store_symbol': store_symbol,
                'fetch_pair': symbol,
                'matches_currency': bool(currency) and currency == base_currency,
                'tracked': store_symbol.lower() in tracked,
            })

        # Surface entity-currency matches first; Yahoo's own order breaks ties.
        results.sort(key=lambda r: not r['matches_currency'])
        return {'results': results, 'currency': base_currency}

    @app.post("/api/market/fetch")
    async def market_fetch(req: FetchRequest = FetchRequest()):
        """Trigger price fetching via the CLI (pricehist). Best-effort with a timeout."""
        pair_bin = BASE_DIR / 'pair'
        cmd = [sys.executable, str(pair_bin), 'market', 'fetch']
        if req.symbol.strip():
            cmd += ['--symbol', req.symbol.strip()]
        if req.tag.strip():
            cmd += ['--tag', req.tag.strip()]
        if req.type.strip():
            cmd += ['--type', req.type.strip()]
        days = req.days if 1 <= req.days <= 3650 else 7
        cmd += ['--days', str(days)]
        try:
            r = subprocess.run(cmd,
                               capture_output=True, text=True, timeout=180,
                               stdin=subprocess.DEVNULL, cwd=str(BASE_DIR))
            out = (r.stdout or '') + (r.stderr or '')
            return {'status': 'ok' if r.returncode == 0 else 'error', 'output': out.strip()[-4000:]}
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'output': 'Fetch timed out after 180s.'}
        except Exception as e:
            return {'status': 'error', 'output': str(e)}

    def _resolve_trade_commodity(symbol):
        """Find a tracked commodity by symbol, or raise 404."""
        from modules.market import _find_commodity
        commodity, _ = _find_commodity(symbol)
        if commodity is None:
            raise HTTPException(status_code=404, detail=f"'{symbol}' is not tracked")
        return commodity

    def _trade_accounts(commodity, requested):
        """Resolve tax account and cash/gains accounts for a trade."""
        from modules.investment import TAX_ACCOUNTS
        accounts = load_config().get('accounts', {})
        tax_account = (requested or commodity.get('tax_account') or 'taxable').lower()
        if tax_account not in TAX_ACCOUNTS:
            raise HTTPException(status_code=400,
                                detail=f"Invalid account '{tax_account}'. Valid: {', '.join(TAX_ACCOUNTS)}")
        return {
            'tax_account': tax_account,
            'cash_account': accounts.get('bank', 'Assets:Current:Chequing'),
            'gains_account': accounts.get('capital_gains', 'Income:Non-Operating:Capital Gains'),
            'registered_gains_account': accounts.get('registered_gains', 'Income:Non-Operating:Registered Gains'),
        }

    @app.get("/api/market/holding")
    async def market_holding(symbol: str, account: str = ''):
        """Current quantity and ACB average for a holding — powers the sell preview."""
        from modules.investment import read_holding_events, compute_acb_from_events
        commodity = _resolve_trade_commodity(symbol)
        acct = _trade_accounts(commodity, account)
        try:
            events = read_holding_events(get_entity_journal(), acct['tax_account'], commodity['symbol'])
        except Exception:
            events = []
        qty, cost, average = compute_acb_from_events(events)
        return {
            'symbol': commodity['symbol'],
            'account': acct['tax_account'],
            'quantity': qty,
            'cost': round(cost, 2),
            'average': round(average, 4),
            'currency': get_entity_currency(),
        }

    @app.post("/api/market/buy")
    async def market_buy(req: BuyRequest):
        """Record a purchase (ACB tracked). Reuses the CLI's build_buy_entry."""
        from modules.investment import build_buy_entry, record_investment_entry
        if req.qty <= 0 or req.price <= 0:
            raise HTTPException(status_code=400, detail="Quantity and price must be positive")
        commodity = _resolve_trade_commodity(req.symbol)
        acct = _trade_accounts(commodity, req.account)
        entity_currency = get_entity_currency()
        quote_currency = commodity.get('currency', entity_currency)
        fx = req.fx if quote_currency != entity_currency else 1.0
        date_str = req.date.strip() or date.today().strftime('%Y-%m-%d')
        try:
            entry = build_buy_entry(
                date=date_str, symbol=commodity['symbol'], qty=req.qty, unit_price=req.price,
                quote_currency=quote_currency, fx=fx, fee=req.fee,
                tax_account=acct['tax_account'], cash_account=acct['cash_account'],
                entity_currency=entity_currency)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        record_investment_entry(entry, date_str)
        total = round(req.qty * req.price * fx + req.fee, 2)
        return {'status': 'ok', 'total': total, 'currency': entity_currency,
                'message': f"Bought {req.qty:g} {commodity['symbol']} for {entity_currency} {total:.2f}"}

    @app.post("/api/market/sell")
    async def market_sell(req: SellRequest):
        """Record a disposal with ACB gain/loss. Reuses the CLI's build_sell_entry."""
        from modules.investment import (
            build_sell_entry, record_investment_entry, read_holding_events,
            compute_acb_from_events, InsufficientHoldingError)
        if req.qty <= 0 or req.price <= 0:
            raise HTTPException(status_code=400, detail="Quantity and price must be positive")
        commodity = _resolve_trade_commodity(req.symbol)
        acct = _trade_accounts(commodity, req.account)
        entity_currency = get_entity_currency()
        date_str = req.date.strip() or date.today().strftime('%Y-%m-%d')
        try:
            events = read_holding_events(get_entity_journal(), acct['tax_account'], commodity['symbol'])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read holdings: {e}")
        _, _, average = compute_acb_from_events(events)
        try:
            entry = build_sell_entry(
                date=date_str, symbol=commodity['symbol'], qty=req.qty, unit_price=req.price,
                fee=req.fee, tax_account=acct['tax_account'], cash_account=acct['cash_account'],
                entity_currency=entity_currency, events=events,
                gains_account=acct['gains_account'],
                registered_gains_account=acct['registered_gains_account'])
        except InsufficientHoldingError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        record_investment_entry(entry, date_str)
        basis = round(req.qty * average, 2)
        proceeds = round(req.qty * req.price - req.fee, 2)
        gain = round(proceeds - basis, 2)
        registered = acct['tax_account'] in ('tfsa', 'rrsp')
        return {'status': 'ok', 'basis': basis, 'proceeds': proceeds, 'gain': gain,
                'registered': registered, 'currency': entity_currency,
                'message': f"Sold {req.qty:g} {commodity['symbol']} — "
                           f"{'gain' if gain >= 0 else 'loss'} {entity_currency} {abs(gain):.2f}"}

    def _account_types(journal=None):
        """Map account name -> hledger type letter, via `hledger accounts --types`.

        Returns (types, error). Never swallows the failure silently: if hledger
        cannot read the journal, pair inference is unavailable and the caller
        must say so rather than reporting "no pair inferred".
        """
        types = {}
        path = journal or get_entity_journal()
        try:
            result = subprocess.run(
                ['hledger', '-f', str(path), 'accounts', '--types'],
                capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            return types, 'hledger is not installed'
        except subprocess.TimeoutExpired:
            return types, 'hledger timed out reading accounts'
        except Exception as e:
            return types, str(e)

        if result.returncode != 0:
            return types, (result.stderr or 'could not read accounts').strip().splitlines()[0]

        for line in result.stdout.splitlines():
            if ';' not in line:
                continue
            name, _, tag = line.partition(';')
            letter = tag.replace('type:', '').strip()
            if name.strip() and letter:
                types[name.strip()] = letter[:1].upper()
        return types, ''

    def _count_raw_postings(text):
        """Posting lines in hand-written journal text (indented, not comments)."""
        return [l for l in (text or '').splitlines()
                if l[:1] in (' ', '\t') and l.strip() and not l.strip().startswith(';')]

    def _entry_fields(req):
        return {
            'date': (req.date or '').strip() or date.today().strftime('%Y-%m-%d'),
            'status': req.status, 'code': req.code, 'payee': req.payee,
            'note': req.note, 'tags': req.tags, 'postings': req.postings or [],
        }

    @app.post("/api/entry/preview")
    async def entry_preview(req: EntryFields):
        """Serialize + validate via hledger. Read-only — never writes."""
        from lib.entry import validate_entry, infer_pair, serialize_entry

        fields = _entry_fields(req)
        named = [p for p in fields['postings'] if (p.get('account') or '').strip()]

        # Preview as soon as there is anything to show. hledger accepts a
        # posting-less transaction (manual: "Postings are not required"), so a
        # header-only entry previews fine and the user gets feedback from the
        # first keystroke instead of a blank box until an account is typed.
        raw_text = (req.journal_text or '').strip()
        if req.raw and raw_text:
            text = raw_text if raw_text.endswith('\n') else raw_text + '\n\n'
            named = _count_raw_postings(text)
        else:
            text = serialize_entry(fields)
        result = validate_entry(text)

        # Valid hledger, but not yet a complete double entry.
        if result['ok'] and len(named) < 2:
            result = {**result, 'incomplete': 'Add at least two postings to write this entry'}

        # Infer the pair code from the posting accounts the client is editing.
        inferred = ''
        inference_error = ''
        accounts = [p.get('account', '').strip() for p in (req.postings or [])]
        accounts = [a for a in accounts if a]
        if len(accounts) > 2:
            inferred = 'compound'
        elif len(accounts) == 2:
            known, inference_error = _account_types()
            if not inference_error:
                typed = [{'account': a, 'type': known.get(a, '')} for a in accounts]
                missing = [t['account'] for t in typed if not t['type']]
                if missing:
                    inference_error = f"unknown account type for: {', '.join(missing)}"
                else:
                    inferred = infer_pair(typed)

        return {**result, 'journal_text': text, 'posting_count': len(named),
                'inferred_pair': inferred, 'inference_error': inference_error}

    @app.post("/api/entry/advanced")
    async def entry_advanced(req: EntryFields):
        """Serialize, validate, then append. Re-validates server-side."""
        import re
        from lib.entry import validate_entry, record_entry, serialize_entry

        fields = _entry_fields(req)
        if req.raw and (req.journal_text or '').strip():
            named = _count_raw_postings(req.journal_text)
        else:
            named = [p for p in fields['postings'] if (p.get('account') or '').strip()]
        if len(named) < 2:
            raise HTTPException(status_code=400, detail="At least two postings are required")

        entry_date = fields['date']
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry_date):
            raise HTTPException(status_code=400, detail=f"Invalid date: {entry_date}")

        # Tag the entry so pair-keyed views keep working.
        extra = ['mode:advanced']
        pair = (req.pair or '').strip()
        if pair:
            extra.append(f"pair:{pair}")

        raw_text = (req.journal_text or '').strip()
        if req.raw and raw_text:
            # Hand-edited text is written as-is apart from the trailing tags,
            # appended to the first line where hledger expects them.
            lines = raw_text.splitlines()
            sep = ', ' if '  ; ' in lines[0] else '  ; '
            lines[0] = lines[0] + sep + ', '.join(extra)
            text = "\n".join(lines).rstrip() + "\n\n"
        else:
            existing = (fields.get('tags') or '').strip()
            fields['tags'] = f"{existing}, {', '.join(extra)}" if existing else ', '.join(extra)
            text = serialize_entry(fields)

        result = validate_entry(text)
        if not result['ok']:
            raise HTTPException(status_code=400, detail=result['errors'] or 'Invalid entry')

        year = record_entry(text, entry_date)
        return {'status': 'ok', 'year': year, 'pair': pair,
                'message': f"Entry written to generated/{year}/entries.journal"}

    @app.get("/api/payroll")
    async def payroll_list():
        """List payroll data: workers from contracts + recent pay runs."""
        import yaml
        entity_dir = get_entity_dir()
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        def load_contact(slug):
            if not slug or not contacts_dir.exists():
                return {}
            cf = contacts_dir / f"{slug}.yaml"
            if not cf.exists():
                return {}
            with open(cf) as cfh:
                return yaml.safe_load(cfh) or {}

        def party_contact(data, roles):
            for party in data.get('parties', []):
                if party.get('role') in roles:
                    return party.get('contact'), party.get('role')
            return None, ''

        employees = []
        contractors = []
        contractor_slugs = set()
        contracts_dir = entity_dir / 'contracts'
        contacts_dir = entity_dir / 'contacts'

        if contracts_dir.exists():
            for f in contracts_dir.glob('*.yaml'):
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                if data.get('type') == 'employment' and data.get('status') == 'active':
                    contact_slug, _ = party_contact(data, {'employee'})
                    contact = load_contact(contact_slug)
                    name = contact.get('name') or data.get('name', '')
                    employees.append({
                        'name': name,
                        'slug': contact_slug or '',
                        'contact_slug': contact_slug or '',
                        'contract_slug': data.get('slug', f.stem),
                        'salary': data.get('value', 0),
                        'schedule': data.get('payment_schedule', 'biweekly'),
                        'start_date': data.get('start_date', ''),
                        'end_date': data.get('end_date', ''),
                        'status': data.get('status', ''),
                        'email': contact.get('email', ''),
                        'currency': data.get('currency', currency),
                    })
                elif data.get('status') == 'active' and data.get('type') in ('service', 'contractor'):
                    contact_slug, party_role = party_contact(data, {'contractor', 'provider', 'vendor'})
                    if not contact_slug:
                        continue
                    contact = load_contact(contact_slug)
                    contractors.append({
                        'name': contact.get('name') or data.get('name', contact_slug),
                        'slug': contact_slug,
                        'contact_slug': contact_slug,
                        'contract_slug': data.get('slug', f.stem),
                        'contract_name': data.get('name', ''),
                        'role': party_role or contact.get('role', ''),
                        'rate': data.get('value', 0),
                        'schedule': data.get('payment_schedule', ''),
                        'start_date': data.get('start_date', ''),
                        'end_date': data.get('end_date', ''),
                        'status': data.get('status', ''),
                        'email': contact.get('email', ''),
                        'currency': data.get('currency', currency),
                    })
                    contractor_slugs.add(contact_slug)

        if contacts_dir.exists():
            for f in contacts_dir.glob('*.yaml'):
                with open(f) as fh:
                    contact = yaml.safe_load(fh) or {}
                if contact.get('role') == 'contractor' and contact.get('slug') not in contractor_slugs:
                    contractors.append({
                        'name': contact.get('name', f.stem),
                        'slug': contact.get('slug', f.stem),
                        'contact_slug': contact.get('slug', f.stem),
                        'contract_slug': '',
                        'contract_name': '',
                        'role': 'contractor',
                        'rate': 0,
                        'schedule': '',
                        'start_date': '',
                        'end_date': '',
                        'status': 'active',
                        'email': contact.get('email', ''),
                        'currency': currency,
                    })

        employees.sort(key=lambda e: e.get('name', '').lower())
        contractors.sort(key=lambda c: c.get('name', '').lower())

        # Get recent pay runs from hledger
        recent_runs = []
        journal = _get_journal_path()
        if journal:
            result = subprocess.run(
                ['hledger', '-f', journal, 'register', 'payroll:salaries', '--output-format', 'csv'],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                seen_txns = set()
                for line in lines[1:]:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 6 and parts[0] not in seen_txns:
                        seen_txns.add(parts[0])
                        recent_runs.append({
                            'date': parts[1],
                            'description': parts[3],
                            'amount': parts[5],
                        })

        # Get YTD totals
        ytd = {'salaries': 0, 'benefits': 0, 'contributions': 0}
        if journal:
            for cat, query in [('salaries', 'payroll:salaries'), ('benefits', 'payroll:benefits'), ('contributions', 'payroll:employer')]:
                result = subprocess.run(
                    ['hledger', '-f', journal, 'bal', query, '--no-total', '-N', '--output-format', 'csv', '-p', 'thisyear'],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n')[1:]:
                        parts = [p.strip('"') for p in line.split('","')]
                        if len(parts) >= 2:
                            amt_str = parts[1].replace(currency, '').strip().replace(',', '')
                            try:
                                ytd[cat] += float(amt_str)
                            except ValueError:
                                pass

        return {
            'employees': employees,
            'contractors': contractors,
            'recent_runs': recent_runs[-10:],
            'ytd': ytd,
            'currency': currency,
        }

    class PayrollRunRequest(BaseModel):
        pay_type: str = 'employee'
        employee_name: str = ''
        contact_slug: str = ''
        gross_amount: float = 0
        cpp_employee: float = 0
        ei_employee: float = 0
        tax_withheld: float = 0
        cpp_employer: float = 0
        ei_employer: float = 0
        benefits: float = 0
        employer_contributions: float = 0
        pay_date: str = ''
        period: str = ''

    @app.post("/api/payroll/run")
    async def payroll_run(req: PayrollRunRequest):
        """Record a pay run."""
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')
        bank = config.get('accounts', {}).get('bank', 'Assets:Current:Business Chequing')
        pay_date = req.pay_date or date.today().isoformat()

        gross = money(req.gross_amount)
        benefits = money(req.benefits)
        cpp_ee = money(req.cpp_employee)
        ei_ee = money(req.ei_employee)
        cpp_er = money(req.cpp_employer)
        ei_er = money(req.ei_employer)
        tax = money(req.tax_withheld)
        employer_contrib = money(req.employer_contributions) + cpp_er + ei_er

        if req.pay_type == 'contractor':
            postings = [
                ('Expenses:Operating:Payroll:Salaries', currency, float(gross)),
                (bank, currency, float(-gross)),
            ]
            description = f"Contractor payment: {req.employee_name}"
        else:
            net_pay = gross - cpp_ee - ei_ee - tax
            postings = [
                ('Expenses:Operating:Payroll:Salaries', currency, float(gross)),
            ]
            if benefits > 0:
                postings.append(('Expenses:Operating:Payroll:Benefits', currency, float(benefits)))
            if employer_contrib > 0:
                postings.append(('Expenses:Operating:Payroll:Employer Contributions', currency, float(employer_contrib)))
            if tax > 0:
                postings.append(('Liabilities:Current:Income Tax Payable', currency, float(-tax)))
            if cpp_ee > 0:
                postings.append(('Liabilities:Current:CPP Payable', currency, float(-(cpp_ee + cpp_er))))
            if ei_ee > 0:
                postings.append(('Liabilities:Current:EI Payable', currency, float(-(ei_ee + ei_er))))

            postings.append(('Liabilities:Current:Payroll Payable', currency, float(-net_pay)))
            postings.append((bank, currency, float(-(float(benefits) + float(employer_contrib)))))

            description = f"Payroll: {req.employee_name}"
            if req.period:
                description += f" | {req.period}"

        tags = {'pair': '0001', 'mode': 'payroll'}
        if req.contact_slug:
            tags['contact'] = req.contact_slug

        entry = format_entry(pay_date, description, postings, tags)

        year = pay_date[:4]
        ensure_year_structure(int(year))
        journal_path = get_generated_dir() / year / "payroll.journal"
        append_journal(journal_path, entry)

        return {'ok': True, 'entry': entry.strip(), 'path': f"generated/{year}/payroll.journal"}

    @app.get("/api/payroll/settings")
    async def payroll_settings_get():
        """Get payroll deduction rate settings."""
        import yaml
        entity_dir = get_entity_dir()
        config_path = entity_dir / 'config.yaml'
        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        payroll_cfg = config.get('payroll', {})
        return {
            'cpp_employee_rate': payroll_cfg.get('cpp_employee_rate', 0.0595),
            'cpp_employer_rate': payroll_cfg.get('cpp_employer_rate', 0.0595),
            'ei_employee_rate': payroll_cfg.get('ei_employee_rate', 0.0163),
            'ei_employer_rate': payroll_cfg.get('ei_employer_rate', 0.0228),
            'cpp_annual_max': payroll_cfg.get('cpp_annual_max', 3867.50),
            'ei_annual_max': payroll_cfg.get('ei_annual_max', 1049.12),
            'cpp_exemption': payroll_cfg.get('cpp_exemption', 3500),
            'period_length_days': payroll_cfg.get('period_length_days', 14),
            'period_closing_day': payroll_cfg.get('period_closing_day', 'friday'),
            'pay_by_days_after': payroll_cfg.get('pay_by_days_after', 5),
        }

    class PayrollSettingsRequest(BaseModel):
        cpp_employee_rate: float = 0.0595
        cpp_employer_rate: float = 0.0595
        ei_employee_rate: float = 0.0163
        ei_employer_rate: float = 0.0228
        cpp_annual_max: float = 3867.50
        ei_annual_max: float = 1049.12
        cpp_exemption: float = 3500
        period_length_days: int = 14
        period_closing_day: str = 'friday'
        pay_by_days_after: int = 5

    @app.post("/api/payroll/settings")
    async def payroll_settings_save(req: PayrollSettingsRequest):
        """Save payroll deduction rate settings to entity config."""
        import yaml
        entity_dir = get_entity_dir()
        config_path = entity_dir / 'config.yaml'
        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}

        config['payroll'] = {
            'cpp_employee_rate': req.cpp_employee_rate,
            'cpp_employer_rate': req.cpp_employer_rate,
            'ei_employee_rate': req.ei_employee_rate,
            'ei_employer_rate': req.ei_employer_rate,
            'cpp_annual_max': req.cpp_annual_max,
            'ei_annual_max': req.ei_annual_max,
            'cpp_exemption': req.cpp_exemption,
            'period_length_days': req.period_length_days,
            'period_closing_day': req.period_closing_day,
            'pay_by_days_after': req.pay_by_days_after,
        }

        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        return {'ok': True, 'message': 'Payroll settings saved'}

    @app.get("/api/payroll/periods")
    async def payroll_periods():
        """Generate the 4 most recent pay periods based on settings."""
        import yaml
        from datetime import timedelta

        entity_dir = get_entity_dir()
        config_path = entity_dir / 'config.yaml'
        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        payroll_cfg = config.get('payroll', {})

        length_days = payroll_cfg.get('period_length_days', 14)
        closing_day_name = payroll_cfg.get('period_closing_day', 'friday').lower()
        pay_by_offset = payroll_cfg.get('pay_by_days_after', 5)

        # Map day name to weekday number (0=Monday)
        day_map = {'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                   'friday': 4, 'saturday': 5, 'sunday': 6}
        closing_weekday = day_map.get(closing_day_name, 4)

        today = date.today()

        # Find the most recent closing day on or before today
        days_since_closing = (today.weekday() - closing_weekday) % 7
        if days_since_closing == 0 and today.weekday() == closing_weekday:
            most_recent_close = today
        else:
            most_recent_close = today - timedelta(days=days_since_closing)

        # Generate 4 recent periods working backwards
        periods = []
        close = most_recent_close
        for i in range(4):
            start = close - timedelta(days=length_days - 1)
            pay_by = close + timedelta(days=pay_by_offset)
            periods.append({
                'label': f"{start.strftime('%b %d')} – {close.strftime('%b %d, %Y')}",
                'start': start.isoformat(),
                'end': close.isoformat(),
                'pay_by': pay_by.isoformat(),
            })
            close = close - timedelta(days=length_days)

        return {'periods': periods}

    @app.get("/api/tax")
    async def tax():
        """Tax summary from hledger."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')
        try:
            # Get HST/tax related balances
            result = subprocess.run(
                ['hledger', '-f', journal, 'bal', 'tax', 'hst', 'gst', '--flat', '--no-total', '--output-format', 'csv'],
                capture_output=True, text=True
            )
            items = []
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n')[1:]:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        acct = parts[0]
                        amt_str = parts[1].replace(currency, '').strip().replace(',', '')
                        try:
                            amt = float(amt_str)
                        except ValueError:
                            amt = 0
                        items.append({'account': acct, 'amount': amt})
            return {'items': items, 'currency': currency}
        except Exception as e:
            return {'items': [], 'error': str(e)}

    @app.get("/api/tax/summary")
    async def tax_summary(period: str = ''):
        """HST collected vs paid vs net owing for a period."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        def bal(acct):
            cmd = ['hledger', '-f', journal, 'bal', acct, '-N', '--no-total', '--output-format', 'csv']
            if period:
                cmd += ['-p', period]
            r = subprocess.run(cmd, capture_output=True, text=True)
            total = 0.0
            if r.returncode == 0:
                for line in r.stdout.strip().split('\n')[1:]:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        v = parts[-1].replace(currency, '').replace(',', '').strip()
                        try:
                            total += float(v)
                        except ValueError:
                            pass
            return total

        collected = abs(bal('Liabilities:Current:HST Payable'))
        paid = 0.0
        for a in ('Assets:Current:HST Receivable', 'Expenses:HST Paid', 'Assets:Current:Input Tax Credits'):
            paid += abs(bal(a))
        return {'collected': round(collected, 2), 'paid': round(paid, 2),
                'net_owing': round(collected - paid, 2), 'currency': currency, 'period': period}

    @app.post("/api/tax/remit")
    async def tax_remit(req: TaxRemitRequest):
        """Record an HST remittance to CRA (pair 1000)."""
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')
        bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')
        if req.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than zero")
        d = req.date or date.today().isoformat()
        amt = money(req.amount)
        if req.period.strip():
            period_desc = req.period.strip()
        else:
            today = date.today()
            period_desc = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
        postings = [
            ('Liabilities:Current:HST Payable', currency, float(amt)),
            (bank, currency, float(-amt)),
        ]
        entry = format_entry(d, f"Tax remittance: HST {period_desc}", postings,
                             {'pair': '1000', 'remittance': 'hst', 'period': period_desc})
        year = d[:4]
        ensure_year_structure(int(year))
        append_journal(get_generated_dir() / year / "tax.journal", entry)
        _ensure_year_include(year, "tax.journal")
        return {'status': 'ok', 'message': f"Remittance recorded: {currency} {amt} ({period_desc})"}

    @app.get("/api/config")
    async def get_config():
        """Return editable entity settings."""
        config = load_config()
        p = config.get('pair', {})
        return {
            'name': p.get('name', ''),
            'slug': p.get('slug', ''),
            'currency': p.get('currency', 'CAD'),
            'divisions': config.get('divisions', []) or [],
            'accounts': config.get('accounts', {}) or {},
        }

    @app.post("/api/config")
    async def update_config(req: ConfigRequest):
        """Update entity name, currency, and divisions."""
        import re
        from lib.helpers import save_config
        config = load_config()
        config.setdefault('pair', {})
        if req.name.strip():
            config['pair']['name'] = req.name.strip()
        if req.currency.strip():
            config['pair']['currency'] = req.currency.strip()
        divs = []
        for d in (req.divisions or []):
            name = (d.get('name') or '').strip() if isinstance(d, dict) else ''
            if not name:
                continue
            slug = (d.get('slug') or '').strip() or re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            divs.append({'name': name, 'slug': slug})
        config['divisions'] = divs
        save_config(config)
        return {'status': 'ok', 'message': 'Settings saved'}

    @app.get("/api/export")
    async def export_data(format: str = 'csv', scope: str = 'all', query: str = '', period: str = ''):
        """Export journal data as a downloadable file (csv / json / beancount)."""
        import shlex
        from fastapi.responses import Response
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")
        entity = get_active_entity() or 'entity'

        scope_map = {'all': [], 'assets': ['type:a'], 'liabilities': ['type:l'],
                     'equity': ['type:e'], 'income': ['type:r'], 'expenses': ['type:x']}
        q = list(scope_map.get(scope, []))
        if query.strip():
            extra, err = _safe_query_terms(query)
            if err:
                raise HTTPException(status_code=400, detail=err)
            q += extra

        if format == 'csv':
            cmd = ['hledger', '-f', journal, 'bal'] + q + ['--layout', 'bare', '-N', '-O', 'csv']
            media, ext = 'text/csv', 'csv'
        elif format == 'json':
            cmd = ['hledger', '-f', journal, 'print'] + q + ['-O', 'json']
            media, ext = 'application/json', 'json'
        elif format == 'beancount':
            cmd = ['hledger', '-f', journal, 'print'] + q + ['-O', 'beancount']
            media, ext = 'text/plain', 'beancount'
        else:
            raise HTTPException(status_code=400, detail=f"Unknown format: {format}")

        if period.strip() and not period.strip().startswith('-'):
            cmd += ['-p', period.strip()]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise HTTPException(status_code=400, detail=r.stderr.strip() or 'Export failed')

        fname = f"{entity}-{scope}.{ext}"
        return Response(content=r.stdout, media_type=media,
                        headers={'Content-Disposition': f'attachment; filename="{fname}"'})

    @app.get("/api/status-items")
    async def status_items():
        """Pending items and status checks."""
        entity_dir = get_entity_dir()
        items = []

        # Check assets needing amortization
        import yaml
        assets_dir = entity_dir / 'assets'
        if assets_dir.exists():
            for f in assets_dir.glob('*.yaml'):
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                if not data.get('disposal') and data.get('useful_life_months'):
                    items.append({'type': 'asset', 'name': data.get('name', f.stem), 'status': 'active'})

        # Check liabilities with payments due
        liab_dir = entity_dir / 'liabilities'
        if liab_dir.exists():
            for f in liab_dir.glob('*.yaml'):
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                items.append({'type': 'liability', 'name': data.get('name', f.stem),
                             'status': f"${data.get('payment_amount', 0)}/mo"})

        # Check expiring contracts
        contracts_dir = entity_dir / 'contracts'
        if contracts_dir.exists():
            for f in contracts_dir.glob('*.yaml'):
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                end = data.get('end_date', '')
                status = data.get('status', 'unknown')
                items.append({'type': 'contract', 'name': data.get('name', f.stem),
                             'status': f"{status} (ends {end})" if end else status})

        return {'items': items}

    @app.get("/api/pairs-ref")
    async def pairs_ref():
        """Full pairs reference table."""
        from modules.pairs import PAIRS as ALL_PAIRS
        ref = []
        for p in ALL_PAIRS:
            ref.append({
                'num': p['num'], 'code': p['code'], 'name': p['name'],
                'normal': p['normal'], 'reversal': p['reversal'], 'edge': p['edge'],
            })
        return {'pairs': ref}

    # ─── Chart data endpoints ──────────────────────────────────────────────

    def _parse_hledger_monthly_csv(output, currency='CAD'):
        """Parse hledger monthly CSV into {labels: [...], datasets: [{name, data}]}."""
        lines = output.strip().split('\n')
        if len(lines) < 2:
            return {'labels': [], 'datasets': []}

        # Header row has account name then month columns
        header = [h.strip('"') for h in lines[0].split('","')]
        # Skip first column (account name), rest are months
        labels = header[1:]

        datasets = []
        for line in lines[1:]:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 2:
                continue
            name = parts[0]
            # Skip total/subtotal rows
            if name.lower() in ('total:', 'total', 'net:', '') or name.startswith(' '):
                continue
            values = []
            for v in parts[1:]:
                cleaned = v.replace(currency, '').replace(',', '').strip()
                try:
                    values.append(round(float(cleaned), 2))
                except (ValueError, TypeError):
                    values.append(0)
            datasets.append({'name': name, 'data': values})

        return {'labels': labels, 'datasets': datasets}

    @app.get("/api/chart/networth")
    async def chart_networth(period: str = '', value: str = ''):
        """Monthly net worth (assets + liabilities historical)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        cmd = ['hledger', '-f', journal, 'bal', 'assets', 'liabilities',
             '--historical', '-M', '--output-format', 'csv', '--row-total', '--no-elide']
        if value == 'market':
            cmd += ['-V']
        if period:
            cmd += ['-p', period]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {'labels': [], 'datasets': [], 'error': result.stderr}

        parsed = _parse_hledger_monthly_csv(result.stdout, currency)

        # Sum all accounts per month to get net worth line
        if parsed['datasets']:
            n_months = len(parsed['labels'])
            net = [0.0] * n_months
            assets_total = [0.0] * n_months
            liab_total = [0.0] * n_months
            for ds in parsed['datasets']:
                for i, v in enumerate(ds['data'][:n_months]):
                    if ds['name'].startswith('Assets:'):
                        assets_total[i] += v
                    elif ds['name'].startswith('Liabilities:'):
                        liab_total[i] += v
                    net[i] += v

            return {
                'labels': parsed['labels'],
                'datasets': [
                    {'name': 'Net Worth', 'data': [round(v, 2) for v in net]},
                    {'name': 'Assets', 'data': [round(v, 2) for v in assets_total]},
                    {'name': 'Liabilities', 'data': [round(abs(v), 2) for v in liab_total]},
                ],
                'currency': currency,
            }
        return {'labels': [], 'datasets': [], 'currency': currency}

    @app.get("/api/chart/revenue")
    async def chart_revenue():
        """Monthly revenue breakdown."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        result = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'income', '-M', '--output-format', 'csv', '--no-elide'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return {'labels': [], 'datasets': []}

        parsed = _parse_hledger_monthly_csv(result.stdout, currency)
        # Negate income (hledger shows as negative)
        for ds in parsed['datasets']:
            ds['data'] = [round(abs(v), 2) for v in ds['data']]
            # Shorten name
            ds['name'] = ds['name'].split(':')[-1]
        return {**parsed, 'currency': currency}

    @app.get("/api/chart/expenses")
    async def chart_expenses_monthly():
        """Monthly expense breakdown."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        result = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'expenses', '-M', '--output-format', 'csv', '--no-elide', '--depth', '3'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return {'labels': [], 'datasets': []}

        parsed = _parse_hledger_monthly_csv(result.stdout, currency)
        for ds in parsed['datasets']:
            ds['name'] = ds['name'].split(':')[-1]
        return {**parsed, 'currency': currency}

    @app.get("/api/chart/cashflow")
    async def chart_cashflow(value: str = ''):
        """Monthly cash balance (chequing + savings historical)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        cmd = ['hledger', '-f', journal, 'bal', 'assets:current',
               '--historical', '-M', '--output-format', 'csv', '--no-elide']
        if value == 'market':
            cmd += ['-V']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {'labels': [], 'datasets': []}

        parsed = _parse_hledger_monthly_csv(result.stdout, currency)
        # Sum all current assets per month
        if parsed['datasets']:
            n_months = len(parsed['labels'])
            total = [0.0] * n_months
            for ds in parsed['datasets']:
                for i, v in enumerate(ds['data'][:n_months]):
                    total[i] += v
            # Also keep individual lines
            short_datasets = [{'name': ds['name'].split(':')[-1], 'data': ds['data']} for ds in parsed['datasets']]
            short_datasets.insert(0, {'name': 'Total Cash', 'data': [round(v, 2) for v in total]})
            return {'labels': parsed['labels'], 'datasets': short_datasets, 'currency': currency}
        return {'labels': [], 'datasets': [], 'currency': currency}

    @app.get("/api/chart/prices")
    async def chart_prices():
        """Commodity price history from prices.journal."""
        entity_dir = get_entity_dir()
        prices_file = entity_dir / 'include' / 'prices.journal'
        if not prices_file.exists():
            return {'commodities': {}}

        commodities = {}
        with open(prices_file) as f:
            for line in f:
                line = line.strip()
                if not line.startswith('P '):
                    continue
                parts = line.split()
                # P 2026-01-02 "SHOP.TO" CAD 125.30
                if len(parts) >= 5:
                    pdate = parts[1]
                    symbol = parts[2].strip('"')
                    try:
                        price = float(parts[-1])
                    except ValueError:
                        continue
                    if symbol not in commodities:
                        commodities[symbol] = {'dates': [], 'prices': []}
                    commodities[symbol]['dates'].append(pdate)
                    commodities[symbol]['prices'].append(price)

        return {'commodities': commodities}

    @app.get("/api/chart/profitloss")
    async def chart_profitloss(period: str = ''):
        """Monthly profit/loss (revenue - expenses)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        # Get income
        cmd_inc = ['hledger', '-f', journal, 'bal', 'income', '-M', '--output-format', 'csv', '--no-elide', '--depth', '1']
        cmd_exp = ['hledger', '-f', journal, 'bal', 'expenses', '-M', '--output-format', 'csv', '--no-elide', '--depth', '1']
        if period:
            cmd_inc += ['-p', period]
            cmd_exp += ['-p', period]
        r_inc = subprocess.run(cmd_inc, capture_output=True, text=True)
        r_exp = subprocess.run(cmd_exp, capture_output=True, text=True)

        inc_parsed = _parse_hledger_monthly_csv(r_inc.stdout, currency) if r_inc.returncode == 0 else {'labels': [], 'datasets': []}
        exp_parsed = _parse_hledger_monthly_csv(r_exp.stdout, currency) if r_exp.returncode == 0 else {'labels': [], 'datasets': []}

        labels = inc_parsed['labels'] or exp_parsed['labels']
        n = len(labels)

        # Sum income (negate since hledger shows negative)
        income_total = [0.0] * n
        for ds in inc_parsed.get('datasets', []):
            for i, v in enumerate(ds['data'][:n]):
                income_total[i] += abs(v)

        # Sum expenses
        expense_total = [0.0] * n
        for ds in exp_parsed.get('datasets', []):
            for i, v in enumerate(ds['data'][:n]):
                expense_total[i] += v

        # Profit = income - expenses
        profit = [round(income_total[i] - expense_total[i], 2) for i in range(n)]

        return {
            'labels': labels,
            'datasets': [
                {'name': 'Revenue', 'data': [round(v, 2) for v in income_total]},
                {'name': 'Expenses', 'data': [round(v, 2) for v in expense_total]},
                {'name': 'Profit/Loss', 'data': profit},
            ],
            'currency': currency,
        }

    @app.get("/api/chart/assets")
    async def chart_assets(value: str = ''):
        """Monthly asset balances over time (stacked area), by top-level asset account.

        Replaces hledger-plot's 'assets monthly' preset.
        """
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        cmd = ['hledger', '-f', journal, 'bal', 'type:a', '--historical', '-M',
               '--output-format', 'csv', '--no-elide', '--depth', '2']
        if value == 'market':
            cmd += ['-V']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {'labels': [], 'datasets': [], 'error': result.stderr}
        parsed = _parse_hledger_monthly_csv(result.stdout, currency)
        for ds in parsed['datasets']:
            ds['name'] = ds['name'].split(':')[-1]
        return {**parsed, 'currency': currency}

    @app.get("/api/chart/query")
    async def chart_query(q: str = '', mode: str = 'line', value: str = ''):
        """Generic monthly balance chart for an arbitrary hledger query.

        Covers pair chart's bar/plot/vega — any account query, rendered monthly.
        The query is tokenised and passed as hledger arguments (no shell).
        """
        import shlex
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        query_args, err = _safe_query_terms(q)
        if err:
            raise HTTPException(status_code=400, detail=err)

        cmd = ['hledger', '-f', journal, 'bal'] + query_args + \
              ['-M', '--output-format', 'csv', '--no-elide', '--depth', '3']
        if value == 'market':
            cmd += ['-V']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {'labels': [], 'datasets': [], 'error': result.stderr.strip() or 'Query failed'}

        parsed = _parse_hledger_monthly_csv(result.stdout, currency)
        # Income/liability/equity read as credits (negative) in hledger — flip so charts read naturally
        for ds in parsed['datasets']:
            nm = ds['name']
            if nm.split(':')[0] in ('Income', 'Revenue', 'Liabilities', 'Equity'):
                ds['data'] = [round(-v, 2) for v in ds['data']]
            ds['name'] = nm.split(':')[-1]
        return {**parsed, 'currency': currency}

    def _period_totals(journal, query, currency, depth=2):
        """Return [(leaf_name, abs_amount)] for a single-period balance query."""
        cmd = ['hledger', '-f', journal, 'bal', query, '--depth', str(depth),
               '-N', '--no-total', '--output-format', 'csv', '--no-elide']
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = []
        if r.returncode != 0:
            return out
        lines = r.stdout.strip().split('\n')
        for line in lines[1:]:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 2:
                continue
            name = parts[0]
            val = parts[-1].replace(currency, '').replace(',', '').strip()
            try:
                amt = float(val)
            except ValueError:
                continue
            out.append((name.split(':')[-1], abs(round(amt, 2))))
        return out

    @app.get("/api/chart/sankey")
    async def chart_sankey():
        """Cash-flow sankey: revenue sources → Cash → expense categories (whole period).

        Reproduces hledger-sankey's flow view natively in Chart.js.
        """
        journal = _get_journal_path()
        if not journal:
            return {'flows': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        income = _period_totals(journal, 'type:r', currency, depth=3)
        expenses = _period_totals(journal, 'type:x', currency, depth=3)
        income_names = {n for n, _ in income}

        flows = []
        for name, amt in income:
            if amt > 0:
                flows.append({'from': name, 'to': 'Cash', 'flow': amt})
        for name, amt in expenses:
            if amt <= 0:
                continue
            # Avoid a cycle if an expense leaf shares a name with an income leaf or the hub
            to_name = name + ' ' if (name in income_names or name == 'Cash') else name
            flows.append({'from': 'Cash', 'to': to_name, 'flow': amt})
        return {'flows': flows, 'currency': currency}

    @app.get("/api/chart/treemap")
    async def chart_treemap():
        """Expense hierarchy treemap (leaf categories, whole period).

        Reproduces the 'treemap' chart as a real treemap via chartjs-chart-treemap.
        """
        journal = _get_journal_path()
        if not journal:
            return {'tree': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        cmd = ['hledger', '-f', journal, 'bal', 'type:x', '--depth', '3',
               '-N', '--no-total', '--output-format', 'csv', '--no-elide', '--layout', 'bare']
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return {'tree': [], 'error': r.stderr.strip()}

        batch_abbr = {'Operating': 'OP', 'Non-Operating': 'NO'}
        tree = []
        lines = r.stdout.strip().split('\n')
        for line in lines[1:]:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 2:
                continue
            segs = parts[0].replace('Expenses:', '').split(':')
            batch = segs[0]
            leaf = segs[-1]
            abbr = batch_abbr.get(batch, batch[:2].upper())
            val = parts[-1].replace(currency, '').replace(',', '').strip()
            try:
                amt = abs(float(val))
            except ValueError:
                continue
            if amt > 0:
                display = f"{abbr} · {leaf}" if leaf != batch else abbr
                tree.append({'name': display, 'value': round(amt, 2), 'group': abbr})
        tree.sort(key=lambda x: x['value'], reverse=True)
        return {'tree': tree, 'currency': currency}

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _load_yaml_dir(subdir):
        """Load all YAML files from an entity subdirectory."""
        import yaml
        entity_dir = get_entity_dir()
        target = entity_dir / subdir
        if not target.exists():
            return []
        items = []
        for f in sorted(target.glob('*.yaml')):
            try:
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                data['_file'] = f.name
                items.append(data)
            except Exception:
                continue
        return items

    def _get_journal_path():
        """Get the journal file path for hledger commands."""
        journal = str(get_entity_journal())
        if not Path(journal).exists():
            alt = Path(journal).parent / 'company.journal'
            if alt.exists():
                return str(alt)
            return None
        return journal

    return app


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Entry point for 'pair web'."""
    cmd_web(args)


def cmd_web(args):
    """Start the PWA server."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    port = 8100
    for i, a in enumerate(remaining):
        if a == '--port' and i + 1 < len(remaining):
            port = int(remaining[i + 1])

    entity_name = get_entity_name()
    print(f"  [{entity_name}] Starting Pairs PWA on http://localhost:{port}")
    print(f"  Press Ctrl+C to stop.\n")

    # Open browser
    webbrowser.open(f"http://localhost:{port}")

    # Use the venv python which has fastapi/uvicorn installed
    venv_python = BASE_DIR / '.venv' / 'bin' / 'python'
    if not venv_python.exists():
        print("  Error: .venv not found. Run: python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn")
        sys.exit(1)

    # Launch uvicorn via venv python
    try:
        subprocess.run(
            [str(venv_python), '-m', 'uvicorn',
             'modules.web:create_app', '--factory',
             '--host', '127.0.0.1',
             '--port', str(port),
             '--log-level', 'warning'],
            cwd=str(BASE_DIR)
        )
    except KeyboardInterrupt:
        print("\n  Server stopped.")


def print_help():
    print("""pair web — Pairs PWA server

  Starts a local web server for progressive entry assembly.
  Installable as a PWA on any device.

Usage:
  pair web                Start on port 8100
  pair web --port 9000    Use custom port

The server provides:
  - Link mode entry UI (same as pair . / pair link)
  - All 14 pair expressions
  - Fuzzy account search
  - Progressive assembly preview
  - Writes to generated/<year>/links.journal

Open http://localhost:8100 in any browser.
""")
