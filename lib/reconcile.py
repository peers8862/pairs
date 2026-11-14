"""Bank statement import + matching core (I69) — pure functions, no
filesystem, no subprocess.

A statement line is a dict:
    {date: 'YYYY-MM-DD', description: str, amount: Decimal,
     fitid: str | None, source_file: str}

Amounts: positive is money IN to the account, negative is money OUT —
the same sign convention as an hledger posting on the account.

CSV column mapping is DECLARED, never guessed. A mapping is a dict:
    {date, description, amount?, debit?, credit?, date_format?}
Exactly one of `amount` or the (`debit`, `credit`) pair must be present;
`date_format` is a strptime format (default '%Y-%m-%d'). A missing
column, a bad date, or both amount styles at once raises ValueError.

OFX is parsed with the standard library only: OFX 2.x XML via
xml.etree.ElementTree, OFX 1.x SGML via a tag regex (leaf elements in
SGML OFX have no closing tags). No new runtime dependencies.

Matching rules (deterministic): a journal posting is a candidate for a
statement line when the amount matches exactly (to the cent) and the
dates are within the window (default +/-3 days). Exactly one candidate
-> matched. Several -> the uniquely closest date wins; a tie on
distance is ambiguous. None -> unmatched.
"""

import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, date as date_cls
from decimal import Decimal, InvalidOperation

DEFAULT_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_WINDOW_DAYS = 3


# ─── amounts ────────────────────────────────────────────────────────────────

def parse_amount(raw):
    """Parse a money string: currency symbols and thousands separators
    are stripped; (1,234.56) is accounting-negative; a leading - is
    negative. Raises ValueError on anything else."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Empty amount.")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace(" ", "").strip()
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Cannot parse amount: {raw!r}")
    return -value if negative else value


def parse_date(raw, date_format):
    """Strict strptime date → 'YYYY-MM-DD'. Raises ValueError."""
    text = str(raw or "").strip()
    try:
        return datetime.strptime(text, date_format).strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"Cannot parse date {raw!r} with format {date_format!r}.")


# ─── CSV ────────────────────────────────────────────────────────────────────

def validate_mapping(mapping):
    """Check a CSV mapping dict. Raises ValueError naming the problem."""
    if not isinstance(mapping, dict):
        raise ValueError("Statement mapping must be a mapping of column names.")
    for key in ("date", "description"):
        if not mapping.get(key):
            raise ValueError(f"Statement mapping is missing the {key!r} column.")
    has_amount = bool(mapping.get("amount"))
    has_split = bool(mapping.get("debit")) or bool(mapping.get("credit"))
    if has_amount and has_split:
        raise ValueError(
            "Statement mapping must use either an 'amount' column or "
            "'debit'/'credit' columns, not both.")
    if not has_amount and not has_split:
        raise ValueError(
            "Statement mapping needs an 'amount' column or "
            "'debit'/'credit' columns.")
    if has_split and not (mapping.get("debit") and mapping.get("credit")):
        raise ValueError(
            "Statement mapping with split amounts needs both 'debit' and "
            "'credit' columns.")
    return mapping


def parse_csv_statement(text, mapping):
    """Parse statement CSV text under a declared mapping.

    Returns a list of statement lines (source_file left blank — the
    caller fills it in). Raises ValueError on a missing column, a bad
    date, or a bad amount, naming the row.
    """
    mapping = validate_mapping(mapping)
    date_format = mapping.get("date_format") or DEFAULT_DATE_FORMAT
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("Statement CSV has no header row.")
    for key in ("date", "description"):
        if mapping[key] not in reader.fieldnames:
            raise ValueError(
                f"Statement CSV is missing the {mapping[key]!r} column "
                f"for {key}.")
    if mapping.get("amount") and mapping["amount"] not in reader.fieldnames:
        raise ValueError(
            f"Statement CSV is missing the {mapping['amount']!r} column "
            f"for amount.")
    for key in ("debit", "credit"):
        if mapping.get(key) and mapping[key] not in reader.fieldnames:
            raise ValueError(
                f"Statement CSV is missing the {mapping[key]!r} column "
                f"for {key}.")
    lines = []
    for n, row in enumerate(reader, start=2):
        if row is None or all(v in (None, "") for v in row.values()):
            continue
        description = (row.get(mapping["description"]) or "").strip()
        try:
            line_date = parse_date(row.get(mapping["date"]), date_format)
        except ValueError as e:
            raise ValueError(f"Row {n}: {e}")
        if mapping.get("amount"):
            try:
                amount = parse_amount(row.get(mapping["amount"]))
            except ValueError as e:
                raise ValueError(f"Row {n}: {e}")
        else:
            debit = row.get(mapping["debit"]) or ""
            credit = row.get(mapping["credit"]) or ""
            try:
                out = parse_amount(debit) if debit.strip() else Decimal("0")
                inn = parse_amount(credit) if credit.strip() else Decimal("0")
            except ValueError as e:
                raise ValueError(f"Row {n}: {e}")
            amount = inn - out
        lines.append({
            "date": line_date, "description": description,
            "amount": amount, "fitid": None, "source_file": "",
        })
    return lines


# ─── OFX ────────────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<([A-Za-z0-9]+)>([^<\r\n]*)")


def _ofx_line(fields):
    """One STMTTRN's fields → a statement line."""
    raw_date = (fields.get("DTPOSTED") or "").strip()[:8]
    if len(raw_date) != 8 or not raw_date.isdigit():
        raise ValueError(f"Bad OFX posting date: {fields.get('DTPOSTED')!r}")
    try:
        amount = parse_amount(fields.get("TRNAMT") or "")
    except ValueError as e:
        raise ValueError(f"OFX transaction {fields.get('FITID')!r}: {e}")
    name = (fields.get("NAME") or "").strip()
    memo = (fields.get("MEMO") or "").strip()
    description = f"{name} — {memo}" if memo else name
    return {
        "date": f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}",
        "description": description,
        "amount": amount,
        "fitid": (fields.get("FITID") or "").strip() or None,
        "source_file": "",
    }


