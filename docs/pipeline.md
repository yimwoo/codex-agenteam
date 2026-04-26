# Pipeline

When you give `@ATeam` a task, it runs the full development pipeline.

The skill-driven pipeline uses runtime planning and policy commands to resolve
roles, stages, gates, verification, and state. The non-interactive
`agenteam-rt run` command is the local executor facade for automation: it uses
the same run state, builds role prompts, invokes `codex exec`, records durable
events, and writes `.agenteam/runs/<run-id>/` artifacts.

## Stages

| Stage | Role(s) | Output | Gate |
|-------|---------|--------|------|
| Research | Researcher | `docs/research/` | auto |
| Strategy | PM | `docs/strategies/` | **human** |
| Design | Architect, PM, Researcher | `docs/designs/` | **human** |
| Plan | Dev | `docs/plans/` | **human** |
| Implement | Dev | `src/**`, `lib/**` | auto |
| Test | Qa | `tests/**` | auto |
| Review | Reviewer | verdict | **human** |

Each role writes to a scoped directory — no overlaps, safe for parallel execution. Human gates pause the pipeline until you approve.

## Collaborative Mode

When using a `collaborative` profile, discovery roles (researcher, architect, PM) run in parallel and produce a convergence summary before handing off to implementation. You see what each specialist found, approve the handoff, then dev/qa/reviewer execute serially with per-role visibility.

## Profiles

Right-size the pipeline to the task:

```yaml
pipeline:
  profiles:
    quick:
      stages: [implement, test]
      hints: [typo, one-line fix, config change]
    standard:
      stages: [design, plan, implement, test, review]
      hints: [new endpoint, refactor, add feature]
```

Use with: `@ATeam --profile quick fix the typo in README`

Without `--profile`, the full pipeline runs.

### Built-in Profile Suggestions

| Profile | Best for |
|---------|----------|
| `quick` | Typos, one-line fixes, config changes, version bumps |
| `standard` | New endpoints, refactors, features, bug fixes |
| *(full)* | Multi-component features, architecture changes |

## Stage Verification

Each stage can define a verification command:

```yaml
pipeline:
  stages:
    - name: implement
      roles: [dev]
      gate: auto
      verify: "python3 -m pytest -v"
      max_retries: 2
      rework_to: plan
```

| Field | Description |
|-------|-------------|
| `verify` | Shell command that must exit 0 for the stage to pass |
| `max_retries` | Number of re-dispatch attempts on verify failure (default: 0) |
| `rework_to` | Stage to loop back to on verify failure |

In `agenteam-rt run`, a non-zero role exit fails the stage before verification
or gates run. Verification failures are recorded as attempts and retried up to
`max_retries`.

## Gates

Gates control when the pipeline advances:

| Gate Type | Behavior |
|-----------|----------|
| `auto` | Advances automatically after verification |
| `human` | Pauses for your approval before advancing |

`agenteam-rt run` blocks on `human`, `reviewer`, and `qa` gates by default and
exits non-zero with JSON error details. Pass `--auto-approve-gates` only when an
unattended run should approve those gates automatically.

Gate criteria can be configured per stage:

```yaml
- name: implement
  gate: auto
  criteria:
    max_files_changed: 20
    scope_paths: ["src/**"]
    requires_tests: true
```

## Resume

Interrupted runs are detected automatically at session start:

```
@ATeam resume <run-id>
```

The runtime re-verifies the last incomplete stage before continuing, and asks before re-dispatching expensive work. Config changes since the run started are detected and flagged.

For non-interactive execution, `agenteam-rt run --run-id <id>` skips completed
or skipped stages and resumes at the first incomplete stage.

## Run Trace

Use `trace` when a run is failed, blocked, stale, or otherwise unclear:

```bash
agenteam-rt trace --run-id <id>
```

The trace derives a diagnostic JSON view from run state and events. It includes
health, stale-run status, stage retry budgets, gate state, failure reasons,
final verification results, known runner artifacts, and a suggested next
action. `status --progress` uses the same trace data but keeps only the compact
progress fields.

## Run Evidence

Use `evidence` when a run needs a portable review record for CI repair,
release review, benchmark conversion, or future workspace-agent export:

```bash
agenteam-rt evidence --run-id <id>
agenteam-rt evidence --run-id <id> --output .agenteam/evidence/<id>.json
```

Evidence is a versioned JSON projection over trace and event summaries. It
includes run outcome, stage metrics, role exits, verification and gate
summaries, final verification, governance metadata when present, and artifact
paths. It references detailed runner artifacts by path instead of embedding raw
stdout, stderr, or prompts.

## Final Verification

After all stages complete, optional final verification runs:

```yaml
final_verify:
  - "python3 -m pytest -v"
final_verify_policy: block     # block | warn
final_verify_max_retries: 1
```

If `block`, the pipeline fails on verification failure. If `warn`, it reports but continues.

## Post-Pipeline: CI Repair

After the pipeline creates a PR, CI may still fail (environment differences, flaky tests, missing dependencies). Use `$ateam:ci-repair` to fix CI failures without re-running the full pipeline:

```
$ateam:ci-repair #42
```

The skill fetches the GitHub Actions failure logs, dispatches dev with bounded context, verifies the fix locally, and pushes only if verification passes. See `docs/cli.md` for usage details.
