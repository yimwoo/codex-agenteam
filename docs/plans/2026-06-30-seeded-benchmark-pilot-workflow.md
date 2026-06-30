---
intent: Build and validate a reproducible one-task benchmark pilot that compares native Codex execution with AgenTeam orchestration without contaminating the source checkout.
success_criteria:
  - The pilot manifest pins one task, four strategies, model settings, seed, checks, timeout, and GPT-5.6 availability.
  - Dry-run planning prepares four isolated workspaces from one revision and validates the seeded precheck.
  - The harness captures resumable native and AgenTeam artifacts that can populate a decision-ready benchmark report.
  - Full repository verification passes and no normal runtime behavior changes.
risk_level: medium
auto_approve: true
branch: feature/v3.15-seeded-benchmark-pilot
worktree: false
---

## Steps

- [x] **Step 1: Add failing manifest and planning tests**
action: Add `TestBenchmarkPilot` cases in `test/test_runtime.py` that invoke `scripts/benchmark-pilot.py` in temporary repositories and assert rejection of missing fields, unknown strategies, invalid reasoning values, unavailable requested models, and mismatched Codex versions; also assert a valid manifest produces four deterministic task/strategy plans without launching Codex.
loop: false
verify: ! python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 2: Implement manifest validation and deterministic planning**
action: Create `scripts/benchmark-pilot.py` with `validate` and `plan` subcommands, typed internal normalization, JSON-only stdout, JSON errors on stderr, live `codex --version` and `codex debug models` capability checks, stable task/strategy ordering, and no subprocess execution in plan mode beyond capability discovery.
loop: until manifest and planning tests pass
max_iterations: 4
verify: python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 3: Define the tracked pilot task, seed, strategy manifest, and team config**
action: Add `benchmarks/tasks/pilot-v1.yaml`, `benchmarks/seeds/dispatch-scope-overlap.patch`, `benchmarks/pilot/manifest.yaml`, and `benchmarks/pilot/agenteam.yaml`; pin the task to `TestWriterGroups`, GPT-5.5 medium for `single_agent`, GPT-5.5 xhigh for `native_high_effort`, GPT-5.5 medium for `minimal_team` and `governed_pipeline`, Codex 0.137.0, workspace-write isolation, one timeout, and an explicit GPT-5.6-unavailable limitation.
loop: until the validate command accepts the files and reports exactly four strategies
max_iterations: 3
verify: python3 scripts/benchmark-pilot.py validate --manifest benchmarks/pilot/manifest.yaml

- [x] **Step 4: Add failing workspace preparation tests**
action: Extend `TestBenchmarkPilot` with temporary Git repositories that assert `prepare` creates one worktree per plan, checks out the same baseline revision, applies the tracked seed, records its SHA-256, proves the configured precheck fails, refuses dirty or reused non-worktree paths, and preserves the source checkout.
loop: false
verify: ! python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 5: Implement isolated workspace preparation and safe cleanup**
action: Add `prepare`, `inspect`, and `cleanup` behavior to `scripts/benchmark-pilot.py`; use argument-list Git subprocesses, store resumable state under `.agenteam/benchmarks/<pilot-id>`, copy the benchmark AgenTeam config only inside experiment worktrees, remove only clean worktrees created by the matching state file, and preserve dirty worktrees with an actionable JSON result.
loop: until workspace preparation tests pass
max_iterations: 4
verify: python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 6: Add failing native adapter and artifact tests**
action: Extend `TestBenchmarkPilot` with a fake Codex executable that emits deterministic JSONL and final output; assert native commands include explicit ephemeral, JSONL, workspace-write, model, and reasoning settings, capture elapsed time and terminal usage, save stdout/stderr/final response/diff/check logs, and resume without rerunning completed strategies.
loop: false
verify: ! python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 7: Implement native strategy execution and capture**
action: Add `run --strategy single_agent|native_high_effort` to `scripts/benchmark-pilot.py`, enforce per-plan timeouts, stream captured output to per-strategy artifacts, parse terminal usage without estimating unavailable cost, run the configured postcheck, derive deterministic success and quality signals, and persist atomic resumable state after every phase.
loop: until native adapter tests pass
max_iterations: 4
verify: python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 8: Add failing AgenTeam adapter and evidence tests**
action: Extend `TestBenchmarkPilot` with fake AgenTeam and Codex execution boundaries; assert team setup generates isolated agents from the benchmark config, selects `minimal_team` or `governed_pipeline`, auto-approves benchmark gates, captures runner JSONL, exports `agenteam.run_evidence`, and never inherits deprecated GPT-5.3-Codex role pins.
loop: false
verify: ! python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 9: Implement AgenTeam strategy execution and evidence conversion**
action: Add `run --strategy minimal_team|governed_pipeline`, invoke the existing generate, run, and evidence commands inside each prepared worktree, preserve runner artifacts and evidence, convert successful or failed terminal evidence into benchmark rows with the manifest metadata, and keep incomplete executions resumable rather than marking them recorded.
loop: until AgenTeam adapter tests pass
max_iterations: 4
verify: python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 10: Add result assembly, report generation, and readiness tests**
action: Extend `TestBenchmarkPilot` so four fake completed strategies assemble one results JSON, generate Markdown through the existing benchmark report command, reject mixed base revisions or capability drift, retain token usage in pilot artifacts, and report `ready_for_executor_decision=true` only when all four cells and provenance fields are complete.
loop: false
verify: ! python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q

