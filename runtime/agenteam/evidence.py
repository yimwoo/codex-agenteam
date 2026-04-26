"""Portable run evidence derived from trace and event summaries."""

import json
from datetime import datetime, timezone
from pathlib import Path

from .events import list_events
from .trace import build_trace

SCHEMA_VERSION = "1"
KIND = "agenteam.run_evidence"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _role_exits(events: list[dict]) -> list[dict]:
    exits = []
    for event in events:
        if event.get("type") != "role_finished":
            continue
        data = event.get("data", {})
        exits.append(
            {
                "stage": event.get("stage"),
                "role": data.get("role"),
                "exit_code": data.get("exit_code"),
                "duration_s": data.get("duration_s"),
                "ts": event.get("ts"),
            }
        )
    return exits


def _stage_evidence(stage: dict) -> dict:
    entry: dict = {
        "name": stage.get("name"),
        "status": stage.get("status", "unknown"),
        "roles": stage.get("roles", []),
    }
    for field in (
        "owner_role",
        "started_at",
        "completed_at",
        "elapsed",
        "verify",
        "retry_budget",
        "rework_to",
        "gate",
        "failure",
        "artifacts",
    ):
        if field in stage:
            entry[field] = stage[field]
    return entry


def _find_stage(trace: dict, name: str | None) -> dict | None:
    if not name:
        return None
    for stage in trace.get("stages", []):
        if stage.get("name") == name:
            return stage
    return None


def _first_failed_stage(trace: dict) -> dict | None:
    for stage in trace.get("stages", []):
        if stage.get("failure"):
            return stage
    for stage in trace.get("stages", []):
        if stage.get("status") == "failed":
            return stage
    return None


def _first_blocked_stage(trace: dict) -> dict | None:
    for stage in trace.get("stages", []):
        gate = stage.get("gate")
        if isinstance(gate, dict) and gate.get("result") == "blocked":
            return stage
    return None


def _outcome_from_trace(trace: dict) -> dict:
    status = trace.get("status", "unknown")
    next_action = trace.get("next_action")
    final_verify = trace.get("final_verify")
    if isinstance(final_verify, dict) and final_verify.get("passed") is False:
        return {
            "result": status,
            "determined_by": "final_verify",
            "stage": None,
            "reason": "final verification failed",
            "role": None,
            "exit_code": None,
            "next_action": next_action,
        }

    failed_stage = _first_failed_stage(trace)
    if failed_stage:
        failure = failed_stage.get("failure", {})
        return {
            "result": status,
            "determined_by": "stage",
            "stage": failed_stage.get("name"),
            "reason": failure.get("reason", "stage failed"),
            "role": failure.get("role"),
            "exit_code": failure.get("exit_code"),
            "next_action": next_action,
        }

    blocked_stage = _first_blocked_stage(trace)
    if blocked_stage:
        return {
            "result": status,
            "determined_by": "stage",
            "stage": blocked_stage.get("name"),
            "reason": "gate blocked",
            "role": blocked_stage.get("owner_role"),
            "exit_code": None,
            "next_action": next_action,
        }

    current_stage = _find_stage(trace, trace.get("current_stage"))
    if status in ("stopped", "running") and current_stage:
        reason = "run stopped" if status == "stopped" else "run running"
        if trace.get("stale", {}).get("is_stale"):
            reason = "run stale"
        return {
            "result": status,
            "determined_by": "stage",
            "stage": current_stage.get("name"),
            "reason": reason,
            "role": current_stage.get("owner_role"),
            "exit_code": None,
            "next_action": next_action,
        }

    reason = "run completed" if status == "completed" else "unknown"
    return {
        "result": status,
        "determined_by": "run",
        "stage": None,
        "reason": reason,
        "role": None,
        "exit_code": None,
        "next_action": next_action,
    }


