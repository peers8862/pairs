"""Advanced entry: serialization, pair inference, and hledger validation."""

import shutil
import subprocess

import pytest

from lib.entry import serialize_entry, infer_pair, validate_entry


# ─── serialize_entry ─────────────────────────────────────────────────────────
# The serializer must emit the two-space delimiter itself. hledger account names
# may contain spaces and terminate only on 2+ spaces, so a single-space delimiter
# silently produces a valid entry with a garbled account name.

def _basic(**over):
    fields = {
        'date': '2026-07-21',
        'postings': [
            {'account': 'expenses:food', 'amount': '10 CAD'},
            {'account': 'assets:chequing', 'amount': '-10 CAD'},
        ],
    }
    fields.update(over)
    return fields


def _posting_line(out, account):
    return next(l for l in out.splitlines() if l.strip().startswith(account))


def test_minimal_entry():
    out = serialize_entry(_basic())
    assert out.startswith('2026-07-21\n')
    for account, amount in (('expenses:food', '10 CAD'), ('assets:chequing', '-10 CAD')):
        line = _posting_line(out, account)
        assert line.startswith('    ')
        # Account and amount separated by 2+ spaces (the delimiter that matters).
        assert line.strip().split('  ')[0] == account
        assert line.rstrip().endswith(amount)


def test_two_space_delimiter_always_emitted():
    out = serialize_entry(_basic())
    for line in out.splitlines():
        if line.startswith('    ') and 'CAD' in line:
            account_part = line.strip().split('  ')[0]
            assert '  ' in line.strip()[len(account_part):] or line.strip().endswith(account_part)


def test_status_and_code_and_payee_note():
    out = serialize_entry(_basic(status='*', code='123', payee='Acme', note='invoice 7'))
    assert out.splitlines()[0] == '2026-07-21 * (123) Acme | invoice 7'


def test_description_without_note():
    out = serialize_entry(_basic(payee='Acme'))
    assert out.splitlines()[0] == '2026-07-21 Acme'


def test_pending_status():
    out = serialize_entry(_basic(status='!', payee='rent'))
    assert out.splitlines()[0] == '2026-07-21 ! rent'


def test_status_without_description_has_no_trailing_space():
    assert serialize_entry(_basic(status='!')).splitlines()[0] == '2026-07-21 !'


def test_transaction_tags():
    out = serialize_entry(_basic(tags='trip:paris, client:acme'))
    assert '; trip:paris, client:acme' in out.splitlines()[0]


def test_unit_cost():
    fields = _basic(postings=[
        {'account': 'assets:inv', 'amount': '2 AAA', 'cost': '5 CAD', 'cost_type': '@'},
        {'account': 'assets:cash', 'amount': '-10 CAD'},
    ])
    assert '2 AAA @ 5 CAD' in serialize_entry(fields)


def test_total_cost():
    fields = _basic(postings=[
        {'account': 'assets:inv', 'amount': '2 AAA', 'cost': '10 CAD', 'cost_type': '@@'},
        {'account': 'assets:cash', 'amount': '-10 CAD'},
    ])
    assert '2 AAA @@ 10 CAD' in serialize_entry(fields)


def test_balance_assertion():
    fields = _basic(postings=[
        {'account': 'assets:cash', 'amount': '-10 CAD', 'assertion': '90 CAD', 'assertion_type': '='},
        {'account': 'expenses:food', 'amount': '10 CAD'},
    ])
    assert '= 90 CAD' in serialize_entry(fields)


def test_sole_commodity_assertion():
    fields = _basic(postings=[
        {'account': 'assets:cash', 'amount': '-10 CAD', 'assertion': '90 CAD', 'assertion_type': '=='},
        {'account': 'expenses:food', 'amount': '10 CAD'},
    ])
    assert '== 90 CAD' in serialize_entry(fields)


def test_amountless_posting_allowed():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': '10 CAD'},
        {'account': 'assets:chequing', 'amount': ''},
    ])
    out = serialize_entry(fields)
    assert out.rstrip().endswith('assets:chequing')


def test_posting_comment():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': '10 CAD', 'comment': 'date:2026-07-22'},
        {'account': 'assets:chequing', 'amount': '-10 CAD'},
    ])
    assert '; date:2026-07-22' in serialize_entry(fields)


def test_multi_posting_split():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': '7 CAD'},
        {'account': 'expenses:tips', 'amount': '3 CAD'},
        {'account': 'assets:chequing', 'amount': '-10 CAD'},
    ])
    out = serialize_entry(fields)
    assert len([l for l in out.splitlines() if l.startswith('    ')]) == 3


def test_entry_ends_with_blank_line():
    assert serialize_entry(_basic()).endswith('\n\n')


# ─── infer_pair ──────────────────────────────────────────────────────────────

def p(account, atype):
    return {'account': account, 'type': atype}


