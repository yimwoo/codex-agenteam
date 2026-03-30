# Phase 1: Branch/Worktree Isolation for Writing Agents

**Date:** 2026-03-30
**Status:** Approved with amendments

## Overview

Writing agents (dev, qa, custom writers) currently operate directly on whatever
branch the user is on. This is the riskiest failure mode in the plugin. Phase 1
adds branch/worktree isolation controlled by the existing `parallel_writes.mode`
config, using an A+ skill-layer approach: runtime resolves metadata, a shared
bash helper executes git operations, skills orchestrate the lifecycle.

## Scope

**In scope:**
- `$ateam:assign` with writing roles in any pipeline mode
- `$ateam:run` in `standalone` mode (dispatch-only has no pipeline to run;
  the run skill already tells the user to use `$ateam:assign` instead)
- Branch creation for `serial` mode
- Worktree creation for `worktree` mode
- Passthrough for `scoped` mode (with explicit warning)

**Out of scope (deferred):**
- `$ateam:run` when `pipeline: hotl` -- HOTL execution already owns
  branch/worktree preflight via its own brainstorming and loop-execution
  skills. Phase 1 defers the run pipeline's git lifecycle to HOTL when
  `pipeline: hotl`. Phase 3 will unify them.
- Note: `$ateam:assign` ALWAYS applies branch isolation regardless of
  pipeline mode, because assign is user-initiated and outside HOTL's
  execution flow.
- Runtime state machine changes (Phase 2)
- HOTL adapter enforcement (Phase 3)

## Architecture

```
User -> skill (assign/run) -> runtime branch-plan (JSON) -> skill reads plan
                                                          -> skill captures current branch
                                                          -> skill calls git-isolate.sh
                                                          -> skill launches agent
                                                          -> skill calls git-isolate.sh return
                                                          -> skill reports to user
```

Runtime stays a pure resolver. Skills own execution. `git-isolate.sh` is the
shared helper that avoids duplication.

## Runtime: `cmd_branch_plan`

New command: `agenteam_rt.py branch-plan --task "<task>" [--run-id <id>] [--role <role>]`

Pure resolver. No git side effects. Returns JSON.

### Output for `serial` mode

**Pipeline run (`--run-id` provided):**
```json
{
  "mode": "serial",
  "action": "create-branch",
  "branch": "ateam/run/20260330T150000Z",
  "base_branch": "main",
  "pipeline_mode": "standalone"
}
```

**Ad-hoc assign (`--role` provided, no `--run-id`):**
```json
{
  "mode": "serial",
  "action": "create-branch",
  "branch": "ateam/dev/add-user-auth",
  "base_branch": "main",
  "pipeline_mode": "standalone"
}
```

### Output for `worktree` mode

```json
{
  "mode": "worktree",
  "action": "create-worktree",
  "branch": "ateam/dev/add-user-auth",
  "worktree_path": ".ateam-worktrees/dev-add-user-auth",
  "base_branch": "main",
  "pipeline_mode": "standalone"
}
```

### Output for `scoped` mode

```json
{
  "mode": "scoped",
  "action": "use-current",
  "branch": null,
  "warning": "Scoped mode uses the current branch. This is NOT isolation -- it trusts that write_scope patterns do not overlap. Verify with: agenteam_rt.py policy check",
  "pipeline_mode": "standalone"
}
```

### Output when `pipeline: hotl` and context is `run`

Only returned for `$ateam:run` (with `--run-id`). Ad-hoc `$ateam:assign`
(with `--role`) still gets normal branch isolation even in HOTL projects.

```json
{
  "mode": "hotl-deferred",
  "action": "none",
  "branch": null,
  "note": "HOTL run mode defers git lifecycle to HOTL execution. Phase 3 will unify.",
  "pipeline_mode": "hotl"
}
```

### Branch naming

| Context | Pattern | Example |
|---------|---------|---------|
| Pipeline run | `ateam/run/<run-id>` | `ateam/run/20260330T150000Z` |
| Ad-hoc assign | `ateam/<role>/<task-slug>` | `ateam/dev/add-user-auth` |

Task slug: first 40 chars of task, lowercased, non-alphanum replaced with `-`,
leading/trailing dashes stripped.

### `base_branch` resolution

**For pipeline runs (`$ateam:run`):** `base_branch` is the repo's default
branch (`git symbolic-ref refs/remotes/origin/HEAD` or fallback to `main`).
Pipeline runs should start from a clean baseline.

