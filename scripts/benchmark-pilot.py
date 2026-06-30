#!/usr/bin/env python3
"""Prepare and run the reproducible AgenTeam benchmark pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

import yaml

SCHEMA_VERSION = "1"
REQUIRED_STRATEGIES = (
    "single_agent",
    "native_high_effort",
    "minimal_team",
    "governed_pipeline",
)
EXPECTED_ADAPTERS = {
    "single_agent": "native",
    "native_high_effort": "native",
    "minimal_team": "agenteam",
    "governed_pipeline": "agenteam",
}


class PilotError(Exception):
    """Raised for an actionable pilot configuration or execution error."""


@dataclass(frozen=True, slots=True)
class CodexCapabilities:
    version: str
    models: dict[str, tuple[str, ...]]


def _fail(message: str) -> NoReturn:
    raise PilotError(message)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value.strip()


def _required_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} must be a mapping")
    return value


def _run_capture(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _fail(f"Command timed out after {timeout} seconds: {' '.join(command)}")
    except OSError as exc:
        _fail(f"Failed to execute {command[0]}: {exc}")


def discover_codex(codex_bin: str) -> CodexCapabilities:
    """Return the exact CLI version and live model/reasoning catalog."""
    version_result = _run_capture([codex_bin, "--version"])
    if version_result.returncode != 0:
        _fail(f"Codex version discovery failed: {version_result.stderr.strip()}")
    version_text = version_result.stdout.strip()
    if not version_text:
        _fail("Codex version discovery returned empty output")
    version = version_text.split()[-1]

    model_result = _run_capture([codex_bin, "debug", "models"])
    if model_result.returncode != 0:
        _fail(f"Codex model discovery failed: {model_result.stderr.strip()}")
    try:
        payload = json.loads(model_result.stdout)
    except json.JSONDecodeError as exc:
        _fail(f"Codex model discovery returned invalid JSON: {exc}")
    models_raw = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models_raw, list):
        _fail("Codex model discovery JSON requires a models list")

    models: dict[str, tuple[str, ...]] = {}
    for item in models_raw:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        levels = item.get("supported_reasoning_levels")
        if not isinstance(slug, str) or not isinstance(levels, list):
            continue
        efforts = tuple(
            level["effort"]
            for level in levels
            if isinstance(level, dict) and isinstance(level.get("effort"), str) and level["effort"]
        )
        models[slug] = efforts
    if not models:
        _fail("Codex model discovery returned no usable model entries")
    return CodexCapabilities(version=version, models=models)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        _fail(f"Failed to hash {path}: {exc}")
    return digest.hexdigest()


def load_manifest(path_str: str, capabilities: CodexCapabilities) -> dict[str, Any]:
    """Load and validate a pilot manifest against live Codex capabilities."""
    path = Path(path_str).resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _fail(f"Failed to read pilot manifest {path}: {exc}")
    except yaml.YAMLError as exc:
        _fail(f"Pilot manifest is invalid YAML: {exc}")
    manifest = _required_mapping(raw, "manifest")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        _fail(f"schema_version must be '{SCHEMA_VERSION}'")
    pilot_id = _required_string(manifest.get("pilot_id"), "pilot_id")
    base_ref = _required_string(manifest.get("base_ref"), "base_ref")
    artifact_root_raw = _required_string(manifest.get("artifact_root"), "artifact_root")
    artifact_root = Path(artifact_root_raw)
    if not artifact_root.is_absolute():
        artifact_root = (path.parent / artifact_root).resolve()
    suite_raw = _required_string(manifest.get("suite"), "suite")
    suite_path = Path(suite_raw)
    if not suite_path.is_absolute():
        suite_path = (path.parent / suite_path).resolve()
    if not suite_path.is_file():
        _fail(f"suite not found: {suite_path}")

    codex = _required_mapping(manifest.get("codex"), "codex")
    expected_version = _required_string(codex.get("version"), "codex.version")
    if expected_version != capabilities.version:
        _fail(
            f"codex.version expects {expected_version}, but live Codex reports "
            f"{capabilities.version}"
        )
    sol = _required_mapping(codex.get("gpt_5_6_sol"), "codex.gpt_5_6_sol")
    if not isinstance(sol.get("available"), bool):
        _fail("codex.gpt_5_6_sol.available must be boolean")
    sol_reason = _required_string(sol.get("reason"), "codex.gpt_5_6_sol.reason")

    task_raw = _required_mapping(manifest.get("task"), "task")
    timeout = task_raw.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        _fail("task.timeout_seconds must be a positive integer")
    seed_raw = _required_string(task_raw.get("seed_patch"), "task.seed_patch")
    seed_path = Path(seed_raw)
    if not seed_path.is_absolute():
        seed_path = (path.parent / seed_path).resolve()
    if not seed_path.is_file():
        _fail(f"task.seed_patch not found: {seed_path}")
    task = {
        "id": _required_string(task_raw.get("id"), "task.id"),
        "prompt": _required_string(task_raw.get("prompt"), "task.prompt"),
        "seed_patch": str(seed_path),
        "seed_sha256": _sha256_file(seed_path),
        "precheck": _required_string(task_raw.get("precheck"), "task.precheck"),
        "verify": _required_string(task_raw.get("verify"), "task.verify"),
        "timeout_seconds": timeout,
    }

    strategies_raw = manifest.get("strategies")
    if not isinstance(strategies_raw, list):
        _fail("strategies must be a list")
    strategies: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(strategies_raw, start=1):
        strategy = _required_mapping(item, f"strategies[{index}]")
        strategy_id = _required_string(strategy.get("id"), f"strategies[{index}].id")
        if strategy_id not in EXPECTED_ADAPTERS:
            _fail(f"Unknown strategy '{strategy_id}'")
        if strategy_id in seen:
            _fail(f"Duplicate strategy '{strategy_id}'")
        seen.add(strategy_id)
        adapter = _required_string(strategy.get("adapter"), f"strategies[{index}].adapter")
        if adapter != EXPECTED_ADAPTERS[strategy_id]:
            _fail(f"Strategy '{strategy_id}' requires adapter '{EXPECTED_ADAPTERS[strategy_id]}'")
        model = _required_string(strategy.get("model"), f"strategies[{index}].model")
        if model not in capabilities.models:
            _fail(f"Strategy '{strategy_id}' model '{model}' is absent from the live Codex catalog")
        effort = _required_string(
            strategy.get("reasoning_effort"),
            f"strategies[{index}].reasoning_effort",
        )
        if effort not in capabilities.models[model]:
            _fail(
                f"Strategy '{strategy_id}' reasoning effort '{effort}' is unsupported by "
                f"model '{model}'"
            )
        normalized = {
            "id": strategy_id,
            "adapter": adapter,
            "model": model,
            "reasoning_effort": effort,
        }
        if adapter == "agenteam":
            normalized["profile"] = _required_string(
                strategy.get("profile"),
                f"strategies[{index}].profile",
            )
        strategies.append(normalized)

    if tuple(strategy["id"] for strategy in strategies) != REQUIRED_STRATEGIES:
        _fail(f"strategies must be declared in order: {', '.join(REQUIRED_STRATEGIES)}")

    return {
        "path": str(path),
        "schema_version": SCHEMA_VERSION,
        "pilot_id": pilot_id,
        "base_ref": base_ref,
        "artifact_root": str(artifact_root),
        "suite": str(suite_path),
        "codex": {
            "version": expected_version,
            "gpt_5_6_sol": {"available": sol["available"], "reason": sol_reason},
        },
        "task": task,
        "strategies": strategies,
    }


def build_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build stable task/strategy workspace plans without mutating the repository."""
    artifact_root = Path(manifest["artifact_root"])
    task = manifest["task"]
    plans = []
    for strategy in manifest["strategies"]:
        plan_id = f"{task['id']}--{strategy['id']}"
        plans.append(
            {
                "plan_id": plan_id,
                "pilot_id": manifest["pilot_id"],
                "task_id": task["id"],
                "strategy": strategy["id"],
                "adapter": strategy["adapter"],
                "profile": strategy.get("profile"),
                "model": strategy["model"],
                "reasoning_effort": strategy["reasoning_effort"],
                "codex_version": manifest["codex"]["version"],
                "base_ref": manifest["base_ref"],
                "seed_patch": task["seed_patch"],
                "seed_sha256": task["seed_sha256"],
                "timeout_seconds": task["timeout_seconds"],
                "worktree_path": str(artifact_root / manifest["pilot_id"] / "worktrees" / plan_id),
                "artifact_path": str(artifact_root / manifest["pilot_id"] / "runs" / plan_id),
            }
        )
    return {
        "pilot_id": manifest["pilot_id"],
        "task_id": task["id"],
        "base_ref": manifest["base_ref"],
        "codex_version": manifest["codex"]["version"],
        "gpt_5_6_sol": manifest["codex"]["gpt_5_6_sol"],
        "plans": plans,
    }


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    result = _run_capture(["git", "-C", str(repo), *args])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        _fail(f"Git command failed ({' '.join(args)}): {detail}")
    return result


