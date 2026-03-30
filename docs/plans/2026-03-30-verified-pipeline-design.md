# AgenTeam v2: Verified Pipeline

**Date:** 2026-03-30
**Status:** Draft

## Problem

AgenTeam organizes work into specialist roles and pipelines, but when an agent
says "done," nothing checks. The pipeline has the shape of a quality process
but no teeth. Verification is prompt-based (trust), not runtime-enforced.

Without HOTL, AgenTeam cannot vouch for the work it produces.

## Solution

Add three capabilities to the standalone pipeline:

1. **Stage verification** -- each stage gets a `verify` command that must exit 0
2. **Retry on failure** -- configurable per stage, re-dispatches the role with failure context
3. **Mandatory final verification** -- runs test suite + lint before declaring success

## Architecture: C+ (Hybrid with State Recording)

```
Skill (run)  →  runtime verify-plan (JSON)  →  scripts/verify-stage.sh (execute)
                                              →  runtime record-verify (persist state)
                                              →  skill reads state, decides retry/block/continue
```

- **Runtime resolves** config + policy (verify-plan, final-verify-plan)
- **Runtime records** verify results in state (record-verify)
- **Runtime does NOT execute** shell commands (stays a resolver/state authority)
- **Scripts execute** verification commands deterministically
- **Skills orchestrate** the lifecycle (retry loop, gate enforcement, completion)

### Workspace binding

Verification MUST run in the same isolated workspace as the stage work.
The `verify-plan` output includes a `cwd` field:

- **Branch mode:** `cwd` is the project root (same checkout, agent worked here)
- **Worktree mode:** `cwd` is the worktree path (e.g., `.ateam-worktrees/dev-add-auth`)

`verify-stage.sh run <command> --cwd <path>` executes the command in the
specified directory. This prevents verification from running against stale
code in the controller's workspace.

On failure, the workspace is preserved for debugging (same rule as
worktree cleanup: dirty = preserved).

## Config Schema

### Stage verification

```yaml
pipeline:
  stages:
    - name: design
      roles: [architect]
      gate: human
      verify: "test -f docs/designs/*.md"
      max_retries: 0

    - name: implement
      roles: [dev]
      gate: auto
      verify: "python3 -m pytest tests/ -v"
      max_retries: 2

    - name: test
      roles: [qa]
      gate: auto
      verify: "python3 -m pytest -v"
      max_retries: 1

    - name: review
      roles: [reviewer]
      gate: reviewer       # reviewer agent approval
      max_retries: 0
```

### Final verification (fail-closed)

```yaml
final_verify:
  - "python3 -m pytest -v"
  - "ruff check ."

final_verify_policy: block    # block (default) | warn
final_verify_max_retries: 1
```

**Fail-closed rule:** If `final_verify` is omitted or empty, the runtime
auto-detects commands using the same repo-signal detection used for stages.
If auto-detection also finds nothing, `final-verify-plan` returns
`"policy": "unverified"` and the run skill prints a prominent warning:

> "No final verification commands configured or detected. AgenTeam cannot
> vouch for this run. Add `final_verify` to your config or install a test
> framework."

The pipeline still completes (it would be hostile to block with zero
configured checks), but it never claims verified success. The trust
promise is explicitly scoped: **AgenTeam vouches for work only when
verification commands are configured or auto-detected.**

### Auto-detection (when verify is omitted)

If a stage has no `verify` field, the runtime auto-detects from repo signals:

| Signal | Verify command |
|--------|---------------|
| `pytest.ini`, `pyproject.toml [tool.pytest]`, `tests/` dir | `python3 -m pytest -v` |
| `package.json` with `test` script | `npm test` |
| `go.mod` | `go test ./...` |
| `Cargo.toml` | `cargo test` |
| `Makefile` with `test` target | `make test` |
| None detected | No verify (stage passes without check) |

Auto-detection runs once at pipeline init and caches the result in state.
Users can override with explicit `verify` at any time.

## Gate Types

| Gate | Who approves | When to use |
|------|-------------|-------------|
| `auto` | Nobody (continue) | Low-risk stages |
| `human` | User only | Design approval, final review, security |
| `reviewer` | Reviewer agent | Code review checkpoints |
| `qa` | QA agent | Test-stage readiness |

Rules:
- `dev` never approves its own work (no self-merge)
- `human` gates are never satisfied by agents
- Agent gates (`reviewer`, `qa`) can be overridden by `human` if the agent blocks

### Agent gate execution model

When a stage has `gate: reviewer` or `gate: qa`:

1. The stage's primary role(s) complete their work (e.g., dev writes code)
2. Verification runs (if configured)
3. The gate agent is dispatched as a **separate subagent** (not the stage actor)
   - For `gate: reviewer`: dispatch the `reviewer` role with the stage output
   - For `gate: qa`: dispatch the `qa` role with the stage output
4. The gate agent produces a verdict: PASS, PASS WITH WARNINGS, or BLOCK
5. The skill parses the verdict:
   - PASS or PASS WITH WARNINGS: record `gate: approved` in state, continue
   - BLOCK: record `gate: rejected` in state, pause for human override
