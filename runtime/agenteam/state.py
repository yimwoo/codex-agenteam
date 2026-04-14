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
from .roles import resolve_roles

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


def is_discoverable_state(state: dict) -> bool:
    """Return True when a state file is safe to treat as the latest run.

    Implicit discovery powers commands like ``status`` (without a run-id),
    ``standup``, and ``health``. Those commands should prefer runtime-managed
    run state and ignore older scratch/demo files that predate the current
    state schema.
    """
    run_id = state.get("run_id")
    status = state.get("status")
    last_update = state.get("last_update")
    stages = state.get("stages")

    return (
        isinstance(run_id, str)
        and bool(run_id)
        and isinstance(status, str)
        and bool(status)
        and isinstance(last_update, str)
        and bool(last_update)
        and isinstance(stages, dict)
    )


def _state_uses_only_known_roles(state: dict, known_roles: set[str] | None) -> bool:
    """Return True when every stage role in state is in known_roles."""
    if known_roles is None:
        return True

    stages = state.get("stages", {})
    if not isinstance(stages, dict):
        return False

    for stage_state in stages.values():
        if not isinstance(stage_state, dict):
            continue
        stage_roles = stage_state.get("roles", [])
        if not isinstance(stage_roles, list):
            continue
        for role_name in stage_roles:
            if isinstance(role_name, str) and role_name not in known_roles:
                return False
    return True


def _load_state_file(path: Path) -> dict | None:
    """Load a state file, returning None on read/parse failure."""
    try:
        with open(path) as f:
            result: dict = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return result


def _unknown_state_roles(state: dict, known_roles: set[str]) -> list[str]:
    """Return sorted unknown role names referenced by a state."""
    unknown_roles: set[str] = set()
    stages = state.get("stages", {})
    if not isinstance(stages, dict):
        return []

    for stage_state in stages.values():
        if not isinstance(stage_state, dict):
            continue
        stage_roles = stage_state.get("roles", [])
        if not isinstance(stage_roles, list):
            continue
        for role_name in stage_roles:
            if isinstance(role_name, str) and role_name not in known_roles:
                unknown_roles.add(role_name)

    return sorted(unknown_roles)


def find_latest_compatible_state(config: dict) -> tuple[dict | None, list[str], bool]:
    """Find the newest discoverable state compatible with the current role set.

    Returns ``(state, warnings, saw_discoverable)`` so callers can distinguish
    between "no runs at all" and "only legacy/incompatible runs were found".
    """
    state_dir = Path.cwd() / ".agenteam" / "state"
    if not state_dir.exists():
        return None, [], False

    known_roles = set(resolve_roles(config).keys())
    warnings: list[str] = []
    saw_discoverable = False

    for path in sorted(state_dir.glob("*.json"), reverse=True):
        state = _load_state_file(path)
        if state is None or not is_discoverable_state(state):
            continue

        saw_discoverable = True
        unknown_roles = _unknown_state_roles(state, known_roles)
        if unknown_roles:
            run_id = state.get("run_id", path.stem)
            warnings.append(
                "Ignored stale local run state "
                f"{run_id}: references unknown roles {', '.join(unknown_roles)}"
            )
            continue

        return state, warnings, True

    return None, warnings, saw_discoverable


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
    governance: dict = {}
    if getattr(args, "initiative", None):
        governance["initiative"] = args.initiative
    if getattr(args, "phase", None):
        governance["phase"] = args.phase
    if getattr(args, "checkpoint", None):
        governance["checkpoint"] = args.checkpoint
    burn_estimate = getattr(args, "burn_estimate", None)
    if burn_estimate is not None:
        try:
            governance["burn_estimate"] = float(burn_estimate)
        except (TypeError, ValueError):
            print(
                json.dumps(
                    {"error": f"Invalid --burn-estimate '{burn_estimate}'. Must be numeric."}
                ),
                file=sys.stderr,
            )
            sys.exit(1)

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
    if governance:
        state["governance"] = governance

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
    event_data = {"task": task, "pipeline_mode": pipeline_mode}
    if governance:
        event_data["governance"] = governance
    append_event(run_id, "run_started", None, event_data)

    print(json.dumps(state))


