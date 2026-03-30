# AgenTeam Roadmap

## Shipped

### v1.0 -- Foundation
- Plugin packaging: install.sh, update.sh, marketplace registration
- 6 built-in roles: researcher, pm, architect, dev, qa, reviewer
- Pipeline: research -> strategy -> design -> plan -> implement -> test -> review
- Serial write policy, scoped artifact paths
- Auto-init on first use (zero-step setup)
- Natural language add-member skill
- HOTL auto-detection for artifact path routing

### v1.1 -- Config Simplification
- Minimal config: just `version: "1"` -- everything else defaulted + auto-detected
- Flat `isolation: branch | worktree | none` replaces nested `team.parallel_writes.mode`
- HOTL auto-detection is default behavior (no `auto` setting needed)
- Legacy schema accepted with deprecation warnings
- Config migration: `.agenteam/config.yaml` preferred, `agenteam.yaml` legacy fallback

### v1.2 -- Standup
- `cmd_standup` with health indicators (on-track / at-risk / off-track)
- Reads state + artifacts, synthesizes Linear-style report (<2s)
- `--dispatch` flag for deepdive mode

### v1.3 -- Deepdive + Branch Isolation
- `@ATeam deepdive`: parallel dispatch of researcher + architect + PM (30-60s)
- `scripts/git-isolate.sh`: preflight, create-branch, create-worktree, return, cleanup
- `cmd_branch_plan`: resolves branch/worktree plan based on isolation mode
- Writing agents never work on user's branch (serial/worktree mode)

### v2.0 -- Verified Pipeline
- Stage verification: `verify` command per stage, must exit 0 to advance
- Auto-detection of test runners (pytest, npm, go, cargo, make)
- Retry on failure: `max_retries` per stage with scope-aware repair role selection
- Final verification: mandatory test suite + lint before declaring success
- Agent gates: reviewer/qa can approve stages (self-approval prevention)
- `scripts/verify-stage.sh`: execute verify commands in isolated workspace

### v2.1 -- Scoped Parallel Writes
- `partition_writer_groups()`: non-overlapping writers dispatch in parallel
- `cmd_scope_audit`: containment check (files outside all scopes = violation)
- Serialized commit capture: controller commits per role after parallel execution
- Serial fallback on containment violation

### v2.2 -- Governance Completion (current)
- Cross-stage rework: test fails -> dev repairs -> test re-verifies (`rework_to`)
- Per-stage rollback: user-confirmed reset to baseline (branch/worktree only)
- Run reports: `.agenteam/reports/<run-id>.md` at completion/failure
- Gate criteria: `max_files_changed`, `scope_paths`, `requires_tests`
- Criteria overrides recorded as distinct audit events
- Run-level + stage-level timestamps in state

## Next

### HOTL Skill Adapter
- Per-stage `strategy: hotl:<skill>` (light bond, not hard dependency)
- Stage-to-skill mapping: design -> brainstorming, plan -> writing-plans, implement -> loop-execution, review -> code-review
- Graceful fallback to standalone when HOTL unavailable
- AgenTeam owns: roles, write policy, gates, state. HOTL owns: step-level execution.
- Design: ready to implement (mapping complete)

### SessionStart Hook
- Auto-detect `.agenteam/config.yaml` on Codex startup
- Inject team context without user action
- Highest-leverage adoption driver

### Audience-Tailored Output
- `--format brief | json` for standup/deepdive
- CI/CD integration (json), Slack (brief), dashboards

## Future

- Resume interrupted pipeline runs
- Execution reports with event logs
- Glob-aware write scope overlap detection
- Organization-level memory and cross-project patterns
