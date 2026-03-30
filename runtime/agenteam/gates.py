"""Gate criteria evaluation: automated checks against git diff stats."""

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

from .state import resolve_stages_for_run


def cmd_gate_eval(args, config: dict) -> None:
    """Evaluate gate criteria for a pipeline stage.

    Arguments: --run-id <id> --stage <stage>
    Returns JSON with: stage, passed, criteria, failed_criteria
    """
    run_id = args.run_id
    stage_name = args.stage

    # Find stage config (prefer state when run-scoped)
    stages = resolve_stages_for_run(run_id, config)
    stage_config = None
    for s in stages:
        if s["name"] == stage_name:
            stage_config = s
            break

    if not stage_config:
        print(
            json.dumps({"error": f"Stage '{stage_name}' not found in pipeline"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Read criteria from stage config
    criteria_config = stage_config.get("criteria", {})
    if not criteria_config:
        # No criteria configured -- auto-pass
        print(json.dumps({
            "stage": stage_name,
            "passed": True,
            "criteria": {},
            "failed_criteria": [],
        }))
        return

    # Get baseline from state
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        print(
            json.dumps({"error": f"Run {run_id} not found"}),
            file=sys.stderr,
        )
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    stage_state = state.get("stages", {}).get(stage_name, {})
    baseline = stage_state.get("baseline")
    if not baseline:
        print(
            json.dumps({
                "error": f"No baseline found for stage"
                f" '{stage_name}'."
                " Run stage-baseline capture first.",
            }),
            file=sys.stderr,
        )
        sys.exit(1)

    # Get changed files via git diff
    try:
        proc_names = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline}..HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [f for f in proc_names.stdout.strip().split("\n") if f]
    except subprocess.CalledProcessError as e:
        print(
            json.dumps({"error": f"git diff failed: {e.stderr.strip()}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Evaluate each criterion
    criteria_results: dict = {}
    failed_criteria: list[str] = []

    # max_files_changed
    max_files = criteria_config.get("max_files_changed")
    if max_files is not None:
        actual_count = len(changed_files)
        passed = actual_count <= max_files
        criteria_results["max_files_changed"] = {
            "configured": max_files,
            "actual": actual_count,
            "passed": passed,
        }
        if not passed:
            failed_criteria.append("max_files_changed")

    # scope_paths
    scope_paths = criteria_config.get("scope_paths")
    if scope_paths is not None:
        out_of_scope = []
        for fpath in changed_files:
            in_scope = False
            for pattern in scope_paths:
                if fnmatch.fnmatch(fpath, pattern):
                    in_scope = True
                    break
            if not in_scope:
                out_of_scope.append(fpath)
        passed = len(out_of_scope) == 0
        criteria_results["scope_paths"] = {
            "configured": scope_paths,
            "actual_out_of_scope": out_of_scope,
            "passed": passed,
        }
        if not passed:
            failed_criteria.append("scope_paths")

    # requires_tests
    requires_tests = criteria_config.get("requires_tests")
    if requires_tests:
        test_patterns = ["test_*", "*_test.*", "tests/**", "test/**", "**/*.test.*", "**/test_*"]
        test_files_found = False
        for fpath in changed_files:
            for pattern in test_patterns:
                if fnmatch.fnmatch(fpath, pattern):
                    test_files_found = True
                    break
            if test_files_found:
                break
        criteria_results["requires_tests"] = {
            "configured": True,
            "test_files_found": test_files_found,
            "passed": test_files_found,
        }
        if not test_files_found:
            failed_criteria.append("requires_tests")

    overall_passed = len(failed_criteria) == 0

    print(json.dumps({
        "stage": stage_name,
        "passed": overall_passed,
        "criteria": criteria_results,
        "failed_criteria": failed_criteria,
    }))
