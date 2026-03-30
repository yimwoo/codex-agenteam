"""Role resolution: load defaults, merge with project overrides."""

import yaml

from .constants import ROLES_DIR


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dicts. Override wins on leaf values; lists replace."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_default_roles() -> dict[str, dict]:
    """Load built-in role templates from roles/*.yaml."""
    roles = {}
    if ROLES_DIR.exists():
        for path in sorted(ROLES_DIR.glob("*.yaml")):
            with open(path) as f:
                role = yaml.safe_load(f)
            if role and "name" in role:
                roles[role["name"]] = role
    return roles


def resolve_roles(config: dict) -> dict[str, dict]:
    """Resolve all roles: plugin defaults merged with project overrides."""
    defaults = load_default_roles()
    overrides = config.get("roles", {}) or {}

    resolved = {}
    # Merge defaults with overrides
    for name, default_role in defaults.items():
        override = overrides.get(name, {})
        if override:
            resolved[name] = deep_merge(default_role, override)
        else:
            resolved[name] = dict(default_role)

    # Add custom roles (not in defaults)
    for name, role_config in overrides.items():
        if name not in defaults:
            if isinstance(role_config, dict):
                role_config.setdefault("name", name)
                resolved[name] = role_config

    return resolved
