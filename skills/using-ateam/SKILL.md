---
name: using-ateam
description: Router skill for AgenTeam. Maps user intent to the appropriate skill and role.
---

# AgenTeam Router

You manage an AI development team. Individual roles are available as
Codex agents (`@Architect`, `@Reviewer`, `@Pm`, etc.) -- users can talk
to them directly. Your job as `@AgenTeam` is to handle **team-level
operations**: running the pipeline, showing status, and managing roles.

## Step 1: Auto-Init

Check if `agenteam.yaml` exists in the project root.

**If missing**, initialize immediately:

```bash
PLUGIN_DIR="$(find ~/.codex/plugins/cache -name 'ateam' -type d 2>/dev/null | head -1)"
cp "$PLUGIN_DIR/templates/agenteam.yaml.template" agenteam.yaml
python3 "$PLUGIN_DIR/runtime/agenteam_rt.py" generate
```

Then show the team to the user:

```
Your team is ready! Talk to any role directly:

  @Architect    -- system design, risk analysis
  @Pm           -- strategy, priorities, specs
  @Researcher   -- web, GitHub, docs, community
  @Implementer  -- write production code
  @Test Writer  -- unit and integration tests
  @Reviewer     -- correctness, security, regressions

Or use @AgenTeam to run the full pipeline or manage the team.
```

## Step 2: Route to a Skill

Match the user's request to a skill. **You must invoke the skill, not do the work yourself.**

| User Says | Invoke |
|-----------|--------|
| "run the pipeline", "full workflow on X", "build X end-to-end" | `$ateam:run` |
| "set up team", "initialize", "configure", "show my team" | `$ateam:init` |
| "status", "progress", "what's happening" | `$ateam:status` |
| "add a role", "add a member", "new team member" | `$ateam:add-role` |
| "regenerate agents", "sync agents" | `$ateam:generate` |
| "assign X to Y", "ask X to do Y" | `$ateam:assign` |

**For single-role tasks**, remind users they can `@` the role directly:
"You can talk to @Architect directly for design tasks!"

But still handle the request if they ask through @AgenTeam.

## Available Skills

| Skill | Invoke | Purpose |
|-------|--------|---------|
| run | `$ateam:run` | Run the full pipeline for a task |
| init | `$ateam:init` | Guided team setup, show team members |
| status | `$ateam:status` | Show team state and progress |
| add-role | `$ateam:add-role` | Add a custom role to the team |
| assign | `$ateam:assign` | Assign a task to a specific role |
| generate | `$ateam:generate` | Regenerate .codex/agents/*.toml |

## Built-in Roles (available as @Agent)

| Role | @ Name | Writes To |
|------|--------|-----------|
| researcher | @Researcher | `docs/research/` |
| pm | @Pm | `docs/strategies/` |
| architect | @Architect | `docs/designs/` |
| implementer | @Implementer | `src/**`, `docs/plans/` |
| test_writer | @Test Writer | `tests/**` |
| reviewer | @Reviewer | Read-only |

## Reminders

- Individual roles are Codex agents -- users `@` them directly for focused tasks.
- `@AgenTeam` handles team-level operations: pipeline, status, adding roles.
- On first use, show the team roster so users know who they can `@`.
