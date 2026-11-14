"""pair report — passthrough to hledger, plus the report builder (I76).

`pair report <hledger-cmd>` is unchanged: it passes arguments through
to hledger against the active entity's journal. The builder sits
alongside it as three subcommands that all run through the same
lib/report_builder.py core as the web UI:

    pair report list                        Named reports from config.yaml
    pair report run <name>                  Run a saved report
    pair report build --cmd register ...    Build one from flags, on the spot

A report is a named hledger query (command + terms + display options),
validated before anything runs. `pair report build --save <name>`
persists a flag-built report into config.yaml `reports:`.
"""

import sys
import subprocess
import shutil
from pathlib import Path

from lib.helpers import load_config, save_config, parse_global_flags
from lib.report_builder import (REPORT_COMMANDS, compose_query, named_reports,
                                run_report, safe_query_terms,
                                validate_definition)
from lib.ui import get_entity_journal, get_entity_name, require_entity


# Builder subcommands. 'run'/'list'/'build' are not hledger commands, so
# intercepting them can never shadow a passthrough.
BUILDER_COMMANDS = ('list', 'run', 'build')

# CLI field flags -> compose_query field names. --date is deliberately
# absent: parse_global_flags eats `--date <value>` as the global date
# override, so date ranges belong in raw --query (e.g. --query 'date:2026').
_FIELD_FLAGS = {
    '--acct': 'acct', '--desc': 'desc', '--payee': 'payee',
    '--note': 'note', '--code': 'code', '--cur': 'cur',
    '--amt': 'amt', '--amt-op': 'amt_op', '--status': 'status',
    '--type': 'type', '--depth': 'depth', '--expr': 'expr',
}


def dispatch(args):
    """Route to the report command."""
    cmd_report(args)


def _fail(message):
    """Clear stdout message + exit 1: the repo CLI convention for bad input."""
    print(f"  {message}")
    sys.exit(1)


def _journal():
    """Active entity's journal, with the company.journal fallback."""
    journal = str(get_entity_journal())
    if not Path(journal).exists():
        alt = Path(journal).parent / 'company.journal'
        if alt.exists():
            journal = str(alt)
    return journal


def _opt(args, name, default=None):
    """Value of an exact `--name <value>` flag, or the default."""
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
    return default


def _load_reports():
    """Validated named reports from config.yaml, or exit 1 on bad config."""
    try:
        return named_reports(load_config())
    except ValueError as e:
        _fail(str(e))


def _run_and_print(journal, definition):
    """Run one validated definition and print its text table."""
    try:
        result = run_report(journal, definition)
    except RuntimeError as e:
        _fail(str(e))
    print(result['text'])


def _cmd_list():
    reports = _load_reports()
    if not reports:
        print("  No named reports defined. See 'pair report build --help'.")
        return
    for name, definition in reports.items():
        title = definition['title']
        extra = f" — {title}" if title != name else ""
        print(f"  {name}: {definition['command']} {definition['query']}{extra}")


def _cmd_run(args):
    if not args:
        _fail("Usage: pair report run <name>  (see 'pair report list')")
    require_entity()
    reports = _load_reports()
    name = args[0]
    if name not in reports:
        _fail(f"Unknown report '{name}'. See 'pair report list'.")
    _run_and_print(_journal(), reports[name])


def _cmd_build(args):
    """Build a report from flags, optionally saving it as a named report."""
    fields = {}
    for flag, field in _FIELD_FLAGS.items():
        value = _opt(args, flag)
        if value is not None:
            fields[field] = value
    if '--real' in args:
        fields['real'] = True
    tag = _opt(args, '--tag')
    if tag is not None:
        name, _, value = tag.partition('=')
        fields['tag_name'] = name
        if value:
            fields['tag_value'] = value
    raw_query = _opt(args, '--query', '') or ''
    composed = compose_query(fields)
    query = ' '.join(part for part in (composed, raw_query.strip()) if part)
    _terms, err = safe_query_terms(query)
    if err:
        _fail(err)
    raw = {
        'title': _opt(args, '--title') or 'ad-hoc',
        'command': _opt(args, '--cmd', 'register'),
        'query': query,
        'period': _opt(args, '--period'),
        'monthly': '--monthly' in args or '-M' in args,
        'tree': '--tree' in args,
        'flat': '--flat' in args,
    }
    save_name = _opt(args, '--save')
    try:
        definition = validate_definition(save_name or 'ad-hoc', raw)
    except ValueError as e:
        _fail(str(e))
    if save_name:
        config = load_config()
        reports = config.get('reports') or {}
        if not isinstance(reports, dict):
            _fail('reports must map names to report definitions')
        if save_name in reports and '--force' not in args:
            _fail(f"Report '{save_name}' already exists "
                  "(use --force to overwrite it)")
        reports[save_name] = definition
        config['reports'] = reports
        save_config(config)
        print(f"  Saved report '{save_name}'.")
    require_entity()
    _run_and_print(_journal(), definition)


