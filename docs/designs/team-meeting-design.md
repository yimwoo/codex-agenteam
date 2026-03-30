# Team Meeting Feature -- Technical Design

## Overview

A new `meeting` command that dispatches all roles in parallel to analyze the
current project from their specialist perspective, then aggregates the results
into a structured team status report.

**Trigger:** `@ATeam give me project status from everyone` (or variants like
`@ATeam team meeting`, `@ATeam standup`, `$ateam:meeting`)

**Output:** A single aggregated report with per-role sections, written to
`docs/meetings/` and displayed to the user.

---

## 1. Design Decision: Parallel Dispatch (Option A)

**Chosen approach:** Dispatch all roles in parallel, aggregate results.

**Why not the alternatives:**

- **(B) Sequential round-robin** is too slow. The whole point is "status from
  everyone" -- serial execution turns a 30-second operation into a 3+ minute
  one. There is no inter-role dependency for read-only status checks.
- **(C) Dedicated monolithic skill** loses the value of specialist perspectives.
  A single prompt trying to be researcher + architect + pm produces shallower
  analysis than six focused prompts. It also bypasses the role system entirely.

**Why parallel works here:**

- Meeting dispatch is **read-only**. No role writes code or modifies artifacts.
  Every role runs in `read` mode with no write locks. This sidesteps the serial
  write policy entirely.
- Each role examines **disjoint data sources** (see Section 2). There are no
  contention or ordering dependencies.
- The existing `dispatch` command already produces dispatch plans with parallel
  entries. The meeting feature follows this pattern.

---

## 2. Data Sources Per Role

Each role's meeting prompt directs it to examine specific project artifacts and
state. All access is read-only.

| Role | Data Sources | What They Report |
|------|-------------|------------------|
| **researcher** | `docs/research/`, web/community changes | Research freshness, gaps, external changes since last report |
| **pm** | `docs/strategies/`, open issues, backlog | Priority alignment, spec coverage, outstanding decisions |
| **architect** | `docs/designs/`, code structure, `docs/plans/` | Design health, tech debt signals, structural concerns |
| **implementer** | `git log --oneline -20`, recent diffs, WIP branches | Recent progress, active work, blockers |
| **qa** | test results (`pytest`/`jest` output), coverage reports | Test health, coverage gaps, failing tests |
| **reviewer** | open PRs, unreviewed changes, `git diff main..HEAD` | Review backlog, unreviewed risk, outstanding issues |

**Implementation note:** The runtime does not execute these checks. The runtime
produces a **meeting dispatch plan** with per-role context hints. The skill layer
(SKILL.md) tells each role agent what to examine. The role agent, running as a
Codex subagent, uses its own tools to read files, run git commands, etc.

---

## 3. Interaction with Codex max_threads=6

**Constraint:** Codex defaults to `max_threads=6` concurrent subagent threads.

**Analysis:** The default team has exactly 6 built-in roles. Dispatching all 6
in parallel saturates the thread pool but does not exceed it.

**Edge cases and mitigations:**

1. **Custom roles bring total above 6.** The runtime's `cmd_meeting` already
   emits a warning when agent count > 6 (same pattern as `cmd_generate`). The
   skill layer can batch: dispatch the first 6, wait for completion, dispatch
   the rest. But for the default team, this is not needed.

2. **User has reduced max_threads.** The skill layer cannot control Codex's
   thread scheduler. If max_threads < role count, Codex will naturally queue
   the excess agents. No special handling needed -- the meeting still completes,
   just with some roles queued behind others.

3. **Meeting during an active pipeline run.** If a pipeline run is in progress
   with active agents, the meeting agents compete for threads. The skill should
   check for active runs and warn: "A pipeline run is in progress. Meeting
   agents will share threads with active pipeline agents."

**Decision:** For v1, dispatch all roles simultaneously. Let Codex's thread
scheduler handle queuing. The runtime emits a warning if role count > 6.

---

## 4. Output Location and Format

### Location: `docs/meetings/`