**For ad-hoc assign (`$ateam:assign`):** `base_branch` is the user's current
HEAD. Ad-hoc work should fork from wherever the user is right now, because
the user may be on a feature branch and want the assignment to build on it.

In both cases, the skill captures the actual current branch before any git
mutation and uses that as the return target (not `base_branch`).

## Shared Helper: `scripts/git-isolate.sh`

Bash script. No Python dependency. Matches the `scripts/` pattern.

### Commands

```bash
# Create branch and switch to it
git-isolate.sh create-branch <branch> [<base>]

# Create worktree at path with branch
git-isolate.sh create-worktree <path> <branch> [<base>]

# Return to a branch (switch back)
git-isolate.sh return <branch>

# Cleanup worktree (conditional: only if clean)
git-isolate.sh cleanup-worktree <path>

# Preflight check (reports issues as JSON)
git-isolate.sh preflight
```

### Preflight Contract

`git-isolate.sh preflight` checks for issues and returns JSON:

```json
{
  "is_git_repo": true,
  "is_clean": true,
  "is_detached": false,
  "current_branch": "main",
  "issues": []
}
```

Possible issues (non-empty `issues` array):

| Condition | Issue | Skill behavior |
|-----------|-------|----------------|
| Not a git repo | `"not-a-git-repo"` | Abort with clear message |
| Dirty worktree | `"dirty-worktree"` | **Block for serial/worktree mode.** User must stash or commit before proceeding. Carrying uncommitted changes into a new branch breaks the isolation guarantee. For scoped mode (no branch switch), this is a warning only. |
| Detached HEAD | `"detached-head"` | **Block.** `git rev-parse --abbrev-ref HEAD` returns `HEAD` in this state, which is not enough to restore the original commit after branch creation. User must checkout a branch first. Phase 2 could store and restore the commit SHA, but Phase 1 hard-blocks for simplicity. |

### `create-branch` behavior

| Condition | Behavior |
|-----------|----------|
| Branch does not exist | Create from base (or current HEAD), switch to it |
| Branch exists at same HEAD | Switch to it (resume) |
| Branch exists at different HEAD | Append `-2`, `-3` suffix to avoid collision |

### `create-worktree` behavior

| Condition | Behavior |
|-----------|----------|
| Path does not exist | Create worktree with new branch |
| Path exists and is a worktree | Reuse (resume scenario). Will be cleaned up after completion if clean. |
| Path exists but is not a worktree | Error: path is occupied |

**Reuse + cleanup rule:** A reused worktree follows the same cleanup rules as
a freshly created one -- if it is clean after the agent completes, it gets
removed. If it has uncommitted changes, it is preserved. There is no
distinction between "new" and "reused" worktrees for cleanup purposes.

### `cleanup-worktree` behavior

| Condition | Behavior |
|-----------|----------|
| Worktree is clean (no uncommitted changes) | Remove worktree |
| Worktree has uncommitted changes | Do NOT remove. Print warning: "Worktree at <path> has uncommitted changes. Inspect or commit before cleanup." |
| Path is not a worktree | No-op |

## Skill Changes

### `assign` skill -- new step between "Check Write Policy" and "Resolve Artifact Paths"

```
### N. Branch Isolation

1. No pipeline mode check needed for assign. Assign ALWAYS applies branch
   isolation regardless of pipeline mode, because it is user-initiated and
   outside HOTL's execution flow.

2. Call preflight:
   bash <plugin-dir>/scripts/git-isolate.sh preflight
   If issues found, warn user and ask how to proceed.

3. Capture the current branch:
   RETURN_BRANCH=$(git rev-parse --abbrev-ref HEAD)

4. Get branch plan from runtime:
   python3 <runtime>/agenteam_rt.py branch-plan --task "<task>" --role "<role>"

5. Execute the plan:
   If action is "create-branch":
     bash <plugin-dir>/scripts/git-isolate.sh create-branch <branch> <base>
   If action is "create-worktree":
     bash <plugin-dir>/scripts/git-isolate.sh create-worktree <path> <branch> <base>
   If action is "use-current":
     Show warning from the plan if present. Continue on current branch.
   If action is "none" (hotl-deferred):
     Skip. Continue on current branch.

6. Launch agent on the isolated branch/worktree.

7. After agent completes:
   If action was "create-branch":
     bash <plugin-dir>/scripts/git-isolate.sh return $RETURN_BRANCH
     Tell user: "Work is on branch <branch>. Merge or create a PR when ready."
   If action was "create-worktree":
     bash <plugin-dir>/scripts/git-isolate.sh cleanup-worktree <path>
     Tell user: "Work is on branch <branch>. Worktree cleaned up (or preserved if dirty)."
```

