"""Entity report builder (I76): one shared core, three front-ends.

The three front-ends (saved named reports in config.yaml, flag-driven
CLI builder, web UI) all run through the same core in
lib/report_builder.py: a report definition is a named hledger query
(command + terms + display options), validated at load time, with every
query term going through the same leading-dash guard that protects
/api/search (see tests/test_search_guard.py). `pair report` itself
stays the raw hledger passthrough — the builder sits alongside it.

Test fixtures only; no entity data is touched. The `peers` entity
has no entity.journal, so tests use a tmp fixture journal.
"""

import subprocess

import pytest
import yaml

import lib.helpers as H
import lib.report_builder as RB
import modules.report as R

needs_hledger = pytest.mark.skipif(
    subprocess.run(['which', 'hledger'], capture_output=True).returncode != 0,
    reason="hledger not installed")

JOURNAL = """2026-01-05 * Big purchase
    Expenses:Operating:Supplies    CAD 500.00
    Assets:Current:Chequing        CAD -500.00

2026-01-06 * Small purchase
    Expenses:Operating:Supplies    CAD 50.00
    Assets:Current:Chequing        CAD -50.00

2026-02-01 * Sale
    Assets:Current:Chequing        CAD 1000.00
    Income:Sales                   CAD -1000.00
"""

CONFIG = {
    'pair': {'currency': 'CAD'},
    'reports': {
        'monthly-expenses': {
            'title': 'Monthly expenses',
            'command': 'register',
            'query': 'acct:Expenses',
            'monthly': True,
        },
        'balances': {'command': 'bal'},
        'income': {'command': 'is', 'query': 'date:2026'},
    },
}


@pytest.fixture
def journal(tmp_path):
    p = tmp_path / 'company.journal'
    p.write_text(JOURNAL)
    return p


