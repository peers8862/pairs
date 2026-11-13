import shutil

import pytest

import modules.scenario as sc

CONFIG = {'pair': {'currency': 'CAD'}, 'accounts': {'bank': 'Assets:Current:Chequing'}}


@pytest.fixture
def entity(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, 'get_entity_dir', lambda: tmp_path)
    monkeypatch.setattr(sc, 'load_config', lambda: CONFIG)
    return tmp_path


def test_add_rule_writes_yaml_and_rules_journal(entity):
    slug = sc.create_scenario('Lean')
    rule = sc.add_rule(slug, {'name': 'Rent', 'amount': 1000, 'start': '2026-01-01', 'months': 2})
    assert rule['id'] == 'r1'
    text = (entity / 'scenarios' / slug / 'rules.journal').read_text()
    assert text.count('scenario:lean') == 2 and 'rule:r1' in text
    assert [f.name for f in sc.scenario_files(slug)] == ['expenses.journal', 'rules.journal']


def test_bad_rule_is_rejected(entity):
    slug = sc.create_scenario('Bad')
    with pytest.raises(ValueError):
        sc.add_rule(slug, {'name': 'x', 'kind': 'nope', 'start': '2026-01-01'})


def test_update_and_remove_rule_regenerate(entity):
    slug = sc.create_scenario('Edit')
    sc.add_rule(slug, {'name': 'Rent', 'amount': 1000, 'start': '2026-01-01', 'months': 2})
    sc.update_rule(slug, 'r1', {'months': 3})
    assert (entity / 'scenarios' / slug / 'rules.journal').read_text().count('rule:r1') == 3
    sc.remove_rule(slug, 'r1')
    assert (entity / 'scenarios' / slug / 'rules.journal').read_text() == ''


def test_copy_keeps_rules_and_retags_entries(entity):
    slug = sc.create_scenario('Base')
    sc.add_rule(slug, {'name': 'Rent', 'amount': 1000, 'start': '2026-01-01', 'every': 'once'})
    sc.add_entries(slug, sc.build_scenario_entries(slug, '2026-02-01', 'Desk', 'Expenses:Office',
                                                   200, 'Assets:Current:Chequing', 'CAD'))
    new = sc.copy_scenario(slug, 'Base copy')
    assert sc.load_rules(new)[0]['name'] == 'Rent'
    assert 'scenario:base-copy' in sc.scenario_journal(new).read_text()
    assert 'scenario:base-copy' in (entity / 'scenarios' / new / 'rules.journal').read_text()


def test_migrate_groups_regular_runs(entity):
    slug = sc.create_scenario('Old')
    sc.add_entries(slug, sc.build_scenario_entries(slug, '2026-01-05', 'Rent', 'Expenses:Rent', 900,
                                                   'Assets:Current:Chequing', 'CAD', repeat=4))
    sc.add_entries(slug, sc.build_scenario_entries(slug, '2026-03-01', 'Laptop', 'Expenses:Office', 2000,
                                                   'Assets:Current:Chequing', 'CAD'))
    assert sc.migrate_entries(slug) == 2
    rules = sc.load_rules(slug)
    assert rules[0]['every'] == 'monthly' and rules[0]['repeat'] == 4
    assert rules[1]['every'] == 'once'
    assert sc.read_entries(slug) == []


@pytest.mark.skipif(shutil.which('hledger') is None, reason="hledger not installed")
def test_report_counts_rules_and_entries(entity):
    slug = sc.create_scenario('Mix')
    sc.add_rule(slug, {'name': 'Rent', 'account': 'Expenses:Rent', 'amount': 1000,
                       'start': '2026-01-01', 'months': 2})
    sc.add_rule(slug, {'name': 'Sales', 'kind': 'revenue', 'account': 'Income:Sales', 'amount': 500,
                       'start': '2026-01-01', 'every': 'once'})
    rows = {a: p for a, _, p, _ in sc.scenario_report_rows(None, sc.scenario_files(slug), slug)}
    assert float(rows['Expenses:Rent']) == 2000 and float(rows['Income:Sales']) == 500
