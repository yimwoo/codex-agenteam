"""Dispatch planning, policy checks, and role queries."""

import json
import sys
from pathlib import Path

from .config import resolve_team_config
from .roles import resolve_roles
from .state import get_pipeline_stages


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
    _, isolation_mode = resolve_team_config(config)
    # Map isolation to write_mode for dispatch logic
    write_mode = (
        "serial"
        if isolation_mode == "branch"
        else ("worktree" if isolation_mode == "worktree" else "scoped")
    )

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
        "policy": isolation_mode,
        "gate": stage_config.get("gate", "auto"),
        "blocked": blocked,
    }

    print(json.dumps(plan))


def cmd_policy_check(args, config: dict) -> None:
    """Validate write scopes don't overlap across writing roles."""
    roles = resolve_roles(config)
    writers = {n: r for n, r in roles.items() if r.get("can_write")}

    overlaps = []
    writer_names = sorted(writers.keys())
    for i, n1 in enumerate(writer_names):
        for n2 in writer_names[i + 1 :]:
            s1 = set(writers[n1].get("write_scope", []))
            s2 = set(writers[n2].get("write_scope", []))
            common = s1 & s2
            if common:
                overlaps.append({"roles": [n1, n2], "overlapping_scopes": sorted(common)})

    result = {
        "policy": resolve_team_config(config)[1],  # isolation mode
        "writers": {n: r.get("write_scope", []) for n, r in writers.items()},
        "overlaps": overlaps,
        "safe_for_parallel": len(overlaps) == 0,
    }
    print(json.dumps(result))


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
