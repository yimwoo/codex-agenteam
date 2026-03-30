#!/usr/bin/env python3
"""Run a repeatable AgenTeam smoke test against an existing or temporary project."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime" / "agenteam_rt.py"
REQUIREMENTS = ROOT / "runtime" / "requirements.txt"
TEMPLATE = ROOT / "templates" / "agenteam.yaml.template"


class SmokeFailure(RuntimeError):
    """Raised when a smoke-test assertion fails."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an AgenTeam smoke test. If the target project does not exist, "
            "a small temporary playground is created automatically."
        )
    )
    parser.add_argument(
        "--project",
        help="Project directory to test. If omitted or missing, a temporary playground is used.",
    )
    parser.add_argument(
        "--task",
        default="Smoke test AgenTeam pipeline orchestration",
        help="Task text used for run initialization.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the generated temporary playground instead of deleting it.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final smoke report as JSON.",
    )
    parser.add_argument(
        "--skip-deps-bootstrap",
        action="store_true",
        help="Do not create an isolated venv when runtime dependencies are missing.",
    )
    return parser.parse_args()


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise SmokeFailure(
            "Command failed:\n"
            f"  cwd: {cwd}\n"
            f"  cmd: {' '.join(command)}\n"
            f"  exit: {result.returncode}\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return result


def load_last_json(output: str) -> dict:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise SmokeFailure(f"Expected JSON output, got none:\n{output}")

    warnings: list[dict] = []
    idx = 0
    while idx < len(lines):
        candidate = lines[idx].strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            break
        if isinstance(parsed, dict) and "warning" in parsed:
            warnings.append(parsed)
            idx += 1
            continue
        break

    payload = "\n".join(lines[idx:]).strip()
    if not payload:
        if warnings:
            return warnings[-1]
        raise SmokeFailure(f"Expected JSON payload after warnings, got none:\n{output}")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"Could not parse JSON output:\n{output}") from exc


def ensure_runtime_python(args: argparse.Namespace, temp_root: Path | None) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, str(RUNTIME), "--help"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return sys.executable, "system"

    combined = (result.stdout or "") + (result.stderr or "")
    missing_runtime_deps = "PyYAML not installed" in combined or "toml not installed" in combined
    if args.skip_deps_bootstrap or not missing_runtime_deps:
        raise SmokeFailure(
            "AgenTeam runtime is not ready and smoke bootstrap is disabled.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    if temp_root is None:
        raise SmokeFailure("Missing temporary root for runtime dependency bootstrap.")

    venv_dir = temp_root / "runtime-venv"
    run_command([sys.executable, "-m", "venv", str(venv_dir)], cwd=ROOT)
    venv_python = venv_dir / "bin" / "python"
    run_command([str(venv_python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], cwd=ROOT)
    return str(venv_python), "venv"


def create_fallback_playground(project_dir: Path) -> None:
    (project_dir / ".agenteam").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE, project_dir / ".agenteam" / "config.yaml")

    package_json = {
        "name": "ateam-smoke-playground",
        "private": True,
        "version": "0.0.1",
        "scripts": {
            "test": "node -e \"console.log('smoke playground test ok')\"",
        },
    }
    (project_dir / "package.json").write_text(json.dumps(package_json, indent=2) + "\n")
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "src" / "index.ts").write_text("export const smoke = true;\n")
    (project_dir / "README.md").write_text("# AgenTeam Smoke Playground\n")


def prepare_project(args: argparse.Namespace, temp_root: Path) -> tuple[Path, bool]:
    if args.project:
        requested = Path(args.project).expanduser().resolve()
        if requested.exists():
            return requested, False
        fallback = temp_root / requested.name
        create_fallback_playground(fallback)
        return fallback, True

    fallback = temp_root / "ateam-smoke-playground"
    create_fallback_playground(fallback)
    return fallback, True