@pytest.fixture
def entity(tmp_path, monkeypatch, journal):
    """Tmp entity dir with config.yaml + include/entity.journal."""
    include = tmp_path / 'include'
    include.mkdir()
    (include / 'entity.journal').write_text(JOURNAL)
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(CONFIG))
    monkeypatch.setattr(H, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(R, 'require_entity', lambda: 'fixture')
    monkeypatch.setattr(R, 'get_entity_journal', lambda: include / 'entity.journal')
    return tmp_path


def _result(journal, definition):
    return RB.run_report(journal, definition)


# ─── the guard, at the lib level ─────────────────────────────────────────────

def test_guard_rejects_leading_dash():
    terms, err = RB.safe_query_terms('--output-file=/tmp/x')
    assert terms == [] and "cannot start with '-'" in err
    terms, err = RB.safe_query_terms('-f /etc/passwd')
    assert terms == [] and err


def test_guard_rejects_unbalanced_quotes():
    terms, err = RB.safe_query_terms('desc:"unclosed')
    assert terms == [] and 'Unbalanced quotes' in err


def test_guard_passes_prefix_queries_and_never_adds_separator():
    terms, err = RB.safe_query_terms('amt:>100')
    assert err == '' and terms == ['amt:>100']
    assert '--' not in terms
    terms, err = RB.safe_query_terms("desc:'Big purchase' type:AL")
    assert err == '' and len(terms) == 2


# ─── compose_query (structured fields -> query string) ───────────────────────

def test_compose_query_fields():
    assert RB.compose_query({'acct': 'Expenses'}) == 'acct:Expenses'
    assert RB.compose_query({'acct': 'Operating Expenses'}) == "acct:'Operating Expenses'"
    assert RB.compose_query({'amt': '100', 'amt_op': '>'}) == "amt:'>100'"
    assert RB.compose_query({'status': 'cleared'}) == 'status:*'
    assert RB.compose_query({'status': 'pending'}) == 'status:!'
    assert RB.compose_query({'type': 'al'}) == 'type:AL'
    assert RB.compose_query({'real': True}) == 'real:'
    assert RB.compose_query({'depth': '2'}) == 'depth:2'
    assert RB.compose_query({'expr': 'amt>0'}) == "expr:'amt>0'"
    assert RB.compose_query({'tag_name': 'division',
                             'tag_value': 'ops'}) == 'tag:division=ops'
    assert RB.compose_query({'date': '2026-01'}) == 'date:2026-01'
    assert RB.compose_query({'acct': 'X', 'negate': {'acct': True}}) == 'not:acct:X'
    assert RB.compose_query({}) == ''


# ─── definition validation ───────────────────────────────────────────────────

def test_validate_definition_minimal():
    d = RB.validate_definition('balances', {'command': 'bal'})
    assert d == {'title': 'balances', 'command': 'bal', 'query': '',
                 'period': None, 'monthly': False, 'tree': False, 'flat': False}


def test_validate_definition_full():
    d = RB.validate_definition('x', {'title': 'T', 'command': 'is',
                                     'query': 'date:2026', 'period': '2026',
                                     'monthly': True, 'tree': True})
    assert d['title'] == 'T' and d['period'] == '2026'
    assert d['monthly'] is True and d['tree'] is True and d['flat'] is False


def test_validate_definition_rejects():
    bad = [
        ({'query': 'acct:Expenses'}, "missing command"),
        ({'command': 'bogus'}, "unknown command"),
        ({'command': 'bal', 'extra': 1}, "unknown key"),
        ({'command': 'bal', 'query': '--output-file=/tmp/x'}, "leading dash"),
        ({'command': 'bal', 'query': 'desc:"unclosed'}, "unbalanced quotes"),
        ({'command': 'bal', 'query': 42}, "non-string query"),
        ({'command': 'bal', 'period': '2026-13'}, "bad period month"),
        ({'command': 'bal', 'period': 'last month'}, "free-text period"),
        ({'command': 'bal', 'period': '2026-Q5'}, "bad quarter"),
        ({'command': 'bal', 'monthly': 'yes'}, "non-bool monthly"),
        ({'command': 'bal', 'title': 7}, "non-string title"),
    ]
    for raw, _why in bad:
        with pytest.raises(ValueError):
            RB.validate_definition('x', raw)
    with pytest.raises(ValueError):
        RB.validate_definition('x', 'not-a-dict')
    with pytest.raises(ValueError):
        RB.validate_definition('', {'command': 'bal'})


def test_named_reports_empty_and_bad():
    assert RB.named_reports({}) == {}
    assert RB.named_reports(None) == {}
    assert RB.named_reports({'pair': {'currency': 'CAD'}}) == {}
    with pytest.raises(ValueError):
        RB.named_reports({'reports': ['a']})
    with pytest.raises(ValueError):
        RB.named_reports({'reports': {'ok': {'command': 'bal'},
                                     'bad': {'command': 'bogus'}}})


def test_named_reports_reads_config():
    reports = RB.named_reports(CONFIG)
    assert set(reports) == {'monthly-expenses', 'balances', 'income'}
    assert reports['monthly-expenses']['monthly'] is True
    assert reports['balances']['title'] == 'balances'
    assert reports['income']['query'] == 'date:2026'


# ─── core run: every supported command ───────────────────────────────────────

@needs_hledger
def test_run_register_rows(journal):
    out = _result(journal, RB.validate_definition('r', {'command': 'register'}))
    assert out['command'] == 'register'
    assert out['columns'] == ['txnidx', 'date', 'code', 'description',
                              'account', 'amount', 'total']
    assert len(out['rows']) == 6
    assert out['rows'][0]['account'] == 'Expenses:Operating:Supplies'
    assert 'CAD 500.00' in out['text']


@needs_hledger
def test_run_register_query_filters(journal):
    out = _result(journal, RB.validate_definition(
        'r', {'command': 'register', 'query': 'acct:Expenses'}))
    assert len(out['rows']) == 2
    out = _result(journal, RB.validate_definition(
        'r', {'command': 'register', 'query': 'amt:>100'}))
    assert len(out['rows']) == 4


@needs_hledger
def test_run_bal_rows(journal):
    out = _result(journal, RB.validate_definition('b', {'command': 'bal'}))
    assert out['columns'] == ['account', 'balance']
    by_acct = {r['account']: r['balance'] for r in out['rows']}
    assert by_acct['Assets:Current:Chequing'] == 'CAD 450.00'
    assert by_acct['Expenses:Operating:Supplies'] == 'CAD 550.00'
    assert by_acct['Total:'] == '0'


@needs_hledger
def test_run_bs_and_is_rows(journal):
    out = _result(journal, RB.validate_definition('b', {'command': 'bs'}))
    assert out['columns'][0] == 'Account'
    by_acct = {r['Account']: r[out['columns'][1]] for r in out['rows']}
    assert by_acct['Assets:Current:Chequing'] == 'CAD 450.00'
    assert by_acct['Net:'] == 'CAD 450.00'
    out = _result(journal, RB.validate_definition('i', {'command': 'is'}))
    by_acct = {r['Account']: r[out['columns'][1]] for r in out['rows']}
    assert by_acct['Income:Sales'] == 'CAD 1000.00'
    assert by_acct['Expenses:Operating:Supplies'] == 'CAD 550.00'
    assert by_acct['Net:'] == 'CAD 450.00'


@needs_hledger
def test_run_accounts_and_print(journal):
    out = _result(journal, RB.validate_definition('a', {'command': 'accounts'}))
    assert out['columns'] == ['account']
    assert [r['account'] for r in out['rows']] == [
        'Assets:Current:Chequing', 'Expenses:Operating:Supplies', 'Income:Sales']
    out = _result(journal, RB.validate_definition('p', {'command': 'print'}))
    assert len(out['rows']) == 6
    assert out['rows'][0]['account'] == 'Expenses:Operating:Supplies'


@needs_hledger
def test_run_period_option(journal):
    out = _result(journal, RB.validate_definition(
        'b', {'command': 'bs', 'period': '2026-01'}))
    by_acct = {r['Account']: r[out['columns'][1]] for r in out['rows']}
    assert by_acct['Assets:Current:Chequing'] == 'CAD -550.00'


@needs_hledger
def test_run_hledger_error_and_missing_journal(journal, tmp_path):
    with pytest.raises(RuntimeError, match='could not parse'):
        _result(journal, RB.validate_definition(
            'r', {'command': 'register', 'query': 'type:Z'}))
    with pytest.raises(RuntimeError):
        _result(tmp_path / 'no-such.journal',
                RB.validate_definition('b', {'command': 'bal'}))


def test_argv_has_no_separator_and_options_before_terms(journal):
    argv = RB.definition_argv(journal, RB.validate_definition(
        'r', {'command': 'register', 'query': 'acct:Expenses',
              'period': '2026-01', 'monthly': True}))
    assert '--' not in argv
    assert argv[-1] == 'acct:Expenses'
    assert '-p' in argv and '2026-01' in argv and '-M' in argv
    assert argv[3] == 'register' and '--output-format' in argv


def test_render_text():
    text = RB.render_text(['account', 'balance'],
                          [{'account': 'Assets:X', 'balance': 'CAD 1.00'}])
    assert 'account' in text and 'Assets:X' in text and 'CAD 1.00' in text


# ─── CLI: list / run ─────────────────────────────────────────────────────────

def test_cli_list(entity, capsys):
    R.cmd_report(['list'])
    out = capsys.readouterr().out
    assert 'monthly-expenses' in out and 'balances' in out and 'income' in out
    assert 'Monthly expenses' in out


def test_cli_list_no_reports(entity, capsys):
    (entity / 'config.yaml').write_text(yaml.safe_dump({'pair': {'currency': 'CAD'}}))
    R.cmd_report(['list'])
    assert 'no named reports' in capsys.readouterr().out.lower()


@needs_hledger
def test_cli_run_named(entity, capsys):
    # monthly-expenses is a monthly register: one row per month, 550.00 in Jan.
    R.cmd_report(['run', 'monthly-expenses'])
    out = capsys.readouterr().out
    assert 'CAD 550.00' in out and 'Expenses:Operating:Supplies' in out


@needs_hledger
def test_cli_run_unknown_name(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['run', 'nope'])
    assert exc.value.code == 1
    assert "Unknown report 'nope'" in capsys.readouterr().out


@needs_hledger
def test_cli_run_named_matches_flag_built(entity, capsys):
    R.cmd_report(['run', 'balances'])
    named = capsys.readouterr().out
    R.cmd_report(['build', '--cmd', 'bal'])
    built = capsys.readouterr().out
    assert named == built


# ─── CLI: build ──────────────────────────────────────────────────────────────

@needs_hledger
def test_cli_build_register_acct(entity, capsys):
    R.cmd_report(['build', '--cmd', 'register', '--acct', 'Expenses'])
    out = capsys.readouterr().out
    assert 'CAD 500.00' in out and 'CAD 50.00' in out
    assert 'CAD 1000.00' not in out


@needs_hledger
def test_cli_build_fields_compose(entity, capsys):
    R.cmd_report(['build', '--cmd', 'register', '--amt', '100', '--amt-op', '>'])
    out = capsys.readouterr().out
    assert 'CAD 500.00' in out and 'CAD 1000.00' in out
    assert 'CAD 50.00' not in out


def test_cli_build_bad_command(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['build', '--cmd', 'bogus'])
    assert exc.value.code == 1
    assert 'bogus' in capsys.readouterr().out


def test_cli_build_guarded_query(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['build', '--cmd', 'register',
                      '--query', '--output-file=/tmp/x'])
    assert exc.value.code == 1
    assert "cannot start with '-'" in capsys.readouterr().out


def test_cli_build_bad_period(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['build', '--cmd', 'bal', '--period', 'last month'])
    assert exc.value.code == 1
    assert 'period' in capsys.readouterr().out.lower()


@needs_hledger
def test_cli_build_save_writes_config_and_runs(entity, capsys):
    R.cmd_report(['build', '--cmd', 'bal', '--save', 'my-bal'])
    out = capsys.readouterr().out
    assert 'CAD 450.00' in out
    assert 'my-bal' in H.load_config()['reports']
    assert H.load_config()['reports']['my-bal']['command'] == 'bal'


@needs_hledger
def test_cli_build_save_existing_refused_then_forced(entity, capsys):
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['build', '--cmd', 'bal', '--save', 'balances'])
    assert exc.value.code == 1
    assert 'already exists' in capsys.readouterr().out
    R.cmd_report(['build', '--cmd', 'register', '--acct', 'Expenses',
                  '--save', 'balances', '--force'])
    assert H.load_config()['reports']['balances']['command'] == 'register'


