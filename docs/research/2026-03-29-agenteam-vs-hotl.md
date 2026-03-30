# Research: AgenTeam vs HOTL -- Capability Comparison

**Date**: 2026-03-29
**Triggered by**: Understanding what a user gets with AgenTeam alone, without HOTL
**Relevance**: Defines the unique value proposition of each plugin and identifies the gap for AgenTeam-only users.

---

## Executive Summary

AgenTeam and HOTL solve different problems along the same development pipeline. AgenTeam answers **"who does the work"** -- it provides a team of specialist agents with role-based dispatch, write isolation, and coordination policies. HOTL answers **"how is the work done safely"** -- it provides a governed execution engine with step-level verification loops, typed verification, and resume capability. Together they form a full stack; alone, each has significant gaps.

A user who installs only AgenTeam gets a multi-agent team that can be dispatched through a pipeline, but the agents execute work without any automated verification or recovery mechanism. A user who installs only HOTL gets rigorous execution governance, but every agent is a generic worker with no role specialization or write-scope enforcement.

---

## Dimension 1: Execution Model

### AgenTeam: Role-based dispatch through a stage pipeline

AgenTeam's execution model is a **pipeline of stages**, each stage dispatching one or more role-specific agents. The runtime (`runtime/agenteam_rt.py`) produces a JSON dispatch plan; the skill layer (`skills/run/SKILL.md`) reads that plan and launches Codex subagents.

The default standalone pipeline is:
```
research -> strategy -> design -> plan -> implement -> test -> review
```

Each stage:
1. Calls `agenteam_rt.py dispatch <stage>` to get a list of roles (line 421-493 of the runtime)
2. Launches each role as a Codex subagent using the generated `.codex/agents/<role>.toml` file
3. Collects outputs and passes them as context to the next stage
4. Checks gates (human or auto) between stages

The stages are configurable via `pipeline.stages` in the config YAML. Roles carry metadata like `can_write`, `write_scope`, `parallel_safe`, and `participates_in`. The runtime enforces write locks in serial mode -- only one writer holds the lock at a time (lines 458-481).

**Key characteristic**: The runtime is a pure planner. It outputs JSON. It never executes agent work, runs shell commands, or verifies outputs. The skill layer invokes Codex subagents and trusts their output.

### HOTL: Step-level execution with verification loops

HOTL's execution model is a **workflow state machine**. A workflow file (`hotl-workflow-<slug>.md`) defines discrete steps, each with an action, a verification command, loop conditions, and optional gates. The `hotl-rt` bash runtime (`runtime/hotl-rt`) manages all state transitions.

For each step, the executor:
1. Calls `hotl-rt step N start` to persist the step start
2. Executes the action (the agent does the work)
3. Calls `hotl-rt step N verify` to run the verification command
4. If verify fails and `loop: until [condition]`:
   - Calls `hotl-rt step N retry` then `hotl-rt step N start`
   - Retries up to `max_iterations` (default 3)
5. If verify passes: step is marked done, workflow checkbox updated to `[x]`
6. If a gate exists: either auto-approves (risk_level != high) or pauses for human

HOTL supports three execution modes over this same state machine:
- **loop-execution**: single agent, autonomous, auto-approve compatible
- **executing-plans**: linear with human checkpoints every 3 steps
- **subagent-execution**: controller keeps governance, delegates implementation steps to fresh subagents

**Key characteristic**: Every step has a verification boundary. The agent does not self-certify completion -- the runtime runs the verify command and atomically transitions the state. The agent cannot claim "done" without evidence.

### Concrete difference

| Aspect | AgenTeam | HOTL |
|--------|----------|------|
| Unit of work | Stage (multi-step, role-scoped) | Step (single action, 2-5 min) |
| Who decides "done" | The agent self-reports | Runtime runs verify command |
| Retry on failure | No automatic retry | Loop with max_iterations |
| Execution state | Stage-level status (pending/in-progress/done) | Step-level with attempt count, timestamps, verify output |
| Concurrency model | Parallel readers, serial writers | One step at a time, subagent delegation optional |

---

## Dimension 2: Verification

### HOTL: Typed verification system

