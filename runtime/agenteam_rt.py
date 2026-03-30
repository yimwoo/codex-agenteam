#!/usr/bin/env python3
"""AgenTeam (codex-agenteam) runtime engine.

Pure config-resolver and policy-enforcer. Outputs JSON.
Skills own subagent execution.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "PyYAML not installed. Run: pip install pyyaml"}), file=sys.stderr)
    sys.exit(1)

try:
    import toml
except ImportError:
    print(json.dumps({"error": "toml not installed. Run: pip install toml"}), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PIPELINES = {"standalone", "hotl", "dispatch-only", "auto"}
VALID_WRITE_MODES = {"serial", "scoped", "worktree"}
PLUGIN_DIR = Path(__file__).resolve().parent.parent
ROLES_DIR = PLUGIN_DIR / "roles"


# ---------------------------------------------------------------------------
# Config loading & validation
# ---------------------------------------------------------------------------

def find_config(path_or_dir: str | None = None) -> Path:
    """Locate config file. Accepts a direct file path or a directory to search."""
    if path_or_dir:
        p = Path(path_or_dir)
        # If it's a file path, use it directly
        if p.is_file():
            return p
        # If it's a directory, search within it
        if p.is_dir():
            preferred = p / ".agenteam" / "config.yaml"
            if preferred.exists():
                return preferred
            legacy = p / "agenteam.yaml"
            if legacy.exists():
                return legacy
            raise FileNotFoundError(
                f"Config not found in {p}. Expected .agenteam/config.yaml or agenteam.yaml"
            )
        raise FileNotFoundError(f"Config path does not exist: {p}")

    # Default: search current directory
    d = Path.cwd()
    preferred = d / ".agenteam" / "config.yaml"
    if preferred.exists():
        return preferred
    legacy = d / "agenteam.yaml"
    if legacy.exists():
        return legacy
    raise FileNotFoundError(
        f"Config not found in {d}. Expected .agenteam/config.yaml or agenteam.yaml"
    )


def load_config(path: Path) -> dict:
    """Load and validate agenteam.yaml."""
    with open(path) as f:
        config = yaml.safe_load(f)
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    """Validate required fields and enum values."""
    errors = []

    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping")

    if "version" not in config:
        errors.append("Missing required field: version")

    team = config.get("team", {})
    if not isinstance(team, dict):
        errors.append("'team' must be a mapping")
    else:
        pipeline = team.get("pipeline")
        if pipeline and pipeline not in VALID_PIPELINES:
            errors.append(f"Invalid pipeline: '{pipeline}'. Must be one of: {', '.join(sorted(VALID_PIPELINES))}")

        pw = team.get("parallel_writes", {})
        if isinstance(pw, dict):
            mode = pw.get("mode")
            if mode and mode not in VALID_WRITE_MODES:
                errors.append(f"Invalid parallel_writes.mode: '{mode}'. Must be one of: {', '.join(sorted(VALID_WRITE_MODES))}")

    if errors:
        raise ValueError("; ".join(errors))


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TOML agent generation
# ---------------------------------------------------------------------------

def generate_agent_toml(role: dict) -> str:
    """Generate Codex agent TOML from a resolved role."""
    agent = {}
    agent["name"] = role["name"]
    agent["description"] = role.get("description", "").strip()

    # Optional config fields
    if "model" in role:
        agent["model"] = role["model"]
    if "reasoning_effort" in role:
        agent["model_reasoning_effort"] = role["reasoning_effort"]
    if "sandbox_mode" in role:
        agent["sandbox_mode"] = role["sandbox_mode"]

    # Build developer_instructions from system_instructions + metadata
    instructions_parts = []
    if "system_instructions" in role:
        instructions_parts.append(role["system_instructions"].rstrip())

    # Append role metadata
    metadata_lines = []
    if "participates_in" in role:
        metadata_lines.append(f"participates_in: {', '.join(role['participates_in'])}")
    if "can_write" in role:
        metadata_lines.append(f"can_write: {str(role['can_write']).lower()}")
    if "parallel_safe" in role:
        metadata_lines.append(f"parallel_safe: {str(role['parallel_safe']).lower()}")

    if metadata_lines:
        instructions_parts.append("\n## Role Metadata\n" + "\n".join(metadata_lines))

    agent["developer_instructions"] = "\n".join(instructions_parts)

    return toml.dumps(agent)


def cmd_generate(args, config: dict) -> None:
    """Generate .codex/agents/*.toml for all resolved roles."""
    roles = resolve_roles(config)
    agents_dir = Path.cwd() / ".codex" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for name, role in sorted(roles.items()):
        toml_content = generate_agent_toml(role)
        out_path = agents_dir / f"{name}.toml"
        with open(out_path, "w") as f:
            f.write(toml_content)
        generated.append(str(out_path))

    result = {"generated": generated}

    count = len(generated)
    warnings = []
    if count > 6:
        warnings.append(
            f"You have {count} agents. Codex defaults to 6 concurrent threads. "
            "Set agents.max_threads in your Codex config.toml to run more in parallel."
        )
    if count > 12:
        warnings.append(
            f"You have {count} agents. Teams above 12 can increase coordination "
            "overhead. Consider consolidating roles with overlapping responsibilities."
        )
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result))


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def generate_run_id() -> str:
    """Generate a timestamp-based run ID."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def get_pipeline_stages(config: dict) -> list[dict]:
    """Extract pipeline stages from config."""
    pipeline = config.get("pipeline", {})
    return pipeline.get("stages", [])


def cmd_init(args, config: dict) -> None:
    """Initialize a run: validate config, create state."""
    task = args.task or "unnamed task"
    run_id = generate_run_id()

    # Create state directory
    state_dir = Path.cwd() / ".agenteam" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Build initial state
    pipeline_mode = config.get("team", {}).get("pipeline", "standalone")
    stages = get_pipeline_stages(config)

    state = {
        "run_id": run_id,
        "task": task,
        "pipeline_mode": pipeline_mode,
        "current_stage": stages[0]["name"] if stages else None,
        "stages": {},
        "write_locks": {
            "active": None,
            "queue": [],
        },
    }

    for stage in stages:
        state["stages"][stage["name"]] = {
            "status": "pending",
            "roles": stage.get("roles", []),
            "gate": stage.get("gate", "auto"),
        }

    # Write state file
    state_path = state_dir / f"{run_id}.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    print(json.dumps(state))


def find_latest_state() -> dict | None:
    """Find the most recent state file."""
    latest_state_path = find_latest_state_path()
    if latest_state_path is None:
        return None
    with open(latest_state_path) as f:
        return json.load(f)


def find_latest_state_path() -> Path | None:
    """Find the most recent state file path."""
    state_dir = Path.cwd() / ".agenteam" / "state"
    if not state_dir.exists():
        return None
    files = sorted(state_dir.glob("*.json"), reverse=True)
    if not files:
        return None
    return files[0]


def cmd_status(args, config: dict) -> None:
    """Show current run status."""
    if args.run_id:
        state_path = Path.cwd() / ".agenteam" / "state" / f"{args.run_id}.json"
        if not state_path.exists():
            print(json.dumps({"error": f"Run {args.run_id} not found"}), file=sys.stderr)
            sys.exit(1)
        with open(state_path) as f:
            state = json.load(f)
    else:
        state = find_latest_state()
        if not state:
            print(json.dumps({"error": "No runs found"}), file=sys.stderr)
            sys.exit(1)

    print(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def cmd_dispatch(args, config: dict) -> None:
    """Generate dispatch plan for a stage."""
    stage_name = args.stage
    task = args.task or ""

    stages = get_pipeline_stages(config)
    stage_config = None
    for s in stages:
        if s["name"] == stage_name:
            stage_config = s
            break

    if not stage_config:
        print(json.dumps({"error": f"Stage '{stage_name}' not found in pipeline"}), file=sys.stderr)
        sys.exit(1)

    roles = resolve_roles(config)
    role_names = stage_config.get("roles", [])
    write_mode = config.get("team", {}).get("parallel_writes", {}).get("mode", "serial")

    # Load current state for write locks
    state = None
    if args.run_id:
        state_path = Path.cwd() / ".agenteam" / "state" / f"{args.run_id}.json"
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)

    active_lock = None
    if state:
        active_lock = state.get("write_locks", {}).get("active")

    dispatch_list = []
    blocked = []
    serial_lock_granted = active_lock  # Track who holds the lock

    for rname in role_names:
        role = roles.get(rname, {"name": rname})
        can_write = role.get("can_write", False)
        mode = "write" if can_write else "read"

        entry = {
            "role": rname,
            "agent": f".codex/agents/{rname}.toml",
            "mode": mode,
            "write_lock": False,
            "task": task,
        }

        if can_write and write_mode == "serial":
            if serial_lock_granted and serial_lock_granted != rname:
                # Another writer already holds the lock
                blocked.append(entry)
                continue
            # Grant lock to this writer (first writer wins)
            entry["write_lock"] = True
            serial_lock_granted = rname

        dispatch_list.append(entry)

    plan = {
        "stage": stage_name,
        "dispatch": dispatch_list,
        "policy": write_mode,
        "gate": stage_config.get("gate", "auto"),
        "blocked": blocked,
    }

    print(json.dumps(plan))


# ---------------------------------------------------------------------------
# Policy check
# ---------------------------------------------------------------------------

def cmd_policy_check(args, config: dict) -> None:
    """Validate write scopes don't overlap across writing roles."""
    roles = resolve_roles(config)
    writers = {n: r for n, r in roles.items() if r.get("can_write")}

    overlaps = []
    writer_names = sorted(writers.keys())
    for i, n1 in enumerate(writer_names):
        for n2 in writer_names[i + 1:]:
            s1 = set(writers[n1].get("write_scope", []))
            s2 = set(writers[n2].get("write_scope", []))
            common = s1 & s2
            if common:
                overlaps.append({"roles": [n1, n2], "overlapping_scopes": sorted(common)})

    result = {
        "policy": config.get("team", {}).get("parallel_writes", {}).get("mode", "serial"),
        "writers": {n: r.get("write_scope", []) for n, r in writers.items()},
        "overlaps": overlaps,
        "safe_for_parallel": len(overlaps) == 0,
    }
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# Roles subcommands
# ---------------------------------------------------------------------------

def cmd_roles_list(args, config: dict) -> None:
    """List all resolved role names."""
    roles = resolve_roles(config)
    print(json.dumps(sorted(roles.keys())))


def cmd_roles_show(args, config: dict) -> None:
    """Show merged config for a specific role."""
    roles = resolve_roles(config)
    name = args.name
    if name not in roles:
        print(json.dumps({"error": f"Role '{name}' not found"}), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(roles[name], default=str))


# ---------------------------------------------------------------------------
# HOTL detection
# ---------------------------------------------------------------------------

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
        config_path = find_config(args.config if getattr(args, "config", None) else None)
    except FileNotFoundError:
        config_path = None
    else:
        config_exists = True
        config = load_config(config_path)
        pipeline_mode = config.get("team", {}).get("pipeline", "standalone")

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


# ---------------------------------------------------------------------------
# Artifact path resolution
# ---------------------------------------------------------------------------

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
    "architect": "docs/plans/",             # HOTL uses docs/plans/ for design docs
    "dev_plans": "./",              # HOTL puts hotl-workflow-*.md at project root
    "dev_code": ["src/", "lib/"],
    "qa": ["tests/"],
}


def resolve_artifact_paths_for_config(config: dict) -> dict:
    """Resolve artifact paths, auto-detecting HOTL vs standalone."""
    pipeline_mode = config.get("team", {}).get("pipeline", "standalone")
    hotl_info = hotl_available()
    hotl_in_project = hotl_active_in_project()
    use_hotl = (pipeline_mode == "hotl") or (
        pipeline_mode == "auto" and hotl_info["available"] and hotl_in_project
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


# ---------------------------------------------------------------------------
# Standup
# ---------------------------------------------------------------------------

def compute_health(state: dict | None) -> tuple[str, list[str]]:
    """Compute health indicator and warnings from run state.

    Returns (health, warnings) where health is one of:
    "on-track", "at-risk", "off-track", "no-active-run".
    """
    if state is None:
        return "no-active-run", []

    warnings = []
    stages = state.get("stages", {})

    # off-track: any stage blocked or failed
    off_track_stages = [
        name for name, info in stages.items()
        if info.get("status") in ("blocked", "failed")
    ]
    if off_track_stages:
        for s in off_track_stages:
            warnings.append(f"Stage '{s}' is {stages[s]['status']}")
        return "off-track", warnings

    # at-risk: any stage in-progress with gate rejection or long-running
    at_risk_stages = []
    for name, info in stages.items():
        if info.get("status") == "in-progress":
            if info.get("gate") == "rejected":
                at_risk_stages.append(name)
                warnings.append(f"Stage '{name}' has an unresolved gate rejection")
            elif info.get("started_at"):
                # If started_at is present, check duration (> 30 min = at-risk)
                try:
                    elapsed = time.time() - info["started_at"]
                    if elapsed > 1800:
                        at_risk_stages.append(name)
                        warnings.append(
                            f"Stage '{name}' has been in-progress for "
                            f"{int(elapsed // 60)} minutes"
                        )
                except (TypeError, ValueError):
                    pass

    if at_risk_stages:
        return "at-risk", warnings

    return "on-track", warnings


def cmd_standup(args, config: dict) -> None:
    """Assemble standup summary: roles, run state, artifacts, health."""
    roles = resolve_roles(config)
    role_names = sorted(roles.keys())

    # Load run state
    state = find_latest_state()

    # Health
    health, warnings = compute_health(state)

    # Run summary
    run_summary = None
    stages_summary = {}
    if state:
        run_summary = {
            "run_id": state.get("run_id"),
            "task": state.get("task"),
            "current_stage": state.get("current_stage"),
        }
        stages_summary = state.get("stages", {})

    # Artifact paths
    artifact_paths = resolve_artifact_paths_for_config(config)

    # Dispatch mode
    dispatch_mode = getattr(args, "dispatch", False) or False

    # Output path
    suffix = "-deepdive.md" if dispatch_mode else "-standup.md"
    output_path = "docs/meetings/" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + suffix

    # >6 roles warning (same pattern as cmd_generate)
    count = len(role_names)
    if count > 6:
        warnings.append(
            f"You have {count} agents. Codex defaults to 6 concurrent threads. "
            "Set agents.max_threads in your Codex config.toml to run more in parallel."
        )
    if count > 12:
        warnings.append(
            f"You have {count} agents. Teams above 12 can increase coordination "
            "overhead. Consider consolidating roles with overlapping responsibilities."
        )

    # Build dispatch list when --dispatch is set (for deepdive skill)
    dispatch_list = None
    if dispatch_mode:
        deepdive_roles = ["researcher", "architect", "pm"]
        dispatch_list = []
        for rname in deepdive_roles:
            if rname in roles:
                dispatch_list.append({
                    "role": rname,
                    "agent": f".codex/agents/{rname}.toml",
                })

    # Task context (--task flag)
    result = {
        "health": health,
        "run": run_summary,
        "roles": role_names,
        "stages": stages_summary,
        "artifact_paths": artifact_paths,
        "dispatch_mode": dispatch_mode,
        "output_path": output_path,
        "warnings": warnings,
    }

    if dispatch_list is not None:
        result["dispatch"] = dispatch_list

    if args.task:
        result["task_context"] = args.task

    print(json.dumps(result))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenteam-rt",
        description="AgenTeam (codex-agenteam) runtime engine",
    )
    parser.add_argument("--config", help="Path to agenteam.yaml")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a run")
    p_init.add_argument("--task", required=False, default="unnamed task")

    # generate
    sub.add_parser("generate", help="Generate .codex/agents/*.toml")

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Generate dispatch plan for a stage")
    p_dispatch.add_argument("stage", help="Stage name")
    p_dispatch.add_argument("--task", default="")
    p_dispatch.add_argument("--run-id", dest="run_id", default=None)

    # status
    p_status = sub.add_parser("status", help="Show run status")
    p_status.add_argument("run_id", nargs="?", default=None)

    # policy
    p_policy = sub.add_parser("policy", help="Policy commands")
    p_policy_sub = p_policy.add_subparsers(dest="policy_cmd")
    p_policy_sub.add_parser("check", help="Check write scope overlaps")

    # roles
    p_roles = sub.add_parser("roles", help="Role commands")
    p_roles_sub = p_roles.add_subparsers(dest="roles_cmd")
    p_roles_sub.add_parser("list", help="List all resolved roles")
    p_show = p_roles_sub.add_parser("show", help="Show a specific role")
    p_show.add_argument("name", help="Role name")

    # hotl
    p_hotl = sub.add_parser("hotl", help="HOTL integration")
    p_hotl_sub = p_hotl.add_subparsers(dest="hotl_cmd")
    p_hotl_sub.add_parser("check", help="Check HOTL availability")

    # health
    sub.add_parser("health", help="Show minimal runtime/project readiness")

    # artifact-paths
    sub.add_parser("artifact-paths", help="Show artifact output paths (auto-detects HOTL)")

    # standup
    p_standup = sub.add_parser("standup", help="Assemble standup summary")
    p_standup.add_argument("--task", required=False, default=None,
                           help="Optional task context for the standup")
    p_standup.add_argument("--dispatch", action="store_true", default=False,
                           help="Include dispatch_mode=true for deepdive skill")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # HOTL check doesn't need config
    if args.command == "hotl":
        if args.hotl_cmd == "check":
            cmd_hotl_check(args)
        else:
            print(json.dumps({"error": "Unknown hotl subcommand"}), file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "health":
        try:
            cmd_health(args)
        except (ValueError, json.JSONDecodeError, OSError, yaml.YAMLError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        return

    # All other commands need config
    try:
        config_path = find_config(args.config if hasattr(args, "config") and args.config else None)
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if args.command == "standup":
        cmd_standup(args, config)
    elif args.command == "artifact-paths":
        cmd_artifact_paths(args, config)
    elif args.command == "init":
        cmd_init(args, config)
    elif args.command == "generate":
        cmd_generate(args, config)
    elif args.command == "dispatch":
        cmd_dispatch(args, config)
    elif args.command == "status":
        cmd_status(args, config)
    elif args.command == "policy":
        if args.policy_cmd == "check":
            cmd_policy_check(args, config)
        else:
            print(json.dumps({"error": "Unknown policy subcommand"}), file=sys.stderr)
            sys.exit(1)
    elif args.command == "roles":
        if args.roles_cmd == "list":
            cmd_roles_list(args, config)
        elif args.roles_cmd == "show":
            cmd_roles_show(args, config)
        else:
            print(json.dumps({"error": "Unknown roles subcommand"}), file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
