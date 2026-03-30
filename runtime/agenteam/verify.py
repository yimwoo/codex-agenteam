"""Verification planning, recording, and gate management for the verified pipeline."""

import json
import sys
from pathlib import Path

from .config import resolve_team_config
from .events import append_event
from .roles import resolve_roles
from .state import resolve_stages_for_run


def detect_verify_command(cwd: str | None = None) -> str | None:
    """Auto-detect a verification command from repo signals in the given directory.

    Checks for:
      - pytest.ini, pyproject.toml with [tool.pytest], or tests/ dir -> "python3 -m pytest -v"
      - package.json with test script -> "npm test"
      - go.mod -> "go test ./..."
      - Cargo.toml -> "cargo test"
      - Makefile with test target -> "make test"

    Returns the verify command string, or None if nothing detected.
    """
    d = Path(cwd) if cwd else Path.cwd()

    # Python / pytest
    if (d / "pytest.ini").exists():
        return "python3 -m pytest -v"

    pyproject = d / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text()
            if "[tool.pytest" in content:
                return "python3 -m pytest -v"
        except OSError:
            pass

    if (d / "tests").is_dir():
        return "python3 -m pytest -v"

    # Node.js / npm
    pkg_json = d / "package.json"
    if pkg_json.exists():
        try:
            import json as _json

            pkg = _json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                return "npm test"
        except (OSError, json.JSONDecodeError):
            pass

    # Go
    if (d / "go.mod").exists():
        return "go test ./..."

    # Rust
    if (d / "Cargo.toml").exists():
        return "cargo test"

    # Makefile
    makefile = d / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text()
            for line in content.splitlines():
                stripped = line.strip()
                if stripped == "test:" or stripped.startswith("test:"):
                    return "make test"
        except OSError:
            pass

    return None


def _resolve_cwd(config: dict, run_id: str | None) -> str:
    """Resolve the working directory for verification.

    In worktree mode, returns the worktree path. Otherwise returns cwd.
    """
    _, isolation_mode = resolve_team_config(config)

    if isolation_mode == "worktree" and run_id:
        # Check state for worktree path
        state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            wt = state.get("worktree_path")
            if wt:
                return str(Path.cwd() / wt)

    return str(Path.cwd())


