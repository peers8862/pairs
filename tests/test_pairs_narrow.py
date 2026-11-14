"""Narrow terminal fallback for `pair pairs` (I70).

The wide 3-column table needs ~130 columns. Below that, `pair pairs`
must render a stacked per-pair layout whose lines never exceed the
terminal width, instead of a table that wraps mid-column.
"""
import os

import pytest

import modules.pairs as P


def _run(capsys, width):
    """Run cmd_pairs with a faked terminal width, return stdout."""
    import shutil
    monkey_width = os.terminal_size((width, 24))
    orig = shutil.get_terminal_size
    P.shutil.get_terminal_size = lambda fallback=None: monkey_width
    try:
        P.cmd_pairs([])
    finally:
        P.shutil.get_terminal_size = orig
    return capsys.readouterr().out


def test_narrow_terminal_uses_stacked_layout(capsys):
    out = _run(capsys, 60)
    lines = out.splitlines()
    # No line may exceed the terminal width.
    assert all(len(line) <= 60 for line in lines), \
        [line for line in lines if len(line) > 60][:3]
    # All 14 pairs still present, with their three descriptions.
    for p in P.PAIRS:
        assert f"[{p['code']}]" in out
        assert p['name'] in out
    assert "Normal:" in out and "Reversal:" in out and "Edge:" in out
    # The wide header row must not appear in narrow mode.
    assert "Account Pair Matrix" not in out or "narrow" in out.lower()


def test_narrow_layout_mentions_it_is_narrow(capsys):
    out = _run(capsys, 80)
    assert "narrow" in out.lower()


def test_wide_terminal_unchanged(capsys):
    out = _run(capsys, 200)
    assert "Account Pair Matrix" in out
    # Wide header row present.
    assert "Normal" in out and "Reversal" in out and "Edge Case" in out
    lines = [line for line in out.splitlines() if "[0000]" in line]
    assert lines, "wide table row for pair 1 missing"
    # Wide mode keeps the grouped table.
    assert "┌" in out


def test_narrow_flag_forces_narrow(capsys):
    out = _run(capsys, 200)
    assert "Account Pair Matrix" in out
    # Explicit --narrow overrides a wide terminal.
    import shutil
    orig = shutil.get_terminal_size
    P.shutil.get_terminal_size = lambda fallback=None: os.terminal_size((200, 24))
    try:
        P.cmd_pairs(['--narrow'])
    finally:
        P.shutil.get_terminal_size = orig
    out = capsys.readouterr().out
    assert "narrow" in out.lower()
    assert all(len(line) <= 200 for line in out.splitlines())


def test_wide_flag_forces_wide(capsys):
    import shutil
    orig = shutil.get_terminal_size
    P.shutil.get_terminal_size = lambda fallback=None: os.terminal_size((60, 24))
    try:
        P.cmd_pairs(['--wide'])
    finally:
        P.shutil.get_terminal_size = orig
    out = capsys.readouterr().out
    assert "Account Pair Matrix" in out
