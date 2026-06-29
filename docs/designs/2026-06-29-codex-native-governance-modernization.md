# AgenTeam Codex-Native Governance Modernization

**Date:** 2026-06-29
**Status:** Accepted for phased implementation
**Scope:** Codex capability compatibility, governed execution, and runner modernization

## Context

AgenTeam 3.10 already materializes role definitions as Codex custom agents and
adds pipeline stages, gates, verification, retry/rework behavior, run evidence,
and workspace-agent export. Codex now provides more of the execution substrate
directly:

- Native subagents with custom agent TOML, concurrency limits, and inherited
  model, sandbox, MCP, and skill configuration.
- Lifecycle hooks including `SubagentStart`, `SubagentStop`, `PreToolUse`,
  `PermissionRequest`, `PostToolUse`, and `Stop`.
- Structured `codex exec` output through `--output-schema`.
- App Server and Python SDK interfaces for persistent threads, streamed turn
  events, model discovery, goals, resume/fork, diffs, and interruption.
- GPT-5.6 Sol preview support for `max` reasoning and an `ultra` mode that uses
  subagents for complex work.

These capabilities reduce the value of orchestration that only assigns
personas or fans work out to several agents. They do not remove the need for a
repeatable policy layer when a task requires explicit ownership, human gates,
scoped writes, deterministic verification, recovery, or portable evidence.

## Product Decision

AgenTeam will be the **policy, workflow, verification, and evidence layer for
Codex-native agent teams**.

Codex owns:

- Model execution and tool use.
- Agent threads and subagent lifecycle.
- Sandbox and approval primitives.
- Worktree creation and thread transport.
- Model and feature capability discovery.

AgenTeam owns:

- Resolved role and handoff contracts.
- Pipeline profiles and stage transitions.
- Write-scope and isolation policy.
- Human, reviewer, and QA gates.
- Verification, retry, and cross-stage rework policy.
- Run status, trace, governance decisions, and evidence bundles.
- Benchmarks that establish when governed teamwork is worth its overhead.

The plugin should not assume that more agents are always better. Small tasks
should be able to use direct Codex execution. Native `ultra` and AgenTeam
pipelines are separate execution strategies; nesting both by default would
create unpredictable fan-out and cost.

## Goals

1. Keep generated roles compatible with current and future Codex model
   capabilities without hard-coding one workspace's model availability.
2. Diagnose stale model pins and unsupported local Codex capabilities before a
   run fails.
3. Make role handoffs machine-readable while preserving human-readable output.
4. Use optional Codex hooks to move policy checks closer to the actions they
   govern without treating hooks as a complete security boundary.
5. Preserve the public `agenteam-rt` JSON/JSONL contracts while introducing a
   native SDK/App Server executor behind a compatibility boundary.
6. Measure single-agent, native multi-agent, and governed-pipeline strategies
   before making larger execution changes.

## Non-Goals

- Making GPT-5.6 the shared default while it is in limited preview.
- Reimplementing Codex subagent scheduling, worktrees, or approval UI.
- Treating prompt personas as independent sources of truth.
- Replacing `AGENTS.md`, Codex sandbox policy, or managed workspace policy.
- Depending on live network access for config validation or unit tests.
- Migrating the runner to the beta Python SDK in the first compatibility PR.

## Architecture

### 1. Capability-Aware Configuration

Add a Codex diagnostics boundary that reports:

- Whether the configured Codex binary is available.
- Its version string.
- Relevant locally reported feature stages when available.
- Model pins found in the effective AgenTeam role configuration.
- Known-deprecated pins and actionable remediation.
- Whether the environment is ready for current AgenTeam execution.

The first slice uses stable local CLI commands and has no network dependency.
A later SDK-backed slice will use App Server `model/list` as the authoritative
source for picker-visible models, supported reasoning efforts, default effort,
and upgrade hints.

Reasoning effort remains a personal override. AgenTeam accepts the current
Codex vocabulary plus preview `max`, but a future SDK-backed doctor performs
the model-specific compatibility check. Shared team config must not pin a
preview-only model.

### 2. Execution Strategies

Introduce the following conceptual strategies without changing the current
default in the first slice:

| Strategy | Intended use | Orchestration owner |
|----------|--------------|---------------------|
| `solo` | Small, well-scoped changes | Codex |
| `native` | Explicit parallel exploration or native `ultra` | Codex |
| `minimal-team` | Implementation plus independent verification | AgenTeam policy over Codex agents |
| `governed-pipeline` | High-risk, multi-stage, auditable delivery | AgenTeam policy over Codex agents |

Profiles may eventually select among these strategies. A task must not combine
native recursive fan-out and a multi-role AgenTeam stage unless the config
provides an explicit delegation budget.

### 3. Structured Role Handoffs

Define a versioned JSON Schema for the final response of a role execution. The
minimum contract includes:

```json
{
  "status": "completed",
  "summary": "Implemented the requested change.",
  "artifacts": ["runtime/agenteam/example.py"],
  "verification": [{"command": "pytest -q", "result": "passed"}],
  "findings": [],
  "recommended_next_stage": "test"
}
```

