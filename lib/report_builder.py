"""Entity report builder core (I76): one shared core, three front-ends.

A report definition is a named hledger query — a command plus query
terms plus display options — validated at load time:

    reports:
      monthly-expenses:
        title: Monthly expenses
        command: register
        query: "acct:Expenses"
        monthly: true

The three front-ends (saved named reports in config.yaml, the
flag-driven `pair report build`, the web UI) all run through here:
validate once, compose the hledger argv once, run once, render once.

Safety: every query term goes through safe_query_terms, the same
leading-dash rejection that guards /api/search (see
tests/test_search_guard.py). No legitimate query term starts with
'-'. Callers must NOT insert a '--' separator before the terms:
hledger stops parsing prefix: query syntax (amt:/type:/expr:) after
'--', so those queries would silently match nothing. The guard is
the whole defence; display options (-p, -M, --tree, --flat) are a
separate allow-list, never free-form flags.
"""

import csv
import io
import re
import shlex
import subprocess

REPORT_COMMANDS = ('register', 'print', 'bal', 'balance', 'bs', 'is', 'accounts')

_KNOWN_KEYS = {'title', 'command', 'query', 'period', 'monthly', 'tree', 'flat'}
_PERIOD_RE = re.compile(r'^\d{4}(Q[1-4]|-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?$')


def safe_query_terms(query):
    """Split a user query into hledger argv terms. Returns (terms, error).

    Argument injection guard: hledger parses any argv item beginning
    with '-' as a FLAG, not a query term. Passing args as a list
    prevents *shell* injection but not this. A smuggled
    --output-file= turns a read-only report into an arbitrary file
    write, and -f repoints it at any file on disk. No legitimate
    query term starts with '-', so reject them. The leading-dash
    rejection here is the whole guard — do NOT "fix" it by inserting
    '--' before the terms (hledger stops parsing amt:/type:/expr:
    prefix syntax after '--').
    """
    try:
        terms = shlex.split(query) if query else []
    except ValueError as e:
        return [], f"Unbalanced quotes: {e}"
    bad = [t for t in terms if t.startswith('-')]
    if bad:
        return [], f"Query terms cannot start with '-': {', '.join(bad)}"
    return terms, ''


def compose_query(fields):
    """Build an hledger query string from structured builder fields.

    One-way by design: fields compose into a query the user can see
    and then edit by hand. Parsing an arbitrary hledger query back
    into fields would need hledger's own grammar and would drift.
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
        terms.append({'unmarked': 'status:', 'pending': 'status:!',
                      'cleared': 'status:*'}[status])

    types = ''.join(t for t in (fields.get('type') or '') if t.upper() in 'ALERXCVG')
    if types:
        terms.append(f"type:{types.upper()}")

    tag_name = (fields.get('tag_name') or '').strip()
    if tag_name:
        tag_value = (fields.get('tag_value') or '').strip()
        add('tag:', f"{tag_name}={tag_value}" if tag_value else tag_name,
            bool(neg.get('tag')))

    depth = str(fields.get('depth') or '').strip()
    if depth.isdigit():
        terms.append(f"depth:{depth}")

    if fields.get('real'):
        terms.append('real:')

    expr = (fields.get('expr') or '').strip()
    if expr:
        terms.append(f"expr:'{expr}'")

    return ' '.join(terms)


def validate_definition(name, raw):
    """Validate one report definition; return the normalized dict.

    Raises ValueError on any bad shape: unknown command or key, a
    query term the guard rejects, a bad period, a non-bool display
    flag. Normalization fills defaults so every later stage sees
    the same keys.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError('report name must be a non-empty string')
    if not isinstance(raw, dict):
        raise ValueError(f"report '{name}' must be a mapping")
    unknown = set(raw) - _KNOWN_KEYS
    if unknown:
        raise ValueError(f"report '{name}': unknown key(s): {', '.join(sorted(unknown))}")
    command = raw.get('command')
    if command not in REPORT_COMMANDS:
        raise ValueError(f"report '{name}': unknown command '{command}' "
                         f"(one of {', '.join(REPORT_COMMANDS)})")
    query = raw.get('query', '')
    if not isinstance(query, str):
        raise ValueError(f"report '{name}': 'query' must be a string")
    query = query.strip()
    _terms, err = safe_query_terms(query)
    if err:
        raise ValueError(f"report '{name}': {err}")
    title = raw.get('title', name)
    if not isinstance(title, str):
        raise ValueError(f"report '{name}': 'title' must be a string")
    period = raw.get('period')
    if period is not None:
        if not isinstance(period, str) or not _PERIOD_RE.match(period):
            raise ValueError(f"report '{name}': bad period '{period}' "
                             "(use YYYY, YYYY-MM, YYYY-MM-DD or YYYYQn)")
    for flag in ('monthly', 'tree', 'flat'):
        if raw.get(flag) is not None and not isinstance(raw[flag], bool):
            raise ValueError(f"report '{name}': '{flag}' must be true/false")
    return {'title': title, 'command': command, 'query': query,
            'period': period, 'monthly': bool(raw.get('monthly', False)),
            'tree': bool(raw.get('tree', False)), 'flat': bool(raw.get('flat', False))}


