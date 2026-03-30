"""Run state management: init, status, state file I/O."""

import json
import sys
import time
from pathlib import Path

from .config import resolve_team_config


def generate_run_id() -> str:
    """Generate a timestamp-based run ID."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def get_pipeline_stages(config: dict) -> list[dict]:
    """Extract pipeline stages from config."""
    pipeline = config.get("pipeline", {})
    stages: list[dict] = pipeline.get("stages", [])
    return stages


def cmd_init(args, config: dict) -> None:
    """Initialize a run: validate config, create state."""
    task = args.task or "unnamed task"
    run_id = generate_run_id()

    # Create state directory
    state_dir = Path.cwd() / ".agenteam" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Build initial state
    pipeline_mode, _ = resolve_team_config(config)
    pipeline_mode = pipeline_mode or "standalone"
    stages = get_pipeline_stages(config)

    state: dict = {
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
        result: dict = json.load(f)
    return result


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
