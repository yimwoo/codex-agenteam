# Scoped Parallel Writes

**Date:** 2026-03-30
**Status:** Draft

## Problem

Today, AgenTeam serializes all writing agents: dev waits for architect, qa waits
for dev. With 7 pipeline stages and serial execution, a full pipeline run is
bottlenecked by the slowest writer at each stage. When write_scopes don't
overlap (the common case), this serialization is unnecessary.

## Solution

Enable scoped parallel execution for writing agents within a stage when their
write_scopes are provably disjoint. This is opportunistic parallelism -- not
true isolation. Safety comes from scope auditing and serial fallback.

## Non-Goals

- Not true filesystem isolation (that's `isolation: worktree`)
- Not automatic conflict resolution (tainted stages rerun serially)
- Not a replacement for verification (verify-retry still runs after dispatch)

## Config

```yaml
isolation: none    # enables scoped parallel mode
```

The `isolation: none` config value enables this feature. In documentation and
skill output, refer to this as **"scoped parallel mode"** (not "none" or "no
protection") since it provides write-scope enforcement with parallel execution.

Write scopes are already declared per role:
```yaml
roles:
  dev:
    write_scope: ["src/**", "lib/**"]
  qa:
    write_scope: ["tests/**", "**/*.test.*"]
  architect:
    write_scope: ["docs/designs/**"]
```

No new config surface. The existing `write_scope` declarations and
`isolation: none` are all that's needed.

## Architecture

```
run skill -> runtime dispatch (grouped) -> launch group 1 in parallel
                                        -> scope audit group 1
                                        -> launch group 2 in parallel
                                        -> scope audit group 2
                                        -> ... (all groups done)
                                        -> stage verification
                                        -> gate check
```

If any scope audit fails: discard ALL parallel stage work, rerun the
entire stage serially from the clean baseline.

## Runtime: Grouped Dispatch

### Writer group partitioning

The runtime partitions a stage's writing roles into **parallel-safe groups**
based on write_scope overlap:

1. Collect all writing roles for the stage
2. For each pair, check write_scope glob intersection (same logic as
   `cmd_policy_check`, but scoped to this stage's roles)
3. Build groups greedily:
   - Start with the first writer in group 1
   - For each subsequent writer, check if it overlaps with any role
     already in the current group
   - If no overlap: add to the current group
   - If overlap: start a new group
4. Groups are ordered deterministically (alphabetical by first role name)

Read-only roles are placed in a separate `read_only` list and run alongside
any group. They are excluded from scope checks and cannot hold write locks.

### Enhanced `cmd_dispatch` output

When `isolation: none` (scoped parallel mode), `cmd_dispatch` returns
`groups` instead of the flat `dispatch` list:

```json
{
  "stage": "design",
  "groups": [
    {
      "group": 1,
      "roles": [
        {"role": "architect", "agent": ".codex/agents/architect.toml", "mode": "write"},
        {"role": "pm", "agent": ".codex/agents/pm.toml", "mode": "write"},
        {"role": "researcher", "agent": ".codex/agents/researcher.toml", "mode": "write"}
      ],
      "parallel": true
    }
  ],
  "read_only": [],
  "policy": "none",
  "gate": "human",
  "blocked": []
}
```

When scopes overlap:
```json
{
  "stage": "implement",
  "groups": [
    {
      "group": 1,
      "roles": [
        {"role": "dev", "agent": ".codex/agents/dev.toml", "mode": "write"}
      ],
      "parallel": true
    },
    {
      "group": 2,
      "roles": [
        {"role": "infra", "agent": ".codex/agents/infra.toml", "mode": "write"}
      ],
      "parallel": true
    }
  ],
  "read_only": [],
  "policy": "none",
  "gate": "auto",
  "blocked": []
}
```

When `isolation: branch` or `isolation: worktree` (non-scoped modes), the
existing flat `dispatch` list is returned unchanged. The `groups` key is
only present for scoped parallel mode.

## Scope Audit

### `cmd_scope_audit`

New runtime command:

```
agenteam_rt.py scope-audit --run-id <id> --stage <stage> --baseline <commit-sha>
```

Arguments:
- `--baseline`: the git commit SHA captured before the stage's parallel
  execution began. The audit compares all changes since this baseline.

### Provenance: serialized commit capture

Git's index/HEAD cannot handle concurrent commits from parallel agents.
The solution: **agents write files in parallel, but commits are serialized
by the skill after all agents complete.**

Execution model:

```
1. Capture baseline: BASELINE=$(git rev-parse HEAD)

2. Launch all roles in the group as parallel subagents
   - Agents write/modify files but do NOT commit
   - Agent instructions: "Write your changes but do not run git add or git commit"

3. Wait for all agents in the group to complete

4. Pre-commit working-tree audit:
   - Run git status --porcelain to get all modified/untracked files
   - Check for files outside ALL declared write_scopes (catches read-only
     role writes and any unexpected file changes)
   - If unexpected files found: flag as violation, trigger serial fallback

5. Serialized commit capture (one role at a time):
   For each writing role in the group:
     a. git add <files matching role's write_scope>
        (use git add with explicit glob patterns from write_scope)
     b. If staged files exist:
        git commit -m "[ateam:<role>] <stage>: <summary>"
     c. If no staged files: skip (role made no changes)

6. Post-commit untracked check:
   - Run git status --porcelain again
   - Any remaining modified/untracked files were not claimed by any role's
     write_scope -> flag as violation
```

This gives clean per-role provenance via separate commits while keeping
the parallelism where it matters (agent thinking + file writing, which is
95%+ of the wall-clock time).

The scope audit then walks commits with full attribution:

Process:
1. Run `git log --name-only --format="%H %s" <baseline>..HEAD` to get
   commits with their changed files
2. Parse the `[ateam:<role>]` tag from each commit message
3. For each writing role, collect all files from its tagged commits
4. Check each file against the role's declared `write_scope` using `fnmatch`
5. The serialized commit capture guarantees: each commit is from exactly
   one role, and files are staged only from that role's scope. Violations
   here indicate a scope declaration mismatch, not a concurrent write issue.

Returns JSON:
```json
{
  "stage": "design",
  "baseline": "abc1234",
  "passed": true,
  "roles": {
    "architect": {"files_changed": ["docs/designs/api.md"], "out_of_scope": []},
    "pm": {"files_changed": ["docs/strategies/roadmap.md"], "out_of_scope": []},
    "researcher": {"files_changed": ["docs/research/caching.md"], "out_of_scope": []}
  }
}
```

On scope violation:
```json
{
  "stage": "design",
  "baseline": "abc1234",
  "passed": false,
  "roles": {
    "architect": {"files_changed": ["docs/designs/api.md", "docs/strategies/priority.md"], "out_of_scope": ["docs/strategies/priority.md"]},
    "pm": {"files_changed": ["docs/strategies/roadmap.md"], "out_of_scope": []}
  },
  "violations": [
    {"role": "architect", "file": "docs/strategies/priority.md", "expected_scope": ["docs/designs/**"]}
  ]
}
```

### Read-only role handling

Read-only roles (`can_write: false`) are detected at TWO checkpoints:

**Checkpoint 1: Pre-commit working-tree audit (step 4 above)**
After all agents complete but before any commits, `git status --porcelain`
reveals all file changes. Files outside all declared write_scopes are
flagged. This catches read-only agents that modified the working tree
even if they didn't attempt a commit. This is the primary detection
mechanism.

**Checkpoint 2: Post-commit audit**
After the serialized commit capture (step 5), any remaining uncommitted
changes (`git status --porcelain` again) indicate files that no role's
scope claimed. These are flagged as violations.

Both checkpoints catch the real failure mode: a "read-only" agent that
writes files accidentally. Any violation triggers the same serial fallback
as a write_scope violation from a writing role.

```json
{
  "violations": [
    {"role": "unknown", "file": "src/auth.py", "reason": "file outside all declared write_scopes (possibly from read-only agent)"}
  ]
}
```

## Serial Fallback

### Baseline safety

The baseline commit (`$BASELINE`) is captured at the start of each stage's
parallel dispatch. It represents the state AFTER all prior stages have
completed and committed their work. Resetting to baseline only discards
the current stage's parallel attempt -- prior stage outputs are safe because
they are committed before any parallel dispatch begins.

**Rule: each stage's output must be committed before the next stage begins.**
The run skill ensures this via the serialized commit capture (step 5 of
the provenance model). The skill verifies tagged commits exist before
advancing to the next stage.

### When a scope audit fails:

1. Log which role touched which out-of-scope files (from the violations list)
2. **Reset to baseline:** `git reset --hard <baseline>` to discard ONLY this
   stage's parallel work. Prior stage outputs are safe (committed before baseline).
3. **Re-run the stage serially:** dispatch each writing role one at a time
   (same order as groups, flattened)
4. **No scope audit after serial rerun** (serial mode is the trusted fallback)
5. **Stage verification still runs** after the serial rerun

The user sees:
```
Scope violation detected in parallel execution:
  @Architect wrote to docs/strategies/priority.md (outside scope: docs/designs/**)
Falling back to serial execution for stage "design"...
```

## Run Skill Changes

The `run` skill's stage dispatch loop changes for scoped parallel mode:

```
For each stage:

  1. Get dispatch plan (may contain groups)

  2. If plan has "groups" key (scoped parallel mode):
     a. Capture baseline: BASELINE=$(git rev-parse HEAD)
     b. For each group in order:
        - Launch all roles in the group as parallel subagents
        - Wait for all to complete
        - Run scope audit:
          agenteam_rt.py scope-audit --run-id <id> --stage <stage> --baseline $BASELINE
        - If audit fails:
          git reset --hard $BASELINE
          Log violation details
          Re-dispatch entire stage serially (flat dispatch, no groups)
          Break out of group loop
     c. After all groups complete (or serial fallback):
        Run stage verification (verify-plan + verify-stage.sh)
        Run gate check

  3. If plan has flat "dispatch" key (branch/worktree mode):
     Existing behavior (serial dispatch, one writer at a time)
```

## HOTL Contracts

### Intent Contract

```
intent: Enable scoped parallel execution for writing agents within a stage
        when their write_scopes are provably disjoint
constraints:
  - Runtime partitions writers into parallel-safe groups (no scope overlap)
  - Groups run sequentially; roles within a group run in parallel
  - Read-only roles run alongside any group; write_scope audit excludes them
    BUT the audit detects if a read-only role accidentally writes files
  - Parallel agents write files but do NOT commit (agents instructed accordingly)
  - Skill serializes commit capture after all agents complete (one role at a time)
  - Pre-commit working-tree audit catches files outside all declared scopes
  - Post-commit scope audit attributes files to roles via tagged commits
  - Unclaimed files after commit capture are flagged as violations
  - Scope violation triggers full stage reset + serial fallback
  - Reset to baseline only discards current stage (prior stages are committed)
  - Serial fallback reruns from clean baseline (tainted work discarded)
  - Existing isolation: branch and isolation: worktree unaffected
  - Stage verification and gate checks run after dispatch (same as serial)
  - No new config surface beyond existing isolation: none and write_scope
success_criteria:
  - Non-overlapping writers in a stage dispatch in parallel
  - Overlapping writers are partitioned into separate sequential groups
  - Pre-commit audit catches working-tree writes outside all scopes
  - Serialized commit capture produces clean per-role commits
  - Post-commit audit catches unclaimed file changes
  - Scope audit detects out-of-scope file changes per role
  - Scope audit detects read-only roles that accidentally wrote files
  - Scope violation triggers reset to baseline + serial fallback
  - Reset to baseline preserves prior stage outputs (committed before baseline)
  - Existing serial/worktree isolation modes continue to work unchanged
  - Pipeline completes correctly with parallel dispatch
  - Parallel dispatch is faster than serial for non-overlapping stages
risk_level: medium
```

### Verification Contract

```
verify_steps:
  - run tests: python3 -m pytest test/test_runtime.py -v
  - run tests: bats test/smoke.bats
  - check: dispatch with isolation:none returns groups (not flat dispatch)
  - check: writer group partitioning puts non-overlapping roles in same group
  - check: overlapping roles are in separate groups
  - check: read-only roles are in read_only list, not in groups
  - check: scope-audit detects out-of-scope file changes
  - check: scope-audit passes when all files are within scope
  - check: scope-audit excludes read-only roles
  - check: serial fallback resets to baseline commit
  - check: existing isolation: branch mode still works (flat dispatch)
  - confirm: parallel dispatch for design stage (3 non-overlapping writers)
    completes faster than serial
```

### Governance Contract

```
approval_gates:
  - Design approval (this document)
  - Implementation review before merge
rollback: git revert; scoped parallel is additive (serial mode unchanged)
ownership: user approves design; implementation is autonomous
```

## Implementation Slices

```
Slice 1: Writer group partitioning in runtime
  Files: runtime dispatch logic
  Tests: TestWriterGroups -- non-overlapping, overlapping, mixed, read-only

Slice 2: Enhanced cmd_dispatch for grouped output
  Files: runtime dispatch
  Tests: TestGroupedDispatch -- groups key present for isolation:none,
         flat dispatch for isolation:branch

Slice 3: cmd_scope_audit
  Files: runtime (new command)
  Tests: TestScopeAudit -- pass, fail, out-of-scope detection, read-only excluded

Slice 4: Update run skill with parallel group dispatch
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 5: Update run skill with scope audit + serial fallback
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 6: Integration tests
  Files: test/test_runtime.py
  Tests: e2e scoped parallel dispatch with audit
  Gate: human
```
