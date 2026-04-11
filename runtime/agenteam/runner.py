"""Non-interactive pipeline runner: drives the full pipeline via codex exec."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .events import append_event
from .prompt import build_prompt
from .report import cmd_history_append
from .state import (
    cmd_init,
)
from .transitions import transition


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


def _load_state(run_id: str) -> dict:
    """Load run state."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(json.dumps({"error": f"Run state not found: {run_id}"}), file=sys.stderr)
        sys.exit(1)
    with open(state_path) as f:
        return json.load(f)


def _bootstrap(args, config: dict) -> str:
    """Bootstrap a run: resume existing or create new. Returns run_id."""
    run_id = getattr(args, "run_id", None)

    if run_id:
        # Resume: state must exist
        state = _load_state(run_id)
        status = state.get("status", "")
        if status in ("completed", "failed", "stopped"):
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

    # Write audit files
    (role_dir / "prompt.txt").write_text(prompt_text)
    (role_dir / "prompt-build.json").write_text(json.dumps(prompt_data, indent=2))

    _emit_event(
        {"type": "role_started", "stage": stage, "role": role_name, "ts": _now_iso()},
        events_file,
    )

    start = time.time()
    cmd = [codex_bin, "exec", "--json", "--full-auto", "-"] + codex_args

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
    (role_dir / "stdout.txt").write_text(stdout)
    (role_dir / "stderr.txt").write_text(stderr)

    exec_result = {
        "exit_code": exit_code,
        "duration_s": duration,
        "started_at": _now_iso(),
        "stage": stage,
        "role": role_name,
    }
    (role_dir / "exec.json").write_text(json.dumps(exec_result, indent=2))

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

    return exec_result


def _run_verify(run_id: str, stage: str, stage_config: dict, config: dict) -> bool:
    """Run stage verification. Returns True if passed."""
    verify_cmd = stage_config.get("verify", "")
    if not verify_cmd:
        return True

    try:
        proc = subprocess.run(  # noqa: S602
            verify_cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=120,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def cmd_run(args, config: dict) -> None:
    """Non-interactive pipeline runner."""
    codex_bin = getattr(args, "codex_bin", "codex") or "codex"
    codex_args_str = getattr(args, "codex_args", "") or ""
    codex_args = codex_args_str.split() if codex_args_str else []
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

            # Transition to dispatched
            transition(run_id, stage_name, "dispatched")
            append_event(
                run_id,
                "stage_dispatched",
                stage_name,
                {"roles": stage_config.get("roles", []), "isolation": "runner"},
            )

            # Dispatch each role
            for role_name in stage_config.get("roles", []):
                _run_role(
                    run_id,
                    stage_name,
                    role_name,
                    config,
                    codex_bin,
                    codex_args,
                    output_dir,
                    events_file,
                )

            # Verify
            verify_cmd = stage_config.get("verify", "")
            if verify_cmd:
                transition(run_id, stage_name, "verifying")
                passed = _run_verify(run_id, stage_name, stage_config, config)

                _emit_event(
                    {
                        "type": "verify_finished",
                        "stage": stage_name,
                        "result": "pass" if passed else "fail",
                        "ts": _now_iso(),
                    },
                    events_file,
                )

                if passed:
                    transition(run_id, stage_name, "passed")
                else:
                    transition(run_id, stage_name, "failed")
                    # TODO: retry / rework logic for v3.3.1
                    run_status = "failed"
                    append_event(
                        run_id,
                        "stage_completed",
                        stage_name,
                        {"result": "failed", "reason": "verify failed"},
                    )
                    break
            else:
                # No verify — go to passed
                transition(run_id, stage_name, "passed")

            # Gate check
            gate = stage_config.get("gate", "auto")
            if gate == "auto":
                transition(run_id, stage_name, "completed")
                _emit_event(
                    {"type": "gate_auto_approved", "stage": stage_name, "ts": _now_iso()},
                    events_file,
                )
            elif gate in ("human", "reviewer", "qa"):
                if auto_approve:
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

    # Completion — persist history on BOTH success and failure
    try:
        import argparse

        history_args = argparse.Namespace(run_id=run_id)
        cmd_history_append(history_args)
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