- [x] **Step 11: Implement finalization and dry-run summary**
action: Add `finalize` and `dry-run` commands that assemble results, invoke existing benchmark validation/reporting, write a compact execution summary, and print the exact post-merge command required for the real four-strategy pilot without starting model calls during implementation verification.
loop: until finalization tests and the tracked manifest dry run pass
max_iterations: 4
verify:
  - type: shell
    command: python3 -m pytest test/test_runtime.py::TestBenchmarkPilot -q
  - type: shell
    command: python3 scripts/benchmark-pilot.py dry-run --manifest benchmarks/pilot/manifest.yaml

- [x] **Step 12: Document operation, limitations, and recovery**
action: Update `benchmarks/README.md` and `docs/cli.md` with the seeded-pilot lifecycle, artifact locations, single-strategy resume, safe cleanup, deterministic scoring, GPT-5.6 availability disclosure, and the rule that real execution and publication occur only after the harness is merged.
loop: false
verify: rg -n 'benchmark-pilot|native_high_effort|GPT-5.6|resume|cleanup' benchmarks/README.md docs/cli.md

- [x] **Step 13: Run full verification and inspect the merge diff**
action: Run the complete Python, Bats, Ruff lint, Ruff format, manifest validation, dry-run, and whitespace checks; inspect `main...HEAD` for runtime-boundary violations, unintended model calls, secrets, generated pilot artifacts, or source-checkout changes.
loop: until every configured check passes
max_iterations: 4
verify:
  - type: shell
    command: python3 -m pytest test/test_runtime.py -q
  - type: shell
    command: bats test/smoke.bats test/test_git_isolate.bats test/test_verify_stage.bats
  - type: shell
    command: python3 -m ruff check runtime/ scripts/ test/
  - type: shell
    command: python3 -m ruff format --check runtime/ scripts/ test/
  - type: shell
    command: python3 scripts/benchmark-pilot.py validate --manifest benchmarks/pilot/manifest.yaml
  - type: shell
    command: python3 scripts/benchmark-pilot.py dry-run --manifest benchmarks/pilot/manifest.yaml
  - type: shell
    command: git diff --check
gate: auto

- [x] **Step 14: Record the post-merge pilot gate**
action: Update local `STATE.md` with the harness outcome, exact post-merge pilot command, four pinned strategies, GPT-5.6 limitation, and the rule that full-matrix execution remains blocked until a decision-ready pilot report exists.
loop: false
verify: rg -n 'seeded benchmark pilot|native_high_effort|decision-ready pilot' STATE.md
