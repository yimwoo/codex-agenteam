# AgenTeam Roadmap

## v1.0.0 (shipped)

- Plugin packaging: install.sh, update.sh, marketplace registration
- 6 built-in roles: researcher, pm, architect, dev, qa, reviewer
- Pipeline: research -> strategy -> design -> plan -> implement -> test -> review
- Serial write policy, scoped artifact paths
- Auto-init on first use (zero-step setup)
- Natural language add-role skill
- HOTL auto-detection for artifact path routing

## v1.1 (next)

- Pipeline reliability: battle-test $ateam:run end-to-end
- Config simplification: kill `team.pipeline` enum, flatten to `isolation: branch | worktree | none`
  - Minimal config: just `version: "1"` -- everything else defaulted + auto-detected
  - HOTL auto-detection becomes default behavior (no `auto` setting)
  - `dispatch-only` eliminated (just "no stages defined")
  - `scoped` renamed `none`, `serial` renamed `branch`
  - Legacy schema accepted with deprecation warning
  - Design: docs/plans/2026-03-30-config-simplification-design.md
- Config migration: .agenteam/config.yaml (preferred) with agenteam.yaml legacy fallback
- Linter improvements: role renames (dev, qa), model inheritance, Codex-compatible sandbox modes

## v1.2

### Standup (`@ATeam standup`)

Quick project status from state files + artifacts. No agent dispatch.

- `cmd_standup` in runtime -- assembles state + artifact paths + health indicator as JSON (~60 lines)
- `skills/standup/SKILL.md` -- reads artifacts, synthesizes Linear-style report
- Health indicator: on-track / at-risk / off-track (computed from blocked stages, failed gates, lock contention)
- Structured blockers: problem + next step + owner
- Output: `docs/meetings/<timestamp>-standup.md`
- Latency: <2s

Format:
```
Health: ON TRACK

## Completed
- [architect] Design doc: chose REST over GraphQL

## In Progress
- [dev] 3 files changed in src/auth/, tests passing

## Blocked
- [qa] Waiting on review (owner: reviewer)

## Next
- reviewer completes -> qa begins test stage
```

Research: docs/research/2026-03-29-team-status-reports.md

## v1.3

### Deepdive (`@ATeam deepdive`)

Full specialist analysis via parallel agent dispatch.

- `skills/deepdive/SKILL.md` -- dispatches researcher + architect + PM in parallel
- Researcher: external signals (GitHub trends, community, competitors)
- Architect: internal signals (tech debt, design drift, dependency health)
- PM: synthesizes both into prioritized "what to build next"
- Reuses same `cmd_standup` runtime command with `--dispatch` flag
- Output: `docs/meetings/<timestamp>-deepdive.md`
- Latency: 30-60s

User story: "As a developer, I can run @ATeam deepdive so the team researches external trends and internal code health, then gives me a prioritized list of what to build next."

## v2+

- Scoped parallel write policy (non-overlapping write_scope)
- Worktree isolation for parallel writers
- SessionStart hooks (auto-detect agenteam.yaml, inject team context)
- Audience-tailored report output (--format brief / --format json)
- Git + artifact summaries in standup (LLM-powered)