def _load_state(run_id: str) -> dict:
    """Load a run state file by run_id."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(
            json.dumps({"error": f"Run {run_id} not found"}),
            file=sys.stderr,
        )
        sys.exit(1)
    with open(state_path) as f:
        return json.load(f)


def _save_state(run_id: str, state: dict) -> None:
    """Save a run state file."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def cmd_verify_plan(args, config: dict) -> None:
    """Return a verification plan for a pipeline stage.

    Arguments: <stage> --run-id <id>
    Returns JSON with: stage, verify, source, max_retries, attempt, cwd
    """
    stage_name = args.stage
    run_id = getattr(args, "run_id", None)

    stages = resolve_stages_for_run(run_id, config)
    stage_config = None
    for s in stages:
        if s["name"] == stage_name:
            stage_config = s
            break

    if not stage_config:
        print(
            json.dumps({"error": f"Stage '{stage_name}' not found in pipeline"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine verify command and source
    verify = stage_config.get("verify")
    source = "config" if verify else None
    max_retries = stage_config.get("max_retries", 0)

    if verify is None:
        # Auto-detect
        cwd = _resolve_cwd(config, run_id)
        detected = detect_verify_command(cwd)
        if detected:
            verify = detected
            source = "auto-detected"
        else:
            source = "none"

    # Determine current attempt from state
    attempt = 0
    if run_id and verify:
        state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
        if state_path.exists():
            with open(state_path) as f:
                state = json.load(f)
            stage_state = state.get("stages", {}).get(stage_name, {})
            attempts = stage_state.get("verify_attempts", [])
            attempt = len(attempts) + 1
        else:
            attempt = 1
    elif verify:
        attempt = 1

    result: dict = {
        "stage": stage_name,
        "verify": verify,
        "source": source,
        "max_retries": max_retries,
        "attempt": attempt,
    }

    # Include cwd only when there is a verify command
    if verify:
        result["cwd"] = _resolve_cwd(config, run_id)

    # Cross-stage rework: if rework_to is configured, resolve the target stage's writing roles
    rework_to = stage_config.get("rework_to")
    if rework_to:
        # Find target stage config
        target_stage_config = None
        for s in stages:
            if s["name"] == rework_to:
                target_stage_config = s
                break

        if not target_stage_config:
            print(
                json.dumps({"error": f"rework_to stage '{rework_to}' not found in pipeline"}),
                file=sys.stderr,
            )
            sys.exit(1)

        # Resolve writing roles from the target stage
        roles = resolve_roles(config)
        target_role_names = target_stage_config.get("roles", [])
        rework_roles = []
        for rname in target_role_names:
            role = roles.get(rname, {"name": rname})
            if role.get("can_write", False):
                rework_roles.append(rname)
        # If no writing roles, include all roles from the target stage
        if not rework_roles:
            rework_roles = list(target_role_names)

        result["rework_to"] = rework_to
        result["rework_roles"] = rework_roles

    print(json.dumps(result))


def cmd_record_verify(args, config: dict) -> None:
    """Record a verification result for a stage.

    Arguments: --run-id <id> --stage <stage> --result pass|fail
               [--output "..."] [--rework-stage <stage>]
    """
    run_id = args.run_id
    stage_name = args.stage
    result_val = args.result
    output = getattr(args, "output", None) or ""
    rework_stage = getattr(args, "rework_stage", None)

    state = _load_state(run_id)

    stages = state.get("stages", {})
    if stage_name not in stages:
        print(
            json.dumps({"error": f"Stage '{stage_name}' not found in state"}),
            file=sys.stderr,
        )
        sys.exit(1)

    stage_state = stages[stage_name]

    # Initialize verify_attempts if needed
    if "verify_attempts" not in stage_state:
        stage_state["verify_attempts"] = []

    attempt_num = len(stage_state["verify_attempts"]) + 1
    entry: dict = {
        "attempt": attempt_num,
        "result": result_val,
    }
    if output:
        entry["output"] = output
    if rework_stage:
        entry["rework_stage"] = rework_stage

    stage_state["verify_attempts"].append(entry)
    stage_state["verify_result"] = result_val

    _save_state(run_id, state)

    # Emit stage_verified event
    # Resolve verify command from state (if run-scoped) or config
    stages = resolve_stages_for_run(run_id, config)
    verify_cmd = ""
    for s in stages:
        if s["name"] == stage_name:
            verify_cmd = s.get("verify", "")
            break
    event_data: dict = {
        "result": result_val,
        "command": verify_cmd,
        "attempt": attempt_num,
    }
    if rework_stage:
        event_data["rework_stage"] = rework_stage
    append_event(run_id, "stage_verified", stage_name, event_data)

    print(json.dumps({
        "recorded": True,
        "stage": stage_name,
        "attempt": attempt_num,
        "result": result_val,
    }))


def cmd_final_verify_plan(args, config: dict) -> None:
    """Return a final verification plan for the run.

    Arguments: --run-id <id>
    Returns JSON with: commands, policy, max_retries, source, cwd
    """
    run_id = getattr(args, "run_id", None)

    # Read from config
    commands = config.get("final_verify")
    policy = config.get("final_verify_policy", "block")
    max_retries = config.get("final_verify_max_retries", 1)

    if commands:
        # Ensure commands is a list
        if isinstance(commands, str):
            commands = [commands]
        source = "config"
    else:
        # Auto-detect
        cwd = _resolve_cwd(config, run_id)
        detected = detect_verify_command(cwd)
        if detected:
            commands = [detected]
            source = "auto-detected"
        else:
            commands = []
            source = "none"
            policy = "unverified"

    result: dict = {
        "commands": commands,
        "policy": policy,
        "max_retries": max_retries,
        "source": source,
    }

    # Include cwd only when there are commands
    if commands:
        result["cwd"] = _resolve_cwd(config, run_id)

    print(json.dumps(result))


def cmd_record_gate(args, config: dict) -> None:
    """Record a gate decision for a stage.

    Arguments: --run-id <id> --stage <stage> --gate-type <type> --result <approved|rejected>
               [--verdict "..."] [--criteria-failed "..."] [--criteria-details "..."]
               [--override-reason "..."]
    """
    run_id = args.run_id
    stage_name = args.stage
    gate_type = args.gate_type
    result_val = args.result
    verdict = getattr(args, "verdict", None) or ""
    criteria_failed = getattr(args, "criteria_failed", None) or ""
    criteria_details = getattr(args, "criteria_details", None) or ""
    override_reason = getattr(args, "override_reason", None) or ""

    state = _load_state(run_id)

    stages = state.get("stages", {})
    if stage_name not in stages:
        print(
            json.dumps({"error": f"Stage '{stage_name}' not found in state"}),
            file=sys.stderr,
        )
        sys.exit(1)

    stage_state = stages[stage_name]

    stage_state["gate"] = gate_type
    stage_state["gate_result"] = result_val

    # For agent gates, record which agent type approved
    if gate_type in ("reviewer", "qa"):
        stage_state["gate_agent"] = gate_type

    if verdict:
        stage_state["gate_verdict"] = verdict

    # Criteria override fields
    if gate_type == "criteria_override":
        stage_state["gate_type"] = "criteria_override"
        if criteria_failed:
            try:
                stage_state["criteria_failed"] = json.loads(criteria_failed)
            except json.JSONDecodeError:
                stage_state["criteria_failed"] = [criteria_failed]
        if criteria_details:
            try:
                stage_state["criteria_details"] = json.loads(criteria_details)
            except json.JSONDecodeError:
                stage_state["criteria_details"] = criteria_details
        if override_reason:
            stage_state["override_reason"] = override_reason

    _save_state(run_id, state)

    # Emit stage_gated event
    append_event(run_id, "stage_gated", stage_name, {"gate_type": gate_type, "result": result_val})

    response: dict = {
        "recorded": True,
        "stage": stage_name,
        "gate_type": gate_type,
        "result": result_val,
    }
    if verdict:
        response["verdict"] = verdict

    print(json.dumps(response))
