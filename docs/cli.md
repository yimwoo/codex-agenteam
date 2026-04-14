# CLI Reference

## Codex Skills

These are the primary commands for Codex App and Codex CLI users:

| Command | Purpose |
|---------|---------|
| `$ateam:init` | Set up team config and generate agents |
| `$ateam:run "task"` | Run the full pipeline on a task |
| `$ateam:resume` | Resume an interrupted run |
| `$ateam:status` | Show team status and current config |
| `$ateam:add-member` | Add a custom team member |
| `$ateam:generate` | Regenerate agents after config changes |
| `$ateam:standup` | Quick project status report |
| `$ateam:assign <role> "task"` | Assign a task to a specific role |
| `$ateam:ci-repair <pr-or-branch>` | Fix CI failures — fetch logs, dispatch dev, verify, push |
| `$ateam:share-config` | Promote local config to shared team config |

## Runtime CLI

The runtime CLI (`agenteam-rt`) is the underlying engine. Skills call it internally, but you can use it directly for automation or debugging.

### Config & Validation

```bash
# Validate config
agenteam-rt validate
agenteam-rt validate --format diagnostics    # full structured output
agenteam-rt validate --strict                # treat warnings as errors

# Migrate legacy config to canonical format
agenteam-rt migrate --dry-run                # preview changes
agenteam-rt migrate                          # apply migration
```

### Roles

```bash
# List all resolved roles
agenteam-rt roles list

# Show a specific role's config
agenteam-rt roles show dev
```

### Pipeline Operations

```bash
# Initialize a run
agenteam-rt init --task "add auth" --profile quick

# Initialize a run with optional governance metadata
agenteam-rt init --task "billing revamp" --profile standard \
  --initiative "billing-platform" --phase "requirements" \
  --checkpoint "kickoff" --burn-estimate 16

# Dispatch a stage
agenteam-rt dispatch implement --task "add auth" --run-id <id>

# Check run status for latest compatible local run
# Includes a memory block with concise carry-forward lessons from
# compatible prior runs when available
agenteam-rt status

# Check run status for a specific run
agenteam-rt status <run-id>

# Get verification plan for a stage
agenteam-rt verify-plan implement --run-id <id>

# Record verification result
agenteam-rt record-verify --run-id <id> --stage implement --result pass

# Get final verification plan
agenteam-rt final-verify-plan --run-id <id>

# Build the fully composed prompt for a role dispatch (for codex exec / harnesses)
agenteam-rt prompt-build --run-id <id> --stage implement --role dev

# Run the full pipeline non-interactively via codex exec
agenteam-rt run --task "add user auth" --auto-approve-gates
agenteam-rt run --task-file seed.md --profile standard --output-dir ./out
agenteam-rt run --run-id <id>  # resume an existing run
```

### Governed Delivery Foundations

```bash
# Scaffold local governed-delivery assets
agenteam-rt governed-bootstrap

# Append a structured decision record
agenteam-rt decision append \
  --outcome escalated \
  --summary "Auth migration requires DBA approval" \
  --initiative "platform-auth" \
  --phase "triage" \
  --role architect \
  --decision-right "schema-change" \
  --artifact-type adr \
  --artifact-ref docs/decisions/012-auth-migration.md

# List decisions (optionally filtered)
agenteam-rt decision list --initiative platform-auth --last 10

# Render Markdown decision log from structured records
agenteam-rt decision render-log

# Evaluate tripwires against changed paths or artifact context
agenteam-rt tripwire check --path src/auth/login.py
agenteam-rt tripwire check --artifact-type adr --decision-right schema-change
```

### Branch & Isolation

```bash
# Resolve branch/worktree plan for a task
agenteam-rt branch-plan --task "add auth" --role dev

# Check write scope overlaps
agenteam-rt policy check

# Audit changed files against write scopes
agenteam-rt scope-audit --run-id <id> --stage implement --baseline <sha>
```

### Gates & Transitions

```bash
# Evaluate gate criteria
agenteam-rt gate-eval --run-id <id> --stage implement

# Record gate decision
agenteam-rt record-gate --run-id <id> --stage implement \
  --gate-type human --result approved

# Validate and apply stage transition
agenteam-rt transition --run-id <id> --stage implement --to passed
```

### Events & Resume

```bash
# Append an event
agenteam-rt event append --run-id <id> --type stage_dispatched \
  --data '{"roles": ["dev"], "isolation": "branch"}'

# List events
agenteam-rt event list --run-id <id> --type stage_verified --last 5

# Detect stale resumable runs
agenteam-rt resume-detect

# Build resume plan
agenteam-rt resume-plan --run-id <id>
```

### Reports & Health

```bash
# Assemble run report
agenteam-rt run-report --run-id <id>

# Show runtime/project readiness
agenteam-rt health

# Assemble standup summary with current health, dispatch hints, and
# compatible carry-forward memory
agenteam-rt standup

# Generate .codex/agents/*.toml from config
agenteam-rt generate
```

### HOTL Integration

```bash
# Check HOTL availability
agenteam-rt hotl check

# Resolve HOTL skill eligibility for a role
agenteam-rt hotl-skills --run-id <id> --stage implement --role dev
```

## Output Format

All runtime commands output JSON to stdout. Errors go to stderr as JSON. Exit code 0 = success, 1 = error.