def cmd_report(args):
    """Pass arguments through to hledger against the active entity's journal.

    Usage:
        pair report register expenses -M
        pair report bs
        pair report is -p 2026
        pair report bal assets --tree
        pair report accounts
        pair report list
        pair report run <name>
        pair report build --cmd register --acct Expenses [--save <name>]
    """
    flags, remaining = parse_global_flags(args)

    if not remaining:
        print_help()
        return

    if remaining[0] in BUILDER_COMMANDS:
        if remaining[0] == 'list':
            _cmd_list()
        elif remaining[0] == 'run':
            _cmd_run(remaining[1:])
        elif flags['help']:
            print_build_help()
        else:
            _cmd_build(remaining[1:])
        return

    if flags['help']:
        print_help()
        return

    require_entity()

    # Verify hledger is available
    if not shutil.which('hledger'):
        print("  hledger is not installed or not in PATH.")
        print("  Install: https://hledger.org/install.html")
        sys.exit(1)

    journal = _journal()
    entity_name = get_entity_name()

    # Build the hledger command: hledger -f <journal> <remaining args...>
    cmd = ['hledger', '-f', journal] + remaining

    # Show what we're running (subtle, one line)
    print(f"  [{entity_name}] hledger {' '.join(remaining)}")
    print(flush=True)

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


def print_build_help():
    print("""pair report build — build a report from flags, on the spot

Usage:
  pair report build --cmd <command> [field flags] [--query Q]
                    [--period P] [--monthly] [--tree] [--flat]
                    [--save <name>] [--force]

Commands (one of): register, print, bal, balance, bs, is, accounts
  (default: register)

Field flags compose a query the same way the web's advanced search does:
  --acct ACCT   --desc TEXT   --payee NAME   --note TEXT   --code CODE
  --cur CUR     --amt N       --amt-op OP    --status unmarked|pending|cleared
  --type TYPES  --tag NAME[=VALUE]  --depth N  --real  --expr EXPR

  --query Q     Raw hledger query terms (combined with the field flags).
                Date ranges belong here, e.g. --query 'date:2026-01'.
  --period P    Report period: YYYY, YYYY-MM, YYYY-MM-DD or YYYYQn
  --monthly     -M: one row per month (register/bs/is)
  --tree        Tree layout (bal/bs/is)      --flat  Flat layout
  --title T     Title (saved reports only; defaults to the name)
  --save NAME   Save this report into config.yaml `reports:` under NAME
  --force       Overwrite an existing saved report of that name

Every query term goes through the same leading-dash guard as /api/search:
terms starting with '-' are rejected. Bad input exits 1, nothing runs.

Examples:
  pair report build --cmd register --acct Expenses
  pair report build --cmd bs --period 2026 --save year-bs
  pair report build --cmd register --amt 100 --amt-op '>' --save big-items
""")


def print_help():
    print("""pair report — passthrough to hledger, plus the report builder

  Runs any hledger command against the active entity's journal file.
  Saves you from remembering the path to the entity journal.

Usage:
  pair report <hledger-command> [args...]
  pair report list
  pair report run <name>
  pair report build --cmd <command> [flags...] [--save <name>]

Examples:
  pair report register              Full register
  pair report register expenses -M  Monthly expense register
  pair report bs                    Balance sheet
  pair report is                    Income statement
  pair report is -p 2026-Q2         Income statement for Q2
  pair report bal assets --tree     Asset balances as tree
  pair report accounts              List all accounts
  pair report bal -M --transpose    Monthly balances transposed
  pair report cashflow              Cash flow statement
  pair report stats                 Journal statistics

  pair report list                  Saved reports from config.yaml `reports:`
  pair report run monthly-expenses  Run a saved report
  pair report build --cmd register --acct Expenses
                                    Build one from flags, on the spot
  pair report build --cmd bs --period 2026 --save year-bs
                                    Build one and save it by name

Any hledger command and flags work in the passthrough — it just supplies
-f <journal>. Builder reports are validated before they run: unknown
commands, bad periods, and leading-dash query terms are rejected.
See 'pair report build --help' for the builder flags.
""")
