def test_project_modules_import():
    from lib import journal
    assert hasattr(journal, 'format_entry')
