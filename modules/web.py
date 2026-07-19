"""pair web — PWA server for progressive entry assembly.

Starts a local FastAPI server serving the link-mode PWA.
"""

import sys
import os
import subprocess
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
from lib.ui import get_entity_journal, get_entity_name, require_entity
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
    async def recent(limit: int = 20):
        """Recent journal entries, grouped by transaction."""
        journal = _get_journal_path()
        if not journal:
            raise HTTPException(status_code=404, detail="No journal found")

        try:
            result = subprocess.run(
                ['hledger', '-f', journal, 'register', '--output-format', 'csv'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return {'entries': []}

            lines = result.stdout.strip().split('\n')
            if len(lines) <= 1:
                return {'entries': []}

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

            # Return last N transactions
            entries = [txns[idx] for idx in txn_order[-limit:]]
            return {'entries': entries}
        except Exception as e:
            return {'entries': [], 'error': str(e)}

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
            hledger_cmd += args.split()

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
        if not slug:
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
        from lib.yaml_store import delete_entity, entity_exists
        if not entity_exists('assets', slug):
            raise HTTPException(status_code=404, detail=f"Asset '{slug}' not found")
        delete_entity('assets', slug)
        return {'status': 'ok', 'message': f"Asset '{slug}' deleted'"}

    @app.get("/api/liabilities")
    async def liabilities():
        """List all liabilities from YAML."""
        return {'items': _load_yaml_dir('liabilities')}

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
                'tags': c.get('tags', []),
                'latest_price': latest.get('price'),
                'latest_date': latest.get('date', ''),
            })

        return {'items': items, 'currency': currency}

    @app.get("/api/payroll")
    async def payroll_list():
        """List payroll data: employees from contracts + recent pay runs."""
        import yaml
        entity_dir = get_entity_dir()
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        # Get employees from employment contracts
        employees = []
        contracts_dir = entity_dir / 'contracts'
        contacts_dir = entity_dir / 'contacts'
        if contracts_dir.exists():
            for f in contracts_dir.glob('*.yaml'):
                with open(f) as fh:
                    data = yaml.safe_load(fh) or {}
                if data.get('type') == 'employment' and data.get('status') == 'active':
                    # Get contact name
                    contact_slug = None
                    for party in data.get('parties', []):
                        if party.get('role') == 'employee':
                            contact_slug = party.get('contact')
                    name = data.get('name', '')
                    if contact_slug and contacts_dir.exists():
                        cf = contacts_dir / f"{contact_slug}.yaml"
                        if cf.exists():
                            with open(cf) as cfh:
                                contact = yaml.safe_load(cfh) or {}
                            name = contact.get('name', contact_slug)
                    employees.append({
                        'name': name,
                        'slug': contact_slug or '',
                        'salary': data.get('value', 0),
                        'schedule': data.get('payment_schedule', 'biweekly'),
                        'start_date': data.get('start_date', ''),
                        'currency': data.get('currency', currency),
                    })

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
    async def chart_networth():
        """Monthly net worth (assets + liabilities historical)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        result = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'assets', 'liabilities',
             '--historical', '-M', '--output-format', 'csv', '--row-total', '--no-elide'],
            capture_output=True, text=True
        )
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
    async def chart_cashflow():
        """Monthly cash balance (chequing + savings historical)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        result = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'assets:current',
             '--historical', '-M', '--output-format', 'csv', '--no-elide'],
            capture_output=True, text=True
        )
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
    async def chart_profitloss():
        """Monthly profit/loss (revenue - expenses)."""
        journal = _get_journal_path()
        if not journal:
            return {'labels': [], 'datasets': []}
        config = load_config()
        currency = config.get('pair', {}).get('currency', 'CAD')

        # Get income
        r_inc = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'income', '-M', '--output-format', 'csv', '--no-elide', '--depth', '1'],
            capture_output=True, text=True
        )
        # Get expenses
        r_exp = subprocess.run(
            ['hledger', '-f', journal, 'bal', 'expenses', '-M', '--output-format', 'csv', '--no-elide', '--depth', '1'],
            capture_output=True, text=True
        )

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