- Path: `docs/meetings/<timestamp>-meeting.md`
- Example: `docs/meetings/20260329T143000Z-meeting.md`
- The `docs/meetings/` directory follows the existing pattern (`docs/research/`,
  `docs/strategies/`, `docs/designs/`, `docs/plans/`).

### Format: Structured Markdown

```markdown
# Team Meeting -- 2026-03-29T14:30:00Z

Task context: <active task or "No active pipeline run">
Pipeline state: <current stage or "Idle">

## Researcher
<researcher's status report>

## PM
<pm's status report>

## Architect
<architect's status report>

## Implementer
<implementer's status report>

## QA
<qa's status report>

## Reviewer
<reviewer's status report>

## Summary
<aggregated highlights, blockers, and suggested next steps>
```

### Display behavior

1. Each role's report is streamed to the user as it completes (not held until
   all finish).
2. After all roles complete, the skill writes the aggregated file to
   `docs/meetings/` and displays the summary section.
3. Stdout shows the full report. The file is a persistent record.

---

## 5. Runtime Changes

### 5a. New command: `agenteam_rt.py meeting`

```
python3 runtime/agenteam_rt.py meeting [--task "<context>"]
```

**Output (JSON):**

```json
{
  "type": "meeting",
  "timestamp": "20260329T143000Z",
  "roles": [
    {
      "role": "researcher",
      "agent": ".codex/agents/researcher.toml",
      "mode": "read",
      "context_hint": "Examine docs/research/ for freshness. Check for external changes.",
      "data_sources": ["docs/research/"]
    },
    {
      "role": "pm",
      "agent": ".codex/agents/pm.toml",
      "mode": "read",
      "context_hint": "Review docs/strategies/ and open issues. Report on priority alignment.",
      "data_sources": ["docs/strategies/"]
    },
    {
      "role": "architect",
      "agent": ".codex/agents/architect.toml",
      "mode": "read",
      "context_hint": "Assess docs/designs/ and code structure. Flag tech debt or structural concerns.",
      "data_sources": ["docs/designs/", "docs/plans/"]
    },
    {
      "role": "implementer",
      "agent": ".codex/agents/implementer.toml",
      "mode": "read",
      "context_hint": "Report on recent git activity, WIP branches, and current progress.",
      "data_sources": []
    },
    {
      "role": "qa",
      "agent": ".codex/agents/qa.toml",
      "mode": "read",
      "context_hint": "Run tests if possible. Report on test health, coverage, and failures.",
      "data_sources": ["tests/"]
    },
    {
      "role": "reviewer",
      "agent": ".codex/agents/reviewer.toml",
      "mode": "read",
      "context_hint": "Check for unreviewed changes. Report on open PRs and review backlog.",
      "data_sources": []
    }
  ],
  "output_path": "docs/meetings/20260329T143000Z-meeting.md",
  "warnings": []
}
```

**Key properties:**

- Every role has `"mode": "read"`. No write locks are needed.
- `context_hint` gives the skill layer a prompt fragment to inject into each
  role agent's task. The runtime does not hardcode prompts -- it provides hints.
- `data_sources` lists directories the role should examine. These are the
  role's artifact paths from the existing config.
- `output_path` tells the skill where to write the aggregated report.
- `warnings` contains thread-count warnings if role count > 6.

**Why a new command (not reusing `dispatch`):**

- `dispatch` is stage-oriented: it takes a stage name, resolves which roles
  participate in that stage, and checks write policy. Meeting is not a pipeline
  stage -- it cross-cuts all roles regardless of their `participates_in` config.
- `dispatch` produces write-lock-aware plans. Meeting is always read-only.
- A dedicated command keeps the meeting semantics clean without overloading
  `dispatch` with mode flags.

### 5b. No new state

Meetings are stateless. They do not create run state, modify pipeline progress,
or acquire write locks. The only persistent artifact is the output file in
`docs/meetings/`.

If there is an active run, the meeting command reads its state to include
context ("Task: X, currently at stage: Y") but does not modify it.

### 5c. Context from active run (optional)