def _parse_ofx_xml(text):
    root = ET.fromstring(text)
    lines = []
    for trn in root.iter("STMTTRN"):
        fields = {}
        for child in trn:
            fields[child.tag] = (child.text or "").strip()
        lines.append(_ofx_line(fields))
    return lines


def _parse_ofx_sgml(text):
    """OFX 1.x: leaf elements have no closing tags, so split on
    <STMTTRN> ... </STMTTRN> blocks and read <TAG>value pairs."""
    lines = []
    blocks = re.split(r"<STMTTRN>", text)
    for block in blocks[1:]:
        block = block.split("</STMTTRN>")[0]
        fields = {}
        for match in _TAG_RE.finditer(block):
            fields[match.group(1)] = match.group(2).strip()
        if fields:
            lines.append(_ofx_line(fields))
    return lines


def parse_ofx_statement(text):
    """Parse OFX text (2.x XML or 1.x SGML) → statement lines."""
    stripped = text.lstrip()
    if stripped.startswith("<?xml") or "</OFX>" in text:
        try:
            return _parse_ofx_xml(text)
        except ET.ParseError:
            pass
    return _parse_ofx_sgml(text)


# ─── matching ───────────────────────────────────────────────────────────────

def dedup_key(line, account):
    """Identity of a statement line for one account: (account, date,
    amount, description, fitid-or-''). Two genuinely identical same-day
    purchases with byte-identical descriptions (CSV, no FITID) share a
    key and dedup to one line — a documented limitation."""
    return (account, line["date"], str(line["amount"]),
            line["description"], line.get("fitid") or "")


def account_slug(account):
    """Account path → store slug: 'Assets:Current:Chequing' ->
    'assets-current-chequing'."""
    slug = account.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "untitled"


def _date_diff_days(a, b):
    da = date_cls.fromisoformat(a)
    db = date_cls.fromisoformat(b)
    return abs((da - db).days)


def match_lines(lines, postings, window_days=DEFAULT_WINDOW_DAYS):
    """Match statement lines to journal postings.

    postings: [{date, description, amount}]. Returns a list of
    {line, status, posting|None, candidates}: status is 'matched',
    'ambiguous' (a tie on closest date), or 'unmatched'.
    """
    results = []
    for line in lines:
        candidates = []
        for posting in postings:
            if posting["amount"] != line["amount"]:
                continue
            dist = _date_diff_days(line["date"], posting["date"])
            if dist <= window_days:
                candidates.append((dist, posting))
        if not candidates:
            results.append({"line": line, "status": "unmatched",
                            "posting": None, "candidates": []})
            continue
        candidates.sort(key=lambda c: c[0])
        best = candidates[0][0]
        closest = [p for d, p in candidates if d == best]
        if len(closest) == 1:
            results.append({"line": line, "status": "matched",
                            "posting": closest[0],
                            "candidates": [p for _, p in candidates]})
        else:
            results.append({"line": line, "status": "ambiguous",
                            "posting": None,
                            "candidates": [p for _, p in candidates]})
    return results


def match_summary(results):
    """Counts of each status in match_lines results."""
    counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for result in results:
        counts[result["status"]] += 1
    return counts
