"""Run trace views for visible run control."""

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .config import resolve_team_config
from .events import list_events


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _format_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed(start_iso: str | None, end_iso: str | None = None) -> str:
    start = _parse_iso(start_iso)
    if not start:
        return ""
    end = _parse_iso(end_iso) or datetime.now(timezone.utc)
    delta = int((end - start).total_seconds())
    minutes, seconds = divmod(max(delta, 0), 60)
    return f"{minutes}m {seconds:02d}s"


def _load_state(run_id: str) -> dict:
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(json.dumps({"error": f"Run {run_id} not found"}), file=sys.stderr)
        sys.exit(1)
    with open(state_path) as f:
        return json.load(f)


def _event_counts(events: list[dict]) -> dict:
    return dict(Counter(event.get("type", "unknown") for event in events))


def _last_stage_event(events: list[dict], stage: str, event_type: str | None = None) -> dict | None:
    for event in reversed(events):
        if event.get("stage") != stage:
            continue
        if event_type and event.get("type") != event_type:
            continue
        return event
    return None


def _artifact_paths(run_id: str, stage_name: str, stage_state: dict) -> list[str]:
    artifacts: list[str] = []
    recorded = stage_state.get("role_artifacts", {})
    if isinstance(recorded, dict):
        for role_paths in recorded.values():
            if isinstance(role_paths, list):
                artifacts.extend(str(path) for path in role_paths)

    if artifacts:
        return sorted(dict.fromkeys(artifacts))

    run_dir = Path.cwd() / ".agenteam" / "runs" / run_id / stage_name
    if not run_dir.exists():
        return []
    for path in sorted(run_dir.glob("*/*")):
        if path.is_file():
            artifacts.append(str(path.relative_to(Path.cwd())))
    return artifacts


def _retry_budget(stage_state: dict) -> dict:
    attempts = stage_state.get("verify_attempts", [])
    used = max(len(attempts) - 1, 0)
    max_retries = int(stage_state.get("max_retries") or 0)
    return {
        "used": used,
        "max": max_retries,
        "remaining": max(max_retries - used, 0),
    }


def _verify_summary(stage_state: dict) -> dict | None:
    attempts = stage_state.get("verify_attempts", [])
    if not attempts and not stage_state.get("verify"):
        return None

    result: dict = {
        "command": stage_state.get("verify"),
        "result": stage_state.get("verify_result"),
        "attempts": len(attempts),
    }
    if attempts:
        last = attempts[-1]
        result["last_attempt"] = last.get("attempt")
        output = str(last.get("output", ""))
        if output:
            result["last_output_excerpt"] = output[:500]
    return result


def _gate_summary(stage_state: dict) -> dict | None:
    if not stage_state.get("gate") and not stage_state.get("gate_result"):
        return None
    result = {
        "type": stage_state.get("gate", "auto"),
        "result": stage_state.get("gate_result"),
    }
    if stage_state.get("gate_agent"):
        result["agent"] = stage_state["gate_agent"]
    if stage_state.get("gate_verdict"):
        result["verdict"] = stage_state["gate_verdict"]
    return result


def _failure_summary(stage_name: str, stage_state: dict, events: list[dict]) -> dict | None:
    if stage_state.get("status") != "failed":
        return None

    completed = _last_stage_event(events, stage_name, "stage_completed")
    if completed:
        data = completed.get("data", {})
        if data.get("result") == "failed":
            failure = {"reason": data.get("reason", "stage failed")}
            if data.get("role"):
                failure["role"] = data["role"]
            if "exit_code" in data:
                failure["exit_code"] = data["exit_code"]
            return failure

    verify = stage_state.get("verify_result")
    if verify == "fail":
        return {"reason": "verify failed"}
    return {"reason": "stage failed"} if stage_state.get("status") == "failed" else None


def _final_verify_summary(state: dict) -> dict | None:
    results = state.get("final_verify_results", [])
    passed = state.get("final_verify_passed")
    policy = state.get("final_verify_policy")
    if passed is None and not results and not policy:
        return None

    summary: dict = {
        "passed": passed,
        "policy": policy,
        "attempts": len(results) if isinstance(results, list) else 0,
    }
    if passed is None and isinstance(results, list) and results:
        summary["passed"] = all(bool(result.get("passed")) for result in results)

    if isinstance(results, list) and results:
        last = results[-1]
        last_result = {
            "command": last.get("command"),
            "attempt": last.get("attempt"),
            "passed": last.get("passed"),
            "exit_code": last.get("exit_code"),
        }
        output = str(last.get("output", ""))
        if output:
            last_result["output_excerpt"] = output[:500]
        summary["last_result"] = last_result

    return summary