def named_reports(config=None):
    """{name: normalized definition} from config's `reports:` section.

    {} with no section configured. Raises ValueError on a bad section
    or a bad entry — a typo must fail loudly, never silently run a
    malformed query.
    """
    raw = (config or {}).get('reports') or {}
    if not isinstance(raw, dict):
        raise ValueError('reports must map names to report definitions')
    return {name: validate_definition(name, definition)
            for name, definition in raw.items()}


def definition_argv(journal, definition):
    """hledger argv for a validated definition. No '--' separator."""
    argv = ['hledger', '-f', str(journal), definition['command']]
    if definition['command'] != 'accounts':
        argv += ['--output-format', 'csv']
    if definition.get('period'):
        argv += ['-p', definition['period']]
    if definition.get('monthly'):
        argv.append('-M')
    if definition.get('tree'):
        argv.append('--tree')
    if definition.get('flat'):
        argv.append('--flat')
    terms, _err = safe_query_terms(definition.get('query') or '')
    return argv + terms


def _parse_csv(text, command):
    """(columns, rows) from hledger --output-format csv output.

    bs/is carry a title row above the header row; the rest are a
    plain header row first.
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return [], []
    if command in ('bs', 'is') and rows[0] and rows[0][0].startswith(
            ('Balance Sheet', 'Income Statement')):
        rows = rows[1:]
    if not rows:
        return [], []
    columns, data = rows[0], rows[1:]
    return columns, [dict(zip(columns, row)) for row in data]


def run_report(journal, definition):
    """Run a validated definition; return {command, query, columns, rows, text}.

    Raises RuntimeError with hledger's own error (truncated) when the
    run fails, and when hledger is not installed.
    """
    argv = definition_argv(journal, definition)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError('hledger is not installed')
    except subprocess.TimeoutExpired:
        raise RuntimeError('Report timed out')
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:2000])
    if definition['command'] == 'accounts':
        rows = [{'account': line} for line in result.stdout.splitlines()
                if line.strip()]
        columns = ['account']
    else:
        columns, rows = _parse_csv(result.stdout, definition['command'])
    return {'command': definition['command'], 'query': definition.get('query', ''),
            'columns': columns, 'rows': rows, 'text': render_text(columns, rows)}


def render_text(columns, rows):
    """Plain-text table from the same columns/rows the web returns."""
    if not columns:
        return ''
    lines = [' | '.join(columns),
             '-+-'.join('-' * max(3, len(c)) for c in columns)]
    lines += [' | '.join(str(row.get(c, '')) for c in columns) for row in rows]
    return '\n'.join(lines)
