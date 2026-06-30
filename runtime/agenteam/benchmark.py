"""Benchmark suite validation and reporting helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import yaml

EVIDENCE_KIND = "agenteam.run_evidence"
EVIDENCE_SCHEMA_VERSION = "1"
TERMINAL_OUTCOMES = {"completed", "failed", "blocked", "stopped"}
EVIDENCE_COUNT_FIELDS = (
    "failed_stage_count",
    "role_attempt_count",
    "role_failure_count",
    "verify_attempt_count",
    "retry_count",
    "rework_count",
    "gate_block_count",
    "artifact_count",
    "handoff_count",
    "invalid_handoff_count",
)
REPRODUCIBILITY_FIELDS = (
    "model",
    "reasoning_effort",
    "codex_version",
    "repo_commit",
)
SHARED_ENVIRONMENT_FIELDS = ("codex_version", "repo_commit")
HEX_REVISION_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _fail(message: str) -> NoReturn:
    print(json.dumps({"error": message}), file=sys.stderr)
    sys.exit(1)


def _load_file(path_str: str, kind: str) -> tuple[Path, Any]:
    path = Path(path_str)
    if not path.exists():
        _fail(f"{kind} file not found: {path}")

    suffix = path.suffix.lower()
    try:
        with open(path, encoding="utf-8") as f:
            if suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(f)
            elif suffix == ".json":
                data = json.load(f)
            else:
                _fail(f"Unsupported {kind} file format: {path.suffix or '<none>'}")
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as e:
        _fail(f"Failed to read {kind} file {path}: {e}")

    return path, data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as e:
        _fail(f"Failed to hash file {path}: {e}")
    return digest.hexdigest()


def _require_string(value: Any, field: str, errors: list[str], context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}: '{field}' must be a non-empty string")
        return ""
    return value.strip()


def _optional_string(value: Any, field: str, errors: list[str], context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{context}: '{field}' must be a non-empty string when present")
        return None
    return value.strip()


def _optional_hex_value(
    value: Any,
    field: str,
    errors: list[str],
    context: str,
    *,
    pattern: re.Pattern[str],
    description: str,
) -> str | None:
    normalized = _optional_string(value, field, errors, context)
    if normalized is not None and not pattern.fullmatch(normalized):
        errors.append(f"{context}: {field} must be {description}")
    return normalized


def _require_string_list(
    value: Any,
    field: str,
    errors: list[str],
    context: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{context}: '{field}' must be a list of non-empty strings")
        return []
    invalid_items = any(not isinstance(item, str) or not item.strip() for item in value)
    if invalid_items:
        errors.append(f"{context}: '{field}' must be a list of non-empty strings")
        return []
    normalized = [item.strip() for item in value]
    if not allow_empty and not normalized:
        errors.append(f"{context}: '{field}' must not be empty")
    return normalized


def _optional_number(
    value: Any,
    field: str,
    errors: list[str],
    context: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{context}: '{field}' must be numeric")
        return None
    number = float(value)
    if not math.isfinite(number):
        errors.append(f"{context}: '{field}' must be finite")
        return None
    if minimum is not None and number < minimum:
        errors.append(f"{context}: '{field}' must be >= {minimum}")
    if maximum is not None and number > maximum:
        errors.append(f"{context}: '{field}' must be <= {maximum}")
    return number


def _optional_nonnegative_int(
    value: Any,
    field: str,
    errors: list[str],
    context: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{context}: '{field}' must be an integer")
        return None
    if value < 0:
        errors.append(f"{context}: '{field}' must be >= 0")
    return int(value)


def _normalize_evidence_summary(
    value: Any,
    errors: list[str],
    context: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{context}: 'evidence' must be a mapping when present")
        return None

    kind = value.get("kind")
    if kind != EVIDENCE_KIND:
        errors.append(f"{context}: evidence.kind must be '{EVIDENCE_KIND}'")
    schema_version = value.get("schema_version")
    if schema_version != EVIDENCE_SCHEMA_VERSION:
        errors.append(f"{context}: evidence.schema_version must be '{EVIDENCE_SCHEMA_VERSION}'")
    source = value.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(f"{context}: evidence.source must be a non-empty string")
    sha256 = _optional_hex_value(
        value.get("sha256"),
        "evidence.sha256",
        errors,
        context,
        pattern=SHA256_PATTERN,
        description="a 64-character hexadecimal digest",
    )

    final_verify_passed = value.get("final_verify_passed")
    if final_verify_passed is not None and not isinstance(final_verify_passed, bool):
        errors.append(f"{context}: evidence.final_verify_passed must be boolean or null")

    normalized = {
        "kind": kind,
        "schema_version": schema_version,
        "source": source.strip() if isinstance(source, str) else source,
        "sha256": sha256,
        "final_verify_passed": final_verify_passed,
    }
    for field in EVIDENCE_COUNT_FIELDS:
        normalized[field] = _optional_nonnegative_int(
            value.get(field, 0),
            f"evidence.{field}",
            errors,
            context,
        )
    return normalized


def load_run_evidence(path_str: str) -> dict[str, Any]:
    """Load and validate one portable AgenTeam run evidence object."""
    path, raw = _load_file(path_str, "run evidence")
    if not isinstance(raw, dict):
        _fail(f"Run evidence must contain a top-level mapping: {path}")

    errors: list[str] = []
    if raw.get("kind") != EVIDENCE_KIND:
        errors.append(f"evidence: 'kind' must be '{EVIDENCE_KIND}'")
    if raw.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append(f"evidence: 'schema_version' must be '{EVIDENCE_SCHEMA_VERSION}'")

    run = raw.get("run")
    outcome = raw.get("outcome")
    metrics = raw.get("metrics")
    final_verify = raw.get("final_verify")
    if not isinstance(run, dict):
        errors.append("evidence: 'run' must be a mapping")
        run = {}
    if not isinstance(outcome, dict):
        errors.append("evidence: 'outcome' must be a mapping")
        outcome = {}
    if not isinstance(metrics, dict):
        errors.append("evidence: 'metrics' must be a mapping")
        metrics = {}
    if not isinstance(final_verify, dict):
        errors.append("evidence: 'final_verify' must be a mapping")
        final_verify = {}

    run_id = _require_string(run.get("run_id"), "run.run_id", errors, "evidence")
    result = _require_string(outcome.get("result"), "outcome.result", errors, "evidence")
    if result and result not in TERMINAL_OUTCOMES:
        errors.append(
            f"evidence: outcome.result must be terminal ({', '.join(sorted(TERMINAL_OUTCOMES))})"
        )
    for field in EVIDENCE_COUNT_FIELDS:
        _optional_nonnegative_int(metrics.get(field, 0), f"metrics.{field}", errors, "evidence")
    final_verify_passed = final_verify.get("passed")
    if final_verify_passed is not None and not isinstance(final_verify_passed, bool):
        errors.append("evidence: final_verify.passed must be boolean or null")

    if errors:
        _fail("; ".join(errors))

    return {
        **raw,
        "path": str(path),
        "sha256": _sha256_file(path),
        "run": {**run, "run_id": run_id},
        "outcome": {**outcome, "result": result},
        "metrics": metrics,
        "final_verify": final_verify,
    }


def load_benchmark_suite(path_str: str) -> dict[str, Any]:
    path, raw = _load_file(path_str, "benchmark suite")
    if not isinstance(raw, dict):
        _fail(f"Benchmark suite must contain a top-level mapping: {path}")

    errors: list[str] = []
    suite_id = _require_string(raw.get("suite_id"), "suite_id", errors, "suite")
    description = _require_string(raw.get("description"), "description", errors, "suite")
    quality_scale = raw.get("quality_scale", "0.0-1.0")
    if quality_scale != "0.0-1.0":
        errors.append("suite: 'quality_scale' must be '0.0-1.0'")

    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        errors.append("suite: 'tasks' must be a non-empty list")
        tasks_raw = []

    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, task_raw in enumerate(tasks_raw, start=1):
        context = f"task[{idx}]"
        if not isinstance(task_raw, dict):
            errors.append(f"{context}: task entry must be a mapping")
            continue

        task_id = _require_string(task_raw.get("id"), "id", errors, context)
        title = _require_string(task_raw.get("title"), "title", errors, context)
        category = _require_string(task_raw.get("category"), "category", errors, context)
        prompt = _require_string(task_raw.get("prompt"), "prompt", errors, context)
        difficulty = _require_string(
            task_raw.get("difficulty", "unspecified"),
            "difficulty",
            errors,
            context,
        )
        setup = _require_string_list(task_raw.get("setup", []), "setup", errors, context)
        checks = _require_string_list(task_raw.get("checks", []), "checks", errors, context)
        acceptance = _require_string_list(
            task_raw.get("acceptance", []),
            "acceptance",
            errors,
            context,
        )
        tags = _require_string_list(task_raw.get("tags", []), "tags", errors, context)
        timeout_minutes = _optional_number(
            task_raw.get("timeout_minutes", 30),
            "timeout_minutes",
            errors,
            context,
            minimum=1,
        )

        if task_id and task_id in seen_ids:
            errors.append(f"{context}: duplicate task id '{task_id}'")
        seen_ids.add(task_id)

        tasks.append(
            {
                "id": task_id,
                "title": title,
                "category": category,
                "difficulty": difficulty,
                "prompt": prompt,
                "setup": setup,
                "checks": checks,
                "acceptance": acceptance,
                "tags": tags,
                "timeout_minutes": timeout_minutes,
            }
        )

    if errors:
        _fail("; ".join(errors))

    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "suite_id": suite_id,
        "description": description,
        "quality_scale": quality_scale,
        "tasks": tasks,
    }


def load_benchmark_results(path_str: str, suite: dict[str, Any] | None = None) -> dict[str, Any]:
    path, raw = _load_file(path_str, "benchmark results")
    if not isinstance(raw, dict):
        _fail(f"Benchmark results must contain a top-level mapping: {path}")

    errors: list[str] = []
    suite_id = _require_string(raw.get("suite_id"), "suite_id", errors, "results")
    quality_scale = raw.get("quality_scale", "0.0-1.0")
    if quality_scale != "0.0-1.0":
        errors.append("results: 'quality_scale' must be '0.0-1.0'")

    strategies = _require_string_list(
        raw.get("strategies", []),
        "strategies",
        errors,
        "results",
        allow_empty=False,
    )
    runs_raw = raw.get("runs")
    if not isinstance(runs_raw, list):
        errors.append("results: 'runs' must be a list")
        runs_raw = []

    task_ids = {task["id"] for task in suite["tasks"]} if suite else set()
    seen_pairs: set[tuple[str, str]] = set()
    runs: list[dict[str, Any]] = []

    for idx, run_raw in enumerate(runs_raw, start=1):
        context = f"run[{idx}]"
        if not isinstance(run_raw, dict):
            errors.append(f"{context}: run entry must be a mapping")
            continue

        task_id = _require_string(run_raw.get("task_id"), "task_id", errors, context)
        strategy = _require_string(run_raw.get("strategy"), "strategy", errors, context)
        status = _require_string(run_raw.get("status", "recorded"), "status", errors, context)
        if status not in {"pending", "recorded"}:
            errors.append(f"{context}: 'status' must be 'pending' or 'recorded'")

        if suite is not None and task_ids and task_id and task_id not in task_ids:
            errors.append(f"{context}: unknown task_id '{task_id}' for suite '{suite['suite_id']}'")
        if strategies and strategy and strategy not in set(strategies):
            errors.append(f"{context}: strategy '{strategy}' not declared in results.strategies")

        pair = (task_id, strategy)
        if task_id and strategy and pair in seen_pairs:
            errors.append(f"{context}: duplicate task/strategy pair '{task_id}' + '{strategy}'")
        seen_pairs.add(pair)

        success = run_raw.get("success")
        if success is not None and not isinstance(success, bool):
            errors.append(f"{context}: 'success' must be boolean when present")

        latency_seconds = _optional_number(
            run_raw.get("latency_seconds"),
            "latency_seconds",
            errors,
            context,
            minimum=0,
        )
        cost_usd = _optional_number(
            run_raw.get("cost_usd"),
            "cost_usd",
            errors,
            context,
            minimum=0,
        )
        quality_score = _optional_number(
            run_raw.get("quality_score"),
            "quality_score",
            errors,
            context,
            minimum=0,
            maximum=1,
        )
        notes = run_raw.get("notes", "")
        if notes is not None and not isinstance(notes, str):
            errors.append(f"{context}: 'notes' must be a string when present")
        model = _optional_string(run_raw.get("model"), "model", errors, context)
        reasoning_effort = _optional_string(
            run_raw.get("reasoning_effort"),
            "reasoning_effort",
            errors,
            context,
        )
        codex_version = _optional_string(
            run_raw.get("codex_version"),
            "codex_version",
            errors,
            context,
        )
        repo_commit = _optional_hex_value(
            run_raw.get("repo_commit"),
            "repo_commit",
            errors,
            context,
            pattern=HEX_REVISION_PATTERN,
            description="a 7-to-64-character hexadecimal revision",
        )
        run_id = run_raw.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            errors.append(f"{context}: 'run_id' must be a string when present")
        profile = run_raw.get("profile")
        if profile is not None and not isinstance(profile, str):
            errors.append(f"{context}: 'profile' must be a string when present")
        failure_reason = run_raw.get("failure_reason")
        if failure_reason is not None and not isinstance(failure_reason, str):
            errors.append(f"{context}: 'failure_reason' must be a string when present")
        evidence = _normalize_evidence_summary(run_raw.get("evidence"), errors, context)

        if status == "recorded":
            if success is None:
                errors.append(f"{context}: recorded runs require 'success'")
            if latency_seconds is None:
                errors.append(f"{context}: recorded runs require 'latency_seconds'")
            if quality_score is None:
                errors.append(f"{context}: recorded runs require 'quality_score'")

        runs.append(
            {
                "task_id": task_id,
                "strategy": strategy,
                "status": status,
                "success": success,
                "latency_seconds": latency_seconds,
                "cost_usd": cost_usd,
                "quality_score": quality_score,
                "notes": notes or "",
                "model": model,
                "reasoning_effort": reasoning_effort,
                "codex_version": codex_version,
                "repo_commit": repo_commit,
                "run_id": run_id,
                "profile": profile,
                "failure_reason": failure_reason,
                "evidence": evidence,
            }
        )

    if suite and suite_id and suite_id != suite["suite_id"]:
        errors.append(f"results: suite_id '{suite_id}' does not match suite '{suite['suite_id']}'")
    if suite and quality_scale != suite["quality_scale"]:
        errors.append(
            f"results: quality_scale '{quality_scale}' does not match suite "
            f"'{suite['quality_scale']}'"
        )

    if errors:
        _fail("; ".join(errors))

    return {
        "path": str(path),
        "suite_id": suite_id,
        "quality_scale": quality_scale,
        "strategies": strategies,
        "generated_at": raw.get("generated_at"),
        "notes": raw.get("notes", ""),
        "runs": runs,
    }


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _evidence_latency_seconds(evidence: dict[str, Any]) -> float:
    run = evidence["run"]
    elapsed_seconds = run.get("elapsed_seconds")
    if isinstance(elapsed_seconds, (int, float)) and not isinstance(elapsed_seconds, bool):
        if elapsed_seconds >= 0:
            return float(elapsed_seconds)

    started_at = _parse_iso(run.get("started_at"))
    ended_at = _parse_iso(run.get("completed_at") or run.get("last_update"))
    if started_at is None or ended_at is None:
        _fail(
            "Run evidence needs non-negative run.elapsed_seconds or valid "
            "run.started_at and terminal timestamps"
        )
    try:
        duration = (ended_at - started_at).total_seconds()
    except TypeError:
        _fail("Run evidence timestamps must use compatible timezone-aware values")
    if duration < 0:
        _fail("Run evidence terminal timestamp must not precede run.started_at")
    return duration


def build_benchmark_record(
    evidence: dict[str, Any],
    *,
    task_id: str,
    strategy: str,
    quality_score: float,
    cost_usd: float | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    codex_version: str | None = None,
    repo_commit: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Convert validated run evidence into one benchmark result record."""
    if not math.isfinite(quality_score) or not 0 <= quality_score <= 1:
        _fail("quality_score must be between 0.0 and 1.0")
    if cost_usd is not None and (not math.isfinite(cost_usd) or cost_usd < 0):
        _fail("cost_usd must be >= 0")

    metadata_errors: list[str] = []
    model = _optional_string(model, "model", metadata_errors, "record")
    reasoning_effort = _optional_string(
        reasoning_effort,
        "reasoning_effort",
        metadata_errors,
        "record",
    )
    codex_version = _optional_string(
        codex_version,
        "codex_version",
        metadata_errors,
        "record",
    )
    repo_commit = _optional_hex_value(
        repo_commit,
        "repo_commit",
        metadata_errors,
        "record",
        pattern=HEX_REVISION_PATTERN,
        description="a 7-to-64-character hexadecimal revision",
    )
    if metadata_errors:
        _fail("; ".join(metadata_errors))

    run = evidence["run"]
    outcome = evidence["outcome"]
    metrics = evidence["metrics"]
    final_verify = evidence["final_verify"]
    success = (
        outcome.get("result") == "completed"
        and int(metrics.get("failed_stage_count") or 0) == 0
        and final_verify.get("passed") is not False
    )
    failure_reason = None if success else outcome.get("reason") or "run did not complete"

    evidence_summary = {
        "kind": evidence["kind"],
        "schema_version": evidence["schema_version"],
        "source": evidence["path"],
        "sha256": evidence["sha256"],
        "final_verify_passed": final_verify.get("passed"),
    }
    for field in EVIDENCE_COUNT_FIELDS:
        evidence_summary[field] = int(metrics.get(field) or 0)

    return {
        "task_id": task_id,
        "strategy": strategy,
        "status": "recorded",
        "success": success,
        "latency_seconds": _round(_evidence_latency_seconds(evidence)),
        "cost_usd": cost_usd,
        "quality_score": quality_score,
        "notes": notes,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "codex_version": codex_version,
        "repo_commit": repo_commit,
        "run_id": run.get("run_id"),
        "profile": run.get("profile"),
        "failure_reason": failure_reason,
        "evidence": evidence_summary,
    }


