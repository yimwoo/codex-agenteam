"""Branch/worktree plan resolution for writing agents."""

import argparse
import json
import re

from .config import resolve_team_config


def make_task_slug(task: str) -> str:
    """Convert a task description into a branch-safe slug."""
    slug = task.lower()[:40]
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "task"


def cmd_branch_plan(args: argparse.Namespace, config: dict) -> None:
    """Return a branch/worktree plan based on write mode and context."""
    pipeline_mode, isolation_mode = resolve_team_config(config)
    task = args.task
    run_id = getattr(args, "run_id", None)
    role = getattr(args, "role", None)

    # HOTL deferral: only for run context (--run-id), not assign (--role)
    if pipeline_mode == "hotl" and run_id and not role:
        print(
            json.dumps(
                {
                    "mode": "hotl-deferred",
                    "action": "none",
                    "branch": None,
                    "note": (
                        "HOTL run mode defers git lifecycle to HOTL execution. Phase 3 will unify."
                    ),
                    "pipeline_mode": pipeline_mode,
                }
            )
        )
        return

    slug = make_task_slug(task)

    if isolation_mode == "none":
        print(
            json.dumps(
                {
                    "mode": "none",
                    "action": "use-current",
                    "branch": None,
                    "warning": "isolation: none -- uses the current branch. This is NOT isolation. "
                    "It trusts that write_scope patterns do not overlap. "
                    "Verify with: agenteam_rt.py policy check",
                    "pipeline_mode": pipeline_mode or "standalone",
                }
            )
        )
        return

    # Determine branch name and base
    if run_id:
        # Pipeline run: one branch per run, fork from default branch
        branch = f"ateam/run/{run_id}"
        base_branch = "main"
    elif role:
        # Ad-hoc assign: one branch per assignment, fork from current HEAD
        branch = f"ateam/{role}/{slug}"
        base_branch = "current"
    else:
        branch = f"ateam/{slug}"
        base_branch = "current"

    if isolation_mode == "worktree":
        worktree_slug = f"{role or 'run'}-{slug}" if role else slug
        print(
            json.dumps(
                {
                    "mode": "worktree",
                    "action": "create-worktree",
                    "branch": branch,
                    "worktree_path": f".ateam-worktrees/{worktree_slug}",
                    "base_branch": base_branch,
                    "pipeline_mode": pipeline_mode or "standalone",
                }
            )
        )
        return

    # Default: branch isolation
    print(
        json.dumps(
            {
                "mode": "branch",
                "action": "create-branch",
                "branch": branch,
                "base_branch": base_branch,
                "pipeline_mode": pipeline_mode or "standalone",
            }
        )
    )