HOTL has a full verification subsystem implemented in `hotl-rt` (lines 157-485 of the runtime). Four verification types:

1. **shell** (default): Runs a shell command, captures stdout/stderr, passes on exit 0. Used for `pytest`, `ruff check`, `npm test`, etc.
   ```
   verify: pytest tests/ -v
   ```

2. **artifact**: Checks that a file or directory exists and optionally matches assertions (`exists`, `contains`, `matches-glob`).
   ```yaml
   verify:
     type: artifact
     path: migrations
     assert:
       kind: matches-glob
       value: "*.sql"
   ```

3. **browser**: Capability-gated visual inspection (falls back to human-review if unavailable).
   ```yaml
   verify:
     type: browser
     url: http://localhost:3000/dashboard
     check: priority badge renders with correct color
   ```

4. **human-review**: Pauses execution, sets run status to `paused`, requires explicit `hotl-rt gate N approved --mode human` call.

HOTL also has a **multi-check** type for steps requiring multiple verification passes (e.g., run tests AND check artifact exists).

Additionally, HOTL mandates the `verification-before-completion` skill (`skills/verification-before-completion/SKILL.md`) before any "done" claim: run tests, run linter, confirm specific behavior, check for regressions. This is not optional.

The `tdd` skill (`skills/tdd/SKILL.md`) enforces RED-GREEN-REFACTOR: never write code before a failing test exists. The `systematic-debugging` skill requires reproduce -> understand -> hypothesize -> fix-and-verify phases before any fix.

### AgenTeam: No verification

AgenTeam has **zero verification infrastructure**. When an agent writes code:

- No test is automatically run
- No verify command exists in the dispatch plan
- No loop/retry mechanism exists
- The agent's self-reported output is accepted as-is
- The next stage receives the previous stage's output without validation

The QA role (`roles/qa.yaml`) writes tests, and the reviewer role (`roles/reviewer.yaml`) reviews code, but these are separate pipeline stages. The reviewer may catch issues, but:
- There is no mechanism to send work back to a previous stage
- There is no retry loop if the reviewer finds problems
- The reviewer's findings are presented to the user at the end, not used to gate merging

**What happens when an AgenTeam agent writes bad code**: The implement stage completes. The test stage (QA agent) may write tests that reveal failures, but those test failures are reported as output, not as a blocking condition. The review stage may flag issues. The user sees the summary and must manually decide what to do. There is no automatic correction loop.

---

## Dimension 3: State Persistence

### HOTL: Full sidecar state with resume

HOTL persists execution state in two parallel artifacts:
- `.hotl/state/<run-id>.json` -- authoritative machine state (JSON, managed atomically by `hotl-rt`)
- `.hotl/reports/<run-id>.md` -- durable Markdown report (initialized at init, updated incrementally)

The state file schema (from `skills/resuming/SKILL.md`) tracks:
- `run_id`, `workflow_path`, `intent`, `branch`
- `status`: running / paused / blocked / completed / abandoned
- `current_step`, `total_steps`
- Per-step: `status`, `attempts`, `started_at`, `completed_at`, `verify` (with output), `gate_result`, `block_reason`
- `last_update` timestamp for stale run detection

Resume capability (`skills/resuming/SKILL.md`):
1. Loads sidecar state
2. Detects stale runs (>10 min since last update with status: running)
3. Uses verify-first strategy: runs verify on the interrupted step before re-executing it
4. Repairs checkbox drift (sidecar vs workflow file)
5. Continues from the exact point of interruption

The Markdown report survives app crashes and provides a debugging artifact.

### AgenTeam: Shallow state

AgenTeam persists run state in `.agenteam/state/<run-id>.json`. The state file tracks:
- `run_id`, `task`, `pipeline_mode`, `current_stage`
- Per-stage: `status` (pending/in-progress/completed), `roles`, `gate`
- `write_locks`: `active` and `queue`

This is stage-level tracking only. There is:
- No per-step state within a stage
- No attempt counts
- No verify output captured
- No timestamps on stage transitions
- No `last_update` for stale detection
- No resume capability (the `run` skill has no resume flow)
- No durable report artifact
- No checkpoint drift repair

