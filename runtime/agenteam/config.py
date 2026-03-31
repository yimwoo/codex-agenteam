"""Config loading, validation, and team config resolution."""

import json
import sys
from pathlib import Path

import yaml

from .constants import (
    ISOLATION_MAP,
    PERSONAL_CONFIG_DIR,
    TEAM_CONFIG_DIR,
)


def resolve_team_config(config: dict) -> tuple[str | None, str]:
    """Resolve (pipeline_mode, isolation_mode) from either new or legacy schema.

    New schema (flat keys):
      isolation: branch | worktree | none
      pipeline: hotl  (top-level string, optional -- only "hotl" is meaningful)

    Legacy schema (nested team block):
      team.pipeline: standalone | hotl | dispatch-only | auto
      team.parallel_writes.mode: serial | scoped | worktree

    Returns:
      (pipeline_mode, isolation_mode)
      pipeline_mode is None for auto-detect, or "hotl" for explicit HOTL.
      isolation_mode is "branch" (default), "worktree", or "none".
    """
    # New schema (flat keys)
    isolation = config.get("isolation")
    # "pipeline" can be either a string (mode) or a dict (stages).
    # Only treat it as a mode if it's a string.
    pipeline_val = config.get("pipeline")
    pipeline = pipeline_val if isinstance(pipeline_val, str) else None

    # Legacy schema (nested team block)
    team = config.get("team", {})
    if isinstance(team, dict):
        if not pipeline:
            legacy_pipeline = team.get("pipeline")
            if legacy_pipeline == "hotl":
                pipeline = "hotl"
            # standalone, auto, dispatch-only all resolve to None (auto-detect)

        if not isolation:
            pw = team.get("parallel_writes", {})
            if isinstance(pw, dict):
                legacy_mode = pw.get("mode")
                if legacy_mode:
                    isolation = ISOLATION_MAP.get(legacy_mode, legacy_mode)

    # Defaults
    isolation = isolation or "branch"
    # pipeline: None means auto-detect at runtime
    return pipeline, isolation


def resolve_project_root(config_path: Path) -> Path:
    """Resolve project root from a config file path.

    .agenteam/config.yaml      -> parent.parent (project root)
    .agenteam.team/config.yaml -> parent.parent (project root)
    agenteam.yaml              -> parent (project root)
    """
    parent = config_path.parent
    if parent.name in (PERSONAL_CONFIG_DIR, TEAM_CONFIG_DIR):
        return parent.parent
    return parent


def find_team_config(project_root: Path) -> Path | None:
    """Find team config in project root. Returns Path or None."""
    team_path = project_root / TEAM_CONFIG_DIR / "config.yaml"
    return team_path if team_path.exists() else None


def find_personal_config(project_root: Path) -> Path | None:
    """Find personal config in project root. Returns Path or None."""
    personal_path = project_root / PERSONAL_CONFIG_DIR / "config.yaml"
    return personal_path if personal_path.exists() else None


def find_config(path_or_dir: str | None = None) -> Path:
    """Locate config file. Accepts a direct file path or a directory to search."""
    if path_or_dir:
        p = Path(path_or_dir)
        # If it's a file path, use it directly
        if p.is_file():
            return p
        # If it's a directory, search within it
        if p.is_dir():
            preferred = p / PERSONAL_CONFIG_DIR / "config.yaml"
            if preferred.exists():
                return preferred
            team = p / TEAM_CONFIG_DIR / "config.yaml"
            if team.exists():
                return team
            legacy = p / "agenteam.yaml"
            if legacy.exists():
                return legacy
            raise FileNotFoundError(
                f"Config not found in {p}. "
                f"Expected .agenteam/config.yaml, "
                f".agenteam.team/config.yaml, or agenteam.yaml"
            )
        raise FileNotFoundError(f"Config path does not exist: {p}")

    # Default: search current directory
    d = Path.cwd()
    preferred = d / PERSONAL_CONFIG_DIR / "config.yaml"
    if preferred.exists():
        return preferred
    team = d / TEAM_CONFIG_DIR / "config.yaml"
    if team.exists():
        return team
    legacy = d / "agenteam.yaml"
    if legacy.exists():
        return legacy
    raise FileNotFoundError(
        f"Config not found in {d}. "
        f"Expected .agenteam/config.yaml, "
        f".agenteam.team/config.yaml, or agenteam.yaml"
    )


