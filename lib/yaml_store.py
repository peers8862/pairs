"""Generic YAML entity storage for pair."""

import yaml
from pathlib import Path

from lib.helpers import ensure_dir


def entity_dir(module_name):
    """Return the directory path for a module's YAML entities."""
    from lib.helpers import get_entity_dir
    return get_entity_dir() / module_name


def load_entity(module_name, slug):
    """Load a YAML entity by module and slug. Returns dict or None."""
    path = entity_dir(module_name) / f"{slug}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def save_entity(module_name, slug, data):
    """Save a YAML entity. Creates directory if needed."""
    directory = entity_dir(module_name)
    ensure_dir(directory)
    path = directory / f"{slug}.yaml"
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def list_entities(module_name):
    """Return list of slugs (filenames without .yaml) in a module directory."""
    directory = entity_dir(module_name)
    if not directory.exists():
        return []
    return sorted([p.stem for p in directory.glob("*.yaml")])


def delete_entity(module_name, slug):
    """Delete a YAML entity file. Returns True if deleted, False if not found."""
    path = entity_dir(module_name) / f"{slug}.yaml"
    if path.exists():
        path.unlink()
        return True
    return False


def entity_exists(module_name, slug):
    """Check if an entity exists."""
    path = entity_dir(module_name) / f"{slug}.yaml"
    return path.exists()
