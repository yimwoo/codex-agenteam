"""State machine: formal stage transitions with validation."""

import json
import sys
import time
from pathlib import Path

# Valid state transitions per the v2.3 design doc.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"dispatched"},
    "dispatched": {"verifying", "passed", "completed"},
    "verifying": {"passed", "failed"},
    "passed": {"gated", "completed"},
    "gated": {"completed", "rejected"},
    "failed": {"dispatched", "rework"},
    "rework": {"dispatched"},
    "rejected": {"dispatched"},
    # Terminal: completed has no outgoing transitions.
    "completed": set(),
}

# Backward compatibility: map v2.2 status values to v2.3 equivalents.
V22_STATUS_MAP: dict[str, str] = {
    "in-progress": "dispatched",
}


def transition(run_id: str, stage: str, to_status: str) -> dict:
    """Validate and apply a stage status transition.

    Returns dict with stage, from, to, last_update on success.
    Calls sys.exit(1) with JSON error on failure.
    """
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(
            json.dumps({"error": f"Run {run_id} not found"}),
            file=sys.stderr,
        )
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    stages = state.get("stages", {})
    if stage not in stages:
        print(
            json.dumps({"error": f"Stage '{stage}' not found in state"}),
            file=sys.stderr,
        )
        sys.exit(1)

    current = stages[stage].get("status", "pending")

    # Map v2.2 status values
    mapped = V22_STATUS_MAP.get(current, current)

    # Validate transition
    valid_targets = VALID_TRANSITIONS.get(mapped, set())
    if to_status not in valid_targets:
        print(
            json.dumps({
                "error": f"Invalid transition: '{current}' -> '{to_status}' for stage '{stage}'",
                "valid_targets": sorted(valid_targets),
            }),
            file=sys.stderr,
        )
        sys.exit(1)

    # Apply transition
    old_status = current
    stages[stage]["status"] = to_status
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["last_update"] = now

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    return {
        "stage": stage,
        "from": old_status,
        "to": to_status,
        "last_update": now,
    }


def cmd_transition(args, config: dict) -> None:
    """CLI handler for: agenteam-rt transition."""
    result = transition(args.run_id, args.stage, args.to)
    print(json.dumps(result))