The state file is created by `cmd_init` (line 338-376) and can be read by `cmd_status`. The `standup` skill reads it to compute health indicators. But if a run is interrupted, there is no mechanism to pick it back up -- the user must start a new run.

---

## Dimension 4: Safety and Governance

### HOTL: Multi-layered governance

1. **Risk levels**: `low`, `medium`, `high`. `risk_level: high` always forces human gates regardless of `auto_approve`.
2. **Gate types**: `human` (pause and ask) and `auto` (continue). Security-sensitive keywords (auth, encrypt, secret, key, password, token, permission, role, billing) force human gates.
3. **Auto-approve rules**: `auto_approve: true` in workflow frontmatter skips human gates for non-high-risk steps.
4. **Review checkpoints**: Code review is dispatched at batch boundaries (every 3 steps in executing-plans, meaningful batches in subagent-execution) and always before final completion. BLOCK findings must be resolved before proceeding.
5. **Verification gates**: Every step's verify result is a gate -- the runtime (not the agent) decides pass/fail.
6. **Durable audit trail**: The report and state files provide a complete audit log of what was done, what was verified, and who approved what.

### AgenTeam: Write isolation and scope enforcement

1. **Write locks**: In serial mode (default), only one writing agent can execute at a time. The dispatch plan includes `write_lock: true/false` and `blocked` lists (lines 458-493).
2. **Write scope**: Each writing role has a `write_scope` (e.g., architect writes to `docs/designs/**`, dev writes to `src/**`). The `policy check` command validates that write scopes don't overlap.
3. **Branch isolation**: `git-isolate.sh` creates branches (`ateam/run/<id>`, `ateam/<role>/<slug>`) or worktrees to isolate work. Preflight checks block on dirty worktree or detached HEAD.
4. **Pipeline gates**: Stages can have `gate: human` requiring user approval before proceeding to the next stage.

**What AgenTeam lacks compared to HOTL**:
- No risk level classification
- No security-keyword detection for automatic human gating
- No automated verification at any level
- No code review dispatch (the reviewer role is a pipeline stage, not an automated checkpoint)
- No audit trail beyond the state file

**What AgenTeam has that HOTL lacks**:
- Write scope enforcement (HOTL agents can write anywhere)
- Write lock serialization (HOTL has one executor at a time by design, but no formal lock)
- Branch/worktree isolation as a first-class concept (HOTL has branch management, but it is workflow-scoped, not role-scoped)

---

## Dimension 5: What Overlaps

Both plugins share several conceptual surfaces:

| Capability | AgenTeam | HOTL |
|-----------|----------|------|
| Skills as Markdown | `skills/*/SKILL.md` (9 skills) | `skills/*/SKILL.md` (17 skills) |
| Orchestration | Pipeline stages with dispatch | Workflow steps with execution |
| State directory | `.agenteam/state/` | `.hotl/state/` |
| Branch management | `git-isolate.sh` (preflight, create, return, cleanup) | Built into loop-execution (preflight, create, checkout) |
| Subagent dispatch | `run` and `assign` skills launch Codex subagents | `subagent-execution` delegates steps to fresh subagents |
| Auto-init / zero-config | Auto-creates config and generates agents on first use | SessionStart hook injects skills automatically |
| Config via YAML | `.agenteam/config.yaml` | Workflow frontmatter (per-workflow config) |
| Artifact generation | Design docs, research reports, strategy docs, code, tests | Execution reports, design docs, workflow plans, code, tests |

---

## Dimension 6: What AgenTeam Has That HOTL Does Not

### 1. Role-based identity and specialization
AgenTeam's 6 built-in roles (researcher, pm, architect, dev, qa, reviewer) each have:
- Custom system instructions (e.g., architect: "Always propose 2-3 approaches with trade-offs")
- Scoped write permissions (`can_write`, `write_scope`)
- Participation rules (`participates_in: [design]`)
- Handoff contracts (`produces`, `expects`, `passes_to`)
- Model and reasoning effort overrides

HOTL agents are generic workers. The `code-reviewer` is the only specialized agent. All other work is done by the session agent or dispatched subagents without role-specific instructions.

