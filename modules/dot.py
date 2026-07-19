"""pair . — rofi popup link mode for progressive entry assembly.

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

# Display order for the direction menu
DIRECTION_MENU = [
    '<', '>', '<<', '>>', '<.', '>.', '<<.', '>>.',
    '<.>', '<..', '>..', '..<', '..>', '..',
]


# ─── Rofi theme ──────────────────────────────────────────────────────────────

ROFI_THEME = """
* {
    bg: #282c34;
    bg-alt: #21252b;
    fg: #abb2bf;
    fg-dim: #5c6370;
    accent: #61afef;
    green: #98c379;
    border-col: #3e4452;
}

window {
    width: 900px;
    height: 440px;
    border: 2px;
    border-color: @border-col;
    border-radius: 8px;
    background-color: @bg;
}

mainbox {
    orientation: horizontal;
    children: [ "left-panel", "right-panel" ];
    spacing: 0;
    background-color: @bg;
}

left-panel {
    orientation: vertical;
    children: [ "inputbar", "listview" ];
    width: 480px;
    background-color: @bg;
}

inputbar {
    padding: 14px 16px;
    background-color: @bg;
    text-color: @fg;
    children: [ "prompt", "entry" ];
    spacing: 8px;
}

prompt {
    text-color: @accent;
}

entry {
    text-color: @fg;
    placeholder-color: @fg-dim;
}

listview {
    lines: 14;
    padding: 4px 8px;
    scrollbar: false;
    fixed-height: true;
    background-color: @bg;
    border: 1px 0 0 0;
    border-color: @border-col;
}

element {
    padding: 4px 16px;
    background-color: @bg;
    text-color: @fg;
}

element selected {
    background-color: @border-col;
    text-color: @accent;
}

right-panel {
    orientation: vertical;
    children: [ "message" ];
    width: 420px;
    background-color: @bg-alt;
    border: 0 0 0 1px;
    border-color: @border-col;
}

message {
    padding: 14px 16px;
    background-color: @bg-alt;
}

textbox {
    text-color: @green;
    background-color: @bg-alt;
}
"""


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch(args):
    """Entry point for 'pair .'."""
    cmd_dot(args)


def cmd_dot(args):
    """Rofi popup link mode."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_help()
        return

    require_entity()

    if not shutil.which('rofi'):
        print("  'rofi' is required for popup link mode.")
        print("  Install: sudo apt install rofi")
        sys.exit(1)

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    entity_name = get_entity_name()
    today = flags.get('date') or date.today().strftime("%Y-%m-%d")

    # Get entity accounts
    accounts = _get_accounts()
    if not accounts:
        print("  No accounts found. Run 'pair generate' first.")
        sys.exit(1)

    # ─── Step 1: Direction ───────────────────────────────────────────────
    direction_input = _rofi_direction(entity_name)
    if not direction_input:
        return

    expr, amount, reversal = _parse_expression(direction_input)
    if expr is None:
        return

    pair = PAIRS[expr]

    # ─── Step 2: First account ───────────────────────────────────────────
    filtered = _filter_accounts(accounts, pair['first_filter'])
    if not filtered:
        filtered = accounts

    display_items, display_map = _make_leaf_display(filtered)
    mesg = _build_mesg(today, None, None, amount, currency, pair, reversal)

    picked = _rofi_select(
        display_items,
        prompt=pair['first_prompt'],
        mesg=mesg
    )
    if not picked:
        return
    first_account = display_map.get(picked, picked)

    # ─── Step 3: Second account (counterpart) ────────────────────────────
    counter_filtered = _filter_accounts(accounts, pair['second_filter'])
    counter_filtered = [a for a in counter_filtered if a != first_account]
    if not counter_filtered:
        counter_filtered = [a for a in accounts if a != first_account]

    # Auto-resolve if only one option
    if len(counter_filtered) == 1:
        second_account = counter_filtered[0]
    else:
        display_items, display_map = _make_leaf_display(counter_filtered)
        mesg = _build_mesg(today, first_account, None, amount, currency, pair, reversal)

        picked = _rofi_select(
            display_items,
            prompt=pair['second_prompt'],
            mesg=mesg
        )
        if not picked:
            return
        second_account = display_map.get(picked, picked)

    # ─── Step 4: Amount ──────────────────────────────────────────────────
    if not amount:
        mesg = _build_mesg(today, first_account, second_account, None, currency, pair, reversal)
        amount_str = _rofi_input(
            prompt='amount:',
            mesg=mesg,
            placeholder='0.00'
        )
        if not amount_str:
            return
        try:
            amount = money(amount_str)
        except Exception:
            _rofi_error("Invalid amount")
            return

    # ─── Step 5: Description ─────────────────────────────────────────────
    auto_desc = _auto_description(first_account, second_account, pair, reversal)
    mesg = _build_mesg(today, first_account, second_account, amount, currency, pair, reversal)
    desc = _rofi_input(
        prompt='desc:',
        mesg=mesg,
        value=auto_desc
    )
    if desc is None:
        return
    if not desc.strip():
        desc = auto_desc

    # ─── Step 6: Assemble entry ──────────────────────────────────────────
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

    # ─── Step 7: Confirm ─────────────────────────────────────────────────
    confirmed = _rofi_confirm(entry.strip())
    if not confirmed:
        return

    # Write
    year = today[:4]
    ensure_year_structure(int(year))
    journal_path = get_generated_dir() / year / "links.journal"
    append_journal(journal_path, entry)

    _rofi_notify(f"✓ written to generated/{year}/links.journal")


