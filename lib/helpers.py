"""Shared helpers for pair."""

import os
import re
import sys
import yaml
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP


# ─── Paths ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
GLOBAL_CONFIG_FILE = BASE_DIR / 'global.yaml'


# ─── Global config (multi-entity) ────────────────────────────────────────────

def load_global_config():
    """Load global.yaml. Returns dict or empty dict if missing."""
    if not GLOBAL_CONFIG_FILE.exists():
        return {}
    with open(GLOBAL_CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save_global_config(data):
    """Save global.yaml."""
    with open(GLOBAL_CONFIG_FILE, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def get_active_entity():
    """Return the active entity slug from global.yaml, or None."""
    config = load_global_config()
    return config.get('active')


# Backward compat alias
get_active_company = get_active_entity


def get_entity_dir():
    """Return Path to active entity directory.

    Reads global.yaml to find the active entity slug, then returns
    BASE_DIR / 'entities' / slug. Falls back to BASE_DIR if global.yaml
    doesn't exist (backward compat during init).
    """
    if not GLOBAL_CONFIG_FILE.exists():
        return BASE_DIR
    config = load_global_config()
    active = config.get('active')
    if not active:
        return BASE_DIR
    return BASE_DIR / 'entities' / active


# Backward compat alias
get_company_dir = get_entity_dir


# ─── Entity config ───────────────────────────────────────────────────────────

def get_config_file():
    """Return path to active entity's config.yaml."""
    return get_entity_dir() / 'config.yaml'


# Keep CONFIG_FILE for backward compat in modules that import it directly.
# This is a module-level reference; prefer get_config_file() for runtime use.
CONFIG_FILE = None  # Sentinel — use get_config_file() instead


# ─── Money ───────────────────────────────────────────────────────────────────

def money(value):
    """Round to 2 decimal places."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ─── Path utilities ──────────────────────────────────────────────────────────

def expand_path(p):
    """Expand ~ in paths."""
    return Path(os.path.expanduser(str(p)))


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


# ─── Config ──────────────────────────────────────────────────────────────────

def load_config():
    """Load entity config.yaml or exit with message."""
    config_file = get_config_file()
    if not config_file.exists():
        print("No config.yaml found. Run 'pair init' first.")
        sys.exit(1)
    with open(config_file) as f:
        return yaml.safe_load(f)


def save_config(config):
    """Write entity config.yaml."""
    config_file = get_config_file()
    ensure_dir(config_file.parent)
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


# ─── Prompts ─────────────────────────────────────────────────────────────────

def prompt(label, default=None, required=True, validator=None):
    """Interactive prompt with optional default and validation."""
    while True:
        if default is not None:
            raw = input(f"{label} [{default}]: ").strip()
            value = raw if raw else str(default)
        else:
            raw = input(f"{label}: ").strip()
            value = raw
        if not value and required:
            print("  Required.")
            continue
        if not value and not required:
            return value
        if validator:
            err = validator(value)
            if err:
                print(f"  {err}")
                continue
        return value


def prompt_choice(label, choices, default=None):
    """Prompt with enumerated choices."""
    print(f"\n{label}")
    for i, choice in enumerate(choices, 1):
        marker = " *" if choice == default else ""
        print(f"  {i}. {choice}{marker}")
    while True:
        raw = input(f"Choice [1-{len(choices)}]: ").strip()
        if not raw and default:
            return default
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except (ValueError, IndexError):
            pass
        print(f"  Enter 1-{len(choices)}.")


def confirm(message, default_yes=True):
    """Yes/no confirmation. Returns bool."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    raw = input(f"{message} {suffix} ").strip().lower()
    if not raw:
        return default_yes
    return raw in ('y', 'yes')


# ─── Validators ──────────────────────────────────────────────────────────────

def slugify(text):
    """Convert text to a slug: lowercase, hyphens, no special chars."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    # Ensure starts with a letter
    if slug and not slug[0].isalpha():
        slug = 'x-' + slug
    return slug or 'untitled'


def validate_slug(value):
    """Slug must be lowercase alphanumeric + hyphens, start with letter."""
    if not re.match(r'^[a-z][a-z0-9-]*$', value):
        return "Must be lowercase letters, numbers, hyphens. Start with a letter."
    return None


def validate_date(value):
    """Must be YYYY-MM-DD."""
    from datetime import datetime
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return "Must be YYYY-MM-DD format."
    return None


def validate_positive_number(value):
    """Must be a positive number."""
    try:
        n = Decimal(value)
        if n <= 0:
            return "Must be positive."
    except Exception:
        return "Must be a number."
    return None


def validate_non_negative_number(value):
    """Must be zero or positive."""
    try:
        n = Decimal(value)
        if n < 0:
            return "Must be zero or positive."
    except Exception:
        return "Must be a number."
    return None


def validate_positive_int(value):
    """Must be a positive integer."""
    try:
        n = int(value)
        if n <= 0:
            return "Must be a positive integer."
    except (ValueError, TypeError):
        return "Must be an integer."
    return None


# ─── Global flags ────────────────────────────────────────────────────────────

def parse_global_flags(args):
    """Extract global flags from args, return (flags_dict, remaining_args)."""
    flags = {
        'yes': False,
        'batch': False,
        'dry_run': False,
        'quiet': False,
        'date': None,
        'help': False,
    }
    remaining = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('--yes', '-y'):
            flags['yes'] = True
        elif arg == '--batch':
            flags['batch'] = True
        elif arg == '--dry-run':
            flags['dry_run'] = True
        elif arg in ('--quiet', '-q'):
            flags['quiet'] = True
        elif arg == '--date' and i + 1 < len(args):
            flags['date'] = args[i + 1]
            i += 1
        elif arg in ('--help', '-h'):
            flags['help'] = True
        else:
            remaining.append(arg)
        i += 1
    return flags, remaining
