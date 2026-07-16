"""pair pairs / pair — account pair reference and interactive entry creation."""

import sys
from datetime import date

from lib.helpers import (
    load_config, money, prompt, prompt_choice, confirm,
    validate_date, validate_positive_number, parse_global_flags
)
from lib.journal import (
    format_entry, append_journal, ensure_year_structure, GENERATED_DIR
)

try:
    from lib.journal import build_tags
except ImportError:
    build_tags = None


# ─── The 14 Account Pairs ───────────────────────────────────────────────────

PAIRS = [
    {
        'code': '0000',
        'num': 1,
        'name': 'Op Expense / Asset',
        'group': 'expense',
        'normal': 'Pay operating expense from bank',
        'reversal': 'Supplier refund received',
        'edge': 'Prepaid expense reclassification',
        'normal_long': 'Operating expense paid directly from a current asset (bank account). The most common business transaction — buying supplies, paying for services, settling invoices.',
        'reversal_long': 'A supplier refund or expense reversal returns value from the expense back to the asset. Credit note applied, returned goods refunded.',
        'edge_long': 'Reclassifying a prepaid asset as an expense when the service period begins. Moving deposits to expense recognition.',
        'scenarios': [
            {'desc': 'Pay monthly internet bill', 'debit': 'Expenses:Operating:Telecommunications', 'credit': 'Assets:Current:Chequing', 'command': 'pair expense add'},
            {'desc': 'Buy office supplies', 'debit': 'Expenses:Operating:Office Supplies', 'credit': 'Assets:Current:Chequing', 'command': 'pair expense add'},
            {'desc': 'Refund from supplier', 'debit': 'Assets:Current:Chequing', 'credit': 'Expenses:Operating:Office Supplies', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '0001',
        'num': 2,
        'name': 'Op Expense / Liability',
        'group': 'expense',
        'normal': 'Expense incurred on credit',
        'reversal': 'Credit card charge reversed',
        'edge': 'Accrued expense adjustment',
        'normal_long': 'Operating expense charged to a liability (credit card, accounts payable). You received the good or service but haven\'t paid cash yet.',
        'reversal_long': 'A credit card dispute won, or a vendor credit applied against an outstanding balance. The liability decreases and the expense is reversed.',
        'edge_long': 'Adjusting an accrued expense estimate at period end. Correcting over/under accruals from prior periods.',
        'scenarios': [
            {'desc': 'Software subscription on credit card', 'debit': 'Expenses:Operating:Software Subscriptions', 'credit': 'Liabilities:Credit Card', 'command': 'pair expense add'},
            {'desc': 'Accrue wages payable', 'debit': 'Expenses:Operating:Wages', 'credit': 'Liabilities:Wages Payable', 'command': 'pair payroll run'},
            {'desc': 'Credit card dispute refund', 'debit': 'Liabilities:Credit Card', 'credit': 'Expenses:Operating:Software Subscriptions', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '0010',
        'num': 3,
        'name': 'Non-Op Expense / Asset',
        'group': 'expense',
        'normal': 'Amortization or non-core expense',
        'reversal': 'Non-op expense reversal',
        'edge': 'Asset impairment write-down',
        'normal_long': 'Non-operating expense reducing an asset. The classic example is amortization/depreciation — systematically expensing a capital asset over its useful life.',
        'reversal_long': 'Reversing a non-operating expense. Rare in practice — typically a correction of a prior-period amortization error.',
        'edge_long': 'Writing down an asset due to impairment. The asset\'s fair value dropped below book value and must be recognized as a loss.',
        'scenarios': [
            {'desc': 'Monthly amortization of equipment', 'debit': 'Expenses:Non-Operating:Amortization', 'credit': 'Assets:Fixed:Equipment:Accumulated Amortization', 'command': 'pair asset amort'},
            {'desc': 'Loss on disposal of asset', 'debit': 'Expenses:Non-Operating:Loss on Disposal', 'credit': 'Assets:Fixed:Equipment', 'command': 'pair asset dispose'},
            {'desc': 'Impairment write-down', 'debit': 'Expenses:Non-Operating:Impairment', 'credit': 'Assets:Fixed:Equipment', 'command': 'pair entry'},
        ],
    },
    {
        'code': '0011',
        'num': 4,
        'name': 'Non-Op Expense / Liability',
        'group': 'expense',
        'normal': 'Interest expense on loan',
        'reversal': 'Interest adjustment/reversal',
        'edge': 'Penalty accrued on debt',
        'normal_long': 'Non-operating expense creating or increasing a liability. Interest expense accruing on a loan is the most common case.',
        'reversal_long': 'Reversing an interest charge — lender error corrected, or early payment reducing accrued interest.',
        'edge_long': 'Penalty charges or late fees accrued against a debt. Recognized as non-operating expense with corresponding liability increase.',
        'scenarios': [
            {'desc': 'Loan interest accrual', 'debit': 'Expenses:Non-Operating:Interest', 'credit': 'Liabilities:Interest Payable', 'command': 'pair liability pay'},
            {'desc': 'Bank penalty fee accrued', 'debit': 'Expenses:Non-Operating:Penalties', 'credit': 'Liabilities:Bank Loan', 'command': 'pair entry'},
            {'desc': 'Interest overcharge reversed', 'debit': 'Liabilities:Interest Payable', 'credit': 'Expenses:Non-Operating:Interest', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '0100',
        'num': 5,
        'name': 'Op Income / Asset',
        'group': 'income',
        'normal': 'Revenue received as cash/deposit',
        'reversal': 'Client refund issued',
        'edge': 'Barter or trade exchange',
        'normal_long': 'Operating revenue received directly as an asset. Client pays invoice and cash arrives in the bank. The core revenue recognition event for most businesses.',
        'reversal_long': 'Issuing a refund to a client. Revenue reversed, asset (cash) reduced. Could be partial or full refund of prior payment.',
        'edge_long': 'Receiving a non-cash asset in exchange for services — barter arrangement where revenue is recognized at fair value of asset received.',
        'scenarios': [
            {'desc': 'Client pays invoice', 'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Consulting', 'command': 'pair revenue paid'},
            {'desc': 'Retainer deposit received', 'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Consulting', 'command': 'pair revenue paid'},
            {'desc': 'Refund to client', 'debit': 'Revenue:Consulting', 'credit': 'Assets:Current:Chequing', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '0101',
        'num': 6,
        'name': 'Op Income / Liability',
        'group': 'income',
        'normal': 'Revenue earned, not yet received',
        'reversal': 'Accrued revenue reversed',
        'edge': 'Deferred revenue recognition',
        'normal_long': 'Revenue earned creating a receivable (asset-like) or reducing a deferred revenue liability. Recognizing revenue for work done when payment hasn\'t arrived yet.',
        'reversal_long': 'Reversing previously accrued revenue — client dispute, contract cancellation, or adjustment to prior-period revenue recognition.',
        'edge_long': 'Converting deferred revenue (liability) to earned revenue as service is delivered over time. Subscription or retainer drawdown.',
        'scenarios': [
            {'desc': 'Recognize deferred revenue', 'debit': 'Liabilities:Deferred Revenue', 'credit': 'Revenue:Consulting', 'command': 'pair entry'},
            {'desc': 'Invoice sent (A/R created)', 'debit': 'Assets:Current:Accounts Receivable', 'credit': 'Revenue:Consulting', 'command': 'pair revenue invoice'},
            {'desc': 'Reverse accrued revenue', 'debit': 'Revenue:Consulting', 'credit': 'Liabilities:Deferred Revenue', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '0110',
        'num': 7,
        'name': 'Non-Op Income / Asset',
        'group': 'income',
        'normal': 'One-time income received',
        'reversal': 'One-time income reversed',
        'edge': 'Gain on sale of asset',
        'normal_long': 'Non-operating income received as an asset. Selling equipment at a gain, receiving insurance proceeds, or interest income deposited to bank.',
        'reversal_long': 'Reversing non-operating income — insurance claim denied after initial recording, or gain recalculated downward.',
        'edge_long': 'Gain recognized on disposal of a capital asset when sale proceeds exceed net book value.',
        'scenarios': [
            {'desc': 'Interest income received', 'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Non-Operating:Interest Income', 'command': 'pair entry'},
            {'desc': 'Insurance payout received', 'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Non-Operating:Insurance Recovery', 'command': 'pair entry'},
            {'desc': 'Gain on asset sale', 'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Non-Operating:Gain on Disposal', 'command': 'pair asset dispose'},
        ],
    },
    {
        'code': '0111',
        'num': 8,
        'name': 'Non-Op Income / Liability',
        'group': 'income',
        'normal': 'Non-op income on credit',
        'reversal': 'Credit income reversed',
        'edge': 'Debt forgiveness as income',
        'normal_long': 'Non-operating income earned against a liability. Debt forgiveness recognized as income, or a liability reduced by non-core revenue.',
        'reversal_long': 'Reversing non-operating income that was recorded against a liability. Debt forgiveness rescinded or restated.',
        'edge_long': 'A creditor forgives part of a debt — the liability decreases and the difference is recognized as non-operating income (gain on settlement).',
        'scenarios': [
            {'desc': 'Debt forgiveness by creditor', 'debit': 'Liabilities:Bank Loan', 'credit': 'Revenue:Non-Operating:Gain on Settlement', 'command': 'pair entry'},
            {'desc': 'Vendor writes off balance owed', 'debit': 'Liabilities:Accounts Payable', 'credit': 'Revenue:Non-Operating:Gain on Settlement', 'command': 'pair entry'},
            {'desc': 'Forgiveness rescinded', 'debit': 'Revenue:Non-Operating:Gain on Settlement', 'credit': 'Liabilities:Bank Loan', 'command': 'pair entry (reversal)'},
        ],
    },
    {
        'code': '1000',
        'num': 9,
        'name': 'Asset / Liability',
        'group': 'balance_sheet',
        'normal': 'Asset acquired on credit (loan)',
        'reversal': 'Loan payment from bank',
        'edge': 'Refinancing existing debt',
        'normal_long': 'An asset acquired by taking on a liability. Borrowing money (cash asset increases, loan liability increases) or buying equipment on credit.',
        'reversal_long': 'Repaying a liability from an asset. Making a loan payment from the bank account — the most common balance-sheet-only transaction.',
        'edge_long': 'Refinancing — replacing one liability with another while the asset position stays the same, or drawing down a line of credit.',
        'scenarios': [
            {'desc': 'Receive loan proceeds', 'debit': 'Assets:Current:Chequing', 'credit': 'Liabilities:Bank Loan', 'command': 'pair liability add'},
            {'desc': 'Make loan payment (principal)', 'debit': 'Liabilities:Bank Loan', 'credit': 'Assets:Current:Chequing', 'command': 'pair liability pay'},
            {'desc': 'Pay credit card balance', 'debit': 'Liabilities:Credit Card', 'credit': 'Assets:Current:Chequing', 'command': 'pair liability pay'},
        ],
    },
    {
        'code': '1001',
        'num': 10,
        'name': 'Asset / Equity',
        'group': 'balance_sheet',
        'normal': 'Owner invests into business',
        'reversal': 'Owner draws from business',
        'edge': 'Dividend or distribution',
        'normal_long': 'Owner contributes an asset to the business, increasing both assets and equity. Cash injection, contributing equipment, or converting personal funds to business use.',
        'reversal_long': 'Owner withdraws an asset from the business. Drawing cash for personal use, or distributing profits. Assets and equity both decrease.',
        'edge_long': 'Formal dividend declaration and payment, or in-kind distribution of business assets to owner.',
        'scenarios': [
            {'desc': 'Owner invests cash', 'debit': 'Assets:Current:Chequing', 'credit': 'Equity:Owner Investment', 'command': 'pair equity invest'},
            {'desc': 'Owner draws cash', 'debit': 'Equity:Owner Draws', 'credit': 'Assets:Current:Chequing', 'command': 'pair equity draw'},
            {'desc': 'Contribute personal equipment', 'debit': 'Assets:Fixed:Equipment', 'credit': 'Equity:Owner Investment', 'command': 'pair equity invest'},
        ],
    },
    {
        'code': '1010',
        'num': 11,
        'name': 'Liability / Equity',
        'group': 'balance_sheet',
        'normal': 'Equity converts to liability',
        'reversal': 'Liability converts to equity',
        'edge': 'Shareholder loan reclassification',
        'normal_long': 'Equity converting to a liability. Declaring a dividend payable (retained earnings becomes a liability) or formalizing a shareholder loan.',
        'reversal_long': 'Converting a liability to equity. A creditor accepts shares instead of repayment, or a shareholder loan is forgiven and reclassified as equity.',
        'edge_long': 'Reclassifying a shareholder loan between liability and equity based on terms or CRA guidance.',
        'scenarios': [
            {'desc': 'Declare dividend payable', 'debit': 'Equity:Retained Earnings', 'credit': 'Liabilities:Dividends Payable', 'command': 'pair entry'},
            {'desc': 'Convert debt to equity', 'debit': 'Liabilities:Shareholder Loan', 'credit': 'Equity:Owner Investment', 'command': 'pair entry (reversal)'},
            {'desc': 'Reclassify shareholder loan', 'debit': 'Equity:Shareholder Loan', 'credit': 'Liabilities:Shareholder Loan', 'command': 'pair entry'},
        ],
    },
    {
        'code': '1011',
        'num': 12,
        'name': 'Asset / Asset',
        'group': 'balance_sheet',
        'normal': 'Internal transfer between assets',
        'reversal': 'Reverse internal transfer',
        'edge': 'Deposit to savings or investment',
        'normal_long': 'Moving value between asset accounts. Transferring between bank accounts, converting cash to an investment, or depositing to a savings account.',
        'reversal_long': 'Reversing an internal asset transfer. Moving money back from savings, or correcting an erroneous inter-account transfer.',
        'edge_long': 'Purchasing a short-term investment from operating cash, or moving funds to a tax reserve account.',
        'scenarios': [
            {'desc': 'Transfer to savings', 'debit': 'Assets:Current:Savings', 'credit': 'Assets:Current:Chequing', 'command': 'pair entry'},
            {'desc': 'Move to tax reserve', 'debit': 'Assets:Current:Tax Reserve', 'credit': 'Assets:Current:Chequing', 'command': 'pair entry'},
            {'desc': 'Cash purchase of equipment', 'debit': 'Assets:Fixed:Equipment', 'credit': 'Assets:Current:Chequing', 'command': 'pair asset add'},
        ],
    },
    {
        'code': '1100',
        'num': 13,
        'name': 'Liability / Liability',
        'group': 'balance_sheet',
        'normal': 'Liability assumed/transferred in',
        'reversal': 'Liability transferred out',
        'edge': 'Refinance one loan with another',
        'normal_long': 'Moving value between liability accounts. Consolidating debts, transferring a balance from one credit facility to another.',
        'reversal_long': 'Transferring a liability to a third party or reversing a prior liability consolidation.',
        'edge_long': 'Refinancing — paying off one loan by taking a new one. The cash doesn\'t actually move through assets if the lender handles it directly.',
        'scenarios': [
            {'desc': 'Consolidate credit card to LOC', 'debit': 'Liabilities:Credit Card', 'credit': 'Liabilities:Line of Credit', 'command': 'pair entry'},
            {'desc': 'Refinance loan', 'debit': 'Liabilities:Old Loan', 'credit': 'Liabilities:New Loan', 'command': 'pair entry'},
            {'desc': 'Transfer payable between accounts', 'debit': 'Liabilities:Accounts Payable', 'credit': 'Liabilities:Notes Payable', 'command': 'pair entry'},
        ],
    },
    {
        'code': '1101',
        'num': 14,
        'name': 'Equity / Equity',
        'group': 'balance_sheet',
        'normal': 'Equity reallocated in',
        'reversal': 'Equity reallocated out',
        'edge': 'Retained earnings closing entry',
        'normal_long': 'Moving value between equity accounts. Allocating retained earnings to reserves, or reclassifying between equity categories.',
        'reversal_long': 'Reversing an equity reallocation. Moving reserves back to retained earnings or correcting a prior-period equity reclassification.',
        'edge_long': 'Year-end closing entry moving net income to retained earnings. Formal appropriation of earnings to a specific reserve.',
        'scenarios': [
            {'desc': 'Close income to retained earnings', 'debit': 'Equity:Current Year Earnings', 'credit': 'Equity:Retained Earnings', 'command': 'pair entry'},
            {'desc': 'Appropriate earnings to reserve', 'debit': 'Equity:Retained Earnings', 'credit': 'Equity:Reserve', 'command': 'pair entry'},
            {'desc': 'Reverse reserve appropriation', 'debit': 'Equity:Reserve', 'credit': 'Equity:Retained Earnings', 'command': 'pair entry (reversal)'},
        ],
    },
]


# ─── Default accounts for interactive entry ──────────────────────────────────

PAIR_DEFAULTS = {
    '0000': {
        'normal': {'debit': 'Expenses:Operating:', 'credit': 'Assets:Current:Chequing'},
        'reversal': {'debit': 'Assets:Current:Chequing', 'credit': 'Expenses:Operating:'},
    },
    '0001': {
        'normal': {'debit': 'Expenses:Operating:', 'credit': 'Liabilities:Credit Card'},
        'reversal': {'debit': 'Liabilities:Credit Card', 'credit': 'Expenses:Operating:'},
    },
    '0010': {
        'normal': {'debit': 'Expenses:Non-Operating:Amortization', 'credit': 'Assets:Fixed:'},
        'reversal': {'debit': 'Assets:Fixed:', 'credit': 'Expenses:Non-Operating:'},
    },
    '0011': {
        'normal': {'debit': 'Expenses:Non-Operating:Interest', 'credit': 'Liabilities:Interest Payable'},
        'reversal': {'debit': 'Liabilities:Interest Payable', 'credit': 'Expenses:Non-Operating:Interest'},
    },
    '0100': {
        'normal': {'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Consulting'},
        'reversal': {'debit': 'Revenue:Consulting', 'credit': 'Assets:Current:Chequing'},
    },
    '0101': {
        'normal': {'debit': 'Liabilities:Deferred Revenue', 'credit': 'Revenue:Consulting'},
        'reversal': {'debit': 'Revenue:Consulting', 'credit': 'Liabilities:Deferred Revenue'},
    },
    '0110': {
        'normal': {'debit': 'Assets:Current:Chequing', 'credit': 'Revenue:Non-Operating:Interest Income'},
        'reversal': {'debit': 'Revenue:Non-Operating:', 'credit': 'Assets:Current:Chequing'},
    },
    '0111': {
        'normal': {'debit': 'Liabilities:Bank Loan', 'credit': 'Revenue:Non-Operating:Gain on Settlement'},
        'reversal': {'debit': 'Revenue:Non-Operating:Gain on Settlement', 'credit': 'Liabilities:Bank Loan'},
    },
    '1000': {
        'normal': {'debit': 'Assets:Current:Chequing', 'credit': 'Liabilities:Bank Loan'},
        'reversal': {'debit': 'Liabilities:Bank Loan', 'credit': 'Assets:Current:Chequing'},
    },
    '1001': {
        'normal': {'debit': 'Assets:Current:Chequing', 'credit': 'Equity:Owner Investment'},
        'reversal': {'debit': 'Equity:Owner Draws', 'credit': 'Assets:Current:Chequing'},
    },
    '1010': {
        'normal': {'debit': 'Equity:Retained Earnings', 'credit': 'Liabilities:Dividends Payable'},
        'reversal': {'debit': 'Liabilities:Shareholder Loan', 'credit': 'Equity:Owner Investment'},
    },
    '1011': {
        'normal': {'debit': 'Assets:Current:Savings', 'credit': 'Assets:Current:Chequing'},
        'reversal': {'debit': 'Assets:Current:Chequing', 'credit': 'Assets:Current:Savings'},
    },
    '1100': {
        'normal': {'debit': 'Liabilities:Credit Card', 'credit': 'Liabilities:Line of Credit'},
        'reversal': {'debit': 'Liabilities:Line of Credit', 'credit': 'Liabilities:Credit Card'},
    },
    '1101': {
        'normal': {'debit': 'Equity:Current Year Earnings', 'credit': 'Equity:Retained Earnings'},
        'reversal': {'debit': 'Equity:Retained Earnings', 'credit': 'Equity:Current Year Earnings'},
    },
}

GROUPS = {
    'expense': {'label': 'Expense Pairs', 'desc': 'Value flows from assets/liabilities into expenses'},
    'income': {'label': 'Income Pairs', 'desc': 'Value flows from revenue into assets/liabilities'},
    'balance_sheet': {'label': 'Balance Sheet Pairs', 'desc': 'Value moves between balance sheet accounts only'},
}


# ─── Dispatch ────────────────────────────────────────────────────────────────

def dispatch_pairs(args):
    """Entry point for 'pair pairs'."""
    cmd_pairs(args)


def dispatch_pair(args):
    """Entry point for 'pair entry'."""
    cmd_pair(args)


# ─── cmd_pairs — reference/education display ─────────────────────────────────

def cmd_pairs(args):
    """Show account pair reference tables."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_pairs_help()
        return

    # Check for flags
    if '--normal' in args:
        show_single_column('normal')
        return
    if '--reversals' in args:
        show_single_column('reversal')
        return
    if '--edge' in args:
        show_single_column('edge')
        return

    # Check for number arg (drill-down)
    if remaining:
        try:
            num = int(remaining[0])
            if 1 <= num <= 14:
                show_drill_down(num)
                return
            else:
                print(f"  Pair number must be 1-14, got: {num}")
                sys.exit(1)
        except ValueError:
            print(f"  Unknown argument: {remaining[0]}")
            print_pairs_help()
            sys.exit(1)

    # No args — show full combined output
    show_wide_table()
    print()
    show_grouped_table()
    print()
    show_help_lines()


def print_pairs_help():
    print("""pair pairs — account pair reference

Usage:
  pair pairs              Full reference table (all 14 pairs)
  pair pairs <N>          Drill-down on pair N (1-14)
  pair pairs --normal     Normal direction descriptions (long)
  pair pairs --reversals  Reversal descriptions (long)
  pair pairs --edge       Edge case descriptions (long)

See also:
  pair entry               Interactive entry creation using any pair
""")


def show_wide_table():
    """Print wide 3-column table with all 14 pairs."""
    hdr = f"{'#':<3} {'Code':<6} {'Pair':<28} {'Normal':<36} {'Reversal':<36} {'Edge Case'}"
    sep = "─" * len(hdr)

    print()
    print("  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════")
    print("  Account Pair Matrix — 14 Double-Entry Relationships")
    print("  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════")
    print()
    print(f"  {hdr}")
    print(f"  {sep}")

    for p in PAIRS:
        num = f"{p['num']:<3}"
        code = f"{p['code']:<6}"
        name = f"{p['name']:<28}"
        normal = f"{p['normal']:<36}"
        reversal = f"{p['reversal']:<36}"
        edge = p['edge']
        print(f"  {num}{code}{name}{normal}{reversal}{edge}")

    print(f"  {sep}")


def show_grouped_table():
    """Print grouped table with single description per pair."""
    print("  ┌─────────────────────────────────────────────────────────────────────────┐")

    for group_key in ('expense', 'income', 'balance_sheet'):
        group = GROUPS[group_key]
        group_pairs = [p for p in PAIRS if p['group'] == group_key]

        print(f"  │ {group['label']:<72}│")
        print(f"  │ {group['desc']:<72}│")
        print(f"  │{'─' * 73}│")

        for p in group_pairs:
            line = f"  {p['num']:>2}. [{p['code']}] {p['name']:<24} → {p['normal']}"
            # Pad to fit box
            content = f"{p['num']:>2}. [{p['code']}] {p['name']:<24} → {p['normal']}"
            print(f"  │  {content:<71}│")

        print(f"  │{'─' * 73}│")

    print("  └─────────────────────────────────────────────────────────────────────────┘")


def show_help_lines():
    """Print help lines at the bottom."""
    print("  Usage:")
    print("    pair pairs <N>          Drill-down with scenarios for pair N")
    print("    pair pairs --normal     Full descriptions for normal direction")
    print("    pair pairs --reversals  Full descriptions for reversal direction")
    print("    pair pairs --edge       Full descriptions for edge cases")
    print("    pair entry               Interactive entry builder (any pair)")
    print()


def show_single_column(column):
    """Show full-width single column with longer descriptions."""
    print()

    if column == 'normal':
        title = "Normal Direction — Primary Flow"
    elif column == 'reversal':
        title = "Reversal Direction — Reverse Flow"
    else:
        title = "Edge Cases — Unusual Applications"

    print(f"  ══════════════════════════════════════════════════════════════════════════════")
    print(f"  {title}")
    print(f"  ══════════════════════════════════════════════════════════════════════════════")
    print()

    for p in PAIRS:
        long_key = f"{column}_long"
        print(f"  {p['num']:>2}. [{p['code']}] {p['name']}")
        # Wrap long description
        desc = p[long_key]
        _print_wrapped(desc, indent=6, width=76)
        print()

    print()


def show_drill_down(num):
    """Show 2-3 scenario boxes for a specific pair."""
    pair = next((p for p in PAIRS if p['num'] == num), None)
    if not pair:
        print(f"  No pair #{num}")
        return

    print()
    print(f"  ══════════════════════════════════════════════════════════════════════════════")
    print(f"  Pair #{pair['num']} — [{pair['code']}] {pair['name']}")
    print(f"  ══════════════════════════════════════════════════════════════════════════════")
    print()
    print(f"  Normal:   {pair['normal_long'][:76]}")
    if len(pair['normal_long']) > 76:
        _print_wrapped(pair['normal_long'][76:], indent=12, width=70)
    print(f"  Reversal: {pair['reversal_long'][:76]}")
    if len(pair['reversal_long']) > 76:
        _print_wrapped(pair['reversal_long'][76:], indent=12, width=70)
    print()

    print("  Scenarios:")
    print("  ─────────────────────────────────────────────────────────────────────────────")

    for i, s in enumerate(pair['scenarios'], 1):
        print(f"  ┌── Scenario {i}: {s['desc']}")
        print(f"  │   Debit:   {s['debit']}")
        print(f"  │   Credit:  {s['credit']}")
        print(f"  │   Command: {s['command']}")
        print(f"  └──")
        print()

    print()


# ─── cmd_pair — interactive entry creation ───────────────────────────────────

def cmd_pair(args):
    """Interactive entry creation using account pairs."""
    flags, remaining = parse_global_flags(args)

    if flags['help']:
        print_pair_help()
        return

    config = load_config()
    currency = config.get('pair', {}).get('currency', 'CAD')
    bank = config.get('accounts', {}).get('bank', 'Assets:Current:Chequing')
    division = config.get('pair', {}).get('division', None)

    # Step 1: Show numbered list and pick a pair
    print()
    print("  Account Pairs — choose a transaction type:")
    print("  ───────────────────────────────────────────────")
    for p in PAIRS:
        print(f"  {p['num']:>2}. [{p['code']}] {p['name']}")
    print()

    pair_num_str = prompt("Pair number (1-14)", validator=_validate_pair_num)
    pair_num = int(pair_num_str)
    pair = next(p for p in PAIRS if p['num'] == pair_num)

    # Step 2: Ask direction
    print(f"\n  Selected: [{pair['code']}] {pair['name']}")
    print(f"    a) Normal:   {pair['normal']}")
    print(f"    b) Reversal: {pair['reversal']}")
    print()

    direction_raw = prompt("Direction (a/b)", default="a")
    direction = 'normal' if direction_raw.lower() in ('a', 'normal') else 'reversal'

    # Step 3: Get defaults for this pair + direction
    defaults = PAIR_DEFAULTS.get(pair['code'], {}).get(direction, {})
    default_debit = defaults.get('debit', '')
    default_credit = defaults.get('credit', '')

    # Substitute bank account from config
    if default_debit == 'Assets:Current:Chequing':
        default_debit = bank
    if default_credit == 'Assets:Current:Chequing':
        default_credit = bank

    # Step 4: Prompt for entry details
    description = prompt("Description", default=pair[direction])
    amount_str = prompt("Amount", validator=validate_positive_number)
    entry_date = prompt("Date", default=date.today().strftime("%Y-%m-%d"),
                        validator=validate_date)
    debit_account = prompt("Debit account", default=default_debit)
    credit_account = prompt("Credit account", default=default_credit)

    amount = money(amount_str)

    # Step 5: Build tags
    pair_code = pair['code']
    extra_tags = {'direction': direction}

    if build_tags is not None:
        tags = build_tags(pair_code, source=None, division=division, **extra_tags)
    else:
        tags = {'pair': pair_code, 'direction': direction}
        if division:
            tags['division'] = division

    # Step 6: Format and write entry
    postings = [
        (debit_account, currency, float(amount)),
        (credit_account, currency, float(-amount)),
    ]

    entry = format_entry(entry_date, description, postings, tags)

    # Show preview
    print(f"\n  Preview:")
    print("  ─────────────────────────────────────────────")
    for line in entry.strip().split('\n'):
        print(f"  {line}")
    print()

    if not flags.get('yes') and not confirm("Write this entry?"):
        print("  Cancelled.")
        return

    year = entry_date[:4]
    ensure_year_structure(int(year))
    journal_path = GENERATED_DIR / year / "pairs.journal"
    append_journal(journal_path, entry)

    if not flags.get('quiet'):
        print(f"\n  ✓ Entry written to: generated/{year}/pairs.journal")
        print(f"    Pair: [{pair_code}] {pair['name']} ({direction})")
        print(f"    Amount: {currency} {amount}")


def print_pair_help():
    print("""pair entry — interactive entry creation

Creates a journal entry by selecting an account pair and direction.
Walks you through choosing accounts, amount, date, and description.

Usage:
  pair entry               Start interactive entry builder

Flags:
  --yes, -y                  Skip confirmation
  --date DATE                Pre-set the date
  --quiet, -q                Minimal output

The entry is written to generated/<year>/pairs.journal.
""")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_pair_num(value):
    """Validate pair number is 1-14."""
    try:
        n = int(value)
        if n < 1 or n > 14:
            return "Must be 1-14."
    except (ValueError, TypeError):
        return "Must be a number 1-14."
    return None


def _print_wrapped(text, indent=6, width=76):
    """Print text wrapped at word boundaries."""
    prefix = " " * indent
    words = text.split()
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            print(f"  {prefix}{line}")
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        print(f"  {prefix}{line}")
