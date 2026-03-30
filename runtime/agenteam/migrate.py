"""Config migration engine: format detection, transforms, and CLI command."""

import copy
import json
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from .constants import ISOLATION_MAP


class ConfigFormat(Enum):
    LEGACY = "legacy"
    CURRENT = "current"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class TransformResult:
    """Result of a single transform."""

    config: dict
    changes: list[str] = field(default_factory=list)
    applied: bool = False


def detect_format(config: dict) -> ConfigFormat:
    """Detect config format based on key presence."""
    team = config.get("team", {})
    has_legacy = False
    if isinstance(team, dict):
        has_legacy = "pipeline" in team or "parallel_writes" in team

    has_current = "isolation" in config
    pipeline_val = config.get("pipeline")
    if isinstance(pipeline_val, dict):
        has_current = True

    if has_legacy and has_current:
        return ConfigFormat.MIXED
    elif has_legacy:
        return ConfigFormat.LEGACY
    elif has_current:
        return ConfigFormat.CURRENT
    else:
        return ConfigFormat.UNKNOWN


def _transform_team_pipeline(config: dict) -> TransformResult:
    """Transform team.pipeline to top-level pipeline (or remove if default)."""
    config = copy.deepcopy(config)
    team = config.get("team")
    if not isinstance(team, dict) or "pipeline" not in team:
        return TransformResult(config=config)

    legacy_pipeline = team.pop("pipeline")
    changes = []

    if legacy_pipeline == "hotl":
        # Only set top-level pipeline if not already set
        if not isinstance(config.get("pipeline"), str):
            config["pipeline"] = "hotl"
            changes.append("Moved team.pipeline: hotl -> pipeline: hotl")
        else:
            changes.append("Removed team.pipeline: hotl (top-level pipeline already set)")
    elif legacy_pipeline == "standalone":
        changes.append("Removed team.pipeline: standalone (default behavior)")
    elif legacy_pipeline == "auto":
        changes.append("Removed team.pipeline: auto (auto-detect is now the default)")
    elif legacy_pipeline == "dispatch-only":
        changes.append("Removed team.pipeline: dispatch-only (no stages = dispatch-only)")
    else:
        changes.append(f"Removed unknown team.pipeline: {legacy_pipeline}")

    return TransformResult(config=config, changes=changes, applied=True)


def _transform_parallel_writes(config: dict) -> TransformResult:
    """Transform team.parallel_writes.mode to top-level isolation."""
    config = copy.deepcopy(config)
    team = config.get("team")
    if not isinstance(team, dict):
        return TransformResult(config=config)

    pw = team.get("parallel_writes")
    if not isinstance(pw, dict) or "mode" not in pw:
        return TransformResult(config=config)

    mode = pw.pop("mode")
    # Clean up empty parallel_writes
    if not pw:
        team.pop("parallel_writes", None)

    mapped = ISOLATION_MAP.get(mode, mode)
    changes = []

    if "isolation" not in config:
        config["isolation"] = mapped
        changes.append(f"Moved team.parallel_writes.mode: {mode} -> isolation: {mapped}")
    else:
        changes.append(
            f"Removed team.parallel_writes.mode: {mode} "
            f"(top-level isolation already set to '{config['isolation']}')"
        )

    return TransformResult(config=config, changes=changes, applied=True)


def _transform_remove_empty_team(config: dict) -> TransformResult:
    """Remove team block if empty after other transforms."""
    config = copy.deepcopy(config)
    team = config.get("team")
    if not isinstance(team, dict):
        return TransformResult(config=config)

    # Remove team.name if present (no longer used)
    changes = []
    if "name" in team:
        team.pop("name")
        changes.append("Removed team.name (no longer used)")

    # Remove team block if empty
    if not team:
        config.pop("team")
        changes.append("Removed empty team block")
        return TransformResult(config=config, changes=changes, applied=True)

    if changes:
        return TransformResult(config=config, changes=changes, applied=True)
    return TransformResult(config=config)


