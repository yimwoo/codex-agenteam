# AgenTeam Benchmark

This directory adds a quantitative evaluation layer to AgenTeam. The goal is
simple: compare orchestration strategies on the same standardized tasks and
publish numbers that other people can reproduce.

## What gets measured

- `success_rate`: fraction of tasks that fully met the acceptance checks
- `latency_seconds`: end-to-end wall-clock time per run
- `cost_usd`: optional model/tool cost when the execution surface exposes it
- `quality_score`: normalized `0.0-1.0` rubric score combining hard checks
  first and judge scoring second
- evidence and recovery counts: role/verification attempts, retries, rework,
  gate blocks, final verification, artifacts, structured handoffs, and invalid
  handoffs

## MVP benchmark shape

The recommended first release compares four strategies on 8 to 12 coding
tasks:

- `single_agent`: the current recommended single-agent Codex setup
- `sol_high_effort`: GPT-5.6 Sol when available, using a supported high-effort
  setting recorded in the run metadata
- `minimal_team`: a lightweight multi-role handoff, such as `dev + reviewer`
- `governed_pipeline`: the full AgenTeam governed pipeline

Keep Codex version, repo commit, prompts, timeouts, and available seeds fixed
across strategies. Keep the exact model and reasoning effort stable across task
rows within each strategy; those values may differ between strategies because
the matrix intentionally compares different native and orchestrated setups. If
a task requires repo setup, use the same setup for every strategy. Do not assume
an `ultra` reasoning-effort value: record the exact setting accepted by the
tested Codex build. If Sol is unavailable, record that limitation and run the
remaining strategies instead of silently substituting another model.

## Files

- `tasks/core-v1.yaml`: illustrative task suite
- `results/sample-results.json`: illustrative fixture data for report formatting
- `results/sample-report.md`: generated Markdown report from the sample fixture

The sample results are not a published claim about AgenTeam performance. They
exist to show the schema and the Markdown report shape. Replace them with real
recorded runs before you cite numbers publicly. The fixture's three placeholder
strategy labels predate the recommended four-strategy matrix and are not a
methodology recommendation.

## CLI workflow

```bash
# Validate the suite definition
python3 runtime/agenteam_rt.py benchmark validate \
  --suite benchmarks/tasks/core-v1.yaml

# Create a blank results matrix for the strategies you want to compare
python3 runtime/agenteam_rt.py benchmark init-results \
  --suite benchmarks/tasks/core-v1.yaml \
  --strategy single_agent \
  --strategy sol_high_effort \
  --strategy minimal_team \
  --strategy governed_pipeline \
  --output benchmarks/results/my-run.json

# Export runner evidence, then convert it into one result row
python3 runtime/agenteam_rt.py evidence --run-id <id> \
  --output .agenteam/evidence/<id>.json
python3 runtime/agenteam_rt.py benchmark record \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/my-run.json \
  --evidence .agenteam/evidence/<id>.json \
  --task-id <task-id> --strategy minimal_team --quality-score 0.85 \
  --model <exact-model-id> \
  --reasoning-effort <accepted-value> \
  --codex-version <exact-version> \
  --repo-commit <git-sha>

# Aggregate the result matrix
python3 runtime/agenteam_rt.py benchmark report \
  --suite benchmarks/tasks/core-v1.yaml \
  --results benchmarks/results/my-run.json \
  --markdown-out benchmarks/results/my-run.md
```

`benchmark record` computes and stores the evidence file's SHA-256. The report
also hashes the suite and emits a reproducibility audit. A matrix is ready for
an executor decision only when every declared cell is recorded, every row has
the four execution fields above, every attached evidence bundle has a digest,
each strategy is internally stable, and Codex version plus repo commit match
across strategies. Historical or illustrative results with missing metadata
still validate, but the report marks them not ready.

## Publishing guidance

- Publish the raw results JSON alongside the aggregate table.
- Preserve the referenced evidence files for every AgenTeam-backed row.
- Disclose the exact strategy definitions, model and reasoning-effort values,
  Codex version, and repo commit.
- Publish the suite SHA-256 and preserve every referenced evidence bundle so
  its recorded SHA-256 can be verified.
- Say where orchestration loses, not just where it wins.
- Treat docs-only or trivial one-shot edits as a separate class of task.