### 2. Team composition and custom roles
Users can add custom roles via `add-member` skill or YAML config. Custom roles get the full agent lifecycle: TOML generation, dispatch eligibility, write scope enforcement.

HOTL has no concept of adding roles. The skill set is fixed by the plugin.

### 3. Write scope enforcement
Each AgenTeam role declares what files it can write to. The `policy check` command (`cmd_policy_check`, lines 500-521) validates that write scopes across all writing roles are disjoint. This is a pre-execution safety check that HOTL does not have.

### 4. Multi-role pipeline coordination
AgenTeam's pipeline passes context between stages with role-specific handoffs. The architect's output feeds into the dev's plan; the QA's tests validate the dev's code; the reviewer examines everything. HOTL executes a linear step list -- it has no concept of different agents receiving different subsets of context.

### 5. Standup and deepdive
- **Standup** (`skills/standup/SKILL.md`): <2s, reads state + artifacts + git, produces Linear-style status report. No agent dispatch.
- **Deepdive** (`skills/deepdive/SKILL.md`): 30-60s, dispatches researcher + architect + PM in parallel, produces prioritized "what to build next" report.

HOTL has no equivalent status/reporting skills. Its reports are per-execution-run, not project-level.

### 6. Direct role addressing
Users can `@Architect` or `@Reviewer` directly for focused tasks, bypassing the pipeline entirely (`assign` skill). HOTL has no equivalent -- all interaction goes through skills/commands.

---

## Dimension 7: What HOTL Has That AgenTeam Does Not

### 1. Step-level verification loops
Every HOTL step can specify a verify command. The runtime runs it, captures output, and transitions state atomically. If it fails and the step has `loop: until [condition]`, the step retries automatically up to `max_iterations`. AgenTeam has nothing comparable -- no verify, no loop, no retry.

### 2. Typed verification (4 types)
Shell, artifact, browser, human-review -- each with specific semantics. Multi-check for compound verification. AgenTeam has no verification types at all.

### 3. TDD enforcement
The `tdd` skill enforces RED-GREEN-REFACTOR. Never write code before a failing test. AgenTeam's QA role writes tests, but there is no constraint that tests are written first or that failing tests exist before implementation.

### 4. Systematic debugging
The `systematic-debugging` skill requires reproduce -> understand -> hypothesize -> fix-and-verify. AgenTeam has no debugging methodology.

### 5. Code review as an automated checkpoint
HOTL's `requesting-code-review` / `receiving-code-review` lifecycle dispatches review at batch boundaries and final completion. BLOCK findings gate merging. AgenTeam's reviewer role is a pipeline stage that runs once at the end, with no mechanism to block merging or require fixes.

### 6. Resume from interruption
HOTL's `resuming` skill loads sidecar state, detects stale runs, uses verify-first to determine whether the interrupted step succeeded, repairs checkbox drift, and continues. AgenTeam has no resume capability.

### 7. Execution reports
HOTL produces `.hotl/reports/<run-id>.md` -- a durable Markdown artifact with a summary table, event log, and per-step details. AgenTeam produces state JSON but no report artifact.

### 8. Brainstorming with contracts
HOTL's `brainstorming` skill produces three explicit contracts (intent, verification, governance) before any implementation. AgenTeam's design stage uses the architect role's system instructions, but there is no structured contract output format.

### 9. Plan authoring with typed verification
HOTL's `writing-plans` skill produces executable workflow files with step granularity, verify commands, loop conditions, and gates. AgenTeam's plan stage produces design documents, not executable plans.

### 10. PR review skill
HOTL's `pr-reviewing` skill reviews PRs across multiple dimensions (description, code, scan, tests) with structured severity levels (BLOCK/WARN/NOTE). AgenTeam's reviewer role does general code review without structured dimensions or severity.

---

## The Integration Story

AgenTeam already has a `pipeline: hotl` mode (documented in `CLAUDE.md` and implemented in `skills/run/SKILL.md`, section 7). When active:

1. AgenTeam manages **who**: role selection, write policy, team composition
2. HOTL manages **how**: phase execution, verification loops, gates, resume

