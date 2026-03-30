# AgenTeam v3: Governance Completion

**Date:** 2026-03-30
**Status:** Draft

## Problem

AgenTeam v2.1 has verification, retry, scoped parallel writes, and branch
isolation. But four governance gaps remain:

1. **No cross-stage rework.** When tests fail, we retry QA -- but we don't
   loop back to dev to fix the code that caused the failure.
2. **No rollback.** If a stage produces bad work, the only recovery is retry
   or manual intervention. There's no mechanism to reset to a known-good state.
3. **No run report.** After a pipeline run, there's no durable record of what
   happened. The user sees chat output but nothing persists to the repo.
4. **No gate criteria.** Gates are binary (agent PASS/BLOCK or human approve).
   There's no automated check like "did this stage change more than 15 files?"

## Solution

Four additive features that complete the governance story. No breaking changes.
No new abstraction layers. No architecture refactor.

## Feature 1: Cross-Stage Rework

### Problem

Current retry is per-stage: if `test` verify fails, QA is re-dispatched.
But QA can't fix dev's code -- it can only rewrite tests. The actual fix
often requires dev to change source code based on test failure output.

### Design

When the `test` stage verify fails AND the failure indicates source code
issues (not just bad tests), the run skill loops back to `dev`:

```
implement -> test -> VERIFY FAILS
                  -> dispatch dev with failure output
                  -> dev fixes code
                  -> re-run test stage verify
                  -> if still fails: retry up to max, then escalate to human
```

### Config

```yaml
pipeline:
  stages:
    - name: test
      roles: [qa]
      verify: "python3 -m pytest -v"
      max_retries: 2
      rework_to: implement    # NEW: on verify failure, loop back to this stage
```

`rework_to` is optional. When set, verify failure dispatches the `rework_to`
stage's roles first, then re-runs the current stage's verify. The rework
counter is shared: `max_retries` counts total attempts across both stages.

When `rework_to` is not set, behavior is unchanged (retry within the same stage).

### Runtime

New field in `verify-plan` output:

```json
{
  "stage": "test",
  "verify": "python3 -m pytest -v",
  "max_retries": 2,
  "attempt": 1,
  "rework_to": "implement",
  "rework_roles": ["dev"],
  "cwd": "/path/to/project"
}
```

`record-verify` already tracks attempts. Add `rework_stage` to attempt entries:

```json
{
  "verify_attempts": [
    {"attempt": 1, "result": "fail", "rework_stage": "implement"},
    {"attempt": 2, "result": "pass", "rework_stage": null}
  ]
}
```

### Skill change

Run skill verify-retry loop adds one branch:

```
If failed and rework_to is set:
  1. Dispatch rework_to stage's roles with failure output
  2. Those roles fix the code (using their own write_scope)
  3. Re-run current stage's verify (not the rework stage's)
  4. Count against max_retries
```

## Feature 2: Per-Stage Rollback

### Problem

If a stage produces bad work and retries are exhausted, the pipeline stops.
But the bad work is still on the branch. The user must manually figure out
what to revert.

### Design

Capture a git baseline before each stage. On failure (retries exhausted),
offer rollback to the stage's baseline.

This extends the baseline capture already used in scoped parallel mode to
ALL isolation modes.

### Runtime

New command: `cmd_stage_baseline`

```
agenteam_rt.py stage-baseline --run-id <id> --stage <stage> --action capture|rollback
```

**capture:** Records `git rev-parse HEAD` in state as the stage's baseline.
Called by the run skill before dispatching a stage.

```json
{
  "stages": {
    "implement": {
      "baseline": "abc1234def"
    }
  }
}
```

**rollback:** Returns the baseline commit for the given stage so the skill
can run `git reset --hard <baseline>`.

```json
{
  "stage": "implement",
  "baseline": "abc1234def",
  "action": "rollback"
}
```

### Skill change

Run skill stage loop:

