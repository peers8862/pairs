from lib.features import resolve, pack_for_command, pack_for_path, PACKS


def test_missing_features_means_baseline_only():
    assert not any(resolve({}, {}).values())


def test_global_list_turns_packs_on():
    state = resolve({'features': ['scenarios', 'executive']}, {})
    assert state['scenarios'] and state['executive'] and not state['captable']


def test_entity_mapping_overrides_global():
    state = resolve({'features': ['scenarios', 'executive']},
                    {'features': {'executive': False, 'captable': True}})
    assert state['scenarios'] and not state['executive'] and state['captable']


def test_entity_list_form_adds_packs():
    assert resolve({}, {'features': ['captable']})['captable']


def test_pack_needing_another_is_off_without_it():
    state = resolve({'features': ['runway']}, {})
    assert not state['runway']
    assert resolve({'features': ['runway', 'scenarios']}, {})['runway']


def test_command_and_path_lookup():
    assert pack_for_command('scenario') == 'scenarios'
    assert pack_for_command('expense') is None
    assert pack_for_path('/api/scenario/x/item') == 'scenarios'
    assert pack_for_path('/api/scenarios') == 'scenarios'
    assert pack_for_path('/api/budgets') is None
    assert pack_for_path('/api/metrics') is None          # dashboard, baseline
    assert pack_for_path('/api/scenariosx') is None


def test_every_pack_requirement_exists():
    for pack in PACKS.values():
        for r in pack.get('requires', []):
            assert r in PACKS
