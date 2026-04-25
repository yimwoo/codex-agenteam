"""Run report generation: assemble a JSON summary of a completed pipeline run."""

import json
import sys
from pathlib import Path


def _build_run_summary(run_id: str) -> dict:
    """Build a structured run summary from state. Returns the summary dict.

    This is the core logic extracted from cmd_run_report, reused by
    history append.
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

    # Assemble per-stage summaries
    stages_summary = []
    for stage_name, stage_state in state.get("stages", {}).items():
        stage_entry: dict = {
            "name": stage_name,
            "status": stage_state.get("status", "unknown"),
        }

        # Verify info
        verify_attempts = stage_state.get("verify_attempts", [])
        if verify_attempts:
            verify_result = stage_state.get("verify_result", "unknown")
            stage_entry["verify"] = {
                "result": verify_result,
                "attempts": len(verify_attempts),
                "details": verify_attempts,
            }

        # Gate info
        gate_result = stage_state.get("gate_result")
        if gate_result:
            gate_info: dict = {
                "type": stage_state.get("gate", "auto"),
                "result": gate_result,
            }
            if stage_state.get("gate_verdict"):
                gate_info["verdict"] = stage_state["gate_verdict"]
            # Criteria override details
            if stage_state.get("gate_type") == "criteria_override":
                gate_info["gate_type"] = "criteria_override"
                if stage_state.get("criteria_failed"):
                    gate_info["criteria_failed"] = stage_state["criteria_failed"]
                if stage_state.get("criteria_details"):
                    gate_info["criteria_details"] = stage_state["criteria_details"]
                if stage_state.get("override_reason"):
                    gate_info["override_reason"] = stage_state["override_reason"]
            stage_entry["gate"] = gate_info

        # Duration (if both timestamps present)
        started = stage_state.get("started_at")
        completed = stage_state.get("completed_at")
        if started and completed:
            stage_entry["started_at"] = started
            stage_entry["completed_at"] = completed

        # Baseline
        baseline = stage_state.get("baseline")
        if baseline:
            stage_entry["baseline"] = baseline

        # Skip info
        skip_reason = stage_state.get("skip_reason")
        if skip_reason:
            stage_entry["skip_reason"] = skip_reason
        skipped_at = stage_state.get("skipped_at")
        if skipped_at:
            stage_entry["skipped_at"] = skipped_at

        stages_summary.append(stage_entry)

    # Rework history: extract from verify_attempts across all stages
    rework_history = []
    for stage_name, stage_state in state.get("stages", {}).items():
        for attempt in stage_state.get("verify_attempts", []):
            if attempt.get("rework_stage"):
                rework_history.append(
                    {
                        "stage": stage_name,
                        "attempt": attempt["attempt"],
                        "result": attempt["result"],
                        "rework_stage": attempt["rework_stage"],
                    }
                )

    report_path = f".agenteam/reports/{run_id}.md"

    return {
        "run_id": run_id,
        "task": state.get("task", ""),
        "status": state.get("status", "unknown"),
        "started_at": state.get("started_at"),
        "completed_at": state.get("completed_at"),
        "branch": state.get("branch"),
        "stages": stages_summary,
        "final_verify_results": state.get("final_verify_results", []),
        "rollback_events": state.get("rollback_events", []),
        "rework_history": rework_history,
        "report_path": report_path,
    }


def _extract_lessons(run_id: str, summary: dict, state: dict) -> dict:
    """Extract factual lessons from a run summary and state.

    Returns a compact lessons dict with verify failures, rework edges,
    gate rejections/overrides, and run metadata.
    """
    # Verify failures: stages where verify failed at least once
    verify_failures = []
    for stage in summary.get("stages", []):
        verify = stage.get("verify")
        if verify and (verify.get("attempts", 1) > 1 or verify.get("result") == "fail"):
            verify_failures.append(
                {
                    "stage": stage["name"],
                    "attempts": verify.get("attempts", 1),
                    "final_result": verify.get("result", "unknown"),
                }
            )

    # Rework edges: from the run summary's rework_history
    rework_edges = []
    for entry in summary.get("rework_history", []):
        edge = {
            "from_stage": entry.get("stage", ""),
            "to_stage": entry.get("rework_stage", ""),
        }
        if edge not in rework_edges:
            rework_edges.append(edge)

    # Gate rejections: from state stages where gate_result == "rejected"
    gate_rejections = []
    for stage_name, stage_state in state.get("stages", {}).items():
        if stage_state.get("gate_result") == "rejected":
            gate_rejections.append(
                {
                    "stage": stage_name,
                    "gate_type": stage_state.get("gate", "unknown"),
                }
            )

    # Gate overrides: from state stages where gate_type == "criteria_override"
    gate_overrides = []
    for stage_name, stage_state in state.get("stages", {}).items():
        if stage_state.get("gate_type") == "criteria_override":
            gate_overrides.append(
                {
                    "stage": stage_name,
                    "criteria_failed": stage_state.get("criteria_failed", []),
                    "override_reason": stage_state.get("override_reason", ""),
                }
            )

    # Final verify: check if all passed
    final_results = state.get("final_verify_results", [])
    final_verify_passed = state.get("final_verify_passed")
    if final_verify_passed is None and final_results:
        final_verify_passed = all(
            r.get("passed") is True or r.get("result") == "pass" for r in final_results
        )
    if final_verify_passed is None:
        final_verify_passed = True

    # Stage counts
    stages = state.get("stages", {})
    total_stages = len(stages)
    completed_stages = sum(1 for s in stages.values() if s.get("status") == "completed")

    # Skipped stages
    skipped_stages = []
    for stage_name, stage_state in stages.items():
        if stage_state.get("status") == "skipped":
            skipped_stages.append(
                {
                    "stage": stage_name,
                    "reason": stage_state.get("skip_reason", ""),
                }
            )

    return {
        "verify_failures": verify_failures,
        "rework_edges": rework_edges,
        "gate_rejections": gate_rejections,
        "gate_overrides": gate_overrides,
        "skipped_stages": skipped_stages,
        "final_verify_passed": final_verify_passed,
        "total_stages": total_stages,
        "completed_stages": completed_stages,
        "profile_used": state.get("profile"),
    }


def cmd_history_append(args) -> None:
    """Persist run summary + lessons to .agenteam/history/.

    Arguments: --run-id <id>
    No config needed.
    """
    run_id = args.run_id

    # Build summary
    summary = _build_run_summary(run_id)

    # Load state for lessons extraction
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    with open(state_path) as f:
        state = json.load(f)

    # Add profile from state
    summary["profile"] = state.get("profile")

    # Extract and attach lessons
    summary["lessons"] = _extract_lessons(run_id, summary, state)

    # Write to history
    history_dir = Path.cwd() / ".agenteam" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{run_id}.json"
    with open(history_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary))


def cmd_history_list(args) -> None:
    """List recent history entries in reverse chronological order.

    Arguments: [--last N]
    No config needed.
    """
    last_n = getattr(args, "last", None) or 10

    history_dir = Path.cwd() / ".agenteam" / "history"
    if not history_dir.exists():
        print(json.dumps([]))
        return

    files = sorted(history_dir.glob("*.json"), reverse=True)
    entries = []
    for f in files[:last_n]:
        try:
            with open(f) as fh:
                entries.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue

    print(json.dumps(entries))


def cmd_run_report(args, config: dict) -> None:
    """Assemble a run report from state.

    Arguments: --run-id <id>
    Returns JSON with: run_id, task, status, started_at, completed_at, branch,
                       stages, final_verify_results, rollback_events, report_path
    """
    report = _build_run_summary(args.run_id)
    print(json.dumps(report))