# ─── Leaf display ────────────────────────────────────────────────────────────

# Known prefixes to strip for display (order matters — longest first)
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

# Short category hints for display
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


def _make_leaf_display(accounts):
    """Create leaf-name display list and mapping back to full paths.

    Returns: (display_list, display_to_full_map)
    """
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

        # Format: "Short Name              (hint)"
        if hint:
            display = f"{short:<32} ({hint})"
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

# Parse order: longest expressions first to avoid prefix collisions
EXPR_PARSE_ORDER = [
    '<<.', '>>.', '<.>', '<..', '>..',
    '..<', '..>', '..',
    '<<', '>>', '<.', '>.',
    '<', '>',
]


def _parse_expression(raw):
    """Parse a pair expression from rofi input.

    Handles:
      "<<   3  NonOpExp / Asset  Amortization"  (menu selection)
      "<< 416.67"                                (typed with amount)
      "</  150"                                  (reversal with amount)

    Returns: (expression, amount_or_None, reversal_bool)
    """
    raw = raw.strip()

    # If it came from menu selection, extract the expression (first token)
    # Menu format: "<    1  OpExp / Asset          Paid operating expense"
    parts = raw.split()
    if len(parts) >= 3:
        # Check if first token is a valid expression
        candidate = parts[0]
        if candidate.rstrip('/') in PAIRS:
            expr = candidate.rstrip('/')
            reversal = candidate.endswith('/')
            return expr, None, reversal

    # Typed input — parse expression + reversal + amount
    # Split on first space for amount
    token_parts = raw.split(None, 1)
    token = token_parts[0]
    amount_str = token_parts[1] if len(token_parts) > 1 else None

    reversal = '/' in token
    token = token.replace('/', '')

    # Match expression (longest first)
    expr = None
    remainder = ''
    for candidate in EXPR_PARSE_ORDER:
        if token.startswith(candidate):
            expr = candidate
            remainder = token[len(candidate):]
            break

    if expr is None:
        return None, None, False

    # Remainder might be a number (e.g., "<500" with no space)
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


# ─── Rofi wrappers ───────────────────────────────────────────────────────────

