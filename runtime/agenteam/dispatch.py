"""Dispatch planning, policy checks, and role queries."""

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

from .config import resolve_team_config
from .roles import resolve_roles
from .state import resolve_stages_for_run

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _scopes_overlap(scope_a: list[str], scope_b: list[str]) -> bool:
    """Return True if any pattern in scope_a exactly matches any pattern in scope_b.

    This uses the same string-equality overlap check as cmd_policy_check:
    two scopes overlap when they share at least one identical pattern string.
    """
    return bool(set(scope_a) & set(scope_b))


def partition_writer_groups(
    stage_roles: list[str],
    resolved_roles: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    """Partition a stage's roles into parallel-safe writer groups.

    Returns:
        (groups, read_only)
        groups  -- list of dicts: {"group": N, "roles": [...], "parallel": True}
        read_only -- list of role names with can_write: false
    """
    writers: list[str] = []
    read_only: list[str] = []

    for rname in stage_roles:
        role = resolved_roles.get(rname, {"name": rname})
        if role.get("can_write", False):
            writers.append(rname)
        else:
            read_only.append(rname)

    # Sort writers alphabetically for deterministic ordering
    writers.sort()

    # Greedy partitioning
    groups: list[list[str]] = []
    # Track the scopes already present in each group (list of sets-of-patterns)
    group_scopes: list[set[str]] = []

    for wname in writers:
        role = resolved_roles.get(wname, {"name": wname})
        w_scope = set(role.get("write_scope", []))

        placed = False
        for gi, grp in enumerate(groups):
            if not (w_scope & group_scopes[gi]):
                # No overlap with any existing role in this group
                grp.append(wname)
                group_scopes[gi] |= w_scope
                placed = True
                break

        if not placed:
            groups.append([wname])
            group_scopes.append(set(w_scope))

    result = [
        {"group": i + 1, "roles": grp, "parallel": True}
        for i, grp in enumerate(groups)
    ]
    return result, read_only


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_dispatch(args, config: dict) -> None:
    """Generate dispatch plan for a stage."""
    stage_name = args.stage
    task = args.task or ""

    run_id = getattr(args, "run_id", None)
    stages = resolve_stages_for_run(run_id, config)
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

    # --- Scoped parallel mode (isolation: none) ---
    if isolation_mode == "none":
        writer_groups, read_only_names = partition_writer_groups(role_names, roles)

        # Build grouped dispatch output
        groups_out = []
        for wg in writer_groups:
            role_entries = []
            for rname in wg["roles"]:
                role_entries.append({
                    "role": rname,
                    "agent": f".codex/agents/{rname}.toml",
                    "mode": "write",
                    "task": task,
                })
            groups_out.append({
                "group": wg["group"],
                "roles": role_entries,
                "parallel": True,
            })

        plan = {
            "stage": stage_name,
            "groups": groups_out,
            "read_only": read_only_names,
            "policy": isolation_mode,
            "gate": stage_config.get("gate", "auto"),
            "blocked": [],
        }
        print(json.dumps(plan))
        return

    # --- Flat dispatch (branch / worktree) ---
    # Map isolation to write_mode for dispatch logic
    write_mode = (
        "serial"
        if isolation_mode == "branch"
        else "worktree"
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


def cmd_scope_audit(args, config: dict) -> None:
    """Audit that all changed files since baseline are within declared write_scopes."""
    stage_name = args.stage
    baseline = args.baseline

    run_id = getattr(args, "run_id", None)
    stages = resolve_stages_for_run(run_id, config)
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

    # Collect all write_scope patterns from writing roles in this stage
    all_scopes: list[str] = []
    for rname in role_names:
        role = roles.get(rname, {"name": rname})
        if role.get("can_write", False):
            all_scopes.extend(role.get("write_scope", []))

    # De-duplicate while preserving order for deterministic output
    seen: set[str] = set()
    unique_scopes: list[str] = []
    for s in all_scopes:
        if s not in seen:
            seen.add(s)
            unique_scopes.append(s)

    # Get changed files via git diff
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline}..HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [f for f in proc.stdout.strip().split("\n") if f]
    except subprocess.CalledProcessError as e:
        print(
            json.dumps({"error": f"git diff failed: {e.stderr.strip()}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Classify each changed file
    files_by_scope: dict[str, list[str]] = {}
    unclaimed_files: list[str] = []

    for fpath in changed_files:
        claimed = False
        for scope in unique_scopes:
            if fnmatch.fnmatch(fpath, scope):
                files_by_scope.setdefault(scope, []).append(fpath)
                claimed = True
                break  # first matching scope wins
        if not claimed:
            unclaimed_files.append(fpath)

    violations = [
        {"file": f, "reason": "outside all declared write_scopes for this stage"}
        for f in unclaimed_files
    ]

    result = {
        "stage": stage_name,
        "baseline": baseline,
        "passed": len(unclaimed_files) == 0,
        "files_by_scope": files_by_scope,
        "unclaimed_files": unclaimed_files,
        "violations": violations,
    }
    print(json.dumps(result))


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
