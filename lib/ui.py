"""Shared UI helpers for pair — menus, entity resolution, passthrough parsing."""

import sys
import subprocess
import shlex
from pathlib import Path

from lib.helpers import get_active_entity, get_entity_dir, load_global_config


# ─── Entity Journal Resolution ───────────────────────────────────────────────

def get_entity_journal():
    """Return the full path to the active entity's master journal file.

    This is the single file you pass to hledger -f to get all data.
    """
    entity_dir = get_entity_dir()
    return entity_dir / 'include' / 'entity.journal'


def get_entity_name():
    """Return the display name of the active entity."""
    config = load_global_config()
    active = config.get('active')
    if not active:
        return None
    entities = config.get('entities', [])
    for e in entities:
        if e.get('slug') == active:
            return e.get('name', active)
    return active


def get_entity_currency():
    """Return the base currency of the active entity."""
    config = load_global_config()
    active = config.get('active')
    if not active:
        return 'CAD'
    entities = config.get('entities', [])
    for e in entities:
        if e.get('slug') == active:
            return e.get('currency', 'CAD')
    return 'CAD'


def require_entity():
    """Exit with message if no active entity is set."""
    entity = get_active_entity()
    if not entity:
        print("  No active entity. Run 'pair init' or 'pair switch <slug>'.")
        sys.exit(1)
    return entity


# ─── Passthrough Parsing ─────────────────────────────────────────────────────

def split_passthrough(args):
    """Split args at '--' into (pair_args, tool_args).

    Everything before '--' is for pair to interpret.
    Everything after '--' passes through to the underlying tool verbatim.

    Returns: (list, list)
    """
    if '--' in args:
        idx = args.index('--')
        return args[:idx], args[idx + 1:]
    return args, []


# ─── Numbered Menu System ────────────────────────────────────────────────────

def show_menu(title, options, prompt_text="Select"):
    """Display a numbered menu and return the selected option.

    Args:
        title: Header line (e.g. "[deskone] Dashboards")
        options: List of dicts with keys:
            - key: short name for direct CLI access (e.g. 'web')
            - label: display text (e.g. 'hledger-web (browser, localhost:5000)')
        prompt_text: The input prompt string

    Returns:
        The selected option dict, or None if user quits.
    """
    entity = get_active_entity() or '?'

    print(f"\n  [{entity}] {title}")
    print(f"  {'─' * 50}")
    for i, opt in enumerate(options, 1):
        print(f"  {i:>2}) {opt['key']:<20} {opt['label']}")
    print()

    while True:
        try:
            raw = input(f"  {prompt_text} [1-{len(options)}, name, or q]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return None

        if not raw or raw.lower() == 'q':
            return None

        # Try numeric
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass

        # Try by key name (case-insensitive)
        for opt in options:
            if raw.lower() == opt['key'].lower():
                return opt

        print(f"  Enter 1-{len(options)}, a name, or q to quit.")


def resolve_menu_or_direct(args, options):
    """If args[0] matches an option key or number, return (option, remaining_args).

    If no args, returns (None, []) signaling interactive menu needed.
    """
    if not args:
        return None, []

    first = args[0]
    remaining = args[1:]

    # Try numeric
    try:
        idx = int(first) - 1
        if 0 <= idx < len(options):
            return options[idx], remaining
    except ValueError:
        pass

    # Try by key name
    for opt in options:
        if first.lower() == opt['key'].lower():
            return opt, remaining

    # Not a menu selection — return None so caller can handle
    return None, args


# ─── Tool Launcher ───────────────────────────────────────────────────────────

def launch_tool(cmd, tool_args=None, background=False, env_extra=None):
    """Launch an external tool with optional arguments.

    Args:
        cmd: list of command parts (e.g. ['hledger-web', '-f', path])
        tool_args: additional args to append
        background: if True, don't wait for exit
        env_extra: dict of extra environment variables
    """
    import os

    full_cmd = list(cmd)
    if tool_args:
        full_cmd.extend(tool_args)

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    try:
        if background:
            subprocess.Popen(full_cmd, env=env,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            print(f"  Launched: {' '.join(full_cmd)}")
        else:
            subprocess.run(full_cmd, env=env)
    except FileNotFoundError:
        tool_name = full_cmd[0] if full_cmd else 'unknown'
        print(f"  Error: '{tool_name}' not found. Is it installed?")
        sys.exit(1)
    except KeyboardInterrupt:
        pass


def check_tool(name):
    """Check if a tool is available on PATH. Returns bool."""
    import shutil
    return shutil.which(name) is not None
