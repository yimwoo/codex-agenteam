# Configuration Reference

AgenTeam works out of the box with zero config. Customize when you're ready.

## Config File Locations

AgenTeam supports a two-layer config model for team collaboration:

| File | Purpose | Tracked in git? |
|------|---------|----------------|
| `.agenteam.team/config.yaml` | **Team config** — shared pipeline, roles, stages, isolation | Yes |
| `.agenteam/config.yaml` | **Personal config** — local overrides (model, reasoning_effort) | No (gitignored) |
| `agenteam.yaml` | Legacy config (still supported) | No (gitignored) |

**How it works:**
- If only one config exists, it's used as the full config
- If both team and personal exist, they merge: team is the base, personal overrides apply to allowlisted fields only
- Personal config is optional — most users only need the team config

**Resolution order:** plugin defaults → team config → personal overrides → effective config

## Minimal Config

```yaml
version: "1"
```

Everything else is inferred from defaults and auto-detection.

## Customized Config

```yaml
version: "2"
isolation: worktree       # branch (default) | worktree | none

roles:
  dev:
    write_scope:
      - "src/**"
      - "lib/**"

pipeline:
  stages:
    - name: implement
      roles: [dev]
      gate: auto
```

## Full Config Example

```yaml
version: "2"
isolation: branch              # branch (default) | worktree | none
# pipeline: hotl               # omit for auto-detect

# Override built-in roles or add custom ones
roles:
  dev:
    model: o4-mini
    reasoning_effort: high
    write_scope:
      - "src/**"
      - "lib/**"
      - "docs/plans/**"

  # Custom roles
  security_auditor:
    description: "Reviews code for security vulnerabilities"
    participates_in: [review]
    can_write: false
    system_instructions: |
      Focus on OWASP top 10, auth/authz logic, and hardcoded secrets.

# Final verification (runs after all stages)
final_verify:
  - "python3 -m pytest -v"
final_verify_policy: block     # block (default) | warn
final_verify_max_retries: 1

# Pipeline stages
pipeline:
  stages:
    - name: research
      roles: [researcher]
      gate: auto
    - name: strategy
      roles: [pm]
      gate: human
    - name: design
      roles: [architect, pm, researcher]
      gate: human
    - name: plan
      roles: [dev]
      gate: human
    - name: implement
      roles: [dev]
      gate: auto
      verify: "python3 -m pytest -v"
      max_retries: 2
      rework_to: plan
    - name: test
      roles: [qa]
      gate: auto
    - name: review
      roles: [reviewer]
      gate: human

  # Pipeline profiles — right-size the pipeline to the task
  profiles:
    quick:
      stages: [implement, test]
      hints: [typo, one-line fix, config change, version bump]
    standard:
      stages: [design, plan, implement, test, review]
      hints: [new endpoint, refactor, add feature, fix bug]
```

Use profiles with `@ATeam --profile quick fix the typo in README`.

## Built-in Roles

| Role | Participates In | Can Write | Write Scope | Parallel Safe |
|------|----------------|-----------|-------------|---------------|
| Researcher | research, design | Yes | `docs/research/**` | Yes |
| PM | strategy, design | Yes | `docs/strategies/**` | Yes |
| Architect | design | Yes | `docs/designs/**` | Yes |
| Dev | plan, implement | Yes | `src/**`, `lib/**`, `docs/plans/**` | No |
| Qa | test | Yes | `tests/**`, `**/*.test.*` | Yes |
| Reviewer | review | No | -- | Yes |

## Custom Roles

Add custom roles in the `roles:` section of your config:

```yaml
roles:
  security_auditor:
    description: "Reviews code for security vulnerabilities"
    participates_in: [review]
    can_write: false
    system_instructions: |
      Focus on OWASP top 10, auth/authz logic, and hardcoded secrets.

  docs_writer:
    description: "Maintains documentation"
    participates_in: [implement]
    can_write: true
    write_scope: ["docs/**", "README.md"]
```

Or add them interactively:

```
@ATeam add a security auditor that focuses on auth and data leaks
@ATeam add a performance engineer to profile API response times
```

## Branch Isolation

Writing agents are automatically isolated — they never touch your current branch directly.

| Mode | Behavior |
|------|----------|
| `branch` *(default)* | Creates `ateam/<role>/<task>` branch per assignment |
| `worktree` | Creates an isolated git worktree per writer |
| `none` | Stays on current branch (relies on non-overlapping write scopes) |

Set in config:

```yaml
isolation: worktree
```

## Model Routing

Different roles benefit from different model strengths. Analysis roles (researcher, pm, architect, reviewer) make judgment calls and evaluate trade-offs — they benefit from strong reasoning models. Execution roles (dev, qa) write code and tests — they benefit from fast coding models.

