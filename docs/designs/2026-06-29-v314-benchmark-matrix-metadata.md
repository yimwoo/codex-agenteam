# v3.14 Benchmark Matrix Metadata And Decision Readiness

## Problem

The benchmark guide requires exact model, reasoning-effort, Codex-version,
repository, and evidence provenance, but the result schema currently stores
only an optional model name and evidence path. A report can therefore look
complete while mixing execution environments or referring to evidence that
has changed since the row was recorded.

The executor roadmap needs a trustworthy comparison before AgenTeam chooses
between the current runtime boundary and a Codex App Server or SDK-backed
executor. That decision cannot be made from a matrix whose environment is not
auditable.

## Decision

Extend each benchmark run with additive execution metadata:

- `model`: exact model identifier used for the row
- `reasoning_effort`: exact reasoning value accepted by that Codex build
- `codex_version`: exact Codex version string
- `repo_commit`: 7-to-64-character hexadecimal repository revision
- `evidence.sha256`: SHA-256 of an attached AgenTeam evidence bundle

`benchmark record` accepts the four execution fields and computes the evidence
digest itself. Existing result files remain valid: the new fields are optional
at schema-validation time so illustrative and historical fixtures do not break.

The report adds a `reproducibility` object and matching Markdown section. It
records the suite SHA-256, metadata completeness, evidence digest coverage,
the distinct environment values observed per strategy, and structured issues.

`ready_for_executor_decision` is true only when:

1. every declared task/strategy cell is recorded;
2. every recorded row has model, reasoning effort, Codex version, and repo
   commit;
3. every evidence-backed row has an evidence SHA-256;
4. each strategy uses a stable environment across its task rows; and
5. Codex version and repo commit do not drift across strategies.

Models and reasoning efforts may differ between strategies because the matrix
intentionally compares the recommended single-agent model, GPT-5.6 Sol, and
AgenTeam profiles. They must remain stable within each strategy.

## Compatibility

- Suite and result schema versions do not change.
- Historical rows with missing metadata still validate and report normally.
- Missing metadata makes a report visibly not decision-ready instead of
  rejecting the file.
- Existing evidence summaries without a digest still validate, but are flagged
  when they are used by a recorded row.
- Benchmark execution remains outside the runtime; this milestone does not add
  a Codex subprocess, App Server client, SDK client, or executable hook.

## CLI Shape

```bash
agenteam-rt benchmark record \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/run-001.json \
  --evidence .agenteam/evidence/<id>.json \
  --task-id <task-id> \
  --strategy minimal_team \
  --quality-score 0.85 \
  --model <exact-model-id> \
  --reasoning-effort <accepted-value> \
  --codex-version <exact-version> \
  --repo-commit <git-sha>
```

## Verification

- CLI tests cover metadata capture and evidence hashing.
- Result validation rejects empty metadata and malformed commit or digest
  values when supplied.
- Report tests cover a ready matrix and cross-strategy environment drift.
- Existing illustrative fixtures continue to validate and render with an
  explicit not-ready status.
- Full pytest, Ruff lint, Ruff format, and smoke suites pass.

## Next Gate

Run the core suite across `single_agent`, `sol_high_effort`, `minimal_team`,
and `governed_pipeline`. Preserve the raw result matrix and evidence bundles.
Only then decide whether an App Server or SDK executor provides enough
observability, resumability, or reliability to justify implementation.
