---
name: status
description: Show the current state of a run — stages, roles, write locks, and gates.
---

# AgenTeam Status

Display the current state of the team's work.

## Process

### 1. Get Status

```bash
python3 <runtime>/agenteam_rt.py status
```

### 2. Format Output

Display the run state in a readable format:

```
AgenTeam: <team-name>
Pipeline: <mode>
Task: <task description>
Run: <run-id>

Stages:
  design     ✓ completed  [architect]        gate: approved
  plan       ✓ completed  [architect]        gate: approved
  implement  → in_progress [dev]     write_lock: active
  test       · pending     [qa]
  review     · pending     [reviewer]

Write Policy: serial
Active Lock: dev
Queue: (empty)
```

### 3. No Active Run

If no run is found, show:
- Team config status (does `.agenteam/config.yaml` or legacy `agenteam.yaml` exist?)
- Available roles
- Suggestion: "Use `$ateam:run` to start a new task."

## Symbols

- `✓` — completed
- `→` — in progress
- `·` — pending
- `✗` — failed/blocked
