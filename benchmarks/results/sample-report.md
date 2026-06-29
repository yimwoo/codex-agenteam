# Benchmark Report: agenteam-core-v1

Standardized software-engineering tasks for comparing orchestration strategies in codex-agenteam. Use this suite as a reproducible starting point, then replace the sample results with real runs before publishing claims.

## Summary

- Tasks: 8
- Strategies: 3
- Recorded runs: 24 / 24
- Pending or missing runs: 0
- Quality scale: 0.0-1.0

## Strategy Comparison

| Rank | Strategy | Success Rate | Avg Quality | Avg Latency (s) | Avg Cost ($) | Coverage |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | full_pipeline | 100.0% | 0.89 | 1530.62 | 2.16 | 100.0% |
| 2 | minimal_team | 75.0% | 0.75 | 1022.50 | 1.31 | 100.0% |
| 3 | single_agent | 37.5% | 0.55 | 781.88 | 0.87 | 100.0% |

## Evidence And Recovery

| Strategy | Evidence Runs | Failed Runs | Role Attempts | Verify Attempts | Retries | Rework | Gate Blocks | Handoffs | Invalid Handoffs | Artifacts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| full_pipeline | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| minimal_team | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| single_agent | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Category Breakdown

| Strategy | Category | Recorded Runs | Success Rate | Avg Quality | Avg Latency (s) | Avg Cost ($) |
| --- | --- | --- | --- | --- | --- | --- |
| single_agent | bugfix | 2 | 50.0% | 0.58 | 775.00 | 0.86 |
| single_agent | config | 1 | 0.0% | 0.47 | 880.00 | 1.03 |
| single_agent | docs | 1 | 100.0% | 0.74 | 430.00 | 0.41 |
| single_agent | feature | 2 | 0.0% | 0.48 | 875.00 | 1.01 |
| single_agent | integration | 1 | 0.0% | 0.38 | 1125.00 | 1.21 |
| single_agent | test | 1 | 100.0% | 0.71 | 520.00 | 0.55 |
| minimal_team | bugfix | 2 | 100.0% | 0.79 | 1005.00 | 1.32 |
| minimal_team | config | 1 | 0.0% | 0.63 | 1145.00 | 1.51 |
| minimal_team | docs | 1 | 100.0% | 0.82 | 640.00 | 0.73 |
| minimal_team | feature | 2 | 100.0% | 0.79 | 1147.50 | 1.51 |
| minimal_team | integration | 1 | 0.0% | 0.58 | 1390.00 | 1.73 |
| minimal_team | test | 1 | 100.0% | 0.81 | 700.00 | 0.87 |
| full_pipeline | bugfix | 2 | 100.0% | 0.88 | 1510.00 | 2.12 |
| full_pipeline | config | 1 | 100.0% | 0.88 | 1695.00 | 2.36 |
| full_pipeline | docs | 1 | 100.0% | 0.90 | 980.00 | 1.28 |
| full_pipeline | feature | 2 | 100.0% | 0.90 | 1665.00 | 2.33 |
| full_pipeline | integration | 1 | 100.0% | 0.92 | 2140.00 | 3.08 |
| full_pipeline | test | 1 | 100.0% | 0.88 | 1080.00 | 1.64 |
