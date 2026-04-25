"""Non-interactive pipeline runner: drives the full pipeline via codex exec."""

import json
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .events import append_event
from .prompt import build_prompt
from .report import _build_run_summary, _extract_lessons
from .state import (
    cmd_init,
)
from .transitions import transition
from .verify import detect_verify_command


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _emit_event(event: dict, events_file: Path | None = None) -> None:
    """Write a JSONL event to stdout and optionally to a file."""
    line = json.dumps(event)
    print(line, flush=True)
    if events_file:
        with open(events_file, "a") as f:
            f.write(line + "\n")


def _check_codex_binary(codex_bin: str) -> None:
    """Verify the codex binary exists."""
    if not shutil.which(codex_bin):
        print(
            json.dumps(
                {
                    "error": f"Codex binary not found: '{codex_bin}'",
                    "hint": "Install Codex CLI or pass --codex-bin with the correct path.",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def _setup_output_dir(output_dir: str, run_id: str) -> Path:
    """Create the output directory structure."""
    out = Path(output_dir) if output_dir else Path.cwd() / ".agenteam" / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    return out


def _parse_codex_args(raw_args: str) -> list[str]:
    """Parse codex exec passthrough args and normalize common bare long flags."""
    if not raw_args:
        return []

    normalized: list[str] = []
    bare_long_flags = {
        "skip-git-repo-check",
    }

    for token in shlex.split(raw_args):
        if token in bare_long_flags:
            normalized.append(f"--{token}")
        else:
            normalized.append(token)

    return normalized


def _load_state(run_id: str) -> dict:
    """Load run state."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(json.dumps({"error": f"Run state not found: {run_id}"}), file=sys.stderr)
        sys.exit(1)
    with open(state_path) as f:
        return json.load(f)


def _save_state(run_id: str, state: dict) -> None:
    """Save run state."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _set_run_status(run_id: str, status: str) -> None:
    """Persist the run-level status."""
    state = _load_state(run_id)
    state["status"] = status
    state["last_update"] = _now_iso()
    _save_state(run_id, state)


def _record_verify_attempt(
    run_id: str,
    stage: str,
    result: str,
    command: str,
    output: str = "",
    rework_stage: str | None = None,
) -> int:
    """Record one verify attempt without printing to stdout."""
    state = _load_state(run_id)
    stage_state = state.get("stages", {}).get(stage)
    if stage_state is None:
        print(json.dumps({"error": f"Stage '{stage}' not found in state"}), file=sys.stderr)
        sys.exit(1)

    attempts = stage_state.setdefault("verify_attempts", [])
    attempt_num = len(attempts) + 1
    entry: dict = {"attempt": attempt_num, "result": result}
    if output:
        entry["output"] = output
    if rework_stage:
        entry["rework_stage"] = rework_stage
    attempts.append(entry)
    stage_state["verify_result"] = result
    state["last_update"] = _now_iso()
    _save_state(run_id, state)

    event_data: dict = {"result": result, "command": command, "attempt": attempt_num}
    if rework_stage:
        event_data["rework_stage"] = rework_stage
    append_event(run_id, "stage_verified", stage, event_data)
    return attempt_num


def _record_gate(run_id: str, stage: str, gate_type: str, result: str) -> None:
    """Record a gate decision without printing to stdout."""
    state = _load_state(run_id)
    stage_state = state.get("stages", {}).get(stage)
    if stage_state is None:
        print(json.dumps({"error": f"Stage '{stage}' not found in state"}), file=sys.stderr)
        sys.exit(1)

    stage_state["gate"] = gate_type
    stage_state["gate_result"] = result
    if gate_type in ("reviewer", "qa"):
        stage_state["gate_agent"] = gate_type
    state["last_update"] = _now_iso()
    _save_state(run_id, state)
    append_event(run_id, "stage_gated", stage, {"gate_type": gate_type, "result": result})


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _record_role_artifacts(run_id: str, stage: str, role_name: str, paths: list[Path]) -> None:
    """Record known runner artifacts for a role."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        return
    state = _load_state(run_id)
    stage_state = state.get("stages", {}).get(stage)
    if stage_state is None:
        return
    role_artifacts = stage_state.setdefault("role_artifacts", {})
    role_artifacts[role_name] = [_display_path(path) for path in paths]
    state["last_update"] = _now_iso()
    _save_state(run_id, state)


def _persist_history(run_id: str) -> None:
    """Persist run history without printing into the runner JSONL stream."""
    summary = _build_run_summary(run_id)
    state = _load_state(run_id)
    summary["profile"] = state.get("profile")
    summary["lessons"] = _extract_lessons(run_id, summary, state)

    history_dir = Path.cwd() / ".agenteam" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{run_id}.json"
    with open(history_path, "w") as f:
        json.dump(summary, f, indent=2)


def _bootstrap(args, config: dict) -> str:
    """Bootstrap a run: resume existing or create new. Returns run_id."""
    run_id = getattr(args, "run_id", None)

    if run_id:
        # Resume: state must exist
        state = _load_state(run_id)
        status = state.get("status", "")
        if status in ("completed", "failed"):
            print(
                json.dumps({"error": f"Run {run_id} is already {status}. Start a new run."}),
                file=sys.stderr,
            )
            sys.exit(1)
        return run_id

    # New run: use init logic
    task = getattr(args, "task", None) or ""
    if not task:
        task_file = getattr(args, "task_file", None)
        if task_file:
            task = Path(task_file).read_text().strip()
    if not task:
        msg = "No task provided. Use --task or --task-file."
        print(json.dumps({"error": msg}), file=sys.stderr)
        sys.exit(1)

    # Create a namespace-like object for cmd_init
    import argparse

    init_args = argparse.Namespace(
        task=task,
        profile=getattr(args, "profile", None),
        config=getattr(args, "config", None),
    )

    # Capture init output by redirecting stdout
    import io

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        cmd_init(init_args, config)
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    state = json.loads(output)
    return state["run_id"]


def _run_role(
    run_id: str,
    stage: str,
    role_name: str,
    config: dict,
    codex_bin: str,
    codex_args: list[str],
    output_dir: Path,
    events_file: Path,
) -> dict:
    """Dispatch a single role via codex exec. Returns exec result dict."""
    role_dir = output_dir / stage / role_name
    role_dir.mkdir(parents=True, exist_ok=True)

    # Build prompt
    prompt_data = build_prompt(run_id, stage, role_name, config)
    prompt_text = prompt_data.get("prompt", "")

    prompt_path = role_dir / "prompt.txt"
    prompt_build_path = role_dir / "prompt-build.json"
    stdout_path = role_dir / "stdout.txt"
    stderr_path = role_dir / "stderr.txt"
    exec_path = role_dir / "exec.json"

    # Write audit files
    prompt_path.write_text(prompt_text)
    prompt_build_path.write_text(json.dumps(prompt_data, indent=2))

    _emit_event(
        {"type": "role_started", "stage": stage, "role": role_name, "ts": _now_iso()},
        events_file,
    )
    append_event(run_id, "role_started", stage, {"role": role_name})

    start = time.time()
    cmd = [codex_bin, "exec", "--json", "--full-auto", *codex_args]

    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=600,  # 10 min default
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = "TIMEOUT: codex exec exceeded 600s"
    except FileNotFoundError:
        exit_code = -2
        stdout = ""
        stderr = f"codex binary not found: {codex_bin}"

    duration = round(time.time() - start, 1)

    # Write output files
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    exec_result = {
        "exit_code": exit_code,
        "duration_s": duration,
        "started_at": _now_iso(),
        "stage": stage,
        "role": role_name,
    }
    exec_path.write_text(json.dumps(exec_result, indent=2))
    _record_role_artifacts(
        run_id,
        stage,
        role_name,
        [prompt_path, prompt_build_path, stdout_path, stderr_path, exec_path],
    )

    _emit_event(
        {
            "type": "role_finished",
            "stage": stage,
            "role": role_name,
            "exit_code": exit_code,
            "duration_s": duration,
            "ts": _now_iso(),
        },
        events_file,
    )
    append_event(
        run_id,
        "role_finished",
        stage,
        {"role": role_name, "exit_code": exit_code, "duration_s": duration},
    )

    return exec_result


def _run_verify(run_id: str, stage: str, stage_config: dict, config: dict) -> dict:
    """Run stage verification. Returns command result details."""
    verify_cmd = stage_config.get("verify", "")
    if not verify_cmd:
        return {"passed": True, "command": "", "output": ""}

    try:
        proc = subprocess.run(  # noqa: S602
            verify_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=120,
        )
        output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
        return {
            "passed": proc.returncode == 0,
            "command": verify_cmd,
            "output": output,
            "exit_code": proc.returncode,
        }
    except (subprocess.TimeoutExpired, OSError):
        return {"passed": False, "command": verify_cmd, "output": "verify command failed to run"}


def _final_verify_commands(config: dict) -> tuple[list[str], str, int]:
    """Return final verify commands and policy."""
    commands = config.get("final_verify")
    policy = config.get("final_verify_policy", "block")
    max_retries = int(config.get("final_verify_max_retries", 1) or 0)
    if isinstance(commands, str):
        commands = [commands]
    if commands:
        return list(commands), policy, max_retries

    detected = detect_verify_command(str(Path.cwd()))
    if detected:
        return [detected], policy, max_retries
    return [], "unverified", max_retries


def _run_final_verify(run_id: str, config: dict, events_file: Path) -> bool:
    """Run final verification commands. Returns True when the run may complete."""
    commands, policy, max_retries = _final_verify_commands(config)
    if not commands:
        state = _load_state(run_id)
        state["final_verify_policy"] = policy
        state["final_verify_results"] = []
        _save_state(run_id, state)
        return True

    results: list[dict] = []
    all_passed = True
    for command in commands:
        command_passed = False
        for attempt in range(1, max_retries + 2):
            event = {
                "type": "final_verify_started",
                "run_id": run_id,
                "command": command,
                "attempt": attempt,
                "ts": _now_iso(),
            }
            _emit_event(event, events_file)
            append_event(
                run_id,
                "final_verify_started",
                None,
                {"command": command, "attempt": attempt},
            )

            try:
                proc = subprocess.run(  # noqa: S602
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=str(Path.cwd()),
                    timeout=120,
                )
                passed = proc.returncode == 0
                output = "\n".join(part for part in [proc.stdout, proc.stderr] if part)
                exit_code = proc.returncode
            except (subprocess.TimeoutExpired, OSError):
                passed = False
                output = "final verify command failed to run"
                exit_code = -1

            result = {
                "command": command,
                "attempt": attempt,
                "passed": passed,
                "exit_code": exit_code,
                "output": output,
            }
            results.append(result)

            result_text = "pass" if passed else "fail"
            _emit_event(
                {
                    "type": "final_verify_finished",
                    "run_id": run_id,
                    "command": command,
                    "attempt": attempt,
                    "result": result_text,
                    "ts": _now_iso(),
                },
                events_file,
            )
            append_event(
                run_id,
                "final_verify_finished",
                None,
                {
                    "command": command,
                    "attempt": attempt,
                    "result": result_text,
                    "exit_code": exit_code,
                },
            )

            if passed:
                command_passed = True
                break

        all_passed = all_passed and command_passed

    state = _load_state(run_id)
    state["final_verify_policy"] = policy
    state["final_verify_results"] = results
    state["final_verify_passed"] = all_passed
    _save_state(run_id, state)

    return all_passed or policy == "warn"


def cmd_run(args, config: dict) -> None:
    """Non-interactive pipeline runner."""
    codex_bin = getattr(args, "codex_bin", "codex") or "codex"
    codex_args_str = getattr(args, "codex_args", "") or ""
    codex_args = _parse_codex_args(codex_args_str)
    auto_approve = getattr(args, "auto_approve_gates", False)
    output_dir_arg = getattr(args, "output_dir", None)

    # Prerequisites
    _check_codex_binary(codex_bin)

    # Bootstrap
    run_id = _bootstrap(args, config)
    state = _load_state(run_id)

    # Output dir
    output_dir = _setup_output_dir(output_dir_arg, run_id)
    events_file = output_dir / "events.jsonl"

    if auto_approve:
        _emit_event(
            {
                "type": "warning",
                "message": "Auto-approve gates enabled. All human gates will be auto-approved.",
                "ts": _now_iso(),
            },
            events_file,
        )

    _emit_event(
        {
            "type": "run_started",
            "run_id": run_id,
            "task": state.get("task", ""),
            "profile": state.get("profile"),
            "ts": _now_iso(),
        },
        events_file,
    )

    # Stage loop
    stage_order = state.get("stage_order", list(state.get("stages", {}).keys()))
    stages_map = state.get("stages", {})
    run_status = "completed"

    try:
        for stage_name in stage_order:
            stage_state = stages_map.get(stage_name, {})
            status = stage_state.get("status", "pending")

            # Skip terminal stages (resume)
            if status in ("completed", "skipped"):
                continue

            if status == "gated":
                gate = stage_state.get("gate", "human")
                if auto_approve:
                    _record_gate(run_id, stage_name, gate, "approved")
                    transition(run_id, stage_name, "completed")
                    append_event(run_id, "stage_completed", stage_name, {"result": "passed"})
                    _emit_event(
                        {
                            "type": "gate_auto_approved",
                            "stage": stage_name,
                            "gate": gate,
                            "note": "auto-approved by --auto-approve-gates flag on resume",
                            "ts": _now_iso(),
                        },
                        events_file,
                    )
                    continue

                run_status = "blocked"
                print(
                    json.dumps(
                        {
                            "error": (
                                f"Human gate at stage '{stage_name}'. "
                                "Rerun with --auto-approve-gates for autonomous mode, "
                                "or use the interactive $ateam:run skill."
                            ),
                            "run_id": run_id,
                            "stage": stage_name,
                        }
                    ),
                    file=sys.stderr,
                )
                break

            stage_config = stage_state  # v2.4+ snapshots full config

            _emit_event(
                {
                    "type": "stage_started",
                    "stage": stage_name,
                    "roles": stage_config.get("roles", []),
                    "ts": _now_iso(),
                },
                events_file,
            )

            max_retries = int(stage_config.get("max_retries") or 0)
            verify_cmd = stage_config.get("verify", "")
            attempt = 0
            stage_passed = status == "passed"
            rework_used = False
            dispatch_roles = status not in ("verifying", "passed")

            if status == "pending":
                transition(run_id, stage_name, "dispatched")
                append_event(
                    run_id,
                    "stage_dispatched",
                    stage_name,
                    {"roles": stage_config.get("roles", []), "isolation": "runner"},
                )
            elif status in ("failed", "rework", "rejected"):
                transition(run_id, stage_name, "dispatched")
            elif status not in ("dispatched", "verifying", "passed"):
                print(
                    json.dumps(
                        {
                            "error": f"Cannot resume stage '{stage_name}' from status '{status}'",
                            "run_id": run_id,
                            "stage": stage_name,
                        }
                    ),
                    file=sys.stderr,
                )
                run_status = "failed"
                break

            while True:
                if stage_passed:
                    break

                attempt += 1
                role_failure = None

                # Dispatch each role
                if dispatch_roles:
                    for role_name in stage_config.get("roles", []):
                        result = _run_role(
                            run_id,
                            stage_name,
                            role_name,
                            config,
                            codex_bin,
                            codex_args,
                            output_dir,
                            events_file,
                        )
                        if result.get("exit_code") != 0:
                            role_failure = result
                            break

                if role_failure:
                    transition(run_id, stage_name, "failed")
                    run_status = "failed"
                    append_event(
                        run_id,
                        "stage_completed",
                        stage_name,
                        {
                            "result": "failed",
                            "reason": "role failed",
                            "role": role_failure.get("role"),
                            "exit_code": role_failure.get("exit_code"),
                        },
                    )
                    _emit_event(
                        {
                            "type": "stage_finished",
                            "stage": stage_name,
                            "result": "failed",
                            "reason": "role failed",
                            "role": role_failure.get("role"),
                            "exit_code": role_failure.get("exit_code"),
                            "ts": _now_iso(),
                        },
                        events_file,
                    )
                    break

                if verify_cmd:
                    current_stage_status = (
                        _load_state(run_id)
                        .get("stages", {})
                        .get(stage_name, {})
                        .get("status", "pending")
                    )
                    if current_stage_status != "verifying":
                        transition(run_id, stage_name, "verifying")
                    verify_result = _run_verify(run_id, stage_name, stage_config, config)
                    passed = bool(verify_result.get("passed"))
                    attempt_num = _record_verify_attempt(
                        run_id,
                        stage_name,
                        "pass" if passed else "fail",
                        verify_result.get("command", verify_cmd),
                        verify_result.get("output", ""),
                    )

                    _emit_event(
                        {
                            "type": "verify_finished",
                            "stage": stage_name,
                            "result": "pass" if passed else "fail",
                            "attempt": attempt_num,
                            "ts": _now_iso(),
                        },
                        events_file,
                    )

                    if passed:
                        transition(run_id, stage_name, "passed")
                        stage_passed = True
                        break

                    transition(run_id, stage_name, "failed")
                    if attempt <= max_retries:
                        append_event(
                            run_id,
                            "runner_retry",
                            stage_name,
                            {"attempt": attempt + 1, "max_retries": max_retries},
                        )
                        _emit_event(
                            {
                                "type": "runner_retry",
                                "stage": stage_name,
                                "attempt": attempt + 1,
                                "max_retries": max_retries,
                                "ts": _now_iso(),
                            },
                            events_file,
                        )
                        transition(run_id, stage_name, "dispatched")
                        dispatch_roles = True
                        continue

                    rework_to = stage_config.get("rework_to")
                    if rework_to and not rework_used:
                        rework_config = stages_map.get(rework_to, {})
                        rework_used = True
                        append_event(
                            run_id,
                            "runner_rework",
                            stage_name,
                            {"rework_to": rework_to, "roles": rework_config.get("roles", [])},
                        )
                        _emit_event(
                            {
                                "type": "runner_rework",
                                "stage": stage_name,
                                "rework_to": rework_to,
                                "roles": rework_config.get("roles", []),
                                "ts": _now_iso(),
                            },
                            events_file,
                        )
                        transition(run_id, stage_name, "rework")
                        rework_failure = None
                        for role_name in rework_config.get("roles", []):
                            result = _run_role(
                                run_id,
                                rework_to,
                                role_name,
                                config,
                                codex_bin,
                                codex_args,
                                output_dir,
                                events_file,
                            )
                            if result.get("exit_code") != 0:
                                rework_failure = result
                                break
                        transition(run_id, stage_name, "dispatched")
                        if rework_failure:
                            transition(run_id, stage_name, "failed")
                            run_status = "failed"
                            append_event(
                                run_id,
                                "stage_completed",
                                stage_name,
                                {
                                    "result": "failed",
                                    "reason": "rework role failed",
                                    "role": rework_failure.get("role"),
                                    "exit_code": rework_failure.get("exit_code"),
                                },
                            )
                            _emit_event(
                                {
                                    "type": "stage_finished",
                                    "stage": stage_name,
                                    "result": "failed",
                                    "reason": "rework role failed",
                                    "role": rework_failure.get("role"),
                                    "exit_code": rework_failure.get("exit_code"),
                                    "ts": _now_iso(),
                                },
                                events_file,
                            )
                            break
                        dispatch_roles = False
                        continue

                    run_status = "failed"
                    append_event(
                        run_id,
                        "stage_completed",
                        stage_name,
                        {"result": "failed", "reason": "verify failed"},
                    )
                    _emit_event(
                        {
                            "type": "stage_finished",
                            "stage": stage_name,
                            "result": "failed",
                            "reason": "verify failed",
                            "ts": _now_iso(),
                        },
                        events_file,
                    )
                    break

                # No verify — go to passed
                transition(run_id, stage_name, "passed")
                stage_passed = True
                break

            if not stage_passed:
                break

            # Gate check
            gate = stage_config.get("gate", "auto")
            if gate == "auto":
                _record_gate(run_id, stage_name, gate, "approved")
                transition(run_id, stage_name, "completed")
                _emit_event(
                    {
                        "type": "gate_auto_approved",
                        "stage": stage_name,
                        "gate": gate,
                        "ts": _now_iso(),
                    },
                    events_file,
                )
            elif gate in ("human", "reviewer", "qa"):
                if auto_approve:
                    _record_gate(run_id, stage_name, gate, "approved")
                    transition(run_id, stage_name, "completed")
                    _emit_event(
                        {
                            "type": "gate_auto_approved",
                            "stage": stage_name,
                            "gate": gate,
                            "note": "auto-approved by --auto-approve-gates flag",
                            "ts": _now_iso(),
                        },
                        events_file,
                    )
                else:
                    _record_gate(run_id, stage_name, gate, "blocked")
                    transition(run_id, stage_name, "gated")
                    _emit_event(
                        {
                            "type": "gate_blocked",
                            "stage": stage_name,
                            "gate": gate,
                            "ts": _now_iso(),
                        },
                        events_file,
                    )
                    run_status = "blocked"
                    print(
                        json.dumps(
                            {
                                "error": (
                                    f"Human gate at stage '{stage_name}'. "
                                    "Rerun with --auto-approve-gates for autonomous mode, "
                                    "or use the interactive $ateam:run skill."
                                ),
                                "run_id": run_id,
                                "stage": stage_name,
                            }
                        ),
                        file=sys.stderr,
                    )
                    break
            else:
                _record_gate(run_id, stage_name, gate, "approved")
                transition(run_id, stage_name, "completed")

            append_event(run_id, "stage_completed", stage_name, {"result": "passed"})

            _emit_event(
                {
                    "type": "stage_finished",
                    "stage": stage_name,
                    "result": "completed",
                    "ts": _now_iso(),
                },
                events_file,
            )

    except KeyboardInterrupt:
        run_status = "stopped"

    if run_status == "completed":
        final_verify_ok = _run_final_verify(run_id, config, events_file)
        if not final_verify_ok:
            run_status = "failed"

    _set_run_status(run_id, run_status)

    # Completion — persist history on BOTH success and failure
    try:
        _persist_history(run_id)
    except Exception:  # noqa: S110
        pass  # Best-effort history persistence

    append_event(run_id, "run_finished", None, {"status": run_status})

    _emit_event(
        {"type": "run_finished", "run_id": run_id, "status": run_status, "ts": _now_iso()},
        events_file,
    )

    # Write run.json summary
    run_summary = {
        "run_id": run_id,
        "task": state.get("task", ""),
        "profile": state.get("profile"),
        "status": run_status,
        "auto_approve_gates": auto_approve,
        "output_dir": str(output_dir),
    }
    (output_dir / "run.json").write_text(json.dumps(run_summary, indent=2))

    if run_status not in ("completed",):
        sys.exit(1)