6. The gate agent is NEVER the same agent that produced the stage work
   (reviewer on review stage = approving own output = not allowed;
   in that case, fall back to `gate: human`)

State persistence:
```json
{
  "stages": {
    "implement": {
      "gate": "reviewer",
      "gate_result": "approved",
      "gate_agent": "reviewer",
      "gate_verdict": "PASS WITH WARNINGS: 2 WARN findings"
    }
  }
}
```

## Runtime Commands (New)

### `cmd_verify_plan`

```
agenteam_rt.py verify-plan <stage> --run-id <id>
```

Returns JSON:
```json
{
  "stage": "implement",
  "verify": "python3 -m pytest tests/ -v",
  "source": "config",
  "max_retries": 2,
  "attempt": 1,
  "cwd": "/path/to/project"
}
```

In worktree mode, `cwd` points to the worktree:
```json
{
  "stage": "implement",
  "verify": "python3 -m pytest tests/ -v",
  "source": "config",
  "max_retries": 2,
  "attempt": 1,
  "cwd": "/path/to/project/.ateam-worktrees/dev-add-auth"
}
```

If no verify in config, auto-detects:
```json
{
  "stage": "implement",
  "verify": "python3 -m pytest -v",
  "source": "auto-detected",
  "max_retries": 2,
  "attempt": 1,
  "cwd": "/path/to/project"
}
```

If no verify and no auto-detection:
```json
{
  "stage": "design",
  "verify": null,
  "source": "none",
  "max_retries": 0,
  "attempt": 0
}
```

### `cmd_record_verify`

```
agenteam_rt.py record-verify --run-id <id> --stage <stage> --result pass|fail [--output "..."]
```

Persists into `.agenteam/state/<id>.json`:
```json
{
  "stages": {
    "implement": {
      "status": "in-progress",
      "verify_attempts": [
        {"attempt": 1, "result": "fail", "output": "2 tests failed..."},
        {"attempt": 2, "result": "pass", "output": "all tests passed"}
      ],
      "verify_result": "pass"
    }
  }
}
```

### `cmd_record_gate`

```
agenteam_rt.py record-gate --run-id <id> --stage <stage> --gate-type <auto|human|reviewer|qa> --result <approved|rejected> [--verdict "..."]
```

Persists gate outcome into `.agenteam/state/<id>.json`:
```json
{
  "stages": {
    "implement": {
      "gate": "reviewer",
      "gate_result": "approved",
      "gate_agent": "reviewer",
      "gate_verdict": "PASS WITH WARNINGS: 2 WARN findings"
    }
  }
}
```

This keeps the runtime as the sole state authority. Skills call `record-gate`
after processing the gate agent's output; they never edit state files directly.

### `cmd_final_verify_plan`

```
agenteam_rt.py final-verify-plan --run-id <id>
```

Returns JSON (includes `cwd` -- same isolated workspace as stage verification):
```json
{
  "commands": ["python3 -m pytest -v", "ruff check ."],
  "policy": "block",
  "max_retries": 1,
  "source": "config",
  "cwd": "/path/to/project"
}
```

`cwd` follows the same rules as `verify-plan`: project root for branch mode,
worktree path for worktree mode. The run skill must pass `--cwd` for every
final-verify command.

## Shared Script: `scripts/verify-stage.sh`

```bash
verify-stage.sh run <command> --cwd <path>
```

`--cwd` is mandatory. Executes the command in the specified directory
(the isolated branch checkout or worktree). Returns JSON:
```json
{
  "exit_code": 0,
  "stdout": "...",
  "stderr": "...",
  "passed": true
}
```

On non-zero exit:
```json
{
  "exit_code": 1,
  "stdout": "...",
  "stderr": "FAILED test_auth.py::test_login...",
  "passed": false
}
```

## Run Skill Changes

### After each stage dispatch (between collect outputs and gate check):

```
1. Get verify plan:
   agenteam_rt.py verify-plan <stage> --run-id <id>

2. If verify is null: skip verification, continue to gate.

3. Execute verification (in the isolated workspace):
   scripts/verify-stage.sh run "<verify command>" --cwd "<cwd from verify-plan>"

4. Record result:
   agenteam_rt.py record-verify --run-id <id> --stage <stage> --result pass|fail --output "..."

5. If passed: continue to gate check.

6. If failed and attempts < max_retries:
   - Log: "Verification failed (attempt N/max). Re-dispatching for repair..."
   - Determine repair role(s) using the same write-scope rule as final-repair:
     * Single-role stage: re-dispatch that role
     * Multi-role stage: identify which role's write_scope covers the failing
       files. If verify output references test files -> qa. If source files -> dev.
       If unclear or multiple scopes -> re-dispatch ALL writing roles from the stage.
       Read-only roles (e.g., reviewer) are never re-dispatched for repair.
     * All-read-only stage (e.g., design with only architect reading): no legal
       repair role exists. Fall through to step 7 immediately (fail-fast to human).
       Validation rule: `validate_config` should warn if a stage has both
       `max_retries > 0` and no writing roles, since retries can never succeed.
   - Re-dispatch repair role(s) with the failure output as context
   - The agent sees what failed and attempts to fix it
   - Go to step 3 (re-verify)

7. If failed and attempts >= max_retries (or no legal repair role):
   - Log: "Verification failed after N attempts. Pipeline stopped."
   - Mark stage as "failed" in state
   - Show failure output to user
   - Do not advance to next stage
```

