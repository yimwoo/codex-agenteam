---
name: ateam-add-role
description: Add a custom role to the project's agenteam.yaml config. Accepts natural language descriptions.
---

# AgenTeam Add Role

Add a new team member from a natural language description.

## Process

### 1. Auto-Init Guard

Check for `agenteam.yaml` in the project root. If missing:
- Copy the template: `cp <plugin-dir>/templates/agenteam.yaml.template agenteam.yaml`
- Set the team name to the project directory name
- Generate agents: `python3 <runtime>/agenteam_rt.py generate`

### 2. Parse Intent

Extract role details from the user's natural language request. Examples:

- "Add a performance tuning engineer" ->
  name: `performance_engineer`, focus: profiling + optimization
- "I need a security auditor on the team" ->
  name: `security_auditor`, focus: vulnerabilities + auth
- "Add a docs writer that maintains README and API docs" ->
  name: `docs_writer`, focus: documentation, write_scope: `docs/**`
- "Add a DevOps engineer for CI/CD" ->
  name: `devops_engineer`, focus: pipelines + deployment

Infer as much as possible from the description:

| Field | How to infer |
|-------|-------------|
| `name` | Snake_case from the role title |
| `description` | From user's description |
| `responsibilities` | 3-5 items inferred from the role's domain |
| `participates_in` | Match to pipeline stages: research, strategy, design, plan, implement, test, review |
| `can_write` | Yes if the role creates/modifies files; no if it only analyzes |
| `write_scope` | Infer from what the role writes (docs, src, tests, configs) |
| `model` | o3 for analysis/review roles, o3-mini for writing/implementation roles |
| `reasoning_effort` | high for analysis roles, medium for writing roles |
| `system_instructions` | Generate focused instructions from the role's domain |

### 3. Confirm with User

Present the inferred role as a summary and ask for confirmation:

```
Here's your new team member:

  Name: performance_engineer
  Focus: Profiling, bottleneck analysis, optimization
  Stages: review, implement
  Writes to: src/** (optimization patches)
  Model: o3 (high reasoning)

  System instructions:
  You are the performance engineer on a AgenTeam. Your primary job is
  to identify bottlenecks and optimize critical paths...

Add to team? (yes / adjust)
```

If the user says "adjust" or requests changes, update the fields and
re-confirm. Do not ask field-by-field -- keep it conversational.

### 4. Write to Config

Read the current `agenteam.yaml` and add the new role under `roles:`.

Write the full role block including:
- `description`
- `responsibilities`
- `participates_in`
- `can_write` and `write_scope` (if applicable)
- `model` and `reasoning_effort`
- `parallel_safe` (true for read-only roles, false for writers unless scoped)
- `system_instructions`

If the role participates in a pipeline stage, also add it to the
appropriate `pipeline.stages[].roles` list.

### 5. Regenerate Agents

```bash
python3 <runtime>/agenteam_rt.py generate
```

### 6. Confirm

Show the user:
- The generated agent file: `.codex/agents/<name>.toml`
- How to use it immediately:
  - Codex App: `@ateam ask <name> to <task>`
  - Codex CLI: `$ateam-assign <name> "<task>"`
- Reminder: "Edit `agenteam.yaml` anytime to adjust this role."
