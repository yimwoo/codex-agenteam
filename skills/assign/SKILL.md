---
name: assign
description: Assign a task to a specific role on your team.
---

# AgenTeam Assign

Assign a task to a specific team member, independent of the pipeline.

## Process

### 1. Auto-Init Guard

Check for `.agenteam/config.yaml` (or legacy `agenteam.yaml`) in the project root. If missing:
- Create config dir: `mkdir -p .agenteam`
- Copy the template: `cp <plugin-dir>/templates/agenteam.yaml.template .agenteam/config.yaml`
- Set the team name to the project directory name
- Generate agents: `python3 <runtime>/agenteam_rt.py generate`
- Tell the user: "AgenTeam auto-initialized with default roles. Edit `.agenteam/config.yaml` to customize."

### 2. Accept Input

Get the role name and task from the user. Examples:
- `$ateam:assign architect "Review this API design"`
- `$ateam:assign reviewer "Check auth logic in src/auth.py"`
- `@ateam assign researcher to investigate caching strategies`
- `@ateam ask pm what we should build next`

If role or task is missing, ask.

### 3. Validate Role

```bash
python3 <runtime>/agenteam_rt.py roles show <role-name>
```

If the role doesn't exist, show available roles:
```bash
python3 <runtime>/agenteam_rt.py roles list
```

### 4. Check Write Policy

If the role has `can_write: true`, check for active write locks:

```bash
python3 <runtime>/agenteam_rt.py status
```

If a write lock is active and the role needs to write:
- Inform the user: "Write lock held by <active_role>. Wait for completion or
  override with confirmation."
- Do not proceed without user approval.

### 5. Resolve Artifact Paths

```bash
python3 <runtime>/agenteam_rt.py artifact-paths
```

Pass the resolved output paths to the agent so it writes artifacts to
the correct location (standalone vs HOTL mode).

### 6. Launch Agent

Launch the role as a Codex subagent using the generated agent file:
- Agent file: `.codex/agents/<role-name>.toml`
- Pass the task description as the prompt
- Pass relevant project context (current branch, recent changes, etc.)
- Pass artifact paths from step 5

### 7. Collect Output

Present the agent's output to the user with the role name as context:
"**[architect]:** <output>"

## Notes

- Assign works regardless of pipeline setting
- Multiple read-only roles can be assigned in parallel
- Write roles follow the configured write policy