def _transform_normalize_final_verify(config: dict) -> TransformResult:
    """Normalize final_verify string to list."""
    config = copy.deepcopy(config)
    fv = config.get("final_verify")
    if isinstance(fv, str):
        config["final_verify"] = [fv]
        return TransformResult(
            config=config,
            changes=[f'Normalized final_verify: "{fv}" -> ["{fv}"]'],
            applied=True,
        )
    return TransformResult(config=config)


def migrate_config(config: dict) -> tuple[dict, list[str]]:
    """Apply all transforms in order. Returns (new_config, list_of_changes).

    Also bumps version to "2".
    """
    transforms = [
        _transform_team_pipeline,
        _transform_parallel_writes,
        _transform_remove_empty_team,
        _transform_normalize_final_verify,
    ]
    all_changes: list[str] = []
    current = config
    for t in transforms:
        result = t(current)
        if result.applied:
            current = result.config
            all_changes.extend(result.changes)

    # Bump version to "2"
    old_version = str(current.get("version", "1"))
    if old_version != "2":
        current = copy.deepcopy(current)
        current["version"] = "2"
        all_changes.append(f'Bumped version: "{old_version}" -> "2"')

    return current, all_changes


def _make_backup_path(source: Path) -> Path:
    """Create a timestamped backup path. Uses counter fallback if collision."""
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = source.parent / f"{source.name}.bak-{ts}"
    if not backup.exists():
        return backup
    # Counter fallback
    for i in range(1, 100):
        backup = source.parent / f"{source.name}.bak-{ts}-{i}"
        if not backup.exists():
            return backup
    raise RuntimeError(f"Cannot create backup for {source}")


def cmd_migrate(args) -> None:
    """CLI handler for: agenteam-rt migrate."""
    from .config import find_config, load_config_raw
    from .schema import validate_schema

    # Find and load config
    try:
        config_path = find_config(args.config if hasattr(args, "config") and args.config else None)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config_raw(config_path)
    except (ValueError, yaml.YAMLError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    # Check if already canonical
    fmt = detect_format(config)
    version = str(config.get("version", "1"))
    if fmt in (ConfigFormat.CURRENT, ConfigFormat.UNKNOWN) and version == "2":
        print(json.dumps({"changes": [], "message": "Config is already in canonical format."}))
        return

    # Apply transforms
    migrated, changes = migrate_config(config)

    # Validate migrated output
    validation = validate_schema(migrated)
    if not validation.valid:
        error_msgs = [d.message for d in validation.errors]
        print(
            json.dumps(
                {
                    "error": "Migrated config failed validation",
                    "validation_errors": error_msgs,
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine target path
    source_is_legacy_path = config_path.name == "agenteam.yaml"
    if source_is_legacy_path:
        target_dir = config_path.parent / ".agenteam"
        target_path = target_dir / "config.yaml"
        # Check conflict
        if target_path.exists():
            print(
                json.dumps(
                    {
                        "error": f"Both {config_path} and {target_path} exist. "
                        "Resolve manually by removing one before migrating."
                    }
                ),
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        target_path = config_path

    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        output = {
            "dry_run": True,
            "source": str(config_path),
            "target": str(target_path),
            "format_detected": fmt.value,
            "changes": changes,
            "warnings": ["YAML comments from the original file are not preserved."],
            "new_config_preview": yaml.dump(migrated, default_flow_style=False),
        }
        print(json.dumps(output))
        return

    # Create backup
    backup_path = _make_backup_path(config_path)
    os.rename(str(config_path), str(backup_path))

    # Write migrated config
    if source_is_legacy_path:
        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

    with open(target_path, "w") as f:
        yaml.dump(migrated, f, default_flow_style=False)

    if source_is_legacy_path:
        changes.append(f"Relocated config: {config_path.name} -> {target_path}")

    output = {
        "dry_run": False,
        "source": str(config_path),
        "target": str(target_path),
        "backup": str(backup_path),
        "format_detected": fmt.value,
        "changes": changes,
        "message": (
            f"Migrated config to {target_path}. "
            f"Previous file backed up to {backup_path}. "
            "Once you're happy, you can delete the backup."
        ),
    }
    print(json.dumps(output))
