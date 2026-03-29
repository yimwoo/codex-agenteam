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

def find_config(directory: str | None = None) -> Path:
    """Locate agenteam.yaml in the given or current directory."""
    d = Path(directory) if directory else Path.cwd()
    path = d / "agenteam.yaml"
    if not path.exists():
        raise FileNotFoundError(f"agenteam.yaml not found in {d}")
    return path


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

    print(json.dumps({"generated": generated}))


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
    state_dir = Path.cwd() / ".agenteam" / "state"
    if not state_dir.exists():
        return None
    files = sorted(state_dir.glob("*.json"), reverse=True)
    if not files:
        return None
    with open(files[0]) as f:
        return json.load(f)


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
            if active_lock and active_lock != rname:
                blocked.append(entry)
                continue
            entry["write_lock"] = True

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


# ---------------------------------------------------------------------------
# Artifact path resolution
# ---------------------------------------------------------------------------

# Default AgenTeam artifact paths (standalone mode)
ATEAM_ARTIFACT_PATHS = {
    "researcher": "docs/research/",
    "pm": "docs/strategies/",
    "architect": "docs/designs/",
    "implementer_plans": "docs/plans/",
    "implementer_code": ["src/", "lib/"],
    "test_writer": ["tests/"],
}

# HOTL artifact paths (when HOTL is active)
HOTL_ARTIFACT_PATHS = {
    "researcher": "docs/research/",
    "pm": "docs/strategies/",
    "architect": "docs/plans/",             # HOTL uses docs/plans/ for design docs
    "implementer_plans": "./",              # HOTL puts hotl-workflow-*.md at project root
    "implementer_code": ["src/", "lib/"],
    "test_writer": ["tests/"],
}


def cmd_artifact_paths(args, config: dict) -> None:
    """Return artifact output paths, auto-detecting HOTL vs standalone."""
    hotl_info = hotl_available()
    hotl_in_project = hotl_active_in_project()
    pipeline_mode = config.get("team", {}).get("pipeline", "standalone")

    # Auto-detect: use HOTL paths if HOTL is active in this project
    # or if pipeline is explicitly set to hotl
    use_hotl = (pipeline_mode == "hotl") or (
        pipeline_mode == "auto" and hotl_info["available"] and hotl_in_project
    )

    paths = HOTL_ARTIFACT_PATHS if use_hotl else ATEAM_ARTIFACT_PATHS

    result = {
        "mode": "hotl" if use_hotl else "standalone",
        "hotl_available": hotl_info["available"],
        "hotl_active_in_project": hotl_in_project,
        "paths": paths,
    }
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

    # artifact-paths
    sub.add_parser("artifact-paths", help="Show artifact output paths (auto-detects HOTL)")

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

    # All other commands need config
    try:
        config_path = find_config(args.config if hasattr(args, "config") and args.config else None)
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    if args.command == "artifact-paths":
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
