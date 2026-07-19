"""pair link — CLI progressive entry assembly via gum.

All 14 accounting pairs addressable via minimal expressions:
  <      Op expense paid from asset
  >      Op expense on credit
  <<     Non-op expense from asset (amortization)
  >>     Non-op expense on credit (interest)
  <.     Op income received as asset
  >.     Op income recognized from liability
  <<.    Non-op income received as asset
  >>.    Non-op income from liability
  <.>    Asset acquired via liability (loan)
  <..    Asset from equity (owner invested)
  >..    Liability from equity (dividend)
  ..<    Asset to asset (internal transfer)
  ..>    Liability to liability (refinance)
  ..     Equity to equity (reclassify)

Append / for reversal. Amount optional after space.
"""

import sys
import subprocess
import shutil
from datetime import date
from decimal import Decimal

from lib.helpers import (
    load_config, money, parse_global_flags, get_active_entity
)
from lib.ui import get_entity_journal, get_entity_name, require_entity
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, get_generated_dir
)


# ─── The 14 pair expressions ────────────────────────────────────────────────

PAIRS = {
    '<': {
        'num': 1, 'name': 'OpExp / Asset',
        'desc': 'Paid operating expense',
        'first_filter': ['Assets:Current'],
        'second_filter': ['Expenses:Operating'],
        'first_prompt': 'paid from?',
        'second_prompt': 'for what?',
        'first_is_credit': True,
    },
    '>': {
        'num': 2, 'name': 'OpExp / Liability',
        'desc': 'Expense on credit',
        'first_filter': ['Liabilities:Current', 'Liabilities:Credit'],
        'second_filter': ['Expenses:Operating'],
        'first_prompt': 'charged to?',
        'second_prompt': 'for what?',
        'first_is_credit': True,
    },
    '<<': {
        'num': 3, 'name': 'NonOpExp / Asset',
        'desc': 'Amortization / write-down',
        'first_filter': ['Assets:Fixed', 'Assets:Accumulated'],
        'second_filter': ['Expenses:Non-Operating'],
        'first_prompt': 'which asset?',
        'second_prompt': 'expense type?',
        'first_is_credit': True,
    },
    '>>': {
        'num': 4, 'name': 'NonOpExp / Liability',
        'desc': 'Interest accrued',
        'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current'],
        'second_filter': ['Expenses:Non-Operating'],
        'first_prompt': 'which debt?',
        'second_prompt': 'expense type?',
        'first_is_credit': True,
    },
    '<.': {
        'num': 5, 'name': 'OpIncome / Asset',
        'desc': 'Revenue received',
        'first_filter': ['Assets:Current'],
        'second_filter': ['Income:Operating'],
        'first_prompt': 'received into?',
        'second_prompt': 'income type?',
        'first_is_credit': False,
    },
    '>.': {
        'num': 6, 'name': 'OpIncome / Liability',
        'desc': 'Deferred revenue recognized',
        'first_filter': ['Liabilities:Current', 'Liabilities:Deferred'],
        'second_filter': ['Income:Operating'],
        'first_prompt': 'from which liability?',
        'second_prompt': 'income type?',
        'first_is_credit': False,
    },
    '<<.': {
        'num': 7, 'name': 'NonOpIncome / Asset',
        'desc': 'Non-op income received',
        'first_filter': ['Assets:Current'],
        'second_filter': ['Income:Non-Operating'],
        'first_prompt': 'received into?',
        'second_prompt': 'income type?',
        'first_is_credit': False,
    },
    '>>.': {
        'num': 8, 'name': 'NonOpIncome / Liability',
        'desc': 'Debt forgiveness / non-op gain',
        'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current'],
        'second_filter': ['Income:Non-Operating'],
        'first_prompt': 'which liability?',
        'second_prompt': 'income type?',
        'first_is_credit': False,
    },
    '<.>': {
        'num': 9, 'name': 'Asset / Liability',
        'desc': 'Received loan proceeds',
        'first_filter': ['Assets:Current'],
        'second_filter': ['Liabilities:Long-Term', 'Liabilities:Current'],
        'first_prompt': 'cash into?',
        'second_prompt': 'which debt?',
        'first_is_credit': False,
    },
    '<..': {
        'num': 10, 'name': 'Asset / Equity',
        'desc': 'Owner invested',
        'first_filter': ['Assets:Current', 'Assets:Fixed'],
        'second_filter': ['Equity'],
        'first_prompt': 'received into?',
        'second_prompt': 'equity type?',
        'first_is_credit': False,
    },
    '>..': {
        'num': 11, 'name': 'Liability / Equity',
        'desc': 'Dividend declared',
        'first_filter': ['Equity'],
        'second_filter': ['Liabilities:Current', 'Liabilities:Dividends'],
        'first_prompt': 'from equity?',
        'second_prompt': 'to which liability?',
        'first_is_credit': False,
    },
    '..<': {
        'num': 12, 'name': 'Asset / Asset',
        'desc': 'Internal transfer',
        'first_filter': ['Assets:Current', 'Assets:Fixed'],
        'second_filter': ['Assets:Current', 'Assets:Fixed'],
        'first_prompt': 'receiving account?',
        'second_prompt': 'sending account?',
        'first_is_credit': False,
    },
    '..>': {
        'num': 13, 'name': 'Liability / Liability',
        'desc': 'Refinance / consolidate',
        'first_filter': ['Liabilities:Long-Term', 'Liabilities:Current', 'Liabilities:Credit'],
        'second_filter': ['Liabilities:Long-Term', 'Liabilities:Current', 'Liabilities:Credit'],
        'first_prompt': 'old debt (retiring)?',
        'second_prompt': 'new debt (replacing)?',
        'first_is_credit': False,
    },
    '..': {
        'num': 14, 'name': 'Equity / Equity',
        'desc': 'Reclassify / year-end close',
        'first_filter': ['Equity'],
        'second_filter': ['Equity'],
        'first_prompt': 'from bucket?',
        'second_prompt': 'to bucket?',
        'first_is_credit': False,
    },
}

