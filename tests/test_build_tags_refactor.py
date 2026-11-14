"""Refactor: all modules call build_tags() instead of inline tag dicts (I78).

Pure refactor — behaviour is identical under the default config (no
`tags:` section means every tag is enabled). The one intended semantic
change: inline dicts ignored a config `tags:` section that disables a
tag, while build_tags() respects it — that is what build_tags() is for.

The grep test below is the proof that no inline tag dict remains, with
an explicit allowlist for the deliberately-left sites:
- modules/pairs.py — the original build_tags() call site, whose fallback
  branch is an import guard (build_tags may be None there).
- modules/expense.py `tags = {}` — a journal-entry *parser*, not tag
  construction; build_tags() builds tags, it does not parse them.
"""
import re
from pathlib import Path

import lib.helpers as H
from lib.journal import build_tags

REPO = Path(__file__).resolve().parent.parent

# Files that build journal-entry tags and must go through build_tags().
REFACTORED = [
    'lib/fundraising.py',
    'lib/plan_rules.py',
    'modules/asset.py',
    'modules/dot.py',
    'modules/equity.py',
    'modules/expense.py',
    'modules/income.py',
    'modules/investment.py',
    'modules/liability.py',
    'modules/link.py',
    'modules/payroll.py',
    'modules/recurring.py',
    'modules/revenue.py',
    'modules/scenario.py',
    'modules/tax.py',
    'modules/transfer.py',
    'modules/web.py',
    'modules/year.py',
]

# (relative path, stripped line) pairs that may still hold an inline dict.
ALLOWLIST = {
    ('modules/pairs.py', "extra_tags = {'direction': direction}"),
    ('modules/pairs.py', "tags = {'pair': pair_code, 'direction': direction}"),
    ('modules/expense.py', 'tags = {}'),
}

INLINE_RE = re.compile(r"^\s*(?:\w+_)?tags = \{")


def test_no_inline_tag_dicts_remain():
    leftovers = []
    for rel in REFACTORED:
        path = REPO / rel
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if INLINE_RE.match(line) and (rel, line.strip()) not in ALLOWLIST:
                leftovers.append(f"{rel}:{n}: {line.strip()}")
    assert not leftovers, (
        "Inline tag dicts remain (convert to build_tags()):\n" + "\n".join(leftovers))


def test_refactored_modules_import_build_tags():
    missing = [rel for rel in REFACTORED
               if 'build_tags' not in (REPO / rel).read_text()]
    assert not missing, f"build_tags not imported in: {missing}"


def test_build_tags_matches_inline_dict_under_default_config(tmp_path, monkeypatch):
    """With no `tags:` section, build_tags() returns exactly the old literal."""
    monkeypatch.setattr(H, 'get_config_file', lambda: tmp_path / 'config.yaml')
    assert build_tags('1011', price='1.00', fee='0.50') == {
        'pair': '1011', 'price': '1.00', 'fee': '0.50'}
    assert build_tags('0000', contact='acme') == {
        'pair': '0000', 'contact': 'acme'}
    assert build_tags('1011', source='assets/x.yaml', division=None) == {
        'pair': '1011', 'source': 'assets/x.yaml'}


def test_build_tags_respects_disabled_tags(tmp_path, monkeypatch):
    """A config `tags:` section disabling a key drops it (inline dicts did not)."""
    config_file = tmp_path / 'config.yaml'
    config_file.write_text("tags:\n  price: false\n")
    monkeypatch.setattr(H, 'get_config_file', lambda: config_file)
    assert build_tags('1011', price='1.00', fee='0.50') == {
        'pair': '1011', 'fee': '0.50'}
