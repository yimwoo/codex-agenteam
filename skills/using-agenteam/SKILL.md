---
name: using-agenteam
description: Router skill for AgenTeam plugin. Maps user intent to the appropriate skill.
---

# AgenTeam Router

You have the **AgenTeam** plugin installed. It provides role-based team
collaboration for AI-assisted development. You are the lead; the plugin
organizes your specialist roles.

## Available Skills

| Skill | Invoke | When to Use |
|-------|--------|-------------|
| ateam-init | `$ateam-init` | Set up team config for a project |
| ateam-run | `$ateam-run` | Run a full pipeline (standalone or HOTL) |
| ateam-assign | `$ateam-assign` | Assign a task to a specific role |
| ateam-status | `$ateam-status` | Show current team state and progress |
| ateam-add-role | `$ateam-add-role` | Add a custom role to the project |
| ateam-generate | `$ateam-generate` | Regenerate .codex/agents/*.toml from config |

## Auto-Init (Zero-Step Setup)

Before routing, check if the current project has `agenteam.yaml`:

1. Look for `agenteam.yaml` in the project root
2. **If missing:** automatically bootstrap the project:
   - Copy the template: `cp <plugin-dir>/templates/agenteam.yaml.template agenteam.yaml`
   - Set the team name to the project directory name
   - Generate agents: `python3 <plugin-dir>/runtime/agenteam_rt.py generate`
   - Tell the user: "AgenTeam initialized with default roles (researcher, pm, architect, implementer, test_writer, reviewer). Edit `agenteam.yaml` to customize."
3. **If present:** continue to intent routing

This ensures users can start using `@ateam` or any skill immediately after
install -- no separate init step required.

## Artifact Path Auto-Detection

After init, resolve where each role should write its artifacts:

```bash
python3 <runtime>/agenteam_rt.py artifact-paths
```

This auto-detects whether HOTL is active in the project and returns the
correct output paths:

| Role | Standalone Mode | HOTL Mode |
|------|----------------|-----------|
| researcher | `docs/research/` | `docs/research/` |
| pm | `docs/strategies/` | `docs/strategies/` |
| architect | `docs/designs/` | `docs/plans/` (HOTL convention) |
| implementer (plans) | `docs/plans/` | `./` (hotl-workflow-*.md at root) |
| implementer (code) | `src/**`, `lib/**` | `src/**`, `lib/**` |

Detection logic:
- If `pipeline: hotl` in config -> use HOTL paths
- If `pipeline: auto` and project has `.hotl/` or `hotl-workflow-*.md` -> use HOTL paths
- Otherwise -> use standalone paths

Skills should call `artifact-paths` before dispatching roles and pass the
resolved paths as context to each agent.

## Intent Routing

Match user intent to the right skill:

- **"Set up team" / "Initialize team" / "Configure roles"** -> `$ateam-init`
- **"Run this task" / "Build feature X" / "Work on this"** -> `$ateam-run`
- **"Ask researcher to..." / "Ask pm to..." / "Assign to reviewer" / "Get architect input"** -> `$ateam-assign`
- **"What should we build next?" / "Research X" / "Prioritize features"** -> `$ateam-assign` (routes to pm or researcher)
- **"Show status" / "What's the team doing?" / "Progress?"** -> `$ateam-status`
- **"Add a security auditor" / "New role" / "Custom role"** -> `$ateam-add-role`
- **"Regenerate agents" / "Update TOML" / "Sync agents"** -> `$ateam-generate`

## Quick Reference

**Default roles:** researcher (research/design), pm (strategy/design),
architect (design/review), implementer (plan/implement),
test_writer (test), reviewer (review).

**Config file:** `agenteam.yaml` in project root.

**Generated agents:** `.codex/agents/*.toml` -- Codex-native custom agents.

**Pipeline modes:** standalone (built-in), hotl (explicit opt-in), dispatch-only (ad-hoc).

**Pipeline flow:** research -> strategy -> design -> plan -> implement -> test -> review
