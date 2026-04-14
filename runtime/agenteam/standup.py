"""Standup summary: health computation and standup command."""

import json
import time

from .artifacts import resolve_artifact_paths_for_config
from .memory import build_visible_memory
from .roles import resolve_roles
from .state import find_latest_compatible_state


def _extract_governance(state: dict | None) -> dict | None:
    """Return governance metadata from nested or top-level state fields."""
    if not isinstance(state, dict):
        return None

    governance = state.get("governance")
    if isinstance(governance, dict) and governance:
        return governance

    keys = (
        "initiative",
        "phase",
        "checkpoint",
        "burn_estimate",
        "escalation_status",
    )
    extracted = {key: state.get(key) for key in keys if state.get(key) is not None}
    return extracted or None


def compute_health(state: dict | None) -> tuple[str, list[str]]:
    """Compute health indicator and warnings from run state.

    Returns (health, warnings) where health is one of:
    "on-track", "at-risk", "off-track", "no-active-run".
    """
    if state is None:
        return "no-active-run", []

    warnings = []
    stages = state.get("stages", {})

    # off-track: any stage rejected, failed, blocked, or in rework
    off_track_stages = []
    for name, info in stages.items():
        status = info.get("status")
        gate_result = info.get("gate_result")
        if status in ("blocked", "failed", "rejected", "rework") or gate_result == "rejected":
            off_track_stages.append(name)
            if gate_result == "rejected":
                warnings.append(f"Stage '{name}' has a rejected gate decision")
            else:
                warnings.append(f"Stage '{name}' is {status}")
    if off_track_stages:
        return "off-track", warnings

    # at-risk: any active stage that is still running for a long time
    at_risk_stages = []
    for name, info in stages.items():
        status = info.get("status")
        if status in ("in-progress", "dispatched", "verifying", "gated", "passed"):
            if info.get("gate") == "rejected":
                at_risk_stages.append(name)
                warnings.append(f"Stage '{name}' has an unresolved gate rejection")
                continue
            started_at = info.get("started_at")
            # If started_at is present, check duration (> 30 min = at-risk)
            try:
                if started_at:
                    elapsed = time.time() - started_at
                    if elapsed > 1800:
                        at_risk_stages.append(name)
                        warnings.append(
                            f"Stage '{name}' has been active for {int(elapsed // 60)} minutes"
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
    state, warnings, _ = find_latest_compatible_state(config)

    # Health
    health, health_warnings = compute_health(state)
    warnings.extend(health_warnings)

    # Run summary
    run_summary = None
    stages_summary = {}
    governance = None
    if state:
        run_summary = {
            "run_id": state.get("run_id"),
            "task": state.get("task"),
            "current_stage": state.get("current_stage"),
        }
        governance = _extract_governance(state)
        if isinstance(governance, dict):
            run_summary["governance"] = governance
            run_summary.update(governance)
        stages_summary = state.get("stages", {})

    memory = build_visible_memory(config, current_run_id=state.get("run_id") if state else None)

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
                dispatch_list.append(
                    {
                        "role": rname,
                        "agent": f".codex/agents/{rname}.toml",
                    }
                )

    # Task context (--task flag)
    result = {
        "health": health,
        "run": run_summary,
        "roles": role_names,
        "stages": stages_summary,
        "artifact_paths": artifact_paths,
        "memory": memory,
        "dispatch_mode": dispatch_mode,
        "output_path": output_path,
        "warnings": warnings,
    }

    if isinstance(governance, dict):
        result["governance"] = governance

    if dispatch_list is not None:
        result["dispatch"] = dispatch_list

    if args.task:
        result["task_context"] = args.task

    print(json.dumps(result))