def test_cli_build_save_validates_before_writing(entity, capsys):
    with pytest.raises(SystemExit):
        R.cmd_report(['build', '--cmd', 'bogus', '--save', 'nope'])
    assert 'nope' not in H.load_config().get('reports', {})


# ─── CLI: passthrough unchanged ──────────────────────────────────────────────

@needs_hledger
def test_cli_passthrough_still_works(entity, capsys):
    # The passthrough runs real hledger, whose stdout bypasses capsys
    # (subprocess inherits the fd), so assert on the exit code and the
    # header line here, and on the accounts via a direct hledger call.
    with pytest.raises(SystemExit) as exc:
        R.cmd_report(['accounts'])
    assert exc.value.code == 0
    assert 'hledger accounts' in capsys.readouterr().out
    import subprocess as sp
    journal = entity / 'include' / 'entity.journal'
    out = sp.run(['hledger', '-f', str(journal), 'accounts'],
                 capture_output=True, text=True).stdout
    assert 'Assets:Current:Chequing' in out
    assert 'Expenses:Operating:Supplies' in out


def test_cli_help_shows_builder(entity, capsys):
    R.cmd_report([])
    out = capsys.readouterr().out
    assert 'list' in out and 'run' in out and 'build' in out


def test_cli_build_help(entity, capsys):
    R.cmd_report(['build', '--help'])
    out = capsys.readouterr().out
    assert '--cmd' in out and '--save' in out