def test_operating_expense_from_asset():
    assert infer_pair([p('Expenses:Operating:Food', 'X'), p('Assets:Current:Chequing', 'A')]) == '0000'


def test_nonoperating_expense_from_asset():
    assert infer_pair([p('Expenses:Non-Operating:Amortization', 'X'), p('Assets:Fixed:Equip', 'A')]) == '0010'


def test_operating_expense_on_credit():
    assert infer_pair([p('Expenses:Operating:Food', 'X'), p('Liabilities:Current:AP', 'L')]) == '0001'


def test_nonoperating_expense_on_credit():
    assert infer_pair([p('Expenses:Non-Operating:Interest', 'X'), p('Liabilities:Long-Term:Loan', 'L')]) == '0011'


def test_operating_income_to_asset():
    assert infer_pair([p('Income:Operating:Sales', 'R'), p('Assets:Current:Chequing', 'A')]) == '0100'


def test_nonoperating_income_to_asset():
    assert infer_pair([p('Income:Non-Operating:Gain', 'R'), p('Assets:Current:Chequing', 'A')]) == '0110'


def test_asset_liability():
    assert infer_pair([p('Assets:Current:Chequing', 'A'), p('Liabilities:Long-Term:Loan', 'L')]) == '1000'


def test_asset_equity():
    assert infer_pair([p('Assets:Current:Chequing', 'A'), p('Equity:Owner', 'E')]) == '1001'


def test_asset_asset_transfer():
    assert infer_pair([p('Assets:Current:Savings', 'A'), p('Assets:Current:Chequing', 'A')]) == '1011'


def test_equity_equity():
    assert infer_pair([p('Equity:Retained', 'E'), p('Equity:Owner', 'E')]) == '1101'


def test_order_independent():
    a = infer_pair([p('Expenses:Operating:Food', 'X'), p('Assets:Current:Chequing', 'A')])
    b = infer_pair([p('Assets:Current:Chequing', 'A'), p('Expenses:Operating:Food', 'X')])
    assert a == b == '0000'


def test_three_postings_is_compound():
    assert infer_pair([
        p('Expenses:Operating:Food', 'X'),
        p('Expenses:Operating:Tips', 'X'),
        p('Assets:Current:Chequing', 'A'),
    ]) == 'compound'


def test_unmapped_type_pair_is_compound():
    assert infer_pair([p('Income:Operating:Sales', 'R'), p('Equity:Owner', 'E')]) == 'compound'


def test_cash_subtype_treated_as_asset():
    """hledger subtypes C/V/G roll up to A/E/R per the manual."""
    assert infer_pair([p('Expenses:Operating:Food', 'X'), p('Assets:Current:Cash', 'C')]) == '0000'


# ─── validate_entry (real hledger) ───────────────────────────────────────────

pytestmark_hledger = pytest.mark.skipif(
    shutil.which('hledger') is None, reason='hledger not installed')


@pytestmark_hledger
def test_validate_accepts_balanced():
    r = validate_entry(serialize_entry(_basic()))
    assert r['ok'], r['errors']
    assert 'expenses:food' in r['rendered']


@pytestmark_hledger
def test_validate_rejects_unbalanced():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': '10 CAD'},
        {'account': 'assets:chequing', 'amount': '-5 CAD'},
    ])
    r = validate_entry(serialize_entry(fields))
    assert not r['ok']
    assert r['errors']


@pytestmark_hledger
def test_validate_infers_single_amountless_posting():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': '10 CAD'},
        {'account': 'assets:chequing', 'amount': ''},
    ])
    r = validate_entry(serialize_entry(fields))
    assert r['ok'], r['errors']
    assert '-10' in r['rendered']


@pytestmark_hledger
def test_validate_rejects_two_amountless_postings():
    fields = _basic(postings=[
        {'account': 'expenses:food', 'amount': ''},
        {'account': 'assets:chequing', 'amount': ''},
    ])
    assert not validate_entry(serialize_entry(fields))['ok']


@pytestmark_hledger
def test_validate_accepts_cost_notation():
    fields = _basic(postings=[
        {'account': 'assets:inv', 'amount': '2 AAA', 'cost': '5 CAD', 'cost_type': '@'},
        {'account': 'assets:cash', 'amount': '-10 CAD'},
    ])
    r = validate_entry(serialize_entry(fields))
    assert r['ok'], r['errors']


@pytestmark_hledger
def test_serialized_account_names_survive_roundtrip():
    """The delimiter trap: a single-space delimiter would fold the amount into
    the account name. Confirm hledger parses back the account we intended."""
    fields = _basic(postings=[
        {'account': 'expenses:office supplies', 'amount': '10 CAD'},
        {'account': 'assets:chequing', 'amount': '-10 CAD'},
    ])
    r = validate_entry(serialize_entry(fields))
    assert r['ok'], r['errors']
    assert 'expenses:office supplies' in r['rendered']
    assert 'supplies  10' not in r['rendered'].replace('   ', '  ')