The existing prompt and transcript artifacts remain available. The structured
handoff becomes the runtime input for gate evaluation, evidence conversion,
and benchmark scoring. Initial integration uses `codex exec --output-schema`;
the later SDK backend uses the equivalent turn result.

### 4. Optional Lifecycle Hooks

Bundle hooks only after a trust and compatibility pass:

- `SubagentStart`: add resolved run, stage, role, and write-policy context.
- `SubagentStop`: require a valid handoff or request one focused continuation.
- `PreToolUse`: deny clearly out-of-scope file changes when the event exposes a
  supported action.
- `PermissionRequest`: apply repository approval policy before interactive
  approval when the policy can decide safely.
- `PostToolUse`: record compact provenance and relevant tool failure metadata.
- `Stop`: prevent a governed run from claiming completion before mandatory
  final verification or a blocking gate is resolved.

Hooks remain optional and require Codex trust review. Because hook interception
does not cover every tool path, authoritative scope auditing and final
verification remain in the AgenTeam runtime.

### 5. Native Executor Boundary

Keep `agenteam-rt run` as the public executor facade. Add an internal backend
interface with two implementations:

- `exec`: existing subprocess behavior and compatibility fallback.
- `app-server`: Python Codex SDK/App Server threads and streamed events.

The native backend should persist Codex thread IDs in run state and map Codex
turn events into existing AgenTeam events. It must support resume, interruption,
per-turn sandbox choice, model discovery, and goal association without changing
the evidence schema until the mappings are proven stable.

## First Implementation Slice

The first PR is intentionally small and reversible:

1. Add `agenteam-rt doctor`, callable with or without project config.
2. Report Codex availability/version and relevant feature stages from local
   CLI output.
3. Inspect effective role model pins when config exists.
4. Warn for known-deprecated Codex model pins without rejecting API-key users
   that may still have access.
5. Accept `minimal`, `low`, `medium`, `high`, `xhigh`, and preview `max`
   reasoning values.
6. Document that model-specific validation is deferred to live capability
   discovery and that GPT-5.6 must not become a shared default during preview.
7. Add deterministic subprocess-backed tests with a fake Codex binary.

The command returns JSON on stdout even when Codex is absent. `--strict`
returns exit code 1 when readiness diagnostics contain warnings or errors,
which makes the command usable in CI without making its default interactive
behavior brittle.

## Benchmark Gate Before Executor Migration

The planned v3.12 runner-backed benchmark must compare at least:

1. Current recommended single-agent Codex.
2. GPT-5.6 Sol `ultra` when generally available to the test environment.
3. AgenTeam `minimal-team`.
4. AgenTeam `governed-pipeline`.

Required dimensions:

- Executable success and quality score.
- Forbidden or out-of-scope file touches.
- Human corrections and gate rejections.
- Retry/rework count and recovery success.
- Latency, token use, and cost when observable.
- Artifact and evidence completeness.

Proceed with SDK executor migration only if it improves observability,
resumability, or reliability without weakening the runner's deterministic
state and evidence contracts. Keep the full pipeline only where the benchmark
shows a quality, policy, or recovery advantage over native execution.

## Security And Trust

- Doctor diagnostics never transmit config or credentials.
- Subprocess commands use argument lists and bounded timeouts.
- Feature and model discovery failures degrade to structured diagnostics.
- Model pins are reported by identifier only; MCP settings and credentials are
  not included.
- Hook decisions fail closed only for checks that can be evaluated
  deterministically. Ambiguous cases continue through normal Codex approval.
- Existing sandbox, branch/worktree isolation, scope audit, and final verify
  remain authoritative.

## Rollout

### Phase A: Compatibility And Diagnostics

- `doctor`, reasoning vocabulary, deprecation warnings, docs, tests.

### Phase B: Benchmark Conversion

- Convert run evidence to benchmark records and compare execution strategies.

### Phase C: Structured Handoffs And Hooks

- Add output schemas, optional trusted hooks, and provenance events.

### Phase D: Native Executor

- Add the Python SDK/App Server backend behind an opt-in flag, then promote it
  only after parity and migration tests pass.

## Acceptance Criteria For Phase A

- `agenteam-rt doctor` works without an AgenTeam config.
- A missing or failing Codex binary produces valid JSON and no traceback.
- A fake Codex binary can deterministically report version and feature stages.
- Configured deprecated models produce warnings, not hard errors.
- `minimal`, `xhigh`, and `max` reasoning values validate successfully.
- An unknown reasoning value still fails validation with an actionable message.
- Existing runtime commands and JSON contracts remain unchanged.
- Unit tests, smoke tests, and Ruff formatting checks pass.

## References

- [GPT-5.6 Sol preview](https://openai.com/index/previewing-gpt-5-6-sol/)
- [Codex models](https://developers.openai.com/codex/models)
- [Codex subagents](https://developers.openai.com/codex/subagents)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive)
- [Codex App Server](https://developers.openai.com/codex/app-server)
- [Codex SDK](https://developers.openai.com/codex/sdk)
