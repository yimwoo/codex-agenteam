"""Artifact path resolution: standalone vs HOTL modes."""

import json

from .config import resolve_team_config
from .hotl import hotl_active_in_project, hotl_available

# Default AgenTeam artifact paths (standalone mode)
ATEAM_ARTIFACT_PATHS = {
    "researcher": "docs/research/",
    "pm": "docs/strategies/",
    "architect": "docs/designs/",
    "dev_plans": "docs/plans/",
    "dev_code": ["src/", "lib/"],
    "qa": ["tests/"],
}

# HOTL artifact paths (when HOTL is active)
HOTL_ARTIFACT_PATHS = {
    "researcher": "docs/research/",
    "pm": "docs/strategies/",
    "architect": "docs/plans/",  # HOTL uses docs/plans/ for design docs
    "dev_plans": "./",  # HOTL puts hotl-workflow-*.md at project root
    "dev_code": ["src/", "lib/"],
    "qa": ["tests/"],
}


def resolve_artifact_paths_for_config(config: dict) -> dict:
    """Resolve artifact paths, auto-detecting HOTL vs standalone."""
    pipeline_mode, _ = resolve_team_config(config)
    hotl_info = hotl_available()
    hotl_in_project = hotl_active_in_project()
    use_hotl = (pipeline_mode == "hotl") or (
        pipeline_mode is None and hotl_info["available"] and hotl_in_project
    )
    return HOTL_ARTIFACT_PATHS if use_hotl else ATEAM_ARTIFACT_PATHS


def cmd_artifact_paths(args, config: dict) -> None:
    """Return artifact output paths, auto-detecting HOTL vs standalone."""
    paths = resolve_artifact_paths_for_config(config)
    hotl_info = hotl_available()
    hotl_in_project = hotl_active_in_project()

    result = {
        "mode": "hotl" if paths is HOTL_ARTIFACT_PATHS else "standalone",
        "hotl_available": hotl_info["available"],
        "hotl_active_in_project": hotl_in_project,
        "paths": paths,
    }
    print(json.dumps(result))
