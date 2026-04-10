"""Visible carry-forward memory derived from compatible run history."""

import json
from pathlib import Path

from .roles import resolve_roles
from .state import is_discoverable_state


def _load_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            result: dict = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return result


def _state_is_compatible(state: dict, known_roles: set[str]) -> bool:
    if not is_discoverable_state(state):
        return False

    stages = state.get("stages", {})
    if not isinstance(stages, dict):
        return False

    for stage_state in stages.values():
        if not isinstance(stage_state, dict):
            continue
        roles = stage_state.get("roles", [])
        if not isinstance(roles, list):
            continue
        for role_name in roles:
            if isinstance(role_name, str) and role_name not in known_roles:
                return False
    return True


def _compatible_history_entries(config: dict, current_run_id: str | None = None) -> list[dict]:
    history_dir = Path.cwd() / ".agenteam" / "history"
    if not history_dir.exists():
        return []

    known_roles = set(resolve_roles(config).keys())
    entries: list[dict] = []

    for path in sorted(history_dir.glob("*.json"), reverse=True):
        entry = _load_json(path)
        if entry is None:
            continue

        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id == current_run_id:
            continue

        state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
        state = _load_json(state_path)
        if state is None or not _state_is_compatible(state, known_roles):
            continue

        entries.append(entry)

    return entries


def _verify_failure_item(entry: dict, lesson: dict) -> dict:
    stage = lesson.get("stage", "unknown")
    attempts = lesson.get("attempts", 1)
    final_result = lesson.get("final_result", "unknown")
    if final_result == "pass":
        summary = f"Stage '{stage}' needed {attempts} verify attempts before passing."
        relevance = "Watch verification coverage and edge cases in this stage."
    else:
        summary = (
            f"Stage '{stage}' ended with verify result '{final_result}' after {attempts} attempts."
        )
        relevance = "This stage previously failed verification and may need extra attention."
    return {
        "type": "verify_failure",
        "summary": summary,
        "source_run_id": entry["run_id"],
        "stage": stage,
        "task": entry.get("task"),
        "relevance": relevance,
    }


def _rework_edge_item(entry: dict, lesson: dict) -> dict:
    from_stage = lesson.get("from_stage", "unknown")
    to_stage = lesson.get("to_stage", "unknown")
    return {
        "type": "rework_edge",
        "summary": f"Work previously looped from '{from_stage}' back to '{to_stage}'.",
        "source_run_id": entry["run_id"],
        "stage": from_stage,
        "task": entry.get("task"),
        "relevance": (
            "This path previously needed rework, so similar changes may hide follow-up fixes."
        ),
    }


def _gate_rejection_item(entry: dict, lesson: dict) -> dict:
    stage = lesson.get("stage", "unknown")
    gate_type = lesson.get("gate_type", "unknown")
    return {
        "type": "gate_rejection",
        "summary": f"Stage '{stage}' previously hit a rejected '{gate_type}' gate.",
        "source_run_id": entry["run_id"],
        "stage": stage,
        "task": entry.get("task"),
        "relevance": "Expect extra scrutiny or missing evidence around this stage.",
    }


def _gate_override_item(entry: dict, lesson: dict) -> dict:
    stage = lesson.get("stage", "unknown")
    override_reason = lesson.get("override_reason", "")
    summary = f"Stage '{stage}' previously needed a criteria override gate."
    if override_reason:
        summary = f"{summary} Reason: {override_reason}"
    return {
        "type": "gate_override",
        "summary": summary,
        "source_run_id": entry["run_id"],
        "stage": stage,
        "task": entry.get("task"),
        "relevance": (
            "This stage needed manual override logic before, so automated "
            "criteria may still be brittle."
        ),
    }


def _skipped_stage_item(entry: dict, lesson: dict) -> dict:
    stage = lesson.get("stage", "unknown")
    reason = lesson.get("reason", "")
    summary = f"Stage '{stage}' was previously skipped."
    if reason:
        summary = f"{summary} Reason: {reason}"
    return {
        "type": "skipped_stage",
        "summary": summary,
        "source_run_id": entry["run_id"],
        "stage": stage,
        "task": entry.get("task"),
        "relevance": "Skipped work can hide assumptions that may no longer hold.",
    }


def build_visible_memory(config: dict, current_run_id: str | None = None, limit: int = 5) -> dict:
    """Build a concise carry-forward memory block from compatible history."""
    entries = _compatible_history_entries(config, current_run_id=current_run_id)

    items: list[dict] = []
    for entry in entries:
        lessons = entry.get("lessons", {})
        if not isinstance(lessons, dict):
            continue

        for lesson in lessons.get("gate_rejections", []):
            items.append(_gate_rejection_item(entry, lesson))
        for lesson in lessons.get("verify_failures", []):
            items.append(_verify_failure_item(entry, lesson))
        for lesson in lessons.get("rework_edges", []):
            items.append(_rework_edge_item(entry, lesson))
        for lesson in lessons.get("gate_overrides", []):
            items.append(_gate_override_item(entry, lesson))
        for lesson in lessons.get("skipped_stages", []):
            items.append(_skipped_stage_item(entry, lesson))

    items = items[:limit]
    if not items:
        return {
            "summary": "No compatible prior memory.",
            "items": [],
        }

    source_run_ids = sorted({item["source_run_id"] for item in items})
    run_word = "run" if len(source_run_ids) == 1 else "runs"
    item_word = "item" if len(items) == 1 else "items"
    return {
        "summary": (
            f"{len(items)} carry-forward {item_word} from {len(source_run_ids)} "
            f"compatible prior {run_word}."
        ),
        "items": items,
    }