def _resolve_repo_root(repo_root: str | None) -> Path:
    candidate = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    result = _run_capture(["git", "-C", str(candidate), "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        _fail(f"Repository root is not a Git checkout: {candidate}")
    return Path(result.stdout.strip()).resolve()


def _state_path(manifest: dict[str, Any]) -> Path:
    return Path(manifest["artifact_root"]) / manifest["pilot_id"] / "state.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_state(manifest: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = _state_path(manifest)
    if not path.is_file():
        _fail(f"Pilot state not found: {path}. Run prepare first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"Failed to read pilot state {path}: {exc}")
    if not isinstance(payload, dict) or payload.get("pilot_id") != manifest["pilot_id"]:
        _fail(f"Pilot state does not match manifest pilot_id: {path}")
    return path, payload


def prepare_workspaces(manifest: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Create seeded detached worktrees and prove the task precheck fails."""
    dirty = _git(repo_root, "status", "--porcelain").stdout.strip()
    if dirty:
        _fail("Source checkout is dirty; commit or remove changes before preparing the pilot")
    base_commit = _git(repo_root, "rev-parse", manifest["base_ref"]).stdout.strip()
    planned = build_plan(manifest)
    state_path = _state_path(manifest)
    if state_path.exists():
        _fail(f"Pilot state already exists: {state_path}. Inspect, resume, or cleanup it first.")

    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": manifest["pilot_id"],
        "manifest_path": manifest["path"],
        "manifest_sha256": _sha256_file(Path(manifest["path"])),
        "repo_root": str(repo_root),
        "base_ref": manifest["base_ref"],
        "base_commit": base_commit,
        "codex_version": manifest["codex"]["version"],
        "status": "preparing",
        "plans": [],
    }
    _write_json_atomic(state_path, state)

    benchmark_config = Path(manifest["path"]).parent / "agenteam.yaml"
    for plan in planned["plans"]:
        worktree = Path(plan["worktree_path"])
        if worktree.exists():
            _fail(f"Path exists and is not a reusable worktree: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _git(repo_root, "worktree", "add", "--detach", str(worktree), base_commit)
        prepared_plan = {
            **plan,
            "status": "applying_seed",
            "base_commit": base_commit,
        }
        state["plans"].append(prepared_plan)
        _write_json_atomic(state_path, state)
        _git(worktree, "apply", plan["seed_patch"])

        if benchmark_config.is_file():
            target_config = worktree / ".agenteam" / "config.yaml"
            target_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(benchmark_config, target_config)

        artifact_path = Path(plan["artifact_path"])
        artifact_path.mkdir(parents=True, exist_ok=True)
        prepared_plan["status"] = "prechecking"
        _write_json_atomic(state_path, state)
        precheck = _run_capture(
            shlex.split(manifest["task"]["precheck"]),
            cwd=worktree,
            timeout=manifest["task"]["timeout_seconds"],
        )
        (artifact_path / "precheck.stdout.txt").write_text(
            precheck.stdout,
            encoding="utf-8",
        )
        (artifact_path / "precheck.stderr.txt").write_text(
            precheck.stderr,
            encoding="utf-8",
        )
        if precheck.returncode == 0:
            _fail(f"Seeded precheck unexpectedly passed for strategy '{plan['strategy']}'")

        prepared_plan["status"] = "prepared"
        prepared_plan["precheck_returncode"] = precheck.returncode
        _write_json_atomic(state_path, state)

    state["status"] = "prepared"
    _write_json_atomic(state_path, state)
    return {
        "prepared": True,
        "pilot_id": manifest["pilot_id"],
        "base_commit": base_commit,
        "prepared_count": len(state["plans"]),
        "state_path": str(state_path),
    }


def inspect_pilot(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a compact projection of current resumable pilot state."""
    state_path, state = _load_state(manifest)
    return {
        "pilot_id": state["pilot_id"],
        "status": state.get("status"),
        "base_commit": state.get("base_commit"),
        "prepared_count": sum(
            1 for plan in state.get("plans", []) if plan.get("status") != "removed"
        ),
        "state_path": str(state_path),
        "plans": state.get("plans", []),
    }


def cleanup_workspaces(
    manifest: dict[str, Any],
    repo_root: Path,
    strategy: str | None,
) -> dict[str, Any]:
    """Remove only clean worktrees recorded by matching pilot state."""
    state_path, state = _load_state(manifest)
    if strategy is not None and strategy not in REQUIRED_STRATEGIES:
        _fail(f"Unknown strategy '{strategy}'")
    removed: list[str] = []
    preserved: list[str] = []
    missing: list[str] = []
    for plan in state.get("plans", []):
        if strategy is not None and plan.get("strategy") != strategy:
            continue
        strategy_id = plan["strategy"]
        worktree = Path(plan["worktree_path"])
        if not worktree.exists():
            missing.append(strategy_id)
            plan["status"] = "removed"
            continue
        if not (worktree / ".git").is_file():
            _fail(f"Refusing cleanup because path is not a Git worktree: {worktree}")
        dirty = _git(worktree, "status", "--porcelain").stdout.strip()
        if dirty:
            preserved.append(strategy_id)
            continue
        _git(repo_root, "worktree", "remove", str(worktree))
        plan["status"] = "removed"
        removed.append(strategy_id)
    _write_json_atomic(state_path, state)
    return {
        "pilot_id": manifest["pilot_id"],
        "removed": removed,
        "preserved": preserved,
        "missing": missing,
        "state_path": str(state_path),
    }


def _jsonl_usage(stdout: str) -> dict[str, int]:
    usage: dict[str, int] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        candidate = event.get("usage")
        if not isinstance(candidate, dict):
            continue
        usage = {
            field: int(candidate.get(field) or 0)
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        }
    return usage


def _find_plan(state: dict[str, Any], strategy: str) -> dict[str, Any]:
    for plan in state.get("plans", []):
        if plan.get("strategy") == strategy:
            return plan
    _fail(f"Strategy '{strategy}' is not present in prepared pilot state")


def _runner_run_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "run_started":
            continue
        run_id = event.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def _runner_terminal(stdout: str) -> bool:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in {"run_finished", "run_completed"}:
            return True
    return False


def _validate_benchmark_team_config(
    config_path: Path,
    expected_model: str,
    expected_effort: str,
) -> None:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        _fail(f"Failed to read isolated AgenTeam config {config_path}: {exc}")
    except yaml.YAMLError as exc:
        _fail(f"Isolated AgenTeam config is invalid YAML: {exc}")
    config = _required_mapping(raw, "agenteam config")
    roles = _required_mapping(config.get("roles"), "agenteam config.roles")
    drift = []
    for role_name, role_raw in roles.items():
        if not isinstance(role_raw, dict):
            drift.append(f"{role_name} (invalid role config)")
            continue
        if role_raw.get("model") != expected_model:
            drift.append(f"{role_name}.model")
        if role_raw.get("reasoning_effort") != expected_effort:
            drift.append(f"{role_name}.reasoning_effort")
    if drift:
        _fail(
            "Benchmark AgenTeam role settings do not match the pinned "
            f"{expected_model}/{expected_effort} strategy: " + ", ".join(sorted(drift))
        )


def run_native_strategy(
    manifest: dict[str, Any],
    repo_root: Path,
    codex_bin: str,
    strategy: str,
) -> dict[str, Any]:
    """Run one native Codex strategy and persist auditable artifacts."""
    state_path, state = _load_state(manifest)
    if Path(state.get("repo_root", "")).resolve() != repo_root:
        _fail("Prepared pilot state belongs to a different repository root")
    plan = _find_plan(state, strategy)
    if plan.get("adapter") != "native":
        _fail(f"Strategy '{strategy}' is not a native Codex strategy")
    if plan.get("status") == "completed" and isinstance(plan.get("result"), dict):
        return {**plan["result"], "already_completed": True}

    worktree = Path(plan["worktree_path"])
    if not (worktree / ".git").is_file():
        _fail(f"Prepared worktree is missing for strategy '{strategy}': {worktree}")
    artifact_path = Path(plan["artifact_path"])
    artifact_path.mkdir(parents=True, exist_ok=True)
    final_response = artifact_path / "final-response.json"
    command = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--json",
        "--sandbox",
        "workspace-write",
        "--model",
        plan["model"],
        "--config",
        f'model_reasoning_effort="{plan["reasoning_effort"]}"',
        "--output-last-message",
        str(final_response),
        manifest["task"]["prompt"],
    ]
    (artifact_path / "command.json").write_text(
        json.dumps(command, indent=2) + "\n",
        encoding="utf-8",
    )
    plan["status"] = "running"
    _write_json_atomic(state_path, state)

    started = time.monotonic()
    executed = _run_capture(
        command,
        cwd=worktree,
        timeout=manifest["task"]["timeout_seconds"],
    )
    latency_seconds = round(time.monotonic() - started, 4)
    (artifact_path / "stdout.jsonl").write_text(executed.stdout, encoding="utf-8")
    (artifact_path / "stderr.txt").write_text(executed.stderr, encoding="utf-8")

    usage = _jsonl_usage(executed.stdout)
    (artifact_path / "usage.json").write_text(
        json.dumps(usage, indent=2) + "\n",
        encoding="utf-8",
    )
    verified = _run_capture(
        shlex.split(manifest["task"]["verify"]),
        cwd=worktree,
        timeout=manifest["task"]["timeout_seconds"],
    )
    (artifact_path / "verify.stdout.txt").write_text(
        verified.stdout,
        encoding="utf-8",
    )
    (artifact_path / "verify.stderr.txt").write_text(
        verified.stderr,
        encoding="utf-8",
    )
    diff = _git(worktree, "diff", "--binary", "HEAD").stdout
    (artifact_path / "diff.patch").write_text(diff, encoding="utf-8")

    success = executed.returncode == 0 and verified.returncode == 0
    result = {
        "completed": True,
        "pilot_id": manifest["pilot_id"],
        "task_id": manifest["task"]["id"],
        "strategy": strategy,
        "success": success,
        "quality_score": 1.0 if success else 0.0,
        "latency_seconds": latency_seconds,
        "codex_returncode": executed.returncode,
        "verify_returncode": verified.returncode,
        "usage": usage,
        "artifact_path": str(artifact_path),
        "already_completed": False,
    }
    plan["status"] = "completed"
    plan["result"] = result
    _write_json_atomic(state_path, state)
    return result


def run_agenteam_strategy(
    manifest: dict[str, Any],
    repo_root: Path,
    codex_bin: str,
    agenteam_rt: str | None,
    strategy: str,
) -> dict[str, Any]:
    """Run one AgenTeam profile and persist runner plus portable evidence."""
    state_path, state = _load_state(manifest)
    if Path(state.get("repo_root", "")).resolve() != repo_root:
        _fail("Prepared pilot state belongs to a different repository root")
    plan = _find_plan(state, strategy)
    if plan.get("adapter") != "agenteam":
        _fail(f"Strategy '{strategy}' is not an AgenTeam strategy")
    if plan.get("status") == "completed" and isinstance(plan.get("result"), dict):
        return {**plan["result"], "already_completed": True}

    worktree = Path(plan["worktree_path"])
    if not (worktree / ".git").is_file():
        _fail(f"Prepared worktree is missing for strategy '{strategy}': {worktree}")
    config_path = worktree / ".agenteam" / "config.yaml"
    if not config_path.is_file():
        _fail(f"Isolated AgenTeam config is missing: {config_path}")
    _validate_benchmark_team_config(
        config_path,
        plan["model"],
        plan["reasoning_effort"],
    )

    runtime_path = (
        Path(agenteam_rt).resolve() if agenteam_rt else worktree / "runtime" / "agenteam_rt.py"
    )
    if not runtime_path.is_file():
        _fail(f"AgenTeam runtime not found: {runtime_path}")

    artifact_path = Path(plan["artifact_path"])
    artifact_path.mkdir(parents=True, exist_ok=True)
    runner_output = artifact_path / "runner"
    evidence_path = artifact_path / "evidence.json"
    prefix = [sys.executable, str(runtime_path), "--config", str(config_path)]
    generate_command = [*prefix, "generate"]
    run_command = [
        *prefix,
        "run",
        "--task",
        manifest["task"]["prompt"],
        "--profile",
        plan["profile"],
        "--codex-bin",
        codex_bin,
        "--codex-args=--ephemeral",
        "--auto-approve-gates",
        "--output-dir",
        str(runner_output),
    ]
    if isinstance(plan.get("runner_run_id"), str):
        run_command.extend(["--run-id", plan["runner_run_id"]])

    resume_evidence = (
        plan.get("phase") == "evidence"
        and plan.get("runner_terminal") is True
        and isinstance(plan.get("runner_run_id"), str)
    )
    plan["status"] = "running"
    if resume_evidence:
        runner_stdout = (artifact_path / "runner.stdout.jsonl").read_text(encoding="utf-8")
        runner_stderr = (artifact_path / "runner.stderr.txt").read_text(encoding="utf-8")
        executed = subprocess.CompletedProcess(
            run_command,
            int(plan.get("runner_returncode") or 0),
            runner_stdout,
            runner_stderr,
        )
        latency_seconds = float(plan.get("runner_latency_seconds") or 0.0)
        runner_run_id = plan["runner_run_id"]
    else:
        plan["phase"] = "generate"
        _write_json_atomic(state_path, state)
        generated = _run_capture(
            generate_command,
            cwd=worktree,
            timeout=manifest["task"]["timeout_seconds"],
        )
        (artifact_path / "generate.stdout.json").write_text(
            generated.stdout,
            encoding="utf-8",
        )
        (artifact_path / "generate.stderr.txt").write_text(
            generated.stderr,
            encoding="utf-8",
        )
        if generated.returncode != 0:
            plan["status"] = "incomplete"
            plan["phase"] = "generate"
            _write_json_atomic(state_path, state)
            return {
                "completed": False,
                "pilot_id": manifest["pilot_id"],
                "task_id": manifest["task"]["id"],
                "strategy": strategy,
                "success": False,
                "phase": "generate",
                "returncode": generated.returncode,
                "artifact_path": str(artifact_path),
                "already_completed": False,
            }

        plan["phase"] = "run"
        _write_json_atomic(state_path, state)
        started = time.monotonic()
        executed = _run_capture(
            run_command,
            cwd=worktree,
            timeout=manifest["task"]["timeout_seconds"],
        )
        latency_seconds = round(time.monotonic() - started, 4)
        (artifact_path / "runner.stdout.jsonl").write_text(
            executed.stdout,
            encoding="utf-8",
        )
        (artifact_path / "runner.stderr.txt").write_text(
            executed.stderr,
            encoding="utf-8",
        )
        runner_run_id = _runner_run_id(executed.stdout) or plan.get("runner_run_id")
        if isinstance(runner_run_id, str):
            plan["runner_run_id"] = runner_run_id
        plan["runner_returncode"] = executed.returncode
        plan["runner_latency_seconds"] = latency_seconds
        plan["runner_terminal"] = _runner_terminal(executed.stdout)
    plan["phase"] = "evidence"
    _write_json_atomic(state_path, state)

    evidence_command = [
        *prefix,
        "evidence",
        "--run-id",
        runner_run_id or "missing-run-id",
        "--output",
        str(evidence_path),
    ]
    commands = {
        "generate": generate_command,
        "run": run_command,
        "evidence": evidence_command,
    }
    (artifact_path / "commands.json").write_text(
        json.dumps(commands, indent=2) + "\n",
        encoding="utf-8",
    )

    if runner_run_id:
        exported = _run_capture(
            evidence_command,
            cwd=worktree,
            timeout=manifest["task"]["timeout_seconds"],
        )
    else:
        exported = subprocess.CompletedProcess(
            evidence_command,
            1,
            "",
            "Runner output did not identify a run_id",
        )
    (artifact_path / "evidence.stdout.json").write_text(
        exported.stdout,
        encoding="utf-8",
    )
    (artifact_path / "evidence.stderr.txt").write_text(
        exported.stderr,
        encoding="utf-8",
    )

    evidence: dict[str, Any] | None = None
    if exported.returncode == 0 and evidence_path.is_file():
        try:
            loaded = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _fail(f"AgenTeam evidence is unreadable for strategy '{strategy}': {exc}")
        if not isinstance(loaded, dict) or loaded.get("kind") != "agenteam.run_evidence":
            _fail(f"AgenTeam evidence has an invalid kind for strategy '{strategy}'")
        evidence = loaded

    verified = _run_capture(
        shlex.split(manifest["task"]["verify"]),
        cwd=worktree,
        timeout=manifest["task"]["timeout_seconds"],
    )
    (artifact_path / "verify.stdout.txt").write_text(
        verified.stdout,
        encoding="utf-8",
    )
    (artifact_path / "verify.stderr.txt").write_text(
        verified.stderr,
        encoding="utf-8",
    )
    diff = _git(worktree, "diff", "--binary", "HEAD").stdout
    (artifact_path / "diff.patch").write_text(diff, encoding="utf-8")

    outcome = evidence.get("outcome", {}) if evidence else {}
    terminal = outcome.get("result") in {"completed", "failed", "blocked", "stopped"}
    success = (
        terminal
        and outcome.get("result") == "completed"
        and executed.returncode == 0
        and exported.returncode == 0
        and verified.returncode == 0
    )
    result = {
        "completed": terminal,
        "pilot_id": manifest["pilot_id"],
        "task_id": manifest["task"]["id"],
        "strategy": strategy,
        "success": success,
        "quality_score": 1.0 if success else 0.0,
        "latency_seconds": latency_seconds,
        "run_id": runner_run_id,
        "runner_returncode": executed.returncode,
        "evidence_returncode": exported.returncode,
        "verify_returncode": verified.returncode,
        "usage": _jsonl_usage(executed.stdout),
        "evidence": evidence,
        "evidence_path": str(evidence_path),
        "artifact_path": str(artifact_path),
        "already_completed": False,
    }
    plan["status"] = "completed" if terminal else "incomplete"
    plan["phase"] = "completed" if terminal else "evidence"
    plan["result"] = result
    _write_json_atomic(state_path, state)
    return result


def _benchmark_runtime(repo_root: Path, agenteam_rt: str | None) -> Path:
    runtime_path = (
        Path(agenteam_rt).resolve() if agenteam_rt else repo_root / "runtime" / "agenteam_rt.py"
    )
    if not runtime_path.is_file():
        _fail(f"AgenTeam runtime not found: {runtime_path}")
    return runtime_path


def _verify_plan_provenance(manifest: dict[str, Any], state: dict[str, Any]) -> None:
    plans = state.get("plans")
    if not isinstance(plans, list) or len(plans) != len(REQUIRED_STRATEGIES):
        _fail("Pilot state does not contain the required four strategy plans")
    base_commit = state.get("base_commit")
    if not isinstance(base_commit, str) or not base_commit:
        _fail("Pilot state is missing its base revision")
    if any(plan.get("base_commit") != base_commit for plan in plans):
        _fail("Pilot plans contain mixed base revisions")

    expected = {item["id"]: item for item in manifest["strategies"]}
    for plan in plans:
        strategy = plan.get("strategy")
        pinned = expected.get(strategy)
        if pinned is None:
            _fail(f"Pilot state contains unknown strategy '{strategy}'")
        drift_fields = [
            field
            for field in ("adapter", "model", "reasoning_effort", "profile")
            if plan.get(field) != pinned.get(field)
        ]
        if plan.get("codex_version") != manifest["codex"]["version"]:
            drift_fields.append("codex_version")
        if drift_fields:
            _fail(
                f"Capability drift detected for strategy '{strategy}': " + ", ".join(drift_fields)
            )


def _evidence_summary(result: dict[str, Any]) -> dict[str, Any] | None:
    evidence = result.get("evidence")
    evidence_path_raw = result.get("evidence_path")
    if not isinstance(evidence, dict) or not isinstance(evidence_path_raw, str):
        return None
    evidence_path = Path(evidence_path_raw)
    if not evidence_path.is_file():
        _fail(f"Recorded evidence file is missing: {evidence_path}")
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), dict) else {}
    final_verify = (
        evidence.get("final_verify") if isinstance(evidence.get("final_verify"), dict) else {}
    )
    summary = {
        "kind": evidence.get("kind"),
        "schema_version": evidence.get("schema_version"),
        "source": str(evidence_path),
        "sha256": _sha256_file(evidence_path),
        "final_verify_passed": final_verify.get("passed"),
    }
    for field in (
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
    ):
        value = metrics.get(field, 0)
        summary[field] = int(value) if isinstance(value, int) and value >= 0 else 0
    return summary


def finalize_pilot(
    manifest: dict[str, Any],
    repo_root: Path,
    agenteam_rt: str | None,
) -> dict[str, Any]:
    """Assemble four terminal runs and delegate validation/reporting."""
    state_path, state = _load_state(manifest)
    if Path(state.get("repo_root", "")).resolve() != repo_root:
        _fail("Prepared pilot state belongs to a different repository root")
    _verify_plan_provenance(manifest, state)
    incomplete = [
        plan.get("strategy")
        for plan in state["plans"]
        if plan.get("status") != "completed"
        or not isinstance(plan.get("result"), dict)
        or plan["result"].get("completed") is not True
    ]
    if incomplete:
        _fail("Pilot cannot finalize before terminal results for: " + ", ".join(incomplete))

    try:
        suite_raw = yaml.safe_load(Path(manifest["suite"]).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _fail(f"Failed to read benchmark suite {manifest['suite']}: {exc}")
    suite = _required_mapping(suite_raw, "suite")
    suite_id = _required_string(suite.get("suite_id"), "suite.suite_id")

    runs = []
    for strategy in REQUIRED_STRATEGIES:
        plan = _find_plan(state, strategy)
        result = plan["result"]
        success = result.get("success") is True
        runs.append(
            {
                "task_id": manifest["task"]["id"],
                "strategy": strategy,
                "status": "recorded",
                "success": success,
                "latency_seconds": result["latency_seconds"],
                "cost_usd": None,
                "quality_score": result["quality_score"],
                "notes": f"Exact token usage retained at {result['artifact_path']}",
                "model": plan["model"],
                "reasoning_effort": plan["reasoning_effort"],
                "codex_version": plan["codex_version"],
                "repo_commit": state["base_commit"],
                "run_id": result.get("run_id"),
                "profile": plan.get("profile"),
                "failure_reason": None if success else "Strategy verification failed",
                "evidence": _evidence_summary(result),
            }
        )

    report_path = Path(manifest["artifact_root"]) / manifest["pilot_id"] / "report"
    report_path.mkdir(parents=True, exist_ok=True)
    results_path = report_path / "results.json"
    results = {
        "suite_id": suite_id,
        "quality_scale": "0.0-1.0",
        "strategies": list(REQUIRED_STRATEGIES),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notes": "Seeded AgenTeam pilot; exact token usage remains in per-run artifacts.",
        "runs": runs,
    }
    _write_json_atomic(results_path, results)

    runtime_path = _benchmark_runtime(repo_root, agenteam_rt)
    validate_command = [
        sys.executable,
        str(runtime_path),
        "benchmark",
        "validate",
        "--suite",
        manifest["suite"],
        "--results",
        str(results_path),
    ]
    validated = _run_capture(validate_command, cwd=repo_root)
    (report_path / "validate.stdout.json").write_text(validated.stdout, encoding="utf-8")
    (report_path / "validate.stderr.txt").write_text(validated.stderr, encoding="utf-8")
    if validated.returncode != 0:
        _fail(f"Benchmark result validation failed: {validated.stderr.strip()}")

    markdown_path = report_path / "report.md"
    report_command = [
        sys.executable,
        str(runtime_path),
        "benchmark",
        "report",
        "--suite",
        manifest["suite"],
        "--results",
        str(results_path),
        "--markdown-out",
        str(markdown_path),
    ]
    reported = _run_capture(report_command, cwd=repo_root)
    (report_path / "report.stderr.txt").write_text(reported.stderr, encoding="utf-8")
    if reported.returncode != 0:
        _fail(f"Benchmark report generation failed: {reported.stderr.strip()}")
    try:
        report = json.loads(reported.stdout)
    except json.JSONDecodeError as exc:
        _fail(f"Benchmark report returned invalid JSON: {exc}")
    _write_json_atomic(report_path / "report.json", report)

    ready = report.get("reproducibility", {}).get("ready_for_executor_decision") is True
    summary = {
        "pilot_id": manifest["pilot_id"],
        "base_commit": state["base_commit"],
        "codex_version": manifest["codex"]["version"],
        "gpt_5_6_sol": manifest["codex"]["gpt_5_6_sol"],
        "recorded_run_count": len(runs),
        "ready_for_executor_decision": ready,
        "results_path": str(results_path),
        "report_path": str(report_path),
    }
    _write_json_atomic(report_path / "summary.json", summary)
    state["status"] = "finalized"
    state["report"] = summary
    _write_json_atomic(state_path, state)
    return {"finalized": True, **summary}


def dry_run_pilot(
    manifest: dict[str, Any],
    repo_root: Path,
    agenteam_rt: str | None,
) -> dict[str, Any]:
    """Validate a plan and suite without preparing worktrees or calling models."""
    runtime_path = _benchmark_runtime(repo_root, agenteam_rt)
    suite_check = _run_capture(
        [
            sys.executable,
            str(runtime_path),
            "benchmark",
            "validate",
            "--suite",
            manifest["suite"],
        ],
        cwd=repo_root,
    )
    if suite_check.returncode != 0:
        _fail(f"Benchmark suite validation failed: {suite_check.stderr.strip()}")
    plan = build_plan(manifest)
    relative_manifest = Path(manifest["path"])
    try:
        manifest_arg = str(relative_manifest.relative_to(repo_root))
    except ValueError:
        manifest_arg = str(relative_manifest)
    return {
        "dry_run": True,
        "model_calls_started": False,
        "pilot_id": manifest["pilot_id"],
        "base_ref": manifest["base_ref"],
        "codex_version": manifest["codex"]["version"],
        "strategy_count": len(plan["plans"]),
        "plans": plan["plans"],
        "post_merge_command": (
            f"python3 scripts/benchmark-pilot.py execute --manifest {shlex.quote(manifest_arg)}"
        ),
    }


def execute_pilot(
    manifest: dict[str, Any],
    repo_root: Path,
    codex_bin: str,
    agenteam_rt: str | None,
) -> dict[str, Any]:
    """Prepare, resume all four strategies, and finalize the merged pilot."""
    if not _state_path(manifest).is_file():
        prepare_workspaces(manifest, repo_root)
    for strategy in manifest["strategies"]:
        if strategy["adapter"] == "native":
            result = run_native_strategy(manifest, repo_root, codex_bin, strategy["id"])
        else:
            result = run_agenteam_strategy(
                manifest,
                repo_root,
                codex_bin,
                agenteam_rt,
                strategy["id"],
            )
        if result.get("completed") is not True:
            _fail(
                f"Strategy '{strategy['id']}' stopped before terminal evidence; "
                "inspect state and rerun execute to resume"
            )
    return finalize_pilot(manifest, repo_root, agenteam_rt)


def _common_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--codex-bin", default="codex")


def _repo_parser(parser: argparse.ArgumentParser) -> None:
    _common_parser(parser)
    parser.add_argument("--repo-root", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _common_parser(subparsers.add_parser("validate", help="Validate manifest and capabilities"))
    _common_parser(subparsers.add_parser("plan", help="Build deterministic workspace plans"))
    _repo_parser(subparsers.add_parser("prepare", help="Create seeded isolated worktrees"))
    _repo_parser(subparsers.add_parser("inspect", help="Inspect resumable pilot state"))
    cleanup = subparsers.add_parser("cleanup", help="Remove clean recorded worktrees")
    _repo_parser(cleanup)
    cleanup.add_argument("--strategy", default=None)
    run = subparsers.add_parser("run", help="Run one prepared benchmark strategy")
    _repo_parser(run)
    run.add_argument("--strategy", required=True, choices=REQUIRED_STRATEGIES)
    run.add_argument("--agenteam-rt", default=None)
    finalize = subparsers.add_parser("finalize", help="Assemble and report terminal results")
    _repo_parser(finalize)
    finalize.add_argument("--agenteam-rt", default=None)
    dry_run = subparsers.add_parser("dry-run", help="Validate the no-model execution plan")
    _repo_parser(dry_run)
    dry_run.add_argument("--agenteam-rt", default=None)
    execute = subparsers.add_parser("execute", help="Run or resume the merged pilot matrix")
    _repo_parser(execute)
    execute.add_argument("--agenteam-rt", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        capabilities = discover_codex(args.codex_bin)
        manifest = load_manifest(args.manifest, capabilities)
        if args.command == "validate":
            output = {
                "valid": True,
                "pilot_id": manifest["pilot_id"],
                "task_id": manifest["task"]["id"],
                "codex_version": manifest["codex"]["version"],
                "strategy_count": len(manifest["strategies"]),
                "gpt_5_6_sol": manifest["codex"]["gpt_5_6_sol"],
            }
        elif args.command == "plan":
            output = build_plan(manifest)
        elif args.command == "prepare":
            output = prepare_workspaces(manifest, _resolve_repo_root(args.repo_root))
        elif args.command == "inspect":
            output = inspect_pilot(manifest)
        elif args.command == "cleanup":
            output = cleanup_workspaces(
                manifest,
                _resolve_repo_root(args.repo_root),
                args.strategy,
            )
        elif args.command == "dry-run":
            output = dry_run_pilot(
                manifest,
                _resolve_repo_root(args.repo_root),
                args.agenteam_rt,
            )
        elif args.command == "finalize":
            output = finalize_pilot(
                manifest,
                _resolve_repo_root(args.repo_root),
                args.agenteam_rt,
            )
        elif args.command == "execute":
            output = execute_pilot(
                manifest,
                _resolve_repo_root(args.repo_root),
                args.codex_bin,
                args.agenteam_rt,
            )
        else:
            repo_root = _resolve_repo_root(args.repo_root)
            strategy = next(item for item in manifest["strategies"] if item["id"] == args.strategy)
            if strategy["adapter"] == "native":
                output = run_native_strategy(manifest, repo_root, args.codex_bin, args.strategy)
            else:
                output = run_agenteam_strategy(
                    manifest,
                    repo_root,
                    args.codex_bin,
                    args.agenteam_rt,
                    args.strategy,
                )
        print(json.dumps(output))
        return 0
    except PilotError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
