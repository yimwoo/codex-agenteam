"""HOTL detection, health checks, and agent existence queries."""

import json
from pathlib import Path

from .config import find_config, load_config, resolve_team_config
from .state import find_latest_state_path


def hotl_available() -> dict:
    """Check if HOTL plugin is installed and accessible."""
    paths = [
        Path.home() / ".codex" / "plugins" / "hotl",
        Path.home() / ".claude" / "plugins" / "cache" / "hotl-plugin",
    ]
    for p in paths:
        if p.exists():
            return {"available": True, "path": str(p)}
    return {"available": False, "path": None}


def hotl_active_in_project() -> bool:
    """Check if the current project is using HOTL (has hotl-workflow-*.md or .hotl/)."""
    cwd = Path.cwd()
    if (cwd / ".hotl").exists():
        return True
    if list(cwd.glob("hotl-workflow-*.md")):
        return True
    return False


def cmd_hotl_check(args, config: dict | None = None) -> None:
    """Check HOTL availability."""
    result = hotl_available()
    result["active_in_project"] = hotl_active_in_project()
    print(json.dumps(result))


def generated_agents_exist() -> bool:
    """Check whether generated Codex agent TOML files exist for the project."""
    agents_dir = Path.cwd() / ".codex" / "agents"
    return agents_dir.exists() and any(agents_dir.glob("*.toml"))


def cmd_health(args) -> None:
    """Report a minimal runtime/project readiness summary."""
    config_exists = False
    pipeline_mode = None

    try:
        found_path = find_config(args.config if getattr(args, "config", None) else None)
    except FileNotFoundError:
        pass
    else:
        config_exists = True
        config = load_config(found_path)
        pm, _ = resolve_team_config(config)
        pipeline_mode = pm or "standalone"

    hotl_info = hotl_available()

    latest_run_id = None
    latest_state_path = find_latest_state_path()
    if latest_state_path is not None:
        with open(latest_state_path) as f:
            state = json.load(f)
        latest_run_id = state.get("run_id")

    result = {
        "config_exists": config_exists,
        "pipeline_mode": pipeline_mode,
        "hotl_available": hotl_info["available"],
        "hotl_active_in_project": hotl_active_in_project(),
        "generated_agents_exist": generated_agents_exist(),
        "latest_run_id": latest_run_id,
    }
    print(json.dumps(result))