def _pango_escape(text):
    """Escape text for pango markup."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def _rofi_select(options, prompt='>', mesg=''):
    """Show rofi dmenu with options and return selection."""
    cmd = [
        'rofi', '-dmenu',
        '-i',
        '-p', prompt,
        '-theme-str', ROFI_THEME,
    ]
    if mesg:
        cmd += ['-mesg', _pango_escape(mesg)]

    try:
        result = subprocess.run(
            cmd,
            input='\n'.join(options),
            stdout=subprocess.PIPE, stderr=None,
            text=True
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _rofi_input(prompt='>', mesg='', value='', placeholder=''):
    """Show rofi in input-only mode."""
    cmd = [
        'rofi', '-dmenu',
        '-p', prompt,
        '-theme-str', ROFI_THEME,
        '-theme-str', 'listview { lines: 0; }',
        '-theme-str', 'entry { placeholder: "' + (placeholder or '') + '"; }',
    ]
    if mesg:
        cmd += ['-mesg', _pango_escape(mesg)]

    input_text = value if value else ''

    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            stdout=subprocess.PIPE, stderr=None,
            text=True
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _rofi_confirm(entry_text):
    """Show entry and ask for confirmation."""
    options = ['✓ Write', '✗ Cancel']
    cmd = [
        'rofi', '-dmenu',
        '-p', 'confirm:',
        '-mesg', _pango_escape(entry_text),
        '-theme-str', ROFI_THEME,
        '-theme-str', 'listview { lines: 2; }',
        '-only-match',
    ]

    try:
        result = subprocess.run(
            cmd,
            input='\n'.join(options),
            stdout=subprocess.PIPE, stderr=None,
            text=True
        )
        if result.returncode != 0:
            return False
        return '✓' in result.stdout
    except (KeyboardInterrupt, EOFError):
        return False


def _rofi_direction(entity_name):
    """Show all 14 pair expressions as menu."""
    options = []
    for expr in DIRECTION_MENU:
        p = PAIRS[expr]
        options.append(f"{expr:<5} {p['num']:<3} {p['name']:<22} {p['desc']}")

    mesg = f"[{entity_name}]  select or type expression"

    cmd = [
        'rofi', '-dmenu',
        '-p', '⊹',
        '-mesg', _pango_escape(mesg),
        '-theme-str', ROFI_THEME,
        '-theme-str', 'listview { lines: 14; }',
    ]

    try:
        result = subprocess.run(
            cmd,
            input='\n'.join(options),
            stdout=subprocess.PIPE, stderr=None,
            text=True
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _rofi_error(msg):
    """Flash an error message."""
    subprocess.run(
        ['rofi', '-e', msg, '-theme-str', ROFI_THEME],
        stderr=None
    )


def _rofi_notify(msg):
    """Success notification."""
    if shutil.which('notify-send'):
        subprocess.run(
            ['notify-send', '--app-name', 'pair', 'pair .', msg],
            stderr=None
        )
    else:
        subprocess.run(
            ['rofi', '-e', msg, '-theme-str', ROFI_THEME],
            stderr=None
        )


# ─── Preview builder ─────────────────────────────────────────────────────────

def _build_mesg(entry_date, first, second, amount, currency, pair, reversal):
    """Build plain text preview for the right panel."""
    rev_mark = ' (reversal)' if reversal else ''
    expr_display = f"[{pair['num']}] {pair['name']}"

    lines = []
    lines.append(f"{expr_display}{rev_mark}")
    lines.append(f"{pair['desc']}")
    lines.append('')
    lines.append(entry_date)

    def _leaf(acct):
        for prefix in KNOWN_PREFIXES:
            if acct.startswith(prefix):
                return acct[len(prefix):]
        return acct

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

    # Use the more descriptive account (usually the expense/income side)
    if pair['first_is_credit']:
        # First is the funding source, second is the purpose
        desc = leaf(second)
    else:
        # First is the destination, second is the source
        desc = leaf(second) if second else leaf(first)

    return f"{prefix}{desc}"


# ─── Help ─────────────────────────────────────────────────────────────────────

def print_help():
    print("""pair . — rofi popup link mode

  All 14 accounting pairs via minimal expressions.
  Floating popup with progressive entry assembly.

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
  >> 179        Interest accrued
  ..<  5000     Transfer $5,000 between accounts
  </  150       Refund of $150

Requires: rofi (sudo apt install rofi)
""")