| Role Class | Examples | Recommended Model Type |
|-----------|----------|----------------------|
| Analysis | researcher, pm, architect, reviewer | Strong reasoning (e.g., `o3-pro`, `claude-sonnet-4-5`) |
| Execution | dev, qa | Fast coding (e.g., `gpt-5.3-codex`, `claude-sonnet-4-5`) |

Model selection is a **personal override** — `share-config` strips `model` and `reasoning_effort` from team config because model availability varies by platform and API key.

```yaml
# In .agenteam/config.yaml (personal)
roles:
  architect:
    model: o3-pro              # strong reasoning for design
  researcher:
    model: o3-pro              # strong reasoning for research
  dev:
    model: gpt-5.3-codex       # fast coding for implementation
  qa:
    model: gpt-5.3-codex       # fast coding for tests
```

**When to override the defaults:**
- **Budget-conscious**: use the same fast model for all roles
- **High-stakes design**: use the strongest available model for architect
- **Large codebase**: prefer models with large context windows for researcher
- **Custom roles**: match the model to the role's primary job (analysis vs execution)

### Cross-Model Review

Using the same model for both dev (writing code) and reviewer (reviewing code) can produce sycophantic reviews — the reviewer tends to approve its own model's patterns. For higher-quality reviews, use different models:

```yaml
roles:
  dev:
    model: gpt-5.3-codex       # writes code
  reviewer:
    model: o3-pro              # reviews with different reasoning
```

This is especially valuable for security-sensitive work where independent review matters most.

## Team Config (Shared)

For teams, create a shared config that all members use:

```
@ATeam share-config
```

This copies your local config to `.agenteam.team/config.yaml`, strips personal
fields (model, reasoning_effort, system_instructions), and sets `version: "2"`.
Commit it to git:

```bash
git add .agenteam.team/
git commit -m "Add shared AgenTeam team config"
```

Team members who clone the repo get the shared pipeline, roles, and stages
automatically — no per-developer setup needed.

## Personal Overrides

Personal config (`.agenteam/config.yaml`) can override a limited set of fields:

| Field | Behavior |
|-------|----------|
| `roles.<name>.model` | Replace (use a different model locally) |
| `roles.<name>.reasoning_effort` | Replace |
| `roles.<name>.system_instructions` | Append (personal addendum, not replacement) |

**Non-overridable fields** (always from team config):
- `pipeline.stages`, gates, verify commands
- `roles.<name>.write_scope`, `can_write`
- `final_verify`, `final_verify_policy`

**Escape hatch:** Team config can widen the personal allowlist:

```yaml
# .agenteam.team/config.yaml
allow_personal_override:
  - isolation
```

**Personal config cannot define new roles.** Custom roles must be added to
the team config.

Example personal override:

```yaml
# .agenteam/config.yaml
version: "2"
roles:
  dev:
    model: o4-mini
    reasoning_effort: medium
```

## Config Migration

If you have a legacy config using `team.pipeline` or `team.parallel_writes.mode`, migrate to the canonical format:

```bash
# Preview changes
python3 runtime/agenteam_rt.py migrate --dry-run

# Apply migration
python3 runtime/agenteam_rt.py migrate
```

Migration bumps `version` to `"2"`, transforms legacy keys to flat top-level keys, and creates a timestamped backup of the original file.

## Validation

Validate your config for errors and warnings:

```bash
# Summary (default)
python3 runtime/agenteam_rt.py validate

# Full structured diagnostics
python3 runtime/agenteam_rt.py validate --format diagnostics

# Treat warnings as errors
python3 runtime/agenteam_rt.py validate --strict
```

Validation checks: required fields, enum values, stage-role cross-references, profile consistency, duplicate stage names, rework_to targets, and suggests corrections for typos.

## Optional Governance Run Metadata

For governed-delivery foundations, you can attach contextual metadata when creating a run:

```bash
agenteam-rt init --task "major feature" \
  --initiative "checkout-v2" \
  --phase "plan" \
  --checkpoint "kickoff" \
  --burn-estimate 24
```

These fields are optional and backward compatible. When present they are stored under `state.governance` and surfaced in `status` and `standup`.

They do not change pipeline behavior by themselves. Use them when you want
extra context on larger initiatives, and ignore them for small tasks or POCs.

## Governed Delivery Tripwires

`agenteam-rt governed-bootstrap` creates a starter tripwire catalog at:

```text
.agenteam/governance/tripwires.yaml
```

Initial tripwires support a small, config-driven format with these match fields:

- `path_glob`
- `artifact_type`
- `decision_right`

And these severities:

- `warn`
- `block`

Evaluate them with:

```bash
agenteam-rt tripwire check --path src/auth/login.py
agenteam-rt tripwire check --artifact-type adr --decision-right schema-change
```

Tripwires are config-driven and opt-in. This is a minimal foundation for
pre-commit and CI integration, not a full policy engine.