def run_rt(
    python_bin: str,
    project_dir: Path,
    *args: str,
) -> dict:
    result = run_command([python_bin, str(RUNTIME), *args], cwd=project_dir)
    return load_last_json(result.stdout)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke(args: argparse.Namespace) -> dict:
    temp_root_path = Path(tempfile.mkdtemp(prefix="ateam-smoke-")).resolve()
    cleanup_root = temp_root_path

    try:
        python_bin, python_source = ensure_runtime_python(args, temp_root_path)
        project_dir, used_fallback = prepare_project(args, temp_root_path)

        health = run_rt(python_bin, project_dir, "health")
        assert_true(health["config_exists"] is True, "Expected config to exist in smoke project.")

        validate = run_rt(python_bin, project_dir, "validate")
        assert_true(validate["valid"] is True, "Config validation should pass.")

        generate = run_rt(python_bin, project_dir, "generate")
        generated = generate["generated"]
        assert_true(len(generated) >= 6, "Expected built-in agents to be generated.")

        roles = run_rt(python_bin, project_dir, "roles", "list")
        assert_true(
            set(["architect", "dev", "pm", "qa", "researcher", "reviewer"]).issubset(set(roles)),
            f"Missing expected built-in roles: {roles}",
        )

        artifacts = run_rt(python_bin, project_dir, "artifact-paths")
        assert_true("paths" in artifacts, "artifact-paths should return path mappings.")

        policy = run_rt(python_bin, project_dir, "policy", "check")
        assert_true("writers" in policy, "policy check should include writers.")

        init = run_rt(python_bin, project_dir, "init", "--task", args.task)
        run_id = init["run_id"]
        assert_true(bool(run_id), "init should return a run_id.")

        status = run_rt(python_bin, project_dir, "status", run_id)
        assert_true(status["run_id"] == run_id, "status should return the initialized run.")

        dispatch_research = run_rt(
            python_bin,
            project_dir,
            "dispatch",
            "research",
            "--task",
            args.task,
            "--run-id",
            run_id,
        )
        assert_true(
            dispatch_research["dispatch"][0]["role"] == "researcher",
            f"Expected researcher dispatch, got: {dispatch_research}",
        )

        dispatch_implement = run_rt(
            python_bin,
            project_dir,
            "dispatch",
            "implement",
            "--task",
            args.task,
            "--run-id",
            run_id,
        )
        assert_true(
            dispatch_implement["dispatch"][0]["role"] == "dev",
            f"Expected dev dispatch, got: {dispatch_implement}",
        )

        verify_plan = run_rt(python_bin, project_dir, "verify-plan", "implement", "--run-id", run_id)
        assert_true(
            verify_plan["verify"] in ("npm test", "python3 -m pytest -v", "go test ./...", "cargo test", "make test"),
            f"Unexpected verify command: {verify_plan}",
        )

        final_verify = run_rt(python_bin, project_dir, "final-verify-plan", "--run-id", run_id)
        assert_true(isinstance(final_verify["commands"], list), "final-verify-plan should return commands.")

        run_rt(
            python_bin,
            project_dir,
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--result",
            "pass",
            "--output",
            "smoke ok",
        )
        run_rt(
            python_bin,
            project_dir,
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "review",
            "--gate-type",
            "human",
            "--result",
            "approved",
            "--verdict",
            "PASS",
        )

        post_status = run_rt(python_bin, project_dir, "status", run_id)
        implement_stage = post_status["stages"]["implement"]
        review_stage = post_status["stages"]["review"]
        assert_true(implement_stage.get("verify_result") == "pass", "verify result should be recorded.")
        assert_true(review_stage.get("gate_result") == "approved", "gate result should be recorded.")

        standup = run_rt(python_bin, project_dir, "standup")
        assert_true(standup["run"]["run_id"] == run_id, "standup should reference the latest run.")

        report = {
            "ok": True,
            "project_dir": str(project_dir),
            "used_fallback_playground": used_fallback,
            "runtime_python": python_bin,
            "runtime_python_source": python_source,
            "run_id": run_id,
            "verify_command": verify_plan["verify"],
            "final_verify_commands": final_verify["commands"],
            "generated_agents": len(generated),
            "roles": roles,
        }
        return report
    finally:
        if not args.keep_temp:
            shutil.rmtree(cleanup_root, ignore_errors=True)


def main() -> int:
    args = parse_args()
    try:
        report = run_smoke(args)
    except SmokeFailure as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        playground_note = "temporary fallback playground" if report["used_fallback_playground"] else "project"
        print(f"Smoke test passed for {playground_note}: {report['project_dir']}")
        print(f"Runtime python: {report['runtime_python_source']} ({report['runtime_python']})")
        print(f"Run ID: {report['run_id']}")
        print(f"Verify command: {report['verify_command']}")
        print(f"Generated agents: {report['generated_agents']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