def record_benchmark_result(
    results: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Replace or append one task/strategy row in normalized benchmark results."""
    pair = (record["task_id"], record["strategy"])
    runs = []
    replaced = False
    for run in results["runs"]:
        if (run["task_id"], run["strategy"]) == pair:
            runs.append(record)
            replaced = True
        else:
            runs.append(run)
    if not replaced:
        runs.append(record)

    return {
        "suite_id": results["suite_id"],
        "generated_at": results.get("generated_at"),
        "quality_scale": results["quality_scale"],
        "strategies": results["strategies"],
        "notes": results.get("notes", ""),
        "runs": runs,
    }


def _round(value: float) -> float:
    return round(value, 4)


def _build_strategy_summary(
    strategy: str,
    runs: list[dict[str, Any]],
    total_tasks: int,
) -> dict[str, Any]:
    recorded = [run for run in runs if run["status"] == "recorded"]
    successes = sum(1 for run in recorded if run["success"] is True)
    task_coverage = len({run["task_id"] for run in recorded}) / total_tasks if total_tasks else 0.0
    latency_values = [
        run["latency_seconds"] for run in recorded if run["latency_seconds"] is not None
    ]
    cost_values = [run["cost_usd"] for run in recorded if run["cost_usd"] is not None]
    quality_values = [run["quality_score"] for run in recorded if run["quality_score"] is not None]
    evidence_rows = [run["evidence"] for run in recorded if isinstance(run.get("evidence"), dict)]

    run_count = len(recorded)
    return {
        "strategy": strategy,
        "recorded_runs": run_count,
        "failed_runs": run_count - successes,
        "pending_runs": sum(1 for run in runs if run["status"] == "pending"),
        "task_coverage": _round(task_coverage),
        "success_rate": _round(successes / run_count) if run_count else 0.0,
        "avg_latency_seconds": _round(sum(latency_values) / len(latency_values))
        if latency_values
        else None,
        "avg_cost_usd": _round(sum(cost_values) / len(cost_values)) if cost_values else None,
        "total_cost_usd": _round(sum(cost_values)) if cost_values else 0.0,
        "avg_quality_score": _round(sum(quality_values) / len(quality_values))
        if quality_values
        else None,
        "evidence_run_count": len(evidence_rows),
        "final_verify_passed_count": sum(
            1 for evidence in evidence_rows if evidence.get("final_verify_passed") is True
        ),
        **{
            f"total_{field}": sum(int(evidence.get(field) or 0) for evidence in evidence_rows)
            for field in EVIDENCE_COUNT_FIELDS
        },
    }


def _distinct_run_values(runs: list[dict[str, Any]], field: str) -> list[str]:
    return sorted(
        {value for run in runs if isinstance((value := run.get(field)), str) and value.strip()}
    )


def _build_reproducibility_summary(
    suite: dict[str, Any],
    results: dict[str, Any],
    missing_runs: list[dict[str, str]],
) -> dict[str, Any]:
    recorded_runs = [run for run in results["runs"] if run["status"] == "recorded"]
    missing_metadata = {
        field: sum(1 for run in recorded_runs if not run.get(field))
        for field in REPRODUCIBILITY_FIELDS
    }
    metadata_complete_run_count = sum(
        1 for run in recorded_runs if all(run.get(field) for field in REPRODUCIBILITY_FIELDS)
    )
    evidence_runs = [run for run in recorded_runs if isinstance(run.get("evidence"), dict)]
    evidence_hash_run_count = sum(1 for run in evidence_runs if run["evidence"].get("sha256"))

    strategy_environments = []
    strategy_drift = []
    for strategy in results["strategies"]:
        strategy_runs = [run for run in recorded_runs if run["strategy"] == strategy]
        values = {
            field: _distinct_run_values(strategy_runs, field) for field in REPRODUCIBILITY_FIELDS
        }
        drift_fields = [field for field, items in values.items() if len(items) > 1]
        if drift_fields:
            strategy_drift.append({"strategy": strategy, "fields": drift_fields})
        strategy_environments.append(
            {
                "strategy": strategy,
                "recorded_runs": len(strategy_runs),
                "models": values["model"],
                "reasoning_efforts": values["reasoning_effort"],
                "codex_versions": values["codex_version"],
                "repo_commits": values["repo_commit"],
                "metadata_complete": bool(strategy_runs)
                and all(
                    all(run.get(field) for field in REPRODUCIBILITY_FIELDS) for run in strategy_runs
                ),
                "stable": bool(strategy_runs) and not drift_fields,
            }
        )

    shared_drift_fields = [
        field
        for field in SHARED_ENVIRONMENT_FIELDS
        if len(_distinct_run_values(recorded_runs, field)) > 1
    ]
    issues: list[dict[str, Any]] = []
    if missing_runs:
        issues.append(
            {
                "code": "incomplete_matrix",
                "message": "One or more declared task/strategy cells are pending or missing.",
                "run_count": len(missing_runs),
            }
        )
    missing_fields = [field for field, count in missing_metadata.items() if count]
    if missing_fields:
        issues.append(
            {
                "code": "missing_execution_metadata",
                "message": "Recorded runs are missing required reproducibility metadata.",
                "fields": missing_fields,
                "counts": {field: missing_metadata[field] for field in missing_fields},
            }
        )
    if evidence_hash_run_count != len(evidence_runs):
        issues.append(
            {
                "code": "unhashed_evidence",
                "message": "One or more evidence-backed rows lack an evidence SHA-256.",
                "run_count": len(evidence_runs) - evidence_hash_run_count,
            }
        )
    if strategy_drift:
        issues.append(
            {
                "code": "strategy_environment_drift",
                "message": "Execution metadata varies across task rows within a strategy.",
                "strategies": strategy_drift,
            }
        )
    if shared_drift_fields:
        issues.append(
            {
                "code": "shared_environment_drift",
                "message": "Shared Codex or repository metadata varies across strategies.",
                "fields": shared_drift_fields,
            }
        )

    return {
        "suite_sha256": suite["sha256"],
        "required_fields": list(REPRODUCIBILITY_FIELDS),
        "recorded_run_count": len(recorded_runs),
        "metadata_complete_run_count": metadata_complete_run_count,
        "missing_metadata": missing_metadata,
        "evidence_run_count": len(evidence_runs),
        "evidence_hash_run_count": evidence_hash_run_count,
        "strategy_environments": strategy_environments,
        "issues": issues,
        "ready_for_executor_decision": not issues,
    }


def build_benchmark_report(suite: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    total_tasks = len(suite["tasks"])
    task_map = {task["id"]: task for task in suite["tasks"]}
    strategies = results["strategies"]

    all_runs_by_strategy: dict[str, list[dict[str, Any]]] = {
        strategy: [] for strategy in strategies
    }
    category_pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    missing_runs: list[dict[str, str]] = []

    for run in results["runs"]:
        if run["strategy"] in all_runs_by_strategy:
            all_runs_by_strategy[run["strategy"]].append(run)

    run_lookup = {(run["task_id"], run["strategy"]): run for run in results["runs"]}
    for task in suite["tasks"]:
        for strategy in strategies:
            run = run_lookup.get((task["id"], strategy))
            if run is None or run["status"] != "recorded":
                missing_runs.append(
                    {
                        "task_id": task["id"],
                        "strategy": strategy,
                        "status": "missing" if run is None else run["status"],
                    }
                )
                continue
            category_pairs.setdefault((strategy, task["category"]), []).append(run)

    strategy_summary = [
        _build_strategy_summary(strategy, all_runs_by_strategy[strategy], total_tasks)
        for strategy in strategies
    ]
    strategy_summary.sort(
        key=lambda row: (
            -row["success_rate"],
            -(row["avg_quality_score"] or 0.0),
            row["avg_cost_usd"] if row["avg_cost_usd"] is not None else float("inf"),
            row["avg_latency_seconds"] if row["avg_latency_seconds"] is not None else float("inf"),
            -row["task_coverage"],
            row["strategy"],
        )
    )
    for idx, row in enumerate(strategy_summary, start=1):
        row["rank"] = idx

    category_breakdown: list[dict[str, Any]] = []
    for strategy in strategies:
        categories = sorted({task["category"] for task in suite["tasks"]})
        for category in categories:
            runs = category_pairs.get((strategy, category), [])
            successes = sum(1 for run in runs if run["success"] is True)
            cost_values = [run["cost_usd"] for run in runs if run["cost_usd"] is not None]
            category_breakdown.append(
                {
                    "strategy": strategy,
                    "category": category,
                    "recorded_runs": len(runs),
                    "success_rate": _round(successes / len(runs)) if runs else 0.0,
                    "avg_latency_seconds": _round(
                        sum(
                            run["latency_seconds"]
                            for run in runs
                            if run["latency_seconds"] is not None
                        )
                        / len(runs)
                    )
                    if runs
                    else None,
                    "avg_cost_usd": _round(sum(cost_values) / len(cost_values))
                    if cost_values
                    else None,
                    "avg_quality_score": _round(
                        sum(
                            run["quality_score"] for run in runs if run["quality_score"] is not None
                        )
                        / len(runs)
                    )
                    if runs
                    else None,
                }
            )

    recorded_runs = [run for run in results["runs"] if run["status"] == "recorded"]
    report = {
        "suite_id": suite["suite_id"],
        "suite_description": suite["description"],
        "quality_scale": suite["quality_scale"],
        "task_count": total_tasks,
        "strategy_count": len(strategies),
        "expected_run_count": total_tasks * len(strategies),
        "recorded_run_count": len(recorded_runs),
        "pending_run_count": len(missing_runs),
        "strategies": strategy_summary,
        "reproducibility": _build_reproducibility_summary(suite, results, missing_runs),
        "category_breakdown": category_breakdown,
        "missing_runs": missing_runs,
        "tasks": list(task_map.values()),
    }
    return report


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{decimals}f}"


def _format_metadata_values(values: list[str]) -> str:
    if not values:
        return "n/a"
    return ", ".join(value.replace("|", "\\|") for value in values)


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Benchmark Report: {report['suite_id']}",
        "",
        report["suite_description"],
        "",
        "## Summary",
        "",
        f"- Tasks: {report['task_count']}",
        f"- Strategies: {report['strategy_count']}",
        f"- Recorded runs: {report['recorded_run_count']} / {report['expected_run_count']}",
        f"- Pending or missing runs: {report['pending_run_count']}",
        f"- Quality scale: {report['quality_scale']}",
        "",
        "## Reproducibility And Decision Readiness",
        "",
        f"- Suite SHA-256: `{report['reproducibility']['suite_sha256']}`",
        (
            "- Complete execution metadata: "
            f"{report['reproducibility']['metadata_complete_run_count']} / "
            f"{report['reproducibility']['recorded_run_count']} recorded runs"
        ),
        (
            "- Evidence SHA-256 coverage: "
            f"{report['reproducibility']['evidence_hash_run_count']} / "
            f"{report['reproducibility']['evidence_run_count']} evidence-backed runs"
        ),
        (
            "- Ready for executor decision: **"
            f"{'yes' if report['reproducibility']['ready_for_executor_decision'] else 'no'}**"
        ),
        "",
        (
            "| Strategy | Model | Reasoning Effort | Codex Version | Repo Commit | "
            "Complete | Stable |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for environment in report["reproducibility"]["strategy_environments"]:
        lines.append(
            "| "
            f"{environment['strategy']} | "
            f"{_format_metadata_values(environment['models'])} | "
            f"{_format_metadata_values(environment['reasoning_efforts'])} | "
            f"{_format_metadata_values(environment['codex_versions'])} | "
            f"{_format_metadata_values(environment['repo_commits'])} | "
            f"{'yes' if environment['metadata_complete'] else 'no'} | "
            f"{'yes' if environment['stable'] else 'no'} |"
        )

    if report["reproducibility"]["issues"]:
        lines.extend(["", "Decision-readiness issues:", ""])
        for issue in report["reproducibility"]["issues"]:
            lines.append(f"- `{issue['code']}`: {issue['message']}")

    lines.extend(
        [
            "",
            "## Strategy Comparison",
            "",
            (
                "| Rank | Strategy | Success Rate | Avg Quality | "
                "Avg Latency (s) | Avg Cost ($) | Coverage |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for row in report["strategies"]:
        lines.append(
            "| "
            f"{row['rank']} | "
            f"{row['strategy']} | "
            f"{_format_percent(row['success_rate'])} | "
            f"{_format_number(row['avg_quality_score'])} | "
            f"{_format_number(row['avg_latency_seconds'])} | "
            f"{_format_number(row['avg_cost_usd'])} | "
            f"{_format_percent(row['task_coverage'])} |"
        )

    lines.extend(
        [
            "",
            "## Evidence And Recovery",
            "",
            (
                "| Strategy | Evidence Runs | Failed Runs | Role Attempts | "
                "Verify Attempts | Retries | Rework | Gate Blocks | Handoffs | "
                "Invalid Handoffs | Artifacts |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["strategies"]:
        lines.append(
            "| "
            f"{row['strategy']} | "
            f"{row['evidence_run_count']} | "
            f"{row['failed_runs']} | "
            f"{row['total_role_attempt_count']} | "
            f"{row['total_verify_attempt_count']} | "
            f"{row['total_retry_count']} | "
            f"{row['total_rework_count']} | "
            f"{row['total_gate_block_count']} | "
            f"{row['total_handoff_count']} | "
            f"{row['total_invalid_handoff_count']} | "
            f"{row['total_artifact_count']} |"
        )

    lines.extend(
        [
            "",
            "## Category Breakdown",
            "",
            (
                "| Strategy | Category | Recorded Runs | Success Rate | "
                "Avg Quality | Avg Latency (s) | Avg Cost ($) |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["category_breakdown"]:
        lines.append(
            "| "
            f"{row['strategy']} | "
            f"{row['category']} | "
            f"{row['recorded_runs']} | "
            f"{_format_percent(row['success_rate'])} | "
            f"{_format_number(row['avg_quality_score'])} | "
            f"{_format_number(row['avg_latency_seconds'])} | "
            f"{_format_number(row['avg_cost_usd'])} |"
        )

    if report["missing_runs"]:
        lines.extend(["", "## Missing Runs", ""])
        for row in report["missing_runs"]:
            lines.append(f"- `{row['strategy']}` on `{row['task_id']}` ({row['status']})")

    return "\n".join(lines) + "\n"


def cmd_benchmark_validate(args) -> None:
    """Validate a benchmark suite and optional results file."""
    suite = load_benchmark_suite(args.suite)
    output = {
        "valid": True,
        "suite_id": suite["suite_id"],
        "task_count": len(suite["tasks"]),
        "quality_scale": suite["quality_scale"],
    }

    if getattr(args, "results", None):
        results = load_benchmark_results(args.results, suite)
        recorded_runs = sum(1 for run in results["runs"] if run["status"] == "recorded")
        output.update(
            {
                "results_valid": True,
                "strategy_count": len(results["strategies"]),
                "recorded_run_count": recorded_runs,
                "pending_run_count": len(results["runs"]) - recorded_runs,
            }
        )

    print(json.dumps(output))


def cmd_benchmark_init_results(args) -> None:
    """Create a benchmark results template for a suite."""
    suite = load_benchmark_suite(args.suite)
    strategies = []
    for strategy in args.strategy:
        name = strategy.strip()
        if name and name not in strategies:
            strategies.append(name)
    if not strategies:
        _fail("At least one --strategy value is required")

    payload = {
        "suite_id": suite["suite_id"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quality_scale": suite["quality_scale"],
        "strategies": strategies,
        "notes": (
            "Fill in each run entry after executing the task with the named strategy. "
            "Set status=recorded once success, latency_seconds, and quality_score "
            "have been collected. Add model, reasoning_effort, codex_version, and "
            "repo_commit for a decision-ready matrix. Cost is optional when it is "
            "not observable."
        ),
        "runs": [
            {
                "task_id": task["id"],
                "strategy": strategy,
                "status": "pending",
                "success": None,
                "latency_seconds": None,
                "cost_usd": None,
                "quality_score": None,
                "notes": "",
                "model": None,
                "reasoning_effort": None,
                "codex_version": None,
                "repo_commit": None,
                "run_id": None,
                "profile": None,
                "failure_reason": None,
                "evidence": None,
            }
            for task in suite["tasks"]
            for strategy in strategies
        ],
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(
            json.dumps(
                {
                    "created": True,
                    "output_path": str(output_path),
                    "suite_id": suite["suite_id"],
                    "strategy_count": len(strategies),
                    "run_count": len(payload["runs"]),
                }
            )
        )
        return

    print(json.dumps(payload, indent=2))


def cmd_benchmark_record(args) -> None:
    """Convert one run evidence bundle into a benchmark results row."""
    suite = load_benchmark_suite(args.suite)
    results = load_benchmark_results(args.results, suite)
    task_ids = {task["id"] for task in suite["tasks"]}
    if args.task_id not in task_ids:
        _fail(f"Unknown task_id '{args.task_id}' for suite '{suite['suite_id']}'")
    if args.strategy not in results["strategies"]:
        _fail(f"Strategy '{args.strategy}' not declared in results.strategies")

    evidence = load_run_evidence(args.evidence)
    record = build_benchmark_record(
        evidence,
        task_id=args.task_id,
        strategy=args.strategy,
        quality_score=args.quality_score,
        cost_usd=args.cost_usd,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        codex_version=args.codex_version,
        repo_commit=args.repo_commit,
        notes=args.notes or "",
    )
    payload = record_benchmark_result(results, record)
    output_path = Path(args.output or args.results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "recorded": True,
                "output_path": str(output_path),
                "suite_id": suite["suite_id"],
                "task_id": args.task_id,
                "strategy": args.strategy,
                "run_id": record["run_id"],
                "success": record["success"],
                "latency_seconds": record["latency_seconds"],
                "quality_score": record["quality_score"],
                "cost_usd": record["cost_usd"],
                "model": record["model"],
                "reasoning_effort": record["reasoning_effort"],
                "codex_version": record["codex_version"],
                "repo_commit": record["repo_commit"],
            }
        )
    )


def cmd_benchmark_report(args) -> None:
    """Aggregate recorded runs into benchmark summary metrics."""
    suite = load_benchmark_suite(args.suite)
    results = load_benchmark_results(args.results, suite)
    report = build_benchmark_report(suite, results)

    if args.markdown_out:
        markdown_path = Path(args.markdown_out)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(render_markdown_report(report))
        report["markdown_path"] = str(markdown_path)

    print(json.dumps(report))
