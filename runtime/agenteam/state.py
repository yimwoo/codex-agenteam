"""Run state management: init, status, state file I/O."""

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

from .config import resolve_team_config
from .events import append_event

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def validate_run_id(run_id: str) -> None:
    """Validate run_id to prevent path traversal.

    Raises ValueError if run_id contains path separators or other
    dangerous characters.
    """
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(
            f"Invalid run_id '{run_id}'. "
            "Must contain only alphanumeric characters, hyphens, "
            "and underscores."
        )


def generate_run_id() -> str:
    """Generate a timestamp-based run ID."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def get_pipeline_stages(config: dict) -> list[dict]:
    """Extract pipeline stages from config."""
    pipeline = config.get("pipeline", {})
    if not isinstance(pipeline, dict):
        return []
    stages: list[dict] = pipeline.get("stages", [])
    return stages


def set_stage_field(run_id: str, stage: str, field: str, value) -> None:
    """Set an arbitrary field on a stage in state.

    Loads the state file, sets state["stages"][stage][field] = value,
    and writes it back. Exits with error if run or stage not found.
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
    stages[stage][field] = value
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def resolve_effective_stages(config: dict, profile: str | None) -> list[dict]:
    """Resolve the effective stage list, optionally filtered by a profile.

    Returns full stage config dicts in pipeline.stages order.
    """
    all_stages = get_pipeline_stages(config)
    if not profile:
        return all_stages

    # Implicit 'full' profile = all stages
    pipeline = config.get("pipeline", {})
    profiles = pipeline.get("profiles", {}) if isinstance(pipeline, dict) else {}

    if profile == "full" and profile not in profiles:
        return all_stages

    profile_def = profiles.get(profile)
    if not profile_def:
        print(
            json.dumps({"error": f"Unknown profile '{profile}'"}),
            file=sys.stderr,
        )
        sys.exit(1)

    profile_stage_names = set(profile_def.get("stages", []))
    effective = [s for s in all_stages if s["name"] in profile_stage_names]

    if not effective:
        print(
            json.dumps({"error": f"Profile '{profile}' resolves to zero stages"}),
            file=sys.stderr,
        )
        sys.exit(1)

    return effective


def resolve_stages_for_run(run_id: str | None, config: dict) -> list[dict]:
    """Return stages from run state if run_id exists, else from config.

    When a run_id is provided and state exists, stages are reconstructed
    entirely from the state snapshot — config is not consulted.
    """
    if run_id:
        state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            stage_order = state.get("stage_order", [])
            stages_map = state.get("stages", {})
            result = []
            for name in stage_order:
                if name in stages_map:
                    stage_dict = {"name": name}
                    stage_dict.update(stages_map[name])
                    result.append(stage_dict)
            if result:
                return result
    return get_pipeline_stages(config)


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
    profile = getattr(args, "profile", None)
    stages = resolve_effective_stages(config, profile)

    # Compute config hash from effective merged config (not a single file)
    # This ensures drift detection catches changes in either team or personal layer
    config_hash = ""
    try:
        canonical = yaml.dump(config, default_flow_style=False, sort_keys=True)
        config_hash = hashlib.sha256(canonical.encode()).hexdigest()
    except (TypeError, yaml.YAMLError):
        pass

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stage_order = [s["name"] for s in stages]

    state: dict = {
        "run_id": run_id,
        "task": task,
        "pipeline_mode": pipeline_mode,
        "profile": profile,
        "stage_order": stage_order,
        "current_stage": stages[0]["name"] if stages else None,
        "started_at": now,
        "last_update": now,
        "config_hash": config_hash,
        "status": "running",
        "branch": None,
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
            "verify": stage.get("verify"),
            "verify_safe": stage.get("verify_safe"),
            "max_retries": stage.get("max_retries", 0),
            "rework_to": stage.get("rework_to"),
            "criteria": stage.get("criteria", {}),
        }

    # Write state file
    state_path = state_dir / f"{run_id}.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)

    # Emit run_started event
    append_event(run_id, "run_started", None, {"task": task, "pipeline_mode": pipeline_mode})

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


def cmd_stage_baseline(args, config: dict) -> None:
    """Capture or retrieve a per-stage git baseline.

    Arguments: --run-id <id> --stage <stage> --action capture|rollback
    """
    run_id = args.run_id
    stage_name = args.stage
    action = args.action

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
    if stage_name not in stages:
        print(
            json.dumps({"error": f"Stage '{stage_name}' not found in state"}),
            file=sys.stderr,
        )
        sys.exit(1)

    stage_state = stages[stage_name]

    if action == "capture":
        # Record current HEAD as baseline
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            sha = proc.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(
                json.dumps({"error": f"git rev-parse HEAD failed: {e.stderr.strip()}"}),
                file=sys.stderr,
            )
            sys.exit(1)

        stage_state["baseline"] = sha
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        print(
            json.dumps(
                {
                    "stage": stage_name,
                    "baseline": sha,
                    "action": "capture",
                }
            )
        )

    elif action == "rollback":
        baseline = stage_state.get("baseline")
        if not baseline:
            print(
                json.dumps({"error": f"No baseline found for stage '{stage_name}'"}),
                file=sys.stderr,
            )
            sys.exit(1)

        # Check isolation mode for safety
        _, isolation_mode = resolve_team_config(config)

        if isolation_mode == "none":
            print(
                json.dumps(
                    {
                        "stage": stage_name,
                        "baseline": baseline,
                        "action": "rollback",
                        "allowed": False,
                        "reason": "Rollback disabled in isolation:none -- "
                        "would affect user's branch directly",
                    }
                )
            )
        else:
            print(
                json.dumps(
                    {
                        "stage": stage_name,
                        "baseline": baseline,
                        "action": "rollback",
                        "allowed": True,
                    }
                )
            )

    else:
        print(
            json.dumps({"error": f"Unknown action '{action}'. Must be 'capture' or 'rollback'"}),
            file=sys.stderr,
        )
        sys.exit(1)


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
