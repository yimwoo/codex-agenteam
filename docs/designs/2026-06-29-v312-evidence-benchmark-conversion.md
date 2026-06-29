# v3.12 Evidence-Backed Benchmark Conversion

Status: accepted for implementation

## Context

AgenTeam already has three pieces that are not yet connected:

- `agenteam-rt evidence` produces versioned, consumer-neutral run evidence.
- `runtime/agenteam/benchmark.py` validates suites and result files and renders
  aggregate reports.
- benchmark documentation describes CLI commands that are not registered by
  the current runtime parser.

As a result, benchmark reports still depend on manually transcribing runner
outcomes. That makes retry, rework, gate, verification, and artifact evidence
easy to omit and difficult to audit.

## Decision

Implement benchmark conversion as a downstream consumer of evidence. Do not
change the runner executor or make the benchmark layer read raw state, event,
prompt, stdout, or stderr files.

The first v3.12 slice will:

1. Register the existing `benchmark validate`, `benchmark init-results`, and
   `benchmark report` commands as config-free runtime commands.
2. Add `benchmark record` to convert one `agenteam.run_evidence` JSON object
   into one task/strategy result row.
3. Preserve evidence-derived recovery and verification metrics in the result
   row and aggregate them by strategy.
4. Keep quality scoring explicit and externally supplied.
5. Treat cost as optional because it is not available in every Codex surface.

## CLI Contract

```bash
agenteam-rt benchmark validate \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/run-001.json

agenteam-rt benchmark init-results \
  --suite benchmarks/tasks/core-v1.yaml \
  --strategy single_agent \
  --strategy minimal_team \
  --strategy governed_pipeline \
  --output benchmarks/results/run-001.json

agenteam-rt benchmark record \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/run-001.json \
  --evidence .agenteam/evidence/<run-id>.json \
  --task-id <task-id> \
  --strategy <strategy> \
  --quality-score 0.85 \
  --model <model>

agenteam-rt benchmark report \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/run-001.json \
  --markdown-out benchmarks/results/run-001.md
```

`benchmark record` updates `--results` in place unless `--output` is supplied.
The command writes the complete result file and prints a compact JSON receipt.

## Evidence Mapping

The converter accepts only:

- `kind: agenteam.run_evidence`
- `schema_version: "1"`
- terminal outcomes: `completed`, `failed`, `blocked`, or `stopped`

Field mapping:

| Benchmark field | Evidence source |
| --- | --- |
| `run_id` | `run.run_id` |
| `success` | completed outcome, no failed stages, and final verify not false |
| `latency_seconds` | `run.elapsed_seconds`, otherwise terminal minus start time |
| `failure_reason` | `outcome.reason` when unsuccessful |
| `profile` | `run.profile` |
| recovery counts | `metrics.retry_count`, `metrics.rework_count` |
| execution counts | role and verification attempt metrics |
| governance friction | `metrics.gate_block_count` |
| evidence completeness | `metrics.artifact_count` and final verification state |

The user supplies `quality_score` because correctness and review quality cannot
be inferred safely from execution status alone. `cost_usd` and `model` are
optional metadata. Unknown cost stays `null`; it is never converted to zero.

## Result Schema Changes

Recorded rows continue to require:

- `success`
- `latency_seconds`
- `quality_score`

`cost_usd` becomes optional. Evidence-backed rows add:

```json
{
  "profile": "standard",
  "failure_reason": null,
  "evidence": {
    "kind": "agenteam.run_evidence",
    "schema_version": "1",
    "source": ".agenteam/evidence/<run-id>.json",
    "final_verify_passed": true,
    "role_attempt_count": 4,
    "verify_attempt_count": 3,
    "retry_count": 1,
    "rework_count": 0,
    "gate_block_count": 0,
    "artifact_count": 12
  }
}
```

Existing result files remain valid. Missing evidence metrics aggregate as zero
counts and do not prevent reports from rendering.

## Report Changes

Each strategy summary will include:

- failed run count
- total role and verification attempts
- total retries and rework events
- total gate blocks
- runs with passing final verification
- runs carrying evidence metadata

Markdown output will add a compact Evidence And Recovery table. Ranking remains
based on success, quality, cost, latency, and coverage; recovery metrics inform
the decision but do not silently change the ranking formula in this slice.

## Validation And Failure Behavior

- Suite task IDs and declared strategies remain authoritative.
- A running evidence snapshot is rejected instead of being recorded as a
  completed benchmark observation.
- Invalid or unsupported evidence emits JSON on stderr and exits non-zero.
- Quality scores outside `0.0-1.0` and negative costs are rejected.
- Result writes create parent directories and use UTF-8 JSON output.
- The converter replaces an existing task/strategy matrix row or appends the
  row when the pair is absent.

## Non-Goals

- Running benchmark tasks or invoking Codex models.
- Automatically judging qualitative quality.
- Parsing token usage or cost from raw logs.
- Changing `runtime/agenteam/runner.py`.
- Publishing performance claims from illustrative sample data.
- Choosing GPT-5.6 Sol as a shared default while availability is limited.

## Verification

- Parser and no-config behavior for all benchmark subcommands.
- Evidence validation and terminal-state handling.
- Completed and failed run conversion.
- In-place and alternate-output result writes.
- Optional cost behavior.
- Recovery metric aggregation and Markdown rendering.
- Existing evidence, runner, formatting, smoke, and plugin validation suites.

## Follow-On

After this slice lands, maintainers can run the four strategy comparisons from
the modernization design and commit raw evidence-backed results. A later slice
may automate task execution only after the record schema proves stable.