def _stage_next_action(run_id: str, stage_name: str, stage_state: dict) -> dict | None:
    status = stage_state.get("status", "pending")
    if status == "gated":
        return {
            "kind": "approve_gate",
            "command": f"agenteam-rt run --run-id {run_id} --auto-approve-gates",
            "reason": f"{stage_name} gate is blocked",
        }
    if status == "failed":
        return {
            "kind": "inspect_failure",
            "command": f"agenteam-rt trace --run-id {run_id}",
            "reason": f"{stage_name} failed",
        }
    if status in ("pending", "dispatched", "verifying", "passed", "rework", "rejected"):
        return {
            "kind": "resume",
            "command": f"agenteam-rt run --run-id {run_id}",
            "reason": f"{stage_name} is resumable",
        }
    return None


def _stage_trace(run_id: str, stage_name: str, stage_state: dict, events: list[dict]) -> dict:
    entry: dict = {
        "name": stage_name,
        "status": stage_state.get("status", "pending"),
        "roles": stage_state.get("roles", []),
    }
    roles = entry["roles"]
    if isinstance(roles, list) and len(roles) == 1:
        entry["owner_role"] = roles[0]

    if stage_state.get("started_at"):
        entry["started_at"] = stage_state["started_at"]
        entry["elapsed"] = _elapsed(stage_state.get("started_at"), stage_state.get("completed_at"))
    if stage_state.get("completed_at"):
        entry["completed_at"] = stage_state["completed_at"]

    verify = _verify_summary(stage_state)
    if verify:
        entry["verify"] = verify
        entry["retry_budget"] = _retry_budget(stage_state)

    if stage_state.get("rework_to"):
        entry["rework_to"] = stage_state["rework_to"]

    gate = _gate_summary(stage_state)
    if gate:
        entry["gate"] = gate

    failure = _failure_summary(stage_name, stage_state, events)
    if failure:
        entry["failure"] = failure

    artifacts = _artifact_paths(run_id, stage_name, stage_state)
    if artifacts:
        entry["artifacts"] = artifacts

    next_action = _stage_next_action(run_id, stage_name, stage_state)
    if next_action:
        entry["next_action"] = next_action

    return entry