### `run` skill -- branch created once at pipeline start

Same logic, but:
- Branch is created once when the run starts (using `--run-id`)
- All stages in the pipeline work on the run branch
- Switch back happens after the final stage completes (or if the pipeline is aborted)
- `RETURN_BRANCH` is captured once at the start and used at the end

## HOTL Contracts

### Intent Contract

```
intent: Add branch/worktree isolation for writing agents so they never
        operate directly on the user's current branch when serial or worktree
        mode is configured
constraints:
  - Runtime stays a pure resolver (no git side effects) -- returns branch-plan JSON
  - Skills own execution: preflight, branch creation, agent launch, return/cleanup
  - Shared git-isolate.sh avoids duplication between assign and run skills
  - Write mode config (serial/worktree/scoped) determines isolation behavior
  - Pipeline runs use one branch per run; ad-hoc assigns use one branch per assignment
  - pipeline: hotl defers ONLY $ateam:run git lifecycle to HOTL; $ateam:assign still isolates
  - Scoped mode uses current branch -- this is NOT isolation, just a passthrough
    with an explicit warning that non-overlap is trusted, not enforced
  - Skill captures the actual current branch before mutation (not runtime's base_branch)
  - Worktree cleanup is conditional: only if worktree is clean
success_criteria:
  - Writing agents never work on main/user-branch when serial or worktree mode is set
  - $ateam:run (standalone) creates one branch per pipeline run
  - $ateam:assign creates one branch per ad-hoc assignment
  - Preflight catches dirty worktree, detached HEAD, non-git-repo before any mutation
  - Branch collision handled gracefully (suffix or resume)
  - Worktree with uncommitted changes is preserved, not auto-deleted
  - pipeline: hotl returns action: none for run only; assign still gets branch isolation
  - Dirty worktree blocks serial/worktree mode (must stash/commit first)
  - Ad-hoc assign branches fork from current HEAD; run branches fork from default branch
  - scoped mode returns action: use-current with explicit warning
risk_level: medium
```

### Verification Contract

```
verify_steps:
  - run tests: python3 -m pytest test/test_runtime.py -v
  - run tests: bats test/smoke.bats
  - check: branch-plan returns correct JSON for serial, worktree, scoped, and hotl modes
  - check: git-isolate.sh preflight detects dirty worktree, detached HEAD, non-git-repo
  - check: git-isolate.sh create-branch handles new, same-HEAD, and different-HEAD cases
  - check: git-isolate.sh create-worktree handles new, existing, and occupied-path cases
  - check: git-isolate.sh cleanup-worktree preserves dirty worktrees
  - check: assign skill creates branch, launches agent, returns to captured branch
  - check: run skill creates run branch at start, all stages use it, returns at end
  - check: hotl mode skips branch isolation for run only; assign still isolates
  - check: dirty worktree blocks serial/worktree mode preflight
  - check: ad-hoc assign forks from current HEAD, not default branch
  - confirm: no writing agent operates on main when serial or worktree mode is configured
```

### Governance Contract

```
approval_gates:
  - Design approval (this document) -- APPROVED with amendments
  - Implementation review before merge (reviewer agent)
rollback: git revert; branches and worktrees are lightweight and disposable
ownership: user approves design; implementation is autonomous within Phase 1 scope
```

## Implementation Slices

```
Slice 1: scripts/git-isolate.sh
  Files: scripts/git-isolate.sh (new)
  Depends on: none
  Tests: bats test for each command (preflight, create-branch, create-worktree, return, cleanup)

Slice 2: cmd_branch_plan in runtime
  Files: runtime/agenteam_rt.py
  Depends on: none
  Tests: test/test_runtime.py -- new TestBranchPlan class

Slice 3: Update assign skill
  Files: skills/assign/SKILL.md
  Depends on: Slice 1, Slice 2
  Tests: manual invocation

Slice 4: Update run skill
  Files: skills/run/SKILL.md
  Depends on: Slice 1, Slice 2
  Tests: manual invocation

Slice 5: Router + smoke tests
  Files: skills/using-ateam/SKILL.md, test/smoke.bats
  Depends on: Slice 1
  Tests: bats test for git-isolate.sh existence
```
