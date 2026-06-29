"""Structured role handoff validation and provenance helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = "1"
HANDOFF_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "role-handoff-v1.json"
HANDOFF_FIELDS = {
    "status",
    "summary",
    "artifacts",
    "verification",
    "findings",
    "recommended_next_stage",
}
VERIFICATION_FIELDS = {"command", "result", "details"}
FINDING_FIELDS = {"severity", "summary", "path", "line"}
VALID_STATUSES = {"completed", "blocked", "failed"}
VALID_VERIFICATION_RESULTS = {"passed", "failed", "skipped"}
VALID_FINDING_SEVERITIES = {"block", "warn", "note"}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_relative_path(value: Any) -> bool:
    if not _nonempty_string(value):
        return False
    normalized = str(value).replace("\\", "/")
    path = PurePosixPath(normalized)
    has_drive_prefix = bool(path.parts and ":" in path.parts[0])
    return not path.is_absolute() and not has_drive_prefix and ".." not in path.parts


def validate_handoff(payload: Any) -> list[str]:
    """Return deterministic validation errors for one handoff payload."""
    if not isinstance(payload, dict):
        return ["handoff must be a JSON object"]

    errors: list[str] = []
    missing = sorted(HANDOFF_FIELDS - payload.keys())
    unknown = sorted(payload.keys() - HANDOFF_FIELDS)
    if missing:
        errors.append(f"missing required fields: {missing}")
    if unknown:
        errors.append(f"unknown fields: {unknown}")

    status = payload.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"status must be one of {sorted(VALID_STATUSES)}")
    if not _nonempty_string(payload.get("summary")):
        errors.append("summary must be a non-empty string")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        invalid_paths = [value for value in artifacts if not _valid_relative_path(value)]
        if invalid_paths:
            errors.append("artifacts must contain only repository-relative paths")
        if all(isinstance(value, str) for value in artifacts) and len(set(artifacts)) != len(
            artifacts
        ):
            errors.append("artifacts must not contain duplicates")

    verification = payload.get("verification")
    if not isinstance(verification, list):
        errors.append("verification must be a list")
    else:
        for index, item in enumerate(verification):
            context = f"verification[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{context} must be an object")
                continue
            if set(item) != VERIFICATION_FIELDS:
                errors.append(f"{context} must contain exactly {sorted(VERIFICATION_FIELDS)}")
            if not _nonempty_string(item.get("command")):
                errors.append(f"{context}.command must be a non-empty string")
            if item.get("result") not in VALID_VERIFICATION_RESULTS:
                errors.append(
                    f"{context}.result must be one of {sorted(VALID_VERIFICATION_RESULTS)}"
                )
            if not isinstance(item.get("details"), str):
                errors.append(f"{context}.details must be a string")

    findings = payload.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be a list")
    else:
        for index, item in enumerate(findings):
            context = f"findings[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{context} must be an object")
                continue
            if set(item) != FINDING_FIELDS:
                errors.append(f"{context} must contain exactly {sorted(FINDING_FIELDS)}")
            if item.get("severity") not in VALID_FINDING_SEVERITIES:
                errors.append(
                    f"{context}.severity must be one of {sorted(VALID_FINDING_SEVERITIES)}"
                )
            if not _nonempty_string(item.get("summary")):
                errors.append(f"{context}.summary must be a non-empty string")
            path = item.get("path")
            if path is not None and not _valid_relative_path(path):
                errors.append(f"{context}.path must be null or a repository-relative path")
            line = item.get("line")
            if line is not None and (
                isinstance(line, bool) or not isinstance(line, int) or line < 1
            ):
                errors.append(f"{context}.line must be null or a positive integer")

    next_stage = payload.get("recommended_next_stage")
    if next_stage is not None and not _nonempty_string(next_stage):
        errors.append("recommended_next_stage must be null or a non-empty string")

    return errors


def load_handoff(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate a persisted handoff file."""
    if not path.exists():
        return None, [f"handoff file not found: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"failed to read handoff: {exc}"]
    errors = validate_handoff(payload)
    return (payload if isinstance(payload, dict) else None), errors


def build_handoff_provenance(path: Path, payload: dict[str, Any], display_path: str) -> dict:
    """Build compact, state-safe provenance for a valid handoff."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "path": display_path,
        "sha256": digest,
        "status": payload["status"],
        "summary": payload["summary"].strip(),
        "artifact_count": len(payload["artifacts"]),
        "verification_count": len(payload["verification"]),
        "finding_count": len(payload["findings"]),
        "recommended_next_stage": payload["recommended_next_stage"],
    }