The integration wraps HOTL skills:
- Design stage -> HOTL brainstorming + architect's instructions
- Plan stage -> HOTL writing-plans
- Implement/test stage -> HOTL loop-execution or subagent-execution
- Review stage -> HOTL code-review + reviewer agent

AgenTeam never modifies HOTL internals. It injects role context and enforces write policy between phases.

---

## Recommendations

### 1. Add step-level verification to standalone mode
**Priority: high | Effort: medium**

AgenTeam's biggest gap is that agents self-certify completion. At minimum, the standalone pipeline should:
- Allow stages to define a `verify` command (similar to HOTL's per-step verify)
- Run the verify after the stage's writing agent completes
- Block progression to the next stage on verify failure
- This does not require HOTL -- it requires adding a `verify` field to stage config and ~50 lines in the dispatch/run flow

### 2. Add retry/loop to standalone stages
**Priority: medium | Effort: medium**

When a stage's verify fails, the current behavior is "stop and show error." Add a `max_retries` field to stage config so the agent can re-attempt. This is the single most impactful feature gap between standalone mode and HOTL mode.

### 3. Add execution reports to standalone mode
**Priority: medium | Effort: small**

Generate a Markdown report at `.agenteam/reports/<run-id>.md` at the end of a pipeline run. Include: task, stages, roles, gate decisions, and a summary of what each role produced. This improves the audit trail without HOTL.

### 4. Document the AgenTeam-only value clearly
**Priority: high | Effort: small**

Users need a clear answer to "why AgenTeam without HOTL?" The answer is:
- Multi-role team with specialized instructions and write scoping
- Direct role addressing (`@Architect`, `@Reviewer`)
- Pipeline coordination with handoff contracts
- Standup and deepdive for project intelligence
- Custom role composition

This should be in the README, not buried in the architecture docs.

### 5. Consider a minimal verification skill
**Priority: medium | Effort: small**

A lightweight `verify` skill (analogous to HOTL's `verification-before-completion`) that agents are instructed to invoke before reporting completion. This is a behavioral constraint, not infrastructure, but it closes the most dangerous gap (agents claiming "done" without running tests).

### 6. Do not duplicate HOTL
**Priority: high | Effort: zero**

AgenTeam should not rebuild HOTL's verification engine, resume system, or typed verification. The integration path (`pipeline: hotl`) already exists. The effort should go into making standalone mode minimally safe (recommendations 1-3) and making the HOTL integration seamless (already in progress).

---

## Sources

- AgenTeam runtime: `/Users/yimwu/Documents/workspace/codex-agenteam/runtime/agenteam_rt.py`
- AgenTeam run skill: `/Users/yimwu/Documents/workspace/codex-agenteam/skills/run/SKILL.md`
- AgenTeam assign skill: `/Users/yimwu/Documents/workspace/codex-agenteam/skills/assign/SKILL.md`
- AgenTeam standup skill: `/Users/yimwu/Documents/workspace/codex-agenteam/skills/standup/SKILL.md`
- AgenTeam deepdive skill: `/Users/yimwu/Documents/workspace/codex-agenteam/skills/deepdive/SKILL.md`
- AgenTeam roadmap: `/Users/yimwu/Documents/workspace/codex-agenteam/docs/strategies/roadmap.md`
- AgenTeam git-isolate: `/Users/yimwu/Documents/workspace/codex-agenteam/scripts/git-isolate.sh`
- HOTL loop-execution skill: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/loop-execution/SKILL.md`
- HOTL brainstorming skill: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/brainstorming/SKILL.md`
- HOTL tdd skill: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/tdd/SKILL.md`
- HOTL verification skill: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/verification-before-completion/SKILL.md`
- HOTL runtime: `/Users/yimwu/Documents/workspace/hotl-plugin/runtime/hotl-rt`
- HOTL subagent-execution: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/subagent-execution/SKILL.md`
- HOTL writing-plans: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/writing-plans/SKILL.md`
- HOTL code-review: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/code-review/SKILL.md`
- HOTL resuming: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/resuming/SKILL.md`
- HOTL requesting-code-review: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/requesting-code-review/SKILL.md`
- HOTL systematic-debugging: `/Users/yimwu/Documents/workspace/hotl-plugin/skills/systematic-debugging/SKILL.md`