def _stale_summary(state: dict, events: list[dict], threshold_minutes: int) -> dict:
    status = state.get("status", "unknown")
    state_last_update = _parse_iso(state.get("last_update"))
    event_last_update = _parse_iso(events[-1].get("ts")) if events else None
    last_update = max(
        [value for value in (state_last_update, event_last_update) if value is not None],
        default=None,
    )
    now = datetime.now(timezone.utc)
    is_stale = False
    reason = ""

    if status in ("running", "blocked", "stopped") and last_update:
        age_minutes = int((now - last_update).total_seconds() // 60)
        if age_minutes >= threshold_minutes:
            is_stale = True
            reason = "last update older than threshold"
    else:
        age_minutes = None

    last_event = events[-1] if events else None
    return {
        "is_stale": is_stale,
        "threshold_minutes": threshold_minutes,
        "age_minutes": age_minutes,
        "reason": reason,
        "last_update": _format_iso(last_update),
        "state_last_update": _format_iso(state_last_update),
        "event_last_update": _format_iso(event_last_update),
        "last_event_type": last_event.get("type") if last_event else None,
    }


def _health(state: dict, stale: dict) -> str:
    status = state.get("status", "unknown")
    if status == "failed":
        return "off-track"
    if status in ("blocked", "stopped") or stale.get("is_stale"):
        return "at-risk"
    if status in ("completed", "running"):
        return "on-track"
    return "unknown"


def _next_action(
    run_id: str,
    state: dict,
    stage_entries: list[dict],
    stale: dict,
    final_verify: dict | None,
) -> dict:
    status = state.get("status", "unknown")
    if status == "completed":
        return {"kind": "none", "command": None, "reason": "run completed"}

    for stage in stage_entries:
        if stage.get("next_action"):
            action = dict(stage["next_action"])
            if stale.get("is_stale") and action.get("kind") == "resume":
                action["reason"] = "run is stale; resume to continue or inspect trace first"
            return action

    if status in ("running", "stopped") or stale.get("is_stale"):
        return {
            "kind": "resume",
            "command": f"agenteam-rt run --run-id {run_id}",
            "reason": "run is resumable",
        }
    if status == "failed":
        if final_verify and final_verify.get("passed") is False:
            return {
                "kind": "inspect_failure",
                "command": f"agenteam-rt trace --run-id {run_id}",
                "reason": "final verification failed",
            }
        return {
            "kind": "inspect_failure",
            "command": f"agenteam-rt trace --run-id {run_id}",
            "reason": "run failed",
        }
    return {"kind": "none", "command": None, "reason": "no action available"}


def _write_policy(config: dict, state: dict) -> dict:
    _, isolation = resolve_team_config(config)
    return {
        "isolation": isolation,
        "active_lock": state.get("write_locks", {}).get("active"),
        "queued_locks": state.get("write_locks", {}).get("queue", []),
    }


def build_trace(run_id: str, config: dict, stale_threshold_minutes: int = 60) -> dict:
    """Build a diagnostic trace for a run."""
    state = _load_state(run_id)
    events = list_events(run_id)
    stage_order = state.get("stage_order", list(state.get("stages", {}).keys()))
    stages_map = state.get("stages", {})
    stages = [
        _stage_trace(run_id, name, stages_map.get(name, {}), events)
        for name in stage_order
        if name in stages_map
    ]
    stale = _stale_summary(state, events, stale_threshold_minutes)
    final_verify = _final_verify_summary(state)
    trace = {
        "run_id": run_id,
        "task": state.get("task", ""),
        "profile": state.get("profile"),
        "status": state.get("status", "unknown"),
        "health": _health(state, stale),
        "started_at": state.get("started_at"),
        "last_update": state.get("last_update"),
        "elapsed": _elapsed(state.get("started_at")),
        "current_stage": state.get("current_stage"),
        "stale": stale,
        "write_policy": _write_policy(config, state),
        "stages": stages,
        "events": {
            "last": events[-1] if events else None,
            "counts": _event_counts(events),
        },
    }
    if final_verify:
        trace["final_verify"] = final_verify
    trace["next_action"] = _next_action(run_id, state, stages, stale, final_verify)

    governance = state.get("governance")
    if isinstance(governance, dict):
        trace["governance"] = governance
    return trace


def build_progress_from_trace(trace: dict) -> dict:
    """Build the compact status --progress view from a full trace."""
    current_stage_name = trace.get("current_stage")
    current_stage = None
    for stage in trace.get("stages", []):
        if stage.get("name") == current_stage_name:
            current_stage = {
                "name": stage.get("name"),
                "status": stage.get("status"),
            }
            for field in (
                "elapsed",
                "owner_role",
                "verify",
                "retry_budget",
                "gate",
                "failure",
                "next_action",
            ):
                if field in stage:
                    current_stage[field] = stage[field]
            if "verify" in stage:
                current_stage["verify_attempt"] = stage["verify"].get("attempts")
            if "retry_budget" in stage:
                current_stage["max_retries"] = stage["retry_budget"].get("max")
            break

    return {
        "run_id": trace.get("run_id"),
        "task": trace.get("task", ""),
        "profile": trace.get("profile"),
        "status": trace.get("status", "unknown"),
        "health": trace.get("health", "unknown"),
        "elapsed": trace.get("elapsed", ""),
        "current_stage": current_stage,
        "stages": [
            {
                key: value
                for key, value in {
                    "name": stage.get("name"),
                    "status": stage.get("status"),
                    "elapsed": stage.get("elapsed"),
                }.items()
                if value is not None
            }
            for stage in trace.get("stages", [])
        ],
        "active_lock": trace.get("write_policy", {}).get("active_lock"),
        "stale": trace.get("stale"),
        **({"final_verify": trace["final_verify"]} if "final_verify" in trace else {}),
        "next_action": trace.get("next_action"),
        "last_event": trace.get("events", {}).get("last"),
        **({"governance": trace["governance"]} if "governance" in trace else {}),
    }


def cmd_trace(args, config: dict) -> None:
    """CLI handler for agenteam-rt trace."""
    threshold = getattr(args, "stale_threshold_minutes", None)
    if threshold is None:
        threshold = 60
    trace = build_trace(args.run_id, config, stale_threshold_minutes=threshold)
    print(json.dumps(trace, indent=2))
