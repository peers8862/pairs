"""Advanced entry creation: serialize structured fields to hledger journal text,
infer a pair code from account types, and validate via the hledger binary.

Design note — we delegate to hledger rather than reimplementing its grammar, so
parity is exact and does not drift across hledger versions.

Correctness note — hledger account names may contain spaces and are terminated
only by TWO OR MORE spaces. A single-space delimiter parses cleanly as an account
name that swallows the amount, producing a valid-but-wrong entry. serialize_entry
therefore always emits the two-space delimiter itself; callers never supply it.
"""

import subprocess

from lib.journal import (
    append_journal, ensure_year_structure, ensure_generated_include, get_generated_dir,
)

# Column at which posting amounts are aligned (matches lib/journal.py convention).
_AMOUNT_COLUMN = 52

# hledger subtypes roll up to their parent type (manual: Account types).
_TYPE_ROLLUP = {'C': 'A', 'V': 'E', 'G': 'R'}

# Type pair -> pair code. Expense/Revenue pairs additionally split on whether the
# expense/revenue account is Operating or Non-Operating (from the account path,
# since hledger's type is just X or R for both).
_PAIR_BY_TYPES = {
    frozenset(('X', 'A')): ('0000', '0010'),   # (operating, non-operating)
    frozenset(('X', 'L')): ('0001', '0011'),
    frozenset(('R', 'A')): ('0100', '0110'),
    frozenset(('R', 'L')): ('0101', '0111'),
    frozenset(('A', 'L')): ('1000', None),
    frozenset(('A', 'E')): ('1001', None),
    frozenset(('L', 'E')): ('1010', None),
    frozenset(('A',)):     ('1011', None),     # asset -> asset transfer
    frozenset(('L',)):     ('1100', None),
    frozenset(('E',)):     ('1101', None),
}

COMPOUND = 'compound'


def _description(fields):
    """Build the description from payee/note, or a plain description."""
    payee = (fields.get('payee') or '').strip()
    note = (fields.get('note') or '').strip()
    if payee and note:
        return f"{payee} | {note}"
    return payee or note or (fields.get('description') or '').strip()


def serialize_entry(fields):
    """Render structured entry fields as hledger journal text.

    fields: {date, status, code, payee, note, description, tags, postings[]}
    posting: {account, amount, cost, cost_type, assertion, assertion_type, comment}

    Returns journal text ending with a blank line.
    """
    header = fields['date']

    status = (fields.get('status') or '').strip()
    if status in ('!', '*'):
        header += f" {status}"

    code = (fields.get('code') or '').strip()
    if code:
        header += f" ({code})"

    desc = _description(fields)
    if desc:
        header += f" {desc}"

    tags = (fields.get('tags') or '').strip()
    if tags:
        header += f"  ; {tags}"

    lines = [header]

    for posting in fields.get('postings', []):
        account = (posting.get('account') or '').strip()
        if not account:
            continue

        # Everything right of the account name. Assembled first so we know
        # whether the two-space delimiter is needed at all.
        right = (posting.get('amount') or '').strip()

        cost = (posting.get('cost') or '').strip()
        if right and cost:
            cost_type = posting.get('cost_type') or '@'
            right += f" {cost_type} {cost}"

        assertion = (posting.get('assertion') or '').strip()
        if assertion:
            assertion_type = posting.get('assertion_type') or '='
            right = f"{right} {assertion_type} {assertion}" if right else f"{assertion_type} {assertion}"

        comment = (posting.get('comment') or '').strip()

        if right:
            padding = max(2, _AMOUNT_COLUMN - len(account))
            line = f"    {account}{' ' * padding}{right}"
        else:
            line = f"    {account}"

        if comment:
            # Two spaces before ; as well: the account name would otherwise
            # absorb it when there is no amount.
            line += f"  ; {comment}"

        lines.append(line)

    lines.append("")
    return "\n".join(lines) + "\n"


def _is_non_operating(account):
    return 'non-operating' in account.lower()


def infer_pair(postings):
    """Infer one of the 14 pair codes from postings' account types.

    postings: [{account, type}] where type is a hledger account type letter.
    Returns a 4-bit code string, or COMPOUND when the two-account model does not
    honestly describe the entry.
    """
    if len(postings) != 2:
        return COMPOUND

    types = set()
    for posting in postings:
        raw = (posting.get('type') or '').strip().upper()[:1]
        if not raw:
            return COMPOUND
        types.add(_TYPE_ROLLUP.get(raw, raw))

    entry = _PAIR_BY_TYPES.get(frozenset(types))
    if entry is None:
        return COMPOUND

    operating_code, non_operating_code = entry
    if non_operating_code is None:
        return operating_code

    # Split on the expense/revenue account's path.
    for posting in postings:
        raw = (posting.get('type') or '').strip().upper()[:1]
        if _TYPE_ROLLUP.get(raw, raw) in ('X', 'R'):
            if _is_non_operating(posting.get('account') or ''):
                return non_operating_code
    return operating_code


def validate_entry(text, timeout=15):
    """Validate journal text by piping it to hledger.

    Returns {ok, rendered, errors}. `rendered` is hledger's own re-rendering
    (print -x), which makes inferred amounts and parsed account names visible —
    the mitigation for valid-but-wrong entries.
    """
    try:
        result = subprocess.run(
            ['hledger', '-f-', 'print', '-x'],
            input=text, capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return {'ok': False, 'rendered': '', 'errors': 'hledger is not installed'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'rendered': '', 'errors': 'hledger timed out'}

    if result.returncode == 0:
        return {'ok': True, 'rendered': result.stdout.strip(), 'errors': ''}
    return {'ok': False, 'rendered': '', 'errors': (result.stderr or result.stdout).strip()}


def record_entry(text, date_str):
    """Append a validated entry to generated/<year>/entries.journal.

    Wires the include so hledger actually sees it (a generated journal added
    after the year aggregator existed is otherwise orphaned).
    """
    year = date_str[:4]
    ensure_year_structure(int(year))
    ensure_generated_include(year, 'entries.journal')
    append_journal(get_generated_dir() / year / 'entries.journal', text)
    return year