# Parse order: longest expressions first
EXPR_PARSE_ORDER = [
    '<<.', '>>.', '<.>', '<..', '>..',
    '..<', '..>', '..',
    '<<', '>>', '<.', '>.',
    '<', '>',
]

# Leaf display prefixes
KNOWN_PREFIXES = [
    'Assets:Accumulated Amortization:',
    'Assets:Current:',
    'Assets:Fixed:',
    'Liabilities:Long-Term:',
    'Liabilities:Current:',
    'Liabilities:',
    'Expenses:Non-Operating:',
    'Expenses:Operating:',
    'Income:Non-Operating:',
    'Income:Operating:',
    'Equity:',
]

PREFIX_HINTS = {
    'Assets:Accumulated Amortization:': 'Accum',
    'Assets:Current:': 'Current',
    'Assets:Fixed:': 'Fixed',
    'Liabilities:Long-Term:': 'Long-Term',
    'Liabilities:Current:': 'Current',
    'Liabilities:': 'Liab',
    'Expenses:Non-Operating:': 'Non-Op',
    'Expenses:Operating:': 'Op',
    'Income:Non-Operating:': 'Non-Op',
    'Income:Operating:': 'Op',
    'Equity:': 'Equity',
}


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Entry point for 'pair link'."""
    cmd_link(args)


def cmd_link(args):
    """Progressive entry assembly via gum CLI."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    if not shutil.which('gum'):
        print("  'gum' is required for link mode.")
        print("  Install: https://github.com/charmbracelet/gum")
        sys.exit(1)

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    entity_name = get_entity_name()
    today = flags.get('date') or date.today().strftime("%Y-%m-%d")

    accounts = _get_accounts()
    if not accounts:
        print("  No accounts found. Run 'pair generate' first.")
        sys.exit(1)

    # ─── Step 1: Expression input ────────────────────────────────────────
    expr, amount, reversal = _prompt_expression(entity_name)
    if expr is None:
        return

    pair = PAIRS[expr]

    # ─── Step 2: First account ───────────────────────────────────────────
    filtered = _filter_accounts(accounts, pair['first_filter'])
    if not filtered:
        filtered = accounts

    leaf_items, leaf_map = _make_leaf_display(filtered)
    header = f"[{pair['num']}] {pair['name']} — {pair['first_prompt']}"

    picked = _gum_filter(leaf_items, header=header, prompt='⊹ ')
    if not picked:
        return
    first_account = leaf_map.get(picked, picked)

    # ─── Step 3: Second account ──────────────────────────────────────────
    counter_filtered = _filter_accounts(accounts, pair['second_filter'])
    counter_filtered = [a for a in counter_filtered if a != first_account]
    if not counter_filtered:
        counter_filtered = [a for a in accounts if a != first_account]

    if len(counter_filtered) == 1:
        second_account = counter_filtered[0]
    else:
        leaf_items, leaf_map = _make_leaf_display(counter_filtered)
        preview = _build_preview(today, first_account, None, amount, currency, pair, reversal)

        picked = _gum_filter(leaf_items, header=preview, prompt='→ ')
        if not picked:
            return
        second_account = leaf_map.get(picked, picked)

    # ─── Step 4: Amount ──────────────────────────────────────────────────
    if not amount:
        preview = _build_preview(today, first_account, second_account, None, currency, pair, reversal)
        amount_str = _gum_input(placeholder='0.00', header=preview, prompt='amount: ')
        if not amount_str:
            return
        try:
            amount = money(amount_str)
        except Exception:
            print("  Invalid amount.")
            return

    # ─── Step 5: Description ─────────────────────────────────────────────
    auto_desc = _auto_description(first_account, second_account, pair, reversal)
    preview = _build_preview(today, first_account, second_account, amount, currency, pair, reversal)
    desc = _gum_input(placeholder=auto_desc, header=preview, prompt='desc: ')
    if desc is None:
        return
    if not desc.strip():
        desc = auto_desc

    # ─── Step 6: Assemble and confirm ────────────────────────────────────
    if pair['first_is_credit']:
        debit_account = second_account
        credit_account = first_account
    else:
        debit_account = first_account
        credit_account = second_account

    if reversal:
        debit_account, credit_account = credit_account, debit_account

    postings = [
        (debit_account, currency, float(amount)),
        (credit_account, currency, float(-amount)),
    ]

    tags = {'mode': 'link', 'pair': str(pair['num']), 'expr': expr}
    if reversal:
        tags['reversal'] = 'true'

    entry = format_entry(today, desc, postings, tags)

    _gum_style(entry.strip(), border='rounded', border_foreground='240')

    if not _gum_confirm("Write this entry?"):
        print("  Cancelled.")
        return

    year = today[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "links.journal"
    append_journal(journal_path, entry)

    print(f"  ✓ generated/{year}/links.journal")


# ─── Leaf display ────────────────────────────────────────────────────────────

def _make_leaf_display(accounts):
    """Create leaf-name display list and mapping back to full paths."""
    display_map = {}
    display_items = []

    for acct in accounts:
        short = acct
        hint = ''

        for prefix in KNOWN_PREFIXES:
            if acct.startswith(prefix):
                short = acct[len(prefix):]
                hint = PREFIX_HINTS.get(prefix, '')
                break

        if hint:
            display = f"{short} ({hint})"
        else:
            display = short

        display_items.append(display)
        display_map[display] = acct

    return display_items, display_map


# ─── Account helpers ──────────────────────────────────────────────────────────

def _get_accounts():
    """Get account list from hledger."""
    journal = str(get_entity_journal())

    from pathlib import Path
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
        unique = []
        for a in accounts:
            if a not in seen:
                seen.add(a)
                unique.append(a)
        return unique
    except Exception:
        return []


def _filter_accounts(accounts, prefixes):
    """Filter accounts to those matching any of the given prefixes."""
    return [a for a in accounts if any(a.startswith(p) for p in prefixes)]


# ─── Expression parsing ───────────────────────────────────────────────────────

def _parse_expression(raw):
    """Parse expression from input string.

    Returns: (expression, amount_or_None, reversal_bool)
    """
    raw = raw.strip()

    token_parts = raw.split(None, 1)
    token = token_parts[0]
    amount_str = token_parts[1] if len(token_parts) > 1 else None

    reversal = '/' in token
    token = token.replace('/', '')

    expr = None
    remainder = ''
    for candidate in EXPR_PARSE_ORDER:
        if token.startswith(candidate):
            expr = candidate
            remainder = token[len(candidate):]
            break

    if expr is None:
        return None, None, False

    amount = None
    if remainder:
        try:
            amount = money(remainder)
        except Exception:
            pass

    if amount is None and amount_str:
        try:
            amount = money(amount_str)
        except Exception:
            pass

    return expr, amount, reversal


# ─── Gum wrappers ────────────────────────────────────────────────────────────

def _gum_filter(options, header='', prompt='> '):
    """Fuzzy filter selection via gum."""
    try:
        cmd = ['gum', 'filter',
               '--header', header,
               '--prompt', prompt,
               '--placeholder', 'type to filter...',
               '--height', '12'] + options
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _gum_input(placeholder='', header='', prompt='> ', value=''):
    """Text input via gum."""
    try:
        cmd = ['gum', 'input',
               '--placeholder', placeholder,
               '--prompt', prompt,
               '--header', header]
        if value:
            cmd += ['--value', value]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _gum_confirm(prompt_text):
    """Yes/no confirmation via gum."""
    result = subprocess.run(['gum', 'confirm', prompt_text], stderr=None)
    return result.returncode == 0


def _gum_style(text, border='rounded', border_foreground='240'):
    """Display styled text via gum."""
    subprocess.run(
        ['gum', 'style', '--border', border,
         '--border-foreground', border_foreground,
         '--padding', '0 1', '--margin', '0 2'],
        input=text, text=True, stderr=None
    )


# ─── Expression prompt ────────────────────────────────────────────────────────

def _prompt_expression(entity_name):
    """Prompt for expression via gum input."""
    header = f"[{entity_name}] link"
    raw = _gum_input(
        placeholder='< > << >> <. >. <<. >>. <.> <.. >.. ..< ..> .. (/ = reversal)',
        header=header,
        prompt='⊹ '
    )

    if not raw:
        return None, None, False

    return _parse_expression(raw)


# ─── Preview builder ─────────────────────────────────────────────────────────

def _build_preview(entry_date, first, second, amount, currency, pair, reversal):
    """Build progressive assembly preview string for gum header."""
    rev_mark = ' (reversal)' if reversal else ''

    def _leaf(acct):
        for prefix in KNOWN_PREFIXES:
            if acct.startswith(prefix):
                return acct[len(prefix):]
        return acct

    lines = [f"[{pair['num']}] {pair['name']}{rev_mark}", '']
    lines.append(entry_date)

    if first and amount:
        lines.append(f"  {_leaf(first):<30} {currency} {amount}")
    elif first:
        lines.append(f"  {_leaf(first):<30} ?")
    else:
        lines.append(f"  {'...':<30} ?")

    if second and amount:
        lines.append(f"  {_leaf(second):<30} {currency} -{amount}")
    elif second:
        lines.append(f"  {_leaf(second):<30} ?")
    else:
        lines.append(f"  {'...':<30} ?")

    return '\n'.join(lines)


# ─── Description auto-generation ─────────────────────────────────────────────

def _auto_description(first, second, pair, reversal):
    """Generate description from accounts and pair info."""
    def leaf(acct):
        return acct.split(':')[-1]

    prefix = "Reversal: " if reversal else ""

    if pair['first_is_credit']:
        desc = leaf(second)
    else:
        desc = leaf(second) if second else leaf(first)

    return f"{prefix}{desc}"


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair link — CLI progressive entry assembly (gum)

  All 14 accounting pairs via minimal expressions.
  Fuzzy account selection with leaf-name display.

Expressions:
  <       Op expense paid from asset          (paid bill)
  >       Op expense on credit                (charged to card)
  <<      Non-op expense from asset           (amortization)
  >>      Non-op expense on credit            (interest accrued)
  <.      Op income received as asset         (client paid)
  >.      Op income recognized from liability (deferred rev)
  <<.     Non-op income received as asset     (interest income)
  >>.     Non-op income from liability        (debt forgiven)
  <.>     Asset from liability                (received loan)
  <..     Asset from equity                   (owner invested)
  >..     Liability from equity               (dividend declared)
  ..<     Asset to asset                      (internal transfer)
  ..>     Liability to liability              (refinance)
  ..      Equity to equity                    (year-end close)

Modifiers:
  /       Reversal (e.g. </ = refund, <.>/ = returned loan)
  amount  Inline (e.g. < 3650, <. 4500)

Examples:
  < 3650        Paid $3,650 op expense from bank
  <. 4500       Received $4,500 revenue
  << 416.67     Amortization entry
  ..<  5000     Transfer $5,000 between accounts
  </  150       Refund of $150

Requires: gum (https://github.com/charmbracelet/gum)
""")