def find_latest_state(known_roles: set[str] | None = None) -> dict | None:
    """Find the most recent state file."""
    latest_state_path = find_latest_state_path(known_roles=known_roles)
    if latest_state_path is None:
        return None
    return _load_state_file(latest_state_path)


def find_latest_state_path(known_roles: set[str] | None = None) -> Path | None:
    """Find the most recent discoverable state file path."""
    state_dir = Path.cwd() / ".agenteam" / "state"
    if not state_dir.exists():
        return None
    files = sorted(state_dir.glob("*.json"), reverse=True)
    for path in files:
        state = _load_state_file(path)
        if state is None:
            continue
        if is_discoverable_state(state) and _state_uses_only_known_roles(state, known_roles):
            return path
    return None


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


def _format_elapsed(start_iso: str, end_iso: str | None = None) -> str:
    """Format elapsed time between two ISO timestamps (or start to now)."""
    from datetime import datetime, timezone

    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        if end_iso:
            end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        else:
            end = datetime.now(timezone.utc)
        delta = int((end - start).total_seconds())
        minutes, seconds = divmod(max(delta, 0), 60)
        return f"{minutes}m {seconds:02d}s"
    except (ValueError, TypeError):
        return ""


def _build_progress_view(state: dict, run_id: str) -> dict:
    """Build a compact progress view from state + last event."""
    from .events import list_events

    # Run-level elapsed
    started_at = state.get("started_at", "")
    elapsed = _format_elapsed(started_at) if started_at else ""

    # Stage summaries
    stage_order = state.get("stage_order", list(state.get("stages", {}).keys()))
    stages_map = state.get("stages", {})
    stages_list = []
    for name in stage_order:
        s = stages_map.get(name, {})
        entry: dict = {"name": name, "status": s.get("status", "pending")}
        s_started = s.get("started_at")
        s_completed = s.get("completed_at")
        if s_started:
            entry["elapsed"] = _format_elapsed(s_started, s_completed)
        stages_list.append(entry)

    # Current stage details
    current_name = state.get("current_stage")
    current_stage = None
    if current_name and current_name in stages_map:
        cs = stages_map[current_name]
        current_stage = {
            "name": current_name,
            "status": cs.get("status", "pending"),
        }
        cs_started = cs.get("started_at")
        if cs_started:
            current_stage["elapsed"] = _format_elapsed(cs_started, cs.get("completed_at"))
        verify_attempts = cs.get("verify_attempts", [])
        if verify_attempts:
            current_stage["verify_attempt"] = len(verify_attempts)
        max_retries = cs.get("max_retries", 0)
        if max_retries:
            current_stage["max_retries"] = max_retries

    # Last event
    last_event = None
    events = list_events(run_id, last_n=1)
    if events:
        last_event = events[0]

    result = {
        "run_id": run_id,
        "task": state.get("task", ""),
        "profile": state.get("profile"),
        "status": state.get("status", "unknown"),
        "elapsed": elapsed,
        "current_stage": current_stage,
        "stages": stages_list,
        "active_lock": state.get("write_locks", {}).get("active"),
        "last_event": last_event,
    }
    governance = state.get("governance")
    if isinstance(governance, dict):
        result["governance"] = governance
    return result


def cmd_status(args, config: dict) -> None:
    """Show current run status."""
    from .memory import build_visible_memory

    if args.run_id:
        state_path = Path.cwd() / ".agenteam" / "state" / f"{args.run_id}.json"
        if not state_path.exists():
            print(json.dumps({"error": f"Run {args.run_id} not found"}), file=sys.stderr)
            sys.exit(1)
        with open(state_path) as f:
            state = json.load(f)
    else:
        state, warnings, saw_discoverable = find_latest_compatible_state(config)
        if not state:
            if saw_discoverable:
                print(
                    json.dumps(
                        {
                            "error": "No compatible runs found for current role config.",
                            "warnings": warnings,
                        }
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            print(json.dumps({"error": "No runs found"}), file=sys.stderr)
            sys.exit(1)

    if getattr(args, "progress", False):
        run_id = state.get("run_id", getattr(args, "run_id", ""))
        progress = _build_progress_view(state, run_id)
        print(json.dumps(progress, indent=2))
    else:
        result = dict(state)
        result["memory"] = build_visible_memory(config, current_run_id=state.get("run_id"))
        print(json.dumps(result, indent=2))