```
Before each stage dispatch:
  agenteam_rt.py stage-baseline --run-id <id> --stage <stage> --action capture

If stage fails (retries exhausted):
  Ask user: "Stage failed after N attempts. Rollback to pre-stage state? (yes/skip)"
  If yes:
    baseline = agenteam_rt.py stage-baseline --run-id <id> --stage <stage> --action rollback
    git reset --hard <baseline>
    Log: "Rolled back to pre-implement state"
```

Rollback is always user-confirmed (never automatic). The `auto_rollback_on_fail`
from the v2 design doc is deferred -- manual rollback is safer for v3.

## Feature 3: Run Report

### Problem

After a pipeline run, there's no durable record. The user sees chat output
but can't review what happened later, share it with teammates, or use it
for debugging.

### Design

At pipeline completion (or failure), write a human-readable report to
`.agenteam/reports/<run-id>.md`.

### Report format

```markdown
# AgenTeam Run Report

**Run:** 20260330T150000Z
**Task:** Add user authentication
**Status:** completed | failed | rolled-back
**Duration:** 4m 32s
**Branch:** ateam/run/20260330T150000Z

## Pipeline

| Stage | Status | Verify | Gate | Duration |
|-------|--------|--------|------|----------|
| research | passed | - | auto | 15s |
| strategy | passed | - | human: approved | 22s |
| design | passed | docs exist | human: approved | 45s |
| implement | passed | pytest (2 attempts) | auto | 1m 10s |
| test | passed | pytest (1 attempt) | auto | 30s |
| review | passed | - | human: approved | 40s |

## Final Verification

- python3 -m pytest -v: PASSED
- ruff check .: PASSED

## Rework History

- test attempt 1: FAILED (2 tests failed)
  - rework to: implement (dev re-dispatched)
- test attempt 2: PASSED
```

### Runtime

New command: `cmd_run_report`

```
agenteam_rt.py run-report --run-id <id>
```

Reads the state file and assembles the report as JSON. The skill renders
it to markdown and writes to `.agenteam/reports/<run-id>.md`.

Returns JSON:
```json
{
  "run_id": "20260330T150000Z",
  "task": "Add user authentication",
  "status": "completed",
  "stages": [...],
  "final_verify": {...},
  "rework_history": [...],
  "report_path": ".agenteam/reports/20260330T150000Z.md"
}
```

### Skill change

Run skill completion section:

```
After final verification (or on pipeline failure):
  report = agenteam_rt.py run-report --run-id <id>
  Write report to report_path as markdown
  Show report summary to user
  Log: "Run report saved to .agenteam/reports/<run-id>.md"
```

## Feature 4: Lightweight Gate Criteria

### Problem

Gates are binary: agent says PASS or human approves. There's no automated
sanity check. An agent could change 100 files and the gate wouldn't notice.

### Design

Add optional criteria to stage config. The runtime evaluates them against
the actual git diff stats. If criteria fail, the gate blocks.

### Config

```yaml
pipeline:
  stages:
    - name: implement
      roles: [dev]
      verify: "python3 -m pytest -v"
      max_retries: 2
      gate: auto
      criteria:                     # NEW
        max_files_changed: 15
        scope_paths: ["src/**", "lib/**"]
        requires_tests: true
```

Three criteria for v3:

| Criterion | What it checks | Default |
|-----------|---------------|---------|
| `max_files_changed` | `git diff --stat` file count since stage baseline | No limit |
| `scope_paths` | All changed files match at least one glob pattern | Stage roles' write_scope |
| `requires_tests` | At least one test file was modified or created | false |

### Runtime

New command: `cmd_gate_eval`

```
agenteam_rt.py gate-eval --run-id <id> --stage <stage>
```

Process:
1. Read stage criteria from config (with defaults)
2. Get stage baseline from state
3. Run `git diff --stat <baseline>..HEAD` for file count
4. Run `git diff --name-only <baseline>..HEAD` for file list
5. Check each criterion
6. Return JSON with pass/fail per criterion