### After the final configured stage:

```
1. Get final verify plan:
   agenteam_rt.py final-verify-plan --run-id <id>

2. Run each command in sequence via verify-stage.sh --cwd <cwd from plan>
   (same isolated workspace as stage verification -- mandatory)

3. If all pass: print success summary.

4. If any fail and retries remain:
   - Determine repair role(s) from failure context:
     * If failing files are in dev's write_scope (src/**, lib/**) -> dispatch dev
     * If failing files are in qa's write_scope (tests/**) -> dispatch qa
     * If both areas fail -> dispatch dev AND qa (parallel if scoped, serial otherwise)
     * If unclear -> dispatch dev as fallback (most common case)
   - Re-dispatch repair role(s) with failure output as context
   - Re-run final_verify

5. If still failing:
   - block mode: mark run failed, keep branch open, print failure summary
   - warn mode: print warning summary with clear "TESTS FAILING" label,
     complete the run but do not suggest merging
```

## HOTL Contracts

### Intent Contract

```
intent: Add verified pipeline so AgenTeam can vouch for its work without HOTL
constraints:
  - Runtime stays a resolver/state authority (no shell execution)
  - Scripts own command execution (deterministic, not prompt-based)
  - Skills orchestrate lifecycle (retry loop, gate, completion)
  - Stage verify auto-detected when not configured (low friction)
  - Retry is stage-configurable with sensible defaults (implement: 2, test: 1, others: 0)
  - Final verification is mandatory by default (block policy)
  - dev never approves its own work
  - human gates are never satisfied by agents
success_criteria:
  - Pipeline stops on verify failure when retries exhausted
  - Retry re-dispatches role with failure context
  - Final verify runs test suite + lint before declaring success
  - Auto-detection finds pytest/npm/go/cargo/make test commands
  - State file records verify attempts and results
  - Legacy configs without verify fields still work (no verify = skip)
  - Verification runs in the isolated workspace (branch/worktree cwd)
  - Final-repair dispatches correct role(s) based on write_scope
  - Agent gates (reviewer, qa) dispatch a separate agent, not the stage actor
  - No final_verify configured + no auto-detect = "unverified" warning (not silent pass)
  - AgenTeam only claims verified success when verify commands are present
risk_level: medium
```

### Verification Contract

```
verify_steps:
  - run tests: python3 -m pytest test/test_runtime.py -v
  - run tests: bats test/smoke.bats
  - check: verify-plan returns correct JSON for stages with/without verify
  - check: verify-plan auto-detects pytest in this repo
  - check: record-verify persists attempts in state file
  - check: final-verify-plan returns commands and policy
  - check: verify-stage.sh captures exit code, stdout, stderr correctly
  - check: verify-stage.sh returns passed:true on exit 0, passed:false on non-zero
  - check: run skill stops pipeline on verify failure after max retries
  - check: run skill retries by re-dispatching role with failure output
  - check: final_verify blocks completion when tests fail (block mode)
  - check: final_verify warns but completes when tests fail (warn mode)
  - confirm: legacy config without verify fields works (stages skip verification)
```

### Governance Contract

```
approval_gates:
  - Design approval (this document)
  - Implementation review before merge
rollback: git revert; verification is additive (no existing behavior changed)
ownership: user approves design; implementation is autonomous
```

## Implementation Slices

```
Slice 1: scripts/verify-stage.sh
  Files: scripts/verify-stage.sh (new)
  Tests: bats tests for pass/fail/timeout cases

Slice 2: cmd_verify_plan + auto-detection
  Files: runtime/agenteam_rt.py (or agenteam/cli.py per new modular layout)
  Tests: TestVerifyPlan class -- config-defined, auto-detected, missing

Slice 3: cmd_record_verify
  Files: runtime state management
  Tests: TestRecordVerify -- persist attempts, read back

Slice 4: cmd_final_verify_plan
  Files: runtime
  Tests: TestFinalVerifyPlan -- commands, policy, retries

Slice 5: cmd_record_gate
  Files: runtime state management
  Tests: TestRecordGate -- persist gate outcome, agent vs human, self-approval prevention

Slice 6: Update run skill with verify-retry loop
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 7: Update run skill with final_verify
  Files: skills/run/SKILL.md
  Tests: manual invocation

Slice 8: Update config template with verify examples
  Files: templates/agenteam.yaml.template
  Tests: smoke test

Slice 9: Gate type expansion (reviewer, qa)
  Files: runtime dispatch, skills/run/SKILL.md
  Tests: TestGateTypes -- agent gate dispatch, verdict parsing, state persistence

Slice 10: Final integration testing
  Files: test/test_runtime.py
  Tests: e2e pipeline with verify
  Gate: human
```