```
python3 runtime/agenteam_rt.py meeting --task "context override"
```

If `--task` is not provided and an active run exists, the runtime pulls the
task description from the latest run state. If no run exists and no `--task`
is provided, the meeting proceeds with generic project-status context.

---

## 6. Skill Layer

### New skill: `skills/meeting/SKILL.md`

The skill is responsible for:

1. Calling the runtime to get the meeting dispatch plan.
2. Launching all role agents in parallel as Codex subagents (read-only).
3. Injecting the `context_hint` into each agent's task prompt.
4. Collecting outputs as they arrive.
5. Assembling the final meeting report.
6. Writing the report to `docs/meetings/`.
7. Displaying the report to the user.

### Meeting prompt template (per role)

Each role agent receives a prompt like:

```
You are attending a team meeting as the {role}. Give a brief project status
report from your perspective.

{context_hint}

Focus on:
- Current state of your area
- Any blockers or concerns
- What you think should happen next

Keep it concise -- 3-5 bullet points. This is a standup, not a design review.
```

### Router integration

The `using-ateam` skill (router) needs a new row in its routing table:

| User Says | Invoke |
|-----------|--------|
| "team meeting", "standup", "project status from everyone", "status from all roles" | `$ateam:meeting` |

---

## 7. Architectural Alignment

| Invariant | How Meeting Respects It |
|-----------|----------------------|
| Runtime is pure config-resolver, never launches agents | `cmd_meeting` returns JSON plan. Skill layer launches agents. |
| All runtime output is JSON | Meeting plan is JSON on stdout. |
| Skills own subagent execution | `skills/meeting/SKILL.md` launches and collects. |
| Write policy is enforced | Meeting is read-only. No write locks needed. |
| State files in `.agenteam/state/` | Meeting does not create or modify state. |
| Roles resolved via deep_merge | Meeting resolves all roles the same way `dispatch` does. |

---

## 8. Implementation Slices

```
Slice 1: Runtime cmd_meeting
  Files: runtime/agenteam_rt.py
  Depends on: none
  Tests: test/test_runtime.py -- new TestMeeting class
  Design ref: Section 5a

  Add the `meeting` subcommand to the CLI. It resolves all roles,
  builds a read-only dispatch plan with context_hints and
  data_sources, and outputs JSON. Includes --task flag and
  active-run context detection. Emits warning if role count > 6.

Slice 2: Runtime tests for cmd_meeting
  Files: test/test_runtime.py
  Depends on: Slice 1
  Tests: TestMeeting class with 4-5 test cases
  Design ref: Section 5a

  Tests:
  - meeting returns all 6 built-in roles
  - all roles have mode "read"
  - output_path is well-formed
  - --task flag overrides context
  - warning emitted when >6 roles
  - meeting works with no active run
  - meeting includes run context when active run exists

Slice 3: Meeting skill (SKILL.md)
  Files: skills/meeting/SKILL.md
  Depends on: Slice 1
  Tests: manual -- invoke $ateam:meeting in Codex
  Design ref: Section 6

  Create the skill markdown that:
  - Calls runtime to get meeting plan
  - Launches all role agents in parallel
  - Collects and aggregates output
  - Writes to docs/meetings/
  - Displays to user

Slice 4: Router update
  Files: skills/using-ateam/SKILL.md
  Depends on: Slice 3
  Tests: manual -- "give me project status from everyone" routes correctly
  Design ref: Section 6 (router integration)

  Add meeting-related intents to the router table in using-ateam.
```

---

## 9. Open Questions

1. **Should custom roles participate in meetings?** Proposed answer: yes.
   `cmd_meeting` resolves all roles (built-in + custom). If someone added a
   `security_auditor`, they presumably want its perspective in meetings too.

2. **Should meetings be configurable (exclude certain roles)?** Defer to v2.
   For now, all resolved roles participate. A future `meeting.exclude` config
   key could filter.

3. **Should the meeting report be committed?** No. Writing to `docs/meetings/`
   makes it available for reference but committing is the user's choice (same
   as all other AgenTeam artifacts).