```json
{
  "stage": "implement",
  "passed": false,
  "criteria": {
    "max_files_changed": {"configured": 15, "actual": 23, "passed": false},
    "scope_paths": {"configured": ["src/**"], "actual_out_of_scope": [], "passed": true},
    "requires_tests": {"configured": true, "test_files_found": true, "passed": true}
  },
  "failed_criteria": ["max_files_changed"]
}
```

### Skill change

Run skill gate check, after verify passes:

```
If stage has criteria:
  result = agenteam_rt.py gate-eval --run-id <id> --stage <stage>
  If result.passed: continue to gate
  If result.failed:
    Log: "Gate criteria failed: max_files_changed (23 > 15)"
    Escalate to human: "Stage exceeded criteria. Approve anyway? (yes/no)"
    If approved: record-gate with override note
    If rejected: mark stage failed
```

Criteria failures always escalate to human. They are guardrails, not blockers.
The user can override with a note explaining why the criteria don't apply.

## HOTL Contracts

### Intent Contract

```
intent: Complete the governance story with cross-stage rework, per-stage
        rollback, run reports, and lightweight gate criteria
constraints:
  - All features are additive (no breaking changes to existing behavior)
  - No new abstraction layers (flat modules, same architecture)
  - Cross-stage rework uses existing verify-retry mechanism + new rework_to field
  - Rollback is always user-confirmed (never automatic in v3)
  - Run report is a human-readable markdown artifact
  - Gate criteria are guardrails that escalate to human, not hard blockers
  - Criteria evaluation uses git diff stats (no LLM calls, deterministic)
success_criteria:
  - test verify failure with rework_to dispatches dev, then re-verifies test
  - Per-stage baseline captured and recoverable via rollback
  - .agenteam/reports/<run-id>.md written at pipeline completion/failure
  - gate-eval checks max_files_changed, scope_paths, requires_tests
  - Criteria failure escalates to human with override option
  - All existing tests still pass
  - Legacy configs without rework_to/criteria work unchanged
risk_level: medium
```

### Verification Contract

```
verify_steps:
  - run tests: python3 -m pytest test/test_runtime.py -v
  - run tests: bats test/smoke.bats
  - check: verify-plan returns rework_to and rework_roles when configured
  - check: record-verify tracks rework_stage in attempts
  - check: stage-baseline captures and returns correct commit SHA
  - check: run-report assembles correct JSON from state
  - check: gate-eval detects max_files_changed violation
  - check: gate-eval detects scope_paths violation
  - check: gate-eval detects requires_tests violation
  - check: gate-eval passes when all criteria met
  - confirm: legacy config without rework_to/criteria still works
```

### Governance Contract

```
approval_gates:
  - Design approval (this document)
  - Implementation review before merge
rollback: git revert; all features are additive
ownership: user approves design; implementation is autonomous
```

## Implementation Slices

```
Slice 1: Cross-stage rework in runtime
  Files: runtime/agenteam/verify.py (extend verify-plan with rework_to)
  Tests: TestCrossStageRework -- rework_to in verify-plan, rework_stage in record-verify

Slice 2: Cross-stage rework in run skill
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 3: Per-stage rollback in runtime
  Files: runtime/agenteam/state.py (cmd_stage_baseline)
  Tests: TestStageBaseline -- capture, rollback, missing baseline

Slice 4: Per-stage rollback in run skill
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 5: Run report in runtime
  Files: runtime/agenteam/report.py (new, cmd_run_report)
  Tests: TestRunReport -- completed run, failed run, rework history

Slice 6: Run report in run skill
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 7: Gate criteria in runtime
  Files: runtime/agenteam/gates.py (new, cmd_gate_eval)
  Tests: TestGateEval -- max_files, scope_paths, requires_tests, all pass, mixed

Slice 8: Gate criteria in run skill + config template
  Files: skills/run/SKILL.md, templates/agenteam.yaml.template
  Tests: manual invocation

Slice 9: Integration tests
  Files: test/test_runtime.py
  Tests: e2e pipeline with rework + rollback + report + criteria
  Gate: human
```
