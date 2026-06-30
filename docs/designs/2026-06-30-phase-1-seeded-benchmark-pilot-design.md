---
design_type: phase
created_at: 2026-06-30
initiative: codex-native-executor-decision
status: approved
---

# Seeded Benchmark Pilot

## Intent Contract

intent: Build and validate a reproducible one-task benchmark pilot that can
compare native Codex execution with AgenTeam orchestration before the full
matrix or an executor migration begins.

constraints:

- Use one immutable repository revision and one deterministic defect seed for
  every strategy.
- Keep benchmark execution outside `runtime/agenteam`; the runtime remains the
  JSON policy, evidence, and reporting boundary.
- Run each strategy in a disposable Git worktree and preserve the source
  checkout unchanged.
- Pin the local Codex version, model, reasoning effort, prompt, timeout, seed,
  and verification command in a machine-readable manifest.
- Record GPT-5.6 Sol as unavailable when it is absent from the live model
  catalog. Do not silently substitute GPT-5.5 under a Sol strategy label.
- Do not add an App Server/SDK executor or executable hooks in this phase.
- Do not publish performance claims from the pilot.

success_criteria:

- A dry run proves that four isolated workspaces can be prepared from the same
  commit with the same seed and a failing precheck.
- The pilot defines `single_agent`, `native_high_effort`, `minimal_team`, and
  `governed_pipeline` with explicit GPT-5.5 reasoning settings.
- Native runs produce auditable JSONL, final response, token, latency, diff,
  and verification artifacts; AgenTeam runs additionally produce portable run
  evidence.
- A completed four-strategy pilot can populate the existing benchmark result
  schema and produce a decision-ready report.
- The full eight-task matrix remains blocked until the pilot report passes its
  reproducibility checks.

risk_level: medium

## Verification Contract

verify_steps:

- Run the focused unit tests for manifest validation, workspace preparation,
  seed application, command generation, resume behavior, and result capture.
- Confirm the seed causes `TestWriterGroups` to fail before an agent
  run and the unseeded repository passes the same check.
- Run a no-model dry run and inspect four distinct worktree plans with the same
  base commit, seed digest, Codex version, and timeout.
- Run repository pytest, all Bats suites, Ruff lint, and Ruff formatting.
- After the implementation lands on `main`, execute the four-strategy pilot
  and confirm `ready_for_executor_decision` is true before expanding the suite.

## Governance Contract

approval_gates:

- The user approved the seeded-pilot approach and four-strategy model plan on
  2026-06-30.
- Merging the harness is a normal reviewed PR gate.
- Publishing pilot performance claims or starting the full 32-run matrix
  requires a completed, reproducible pilot report.
- Starting an App Server/SDK executor spike requires the full matrix decision,
  not merely a successful pilot.

rollback: Stop active Codex processes, preserve dirty experiment worktrees and
artifacts for inspection, remove only clean disposable worktrees, and revert
the harness PR if it changes normal repository behavior.

ownership: AgenTeam maintainers own the fixture, strategy definitions, scoring
rubric, and public interpretation; the harness owns deterministic isolation and
artifact capture but never chooses the executor roadmap outcome.

## Scope

| In | Out |
| --- | --- |
| One seeded `dispatch-scope-guardrail` pilot task | Full eight-task matrix |
| Four explicit local strategies | GPT-5.6 execution without verified access |
| Disposable worktree preparation and cleanup | App Server or SDK migration |
| Dry-run, single-strategy, resume, and inspect modes | General-purpose benchmark service |
| JSONL, final response, diff, checks, usage, and evidence capture | Automatic qualitative judge model |
| Deterministic fixture and manifest validation | Public performance claims |

## Decisions

| # | Decision | Choice | Rejected alternatives |
| --- | --- | --- | --- |
| 1 | Task state | Apply a deterministic dispatch overlap regression to the same revision for every run | Current `main` no-op tasks; different historical commits |
| 2 | Native baseline | GPT-5.5 medium for `single_agent` | Deprecated GPT-5.3-Codex pin |
| 3 | High-effort native | GPT-5.5 xhigh under `native_high_effort` | Calling it `sol_high_effort`; unavailable GPT-5.6 preview |
| 4 | Team models | GPT-5.5 medium for both AgenTeam strategies | Inheriting deprecated local role pins |
| 5 | Isolation | One disposable Git worktree per task/strategy pair | Shared checkout; branch reuse |
| 6 | Execution boundary | Repository script prepares workspaces, invokes existing CLIs, and captures artifacts | Adding execution to the benchmark runtime module |
| 7 | Pilot timing | Merge harness first, then execute from merged `main` | Publishing results from an unmerged implementation branch |
| 8 | Scoring | Executable checks determine success; quality uses a documented deterministic rubric | Unreviewed model-as-judge score |

## Surface

Manifest: a tracked pilot manifest identifies the immutable baseline policy,
Codex/model snapshot, strategy definitions, task prompt, seed, precheck,
verification command, timeout, artifact root, and GPT-5.6 availability note.

Fixture: a tracked seed patch introduces the overlap regression without
changing task instructions. Because the manifest and seed are tracked at the
recorded repository revision, `repo_commit` plus suite provenance identifies
the exact fixture.

Harness: a repository script validates inputs, prepares worktrees, applies the
seed, confirms the precheck fails, invokes the selected strategy, runs the
postcheck, captures artifacts, and updates resumable pilot state. It supports
planning without model calls and one-strategy execution for recovery.

Native adapter: invokes `codex exec` with explicit model, reasoning, sandbox,
ephemeral session, JSONL, and final-response capture. It derives token usage
from the terminal JSONL event instead of estimating cost.

AgenTeam adapter: writes an isolated benchmark config that removes deprecated
model pins, selects the minimal or governed profile, auto-approves declared
benchmark gates, invokes the existing runner, and exports portable evidence.

Artifacts: ignored local output contains the resolved manifest, state,
commands, timestamps, JSONL streams, final responses, diffs, check logs,
evidence, result JSON, and Markdown report. Publication is a separate reviewed
step.

## Risks & Open Questions

- ChatGPT-managed model availability can change between planning and execution;
  the harness must recheck the live catalog and fail closed on drift.
- GPT-5.5 xhigh may consume substantially more time and credits than medium;
  the pilot bounds this to one task before a full matrix.
- Auto-approved benchmark gates measure unattended governed execution, not
  human-in-the-loop review quality; the report must disclose that limitation.
- A seeded diff can reveal the regression location through Git inspection.
  This is acceptable for the pilot because the task measures repair and
  orchestration behavior, but later fixtures should include less localized
  failures.
- The existing benchmark schema does not store token counts directly. Pilot
  artifacts retain exact usage, while a later schema decision can add tokens
  only if the pilot proves them useful.
