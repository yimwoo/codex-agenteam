"""Run report generation: assemble a JSON summary of a completed pipeline run."""

import json
import sys
from pathlib import Path


def cmd_run_report(args, config: dict) -> None:
    """Assemble a run report from state.

    Arguments: --run-id <id>
    Returns JSON with: run_id, task, status, started_at, completed_at, branch,
                       stages, final_verify_results, rollback_events, report_path
    """
    run_id = args.run_id

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

    report: dict = {
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

    print(json.dumps(report))
