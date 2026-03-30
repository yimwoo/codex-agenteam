"""Resume: detect stale runs and build resume plans."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import find_config
from .events import list_events
from .state import resolve_stages_for_run

# Stale threshold in seconds (10 minutes).
STALE_THRESHOLD = 600

# Known safe verify command prefixes.
SAFE_VERIFY_PREFIXES = [
    "python3 -m pytest",
    "python -m pytest",
    "pytest",
    "npm test",
    "go test",
    "cargo test",
    "make test",
]

# Terminal stage states.
TERMINAL_STATES = {"completed"}
# Blocking states (non-terminal but not progressing).
BLOCKING_STATES = {"failed", "rejected", "rework"}


def _is_stale(last_update: str) -> bool:
    """Check if a last_update timestamp is stale (>10 min old)."""
    try:
        dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() > STALE_THRESHOLD
    except (ValueError, TypeError):
        return True


def _is_verify_safe(command: str | None, stage_config: dict | None) -> tuple[bool, str]:
    """Determine if a verify command is safe to auto-run.

    Returns (is_safe, source) where source is 'config' or 'heuristic'.
    """
    if stage_config and "verify_safe" in stage_config:
        return bool(stage_config["verify_safe"]), "config"

    if not command:
        return False, "heuristic"

    for prefix in SAFE_VERIFY_PREFIXES:
        if command.strip().startswith(prefix):
            return True, "heuristic"

    return False, "heuristic"


def _find_interrupted_stage(state: dict, run_id: str) -> dict | None:
    """Find the interrupted stage using current_stage, falling back to event history."""
    stages = state.get("stages", {})
    current_stage = state.get("current_stage")

    # Try current_stage first
    if current_stage and current_stage in stages:
        stage_state = stages[current_stage]
        status = stage_state.get("status", "pending")
        if status not in TERMINAL_STATES:
            return {"name": current_stage, **stage_state}

    # Fall back to most recent non-terminal stage by event timestamp
    events = list_events(run_id)
    if events:
        # Walk events in reverse to find the last stage that was active
        for event in reversed(events):
            stage_name = event.get("stage")
            if stage_name and stage_name in stages:
                status = stages[stage_name].get("status", "pending")
                if status not in TERMINAL_STATES:
                    return {"name": stage_name, **stages[stage_name]}

    # Last resort: find first non-completed stage
    for name, stage_state in stages.items():
        status = stage_state.get("status", "pending")
        if status not in TERMINAL_STATES:
            return {"name": name, **stage_state}

    return None


def cmd_resume_detect(args) -> None:
    """Scan for stale, resumable runs. No config needed."""
    state_dir = Path.cwd() / ".agenteam" / "state"
    resumable: list[dict] = []

    if state_dir.exists():
        for f in sorted(state_dir.glob("*.json"), reverse=True):
            try:
                with open(f) as fh:
                    state = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue

            status = state.get("status", "")
            last_update = state.get("last_update", "")

            if status not in ("running", "blocked"):
                continue
            if not _is_stale(last_update):
                continue

            resumable.append({
                "run_id": state.get("run_id", f.stem),
                "task": state.get("task", ""),
                "stage": state.get("current_stage", ""),
                "last_update": last_update,
            })

    print(json.dumps({"resumable_runs": resumable}))


def cmd_resume_plan(args, config: dict) -> None:
    """Build a structured resume plan for a specific run."""
    run_id = args.run_id
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"

    if not state_path.exists():
        print(json.dumps({"error": f"Run {run_id} not found"}), file=sys.stderr)
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    # Stale check
    last_update = state.get("last_update", "")
    stale = _is_stale(last_update)

    # Config hash match
    stored_hash = state.get("config_hash", "")
    current_hash = ""
    try:
        config_path = find_config(args.config if hasattr(args, "config") and args.config else None)
        current_hash = hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
    except (FileNotFoundError, OSError):
        pass
    config_hash_match = stored_hash == current_hash if stored_hash else True

    # Find interrupted stage
    interrupted = _find_interrupted_stage(state, run_id)

    # Build interrupted_stage details
    interrupted_stage = None
    if interrupted:
        stage_name = interrupted["name"]
        # Find stage config for verify details
        pipeline_stages = resolve_stages_for_run(run_id, config)
        stage_config = None
        for s in pipeline_stages:
            if s["name"] == stage_name:
                stage_config = s
                break

        verify_cmd = stage_config.get("verify") if stage_config else None
        has_verify = verify_cmd is not None
        verify_safe, verify_safe_source = _is_verify_safe(verify_cmd, stage_config)

        gate_type = stage_config.get("gate", "auto") if stage_config else "auto"
        has_gate = gate_type in ("human", "reviewer")

        baseline = interrupted.get("baseline")

        interrupted_stage = {
            "name": stage_name,
            "status": interrupted.get("status", "pending"),
            "roles": interrupted.get("roles", []),
            "has_verify": has_verify,
            "verify_command": verify_cmd or "",
            "verify_safe": verify_safe if has_verify else False,
            "verify_safe_source": verify_safe_source if has_verify else "none",
            "has_gate": has_gate,
            "has_baseline": baseline is not None,
            "baseline": baseline or "",
        }

    # Completed and remaining stages
    stages = state.get("stages", {})
    pipeline_stages = resolve_stages_for_run(run_id, config)
    stage_order = [s["name"] for s in pipeline_stages]

    completed_stages = [n for n in stage_order if stages.get(n, {}).get("status") == "completed"]
    remaining_stages = [
        n for n in stage_order
        if n not in completed_stages and (not interrupted_stage or n != interrupted_stage["name"])
    ]

    result = {
        "run_id": run_id,
        "task": state.get("task", ""),
        "status": state.get("status", ""),
        "pipeline_mode": state.get("pipeline_mode", "standalone"),
        "last_update": last_update,
        "stale": stale,
        "config_hash_match": config_hash_match,
        "interrupted_stage": interrupted_stage,
        "completed_stages": completed_stages,
        "remaining_stages": remaining_stages,
    }

    print(json.dumps(result))