def merge_with_allowlist(
    team: dict,
    personal: dict,
    default_roles: dict,
) -> dict:
    """Merge team config with personal overrides using allowlist.

    Returns the merged config. Personal overrides are limited to
    allowlisted role fields. Non-overridable fields are always from team.
    """
    import copy

    from .constants import NON_OVERRIDABLE_ROLE_FIELDS, PERSONAL_OVERRIDE_ALLOWLIST

    merged = copy.deepcopy(team)

    # Compute known roles: defaults + team
    known_roles = set(default_roles.keys()) | set(
        team.get("roles", {}).keys() if isinstance(team.get("roles"), dict) else []
    )

    # Read team's escape hatch
    extra_allowed = set(team.get("allow_personal_override", []))

    # Effective role-level allowlist
    role_allowlist = PERSONAL_OVERRIDE_ALLOWLIST | (
        extra_allowed & {"model", "reasoning_effort", "system_instructions"}
    )

    # Merge personal role overrides
    personal_roles = personal.get("roles", {})
    if isinstance(personal_roles, dict):
        if "roles" not in merged:
            merged["roles"] = {}
        for role_name, role_overrides in personal_roles.items():
            if not isinstance(role_overrides, dict):
                continue
            if role_name not in known_roles:
                print(
                    json.dumps(
                        {
                            "warning": (
                                f"Personal config defines unknown role "
                                f"'{role_name}'. Custom roles must be "
                                f"added to team config."
                            )
                        }
                    ),
                    file=sys.stderr,
                )
                continue

            if role_name not in merged["roles"]:
                merged["roles"][role_name] = {}

            for field, value in role_overrides.items():
                if field in NON_OVERRIDABLE_ROLE_FIELDS:
                    print(
                        json.dumps(
                            {
                                "warning": (
                                    f"Personal override blocked: "
                                    f"roles.{role_name}.{field} "
                                    f"is not personally overridable."
                                )
                            }
                        ),
                        file=sys.stderr,
                    )
                    continue
                if field not in role_allowlist:
                    print(
                        json.dumps(
                            {
                                "warning": (
                                    f"Personal override blocked: "
                                    f"roles.{role_name}.{field} "
                                    f"is not in the personal allowlist."
                                )
                            }
                        ),
                        file=sys.stderr,
                    )
                    continue

                if field == "system_instructions":
                    # Append, don't replace
                    existing = merged["roles"][role_name].get("system_instructions", "")
                    merged["roles"][role_name]["system_instructions"] = (
                        f"{existing}\n{value}".lstrip("\n")
                    )
                else:
                    merged["roles"][role_name][field] = value

    # Merge non-role top-level personal overrides (only if allowed)
    for key, value in personal.items():
        if key in ("version", "roles"):
            continue  # handled above or skip
        if key in extra_allowed:
            merged[key] = value

    return merged


def load_config(path: Path) -> dict:
    """Load, merge layers, and validate config file.

    If both team and personal configs exist under the same project root,
    they are merged using the allowlisted merge strategy.
    """
    from .roles import load_default_roles

    project_root = resolve_project_root(path)
    team_path = find_team_config(project_root)
    personal_path = find_personal_config(project_root)

    # Determine which layers are present
    team_config = None
    personal_config = None

    if team_path:
        with open(team_path) as f:
            team_config = yaml.safe_load(f)
    if personal_path:
        with open(personal_path) as f:
            personal_config = yaml.safe_load(f)

    if team_config and personal_config:
        default_roles = load_default_roles()
        config = merge_with_allowlist(team_config, personal_config, default_roles)
    elif team_config:
        config = team_config
    elif personal_config:
        config = personal_config
    else:
        # Fallback: load the path directly (legacy agenteam.yaml)
        with open(path) as f:
            config = yaml.safe_load(f)

    validate_config(config)
    return config


def load_config_raw(path: Path) -> dict:
    """Load config YAML without validation. Used by migrate command."""
    with open(path) as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")
    return config


def load_config_merged_raw(path: Path) -> dict:
    """Load and merge config layers without validation.

    Used by validate command so it can report all errors structurally
    while still operating on the effective merged config.
    """
    from .roles import load_default_roles

    project_root = resolve_project_root(path)
    team_path = find_team_config(project_root)
    personal_path = find_personal_config(project_root)

    team_config = None
    personal_config = None

    if team_path:
        with open(team_path) as f:
            raw = yaml.safe_load(f)
            team_config = raw if isinstance(raw, dict) else None
    if personal_path:
        with open(personal_path) as f:
            raw = yaml.safe_load(f)
            personal_config = raw if isinstance(raw, dict) else None

    if team_config and personal_config:
        return merge_with_allowlist(team_config, personal_config, load_default_roles())
    elif team_config:
        return team_config
    elif personal_config:
        return personal_config
    else:
        with open(path) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError("Config must be a YAML mapping")
        return config


def load_config_layers(path_or_dir: str | None = None) -> dict:
    """Return config layer provenance for diagnostics.

    Shows which config files exist, which keys were overridden
    or blocked, and the effective merged config.
    """
    config_path = find_config(path_or_dir)
    project_root = resolve_project_root(config_path)
    team_path = find_team_config(project_root)
    personal_path = find_personal_config(project_root)

    result: dict = {
        "team_config": str(team_path) if team_path else None,
        "personal_config": str(personal_path) if personal_path else None,
        "legacy_config": None,
        "effective_source": "merged" if (team_path and personal_path) else "single",
    }

    # Check for legacy
    legacy = project_root / "agenteam.yaml"
    if legacy.exists():
        result["legacy_config"] = str(legacy)

    return result


def validate_config(config: dict) -> None:
    """Validate required fields and enum values (new + legacy schema).

    Delegates to schema.validate_schema() internally.
    Raises ValueError on errors, emits warnings to stderr as JSON.
    Preserves existing external contract.
    """
    from .schema import validate_schema

    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")

    result = validate_schema(config)

    # Emit warnings to stderr as JSON (preserving current behavior)
    for d in result.warnings:
        print(json.dumps({"warning": d.message}), file=sys.stderr)

    # Raise on errors (with path-prefixed messages, no codes)
    if not result.valid:
        messages = [d.message for d in result.errors]
        raise ValueError("; ".join(messages))