def _metrics_from_trace(trace: dict, events: list[dict], role_exits: list[dict]) -> dict:
    stages = trace.get("stages", [])
    completed = failed = blocked = skipped = 0
    verify_attempt_count = 0
    retry_count = 0
    gate_block_count = 0
    artifact_count = 0

    for stage in stages:
        status = stage.get("status")
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
        elif status == "gated":
            blocked += 1
        elif status == "skipped":
            skipped += 1

        verify = stage.get("verify")
        if isinstance(verify, dict):
            verify_attempt_count += int(verify.get("attempts") or 0)

        retry_budget = stage.get("retry_budget")
        if isinstance(retry_budget, dict):
            retry_count += int(retry_budget.get("used") or 0)

        gate = stage.get("gate")
        if isinstance(gate, dict) and gate.get("result") == "blocked":
            gate_block_count += 1

        artifacts = stage.get("artifacts")
        if isinstance(artifacts, list):
            artifact_count += len(artifacts)

    return {
        "stage_count": len(stages),
        "completed_stage_count": completed,
        "failed_stage_count": failed,
        "blocked_stage_count": blocked,
        "skipped_stage_count": skipped,
        "role_attempt_count": len(role_exits),
        "role_failure_count": sum(
            1
            for role_exit in role_exits
            if isinstance(role_exit.get("exit_code"), int) and role_exit["exit_code"] != 0
        ),
        "verify_attempt_count": verify_attempt_count,
        "retry_count": retry_count,
        "rework_count": sum(1 for event in events if event.get("type") == "runner_rework"),
        "gate_block_count": gate_block_count,
        "artifact_count": artifact_count,
    }


def _final_verify_from_trace(trace: dict) -> dict:
    final_verify = trace.get("final_verify")
    if not isinstance(final_verify, dict):
        return {"configured": False, "passed": None, "policy": None, "attempts": 0}
    attempts = int(final_verify.get("attempts") or 0)
    policy = final_verify.get("policy")
    configured = attempts > 0 or policy in ("block", "warn")
    return {
        "configured": configured,
        "passed": final_verify.get("passed"),
        "policy": policy,
        "attempts": attempts,
        **(
            {"last_result": final_verify["last_result"]}
            if isinstance(final_verify.get("last_result"), dict)
            else {}
        ),
    }


def build_evidence(run_id: str, config: dict, stale_threshold_minutes: int = 60) -> dict:
    """Build a portable evidence bundle for release, CI, and benchmark consumers."""
    trace = build_trace(run_id, config, stale_threshold_minutes=stale_threshold_minutes)
    events = list_events(run_id)
    role_exits = _role_exits(events)
    artifact_paths = sorted(
        {artifact for stage in trace.get("stages", []) for artifact in stage.get("artifacts", [])}
    )

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": _now_iso(),
        "run": {
            "run_id": trace.get("run_id"),
            "task": trace.get("task", ""),
            "profile": trace.get("profile"),
            "pipeline_mode": trace.get("pipeline_mode"),
            "status": trace.get("status", "unknown"),
            "health": trace.get("health", "unknown"),
            "started_at": trace.get("started_at"),
            "last_update": trace.get("last_update"),
            "elapsed": trace.get("elapsed", ""),
            "current_stage": trace.get("current_stage"),
        },
        "outcome": _outcome_from_trace(trace),
        "metrics": _metrics_from_trace(trace, events, role_exits),
        "stages": [_stage_evidence(stage) for stage in trace.get("stages", [])],
        "role_exits": role_exits,
        "final_verify": _final_verify_from_trace(trace),
        "stale": trace.get("stale"),
        "events": {
            "last_type": (trace.get("events", {}).get("last") or {}).get("type"),
            "counts": trace.get("events", {}).get("counts", {}),
        },
        "artifacts": {
            "root": f".agenteam/runs/{trace.get('run_id')}",
            "paths": artifact_paths,
        },
    }
    if isinstance(trace.get("governance"), dict):
        evidence["governance"] = trace["governance"]
    return evidence


def cmd_evidence(args, config: dict) -> None:
    """CLI handler for agenteam-rt evidence."""
    threshold = getattr(args, "stale_threshold_minutes", None)
    if threshold is None:
        threshold = 60
    evidence = build_evidence(args.run_id, config, stale_threshold_minutes=threshold)
    rendered = json.dumps(evidence, indent=2)

    output = getattr(args, "output", None)
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n")

    print(rendered)
