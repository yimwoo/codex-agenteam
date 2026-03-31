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

# Dispatch a stage
agenteam-rt dispatch implement --task "add auth" --run-id <id>

# Check run status
agenteam-rt status <run-id>

# Get verification plan for a stage
agenteam-rt verify-plan implement --run-id <id>

# Record verification result
agenteam-rt record-verify --run-id <id> --stage implement --result pass

# Get final verification plan
agenteam-rt final-verify-plan --run-id <id>
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
