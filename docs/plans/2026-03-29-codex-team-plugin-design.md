# codex-team Plugin Design

## Overview

A Codex plugin that provides role-based team collaboration for AI-assisted
development. Roles (architect, implementer, reviewer, test-writer) are
defined as structured templates, materialized into Codex-native custom agents
(`.codex/agents/*.toml`), and orchestrated through a configurable pipeline.

**Positioning:**

- **HOTL = phase engine** (brainstorm -> plan -> execute -> review -> verify)
- **codex-team = role engine** (who participates, who writes, how handoffs work)
- **Human = final decisions** (review, merge, promotion)

## Architecture: Codex-Native Role Engine

Lean into Codex's native agent system. Roles are materialized as
`.codex/agents/*.toml` files. The plugin provides the config layer, dispatch
logic, and pipeline orchestration.

### Plugin Structure

```
codex-team/
├── .codex-plugin/
│   └── plugin.json                  # Codex plugin manifest
├── skills/
│   ├── using-codex-team/SKILL.md    # Router skill (session start)
│   ├── team-init/SKILL.md           # Initialize team config + generate agents
│   ├── team-dispatch/SKILL.md       # Dispatch a specific role for a task
│   ├── team-run/SKILL.md            # Run full pipeline (standalone or HOTL)
│   ├── team-status/SKILL.md         # Show current team state
│   ├── team-add-role/SKILL.md       # Add a custom role interactively
│   └── team-generate/SKILL.md       # Regenerate .codex/agents/*.toml
├── roles/                           # Built-in role templates (internal YAML)
│   ├── architect.yaml
│   ├── implementer.yaml
│   ├── reviewer.yaml
│   └── test-writer.yaml
├── runtime/
│   ├── codex_team_rt.py             # Runtime engine (Python 3, single file)
│   └── requirements.txt             # PyYAML, toml
├── scripts/
│   └── check-update.sh              # Version check (bash, no deps)
├── templates/
│   └── codex-team.yaml.template     # Starter config
├── docs/
│   └── setup.md
└── test/
    ├── smoke.bats                   # Structural smoke tests (bash)
    └── test_runtime.py              # Runtime unit tests (pytest)
```

**Key decisions:**

- **No `commands/` directory.** Skills are the official plugin extension point.
  All user-facing operations (init, run, dispatch, status, add-role, generate)
  are implemented as skills. Users invoke them via `/skills` in Codex CLI/IDE,
  or `$team-run` / `$team-init` syntax.
- **No plugin-local `hooks/` in v1.** Codex hooks are experimental and require
  `codex_hooks = true` plus config-adjacent `hooks.json`. Deferred to v2 with
  an install step that writes repo/user hook config.
- **Internal role format is YAML.** Generated Codex agent format is TOML.
  These are separate schemas with a Python generation step between them.
- **Runtime is Python 3, not bash.** YAML parsing, config merging, TOML
  generation, and schema validation exceed what bash + jq can do cleanly.
  Python 3 is pre-installed on macOS/Linux. Dependencies: PyYAML + toml.
- **Runtime returns data, skills own execution.** `codex-team-rt` is a pure
  config-resolver and policy-enforcer. It outputs JSON dispatch plans. The
  skill layer reads those plans and launches Codex subagents.

## Role Definition

### Internal Schema (roles/*.yaml)

The plugin's authoring format for role templates:

```yaml
# roles/architect.yaml
name: architect
base_agent: default           # default | worker | explorer
description: >
  Designs system architecture and critiques plans.
  Analyzes requirements, proposes approaches, and identifies risks.
responsibilities:
  - Analyze requirements and propose 2-3 approaches with trade-offs
  - Review implementation plans for completeness and risk
  - Identify constraints, dependencies, and architectural boundaries
  - Critique designs for YAGNI violations and scope creep
participates_in:
  - design
  - plan
  - review
model: o3
reasoning_effort: high
sandbox_mode: network-read
can_write: false
write_scope: []
parallel_safe: true
handoff_contract:
  produces: "Design doc or plan critique with explicit approval/rejection"
  expects: "Requirements, user intent, or implementation plan"
  passes_to: "implementer (approved design) or back to user (rejection)"
system_instructions: |
  You are the **architect** on a codex-team. Your primary job is to
  design and critique, not to implement.

  ## Operating Rules
  - Always propose 2-3 approaches with trade-offs before recommending one
  - Flag any YAGNI violations or scope creep
  - You are read-only: never modify source code
  - Produce structured output: decisions, constraints, risks, next steps
  - When reviewing a plan, check: are all files identified? Are tests planned?
    Is the risk level appropriate?
```

### Generated Codex Agent Schema (.codex/agents/*.toml)

What `codex-team-rt generate` produces from the internal role:

```toml
# .codex/agents/architect.toml
name = "architect"
description = "Designs system architecture and critiques plans."
model = "o3"
model_reasoning_effort = "high"
sandbox_mode = "network-read"

developer_instructions = """
You are the **architect** on a codex-team. Your primary job is to
design and critique, not to implement.

## Operating Rules
- Always propose 2-3 approaches with trade-offs before recommending one
- Flag any YAGNI violations or scope creep
- You are read-only: never modify source code
- Produce structured output: decisions, constraints, risks, next steps
- When reviewing a plan, check: are all files identified? Are tests planned?
  Is the risk level appropriate?

## Role Metadata
participates_in: design, plan, review
can_write: false
parallel_safe: true
"""
```

**Note:** The exact TOML field names and structure should be verified against
the latest Codex custom agent docs during implementation. The schema above
reflects the documented required fields (`name`, `description`,
`developer_instructions`) and optional fields (`model`,
`model_reasoning_effort`, `sandbox_mode`) as flat top-level keys.

### Built-in Roles

| Role | Stages | Writes | Parallel-safe | Purpose |
|------|--------|--------|---------------|---------|
| `architect` | design, plan, review | no | yes | Design, critique, risk analysis |
| `implementer` | implement | yes (src/) | no | Primary code writer |
| `test_writer` | test | yes (tests/) | yes (scoped) | Test creation and coverage |
| `reviewer` | review | no | yes | Correctness, security, regression checks |

## Project Configuration (codex-team.yaml)

```yaml
version: "1"

# Team-level settings
team:
  name: my-project-team
  pipeline: standalone          # auto | standalone | hotl | dispatch-only

  parallel_writes:
    mode: serial                # serial | scoped | worktree (v2+)

# Role overrides (deep-merged with plugin defaults)
roles:
  architect:
    model: o3
    reasoning_effort: high

  implementer:
    can_write: true
    write_scope:
      - "src/**"
      - "lib/**"

  test_writer:
    can_write: true
    write_scope:
      - "tests/**"
      - "**/*.test.*"

  reviewer:
    can_write: false
    participates_in: [review]

  # Custom role — fully user-defined
  security_auditor:
    base_agent: default
    description: "Reviews code for security vulnerabilities"
    responsibilities:
      - "Check for OWASP top 10 vulnerabilities"
      - "Review auth/authz logic"
      - "Flag hardcoded secrets"
    participates_in: [review]
    model: o3
    reasoning_effort: high
    can_write: false
    parallel_safe: true
    system_instructions: |
      You are a security auditor. Focus exclusively on security concerns.
      Do not suggest style or performance changes unless they have
      security implications.

# Standalone pipeline stages (used when pipeline != hotl)
pipeline:
  stages:
    - name: design
      roles: [architect]
      gate: human               # human | auto
    - name: plan
      roles: [architect]
      gate: human
    - name: implement
      roles: [implementer]
      gate: auto
    - name: test
      roles: [test_writer]
      gate: auto
    - name: review
      roles: [reviewer, security_auditor]
      gate: human
```

### Pipeline Modes

| Mode | Behavior |
|------|----------|
| `standalone` | Runs built-in pipeline (design -> plan -> implement -> test -> review) |
| `hotl` | Explicit opt-in. Delegates phase orchestration to HOTL. codex-team provides role selection and write policy. |
| `dispatch-only` | No pipeline. User invokes roles directly for ad-hoc tasks. |
| `auto` | Detects HOTL presence and suggests switching, but does not silently activate. Falls back to standalone. |

### Auto Mode Behavior

When `pipeline: auto`:

1. Check for HOTL plugin installation
2. If found: prompt user — "HOTL detected. Switch to HOTL-integrated mode? (y/n)"
3. If user confirms: run in `hotl` mode for this session
4. If declined or not found: run in `standalone` mode
5. Never silently switch

## Runtime Engine (codex-team-rt)

### Runtime Language Decision

**Problem:** The original design constrained the runtime to bash + jq. However,
the runtime must parse YAML, deep-merge layered configs, validate schemas,
generate TOML, and manage state — too much complexity for bash scripting
without introducing fragility.

**Decision: Python 3 (single-file, stdlib-only for core, PyYAML + toml for
config processing).**

Rationale:
- Python 3 is pre-installed on macOS and most Linux systems
- PyYAML and toml are lightweight, widely available (`pip install pyyaml toml`)
- Single-file runtime (`codex-team-rt`) avoids build steps
- HOTL uses bash for its runtime, which works because HOTL's state format is
  JSON-only. codex-team needs YAML parsing + TOML generation, which pushes
  past what bash + jq can do cleanly.
- Alternative considered: Node.js — heavier dependency, less likely pre-installed
  on server/CI environments

**Dependency contract:**
- Required: Python 3.8+, PyYAML, toml (or tomli-w for Python 3.11+)
- `team-init` skill checks for Python and deps, offers to install via pip if missing
- The plugin ships a `requirements.txt` with pinned versions
- Scripts that don't need YAML/TOML (check-update, simple queries) remain bash

### Commands

| Command | Purpose |
|---------|---------|
| `codex-team-rt init` | Parse `codex-team.yaml`, validate schema, create `.codex-team/state/` |
| `codex-team-rt generate` | Merge plugin defaults + project overrides, produce `.codex/agents/*.toml` |
| `codex-team-rt dispatch <stage>` | Select roles for stage, enforce write policy, return dispatch plan (JSON) |
| `codex-team-rt status [run-id]` | Show active roles, current stage, write locks |
| `codex-team-rt run <task-description>` | Run full pipeline for a task |
| `codex-team-rt policy check` | Validate write scopes for overlap before parallel dispatch |
| `codex-team-rt roles list` | List all resolved roles (defaults + overrides + custom) |
| `codex-team-rt roles show <name>` | Show merged config for a specific role |

### Config Merge Logic

```
resolve_role(name):
  base = load_yaml(plugin_dir/roles/{name}.yaml)   # plugin default
  override = codex_team_yaml.roles.get(name, {})    # project override
  return deep_merge(base, override)                  # override wins
```

For custom roles (not in plugin defaults), the project config is the sole source.

### State Management

```
.codex-team/
└── state/
    └── <run-id>.json          # Tracks stage progress, write locks, role outputs
```

State file structure:

```json
{
  "run_id": "abc123",
  "task": "Add user authentication",
  "pipeline_mode": "standalone",
  "current_stage": "implement",
  "stages": {
    "design": { "status": "completed", "roles": ["architect"], "gate": "approved" },
    "plan": { "status": "completed", "roles": ["architect"], "gate": "approved" },
    "implement": { "status": "in_progress", "roles": ["implementer"], "write_lock": "implementer" },
    "test": { "status": "pending", "roles": ["test_writer"] },
    "review": { "status": "pending", "roles": ["reviewer", "security_auditor"] }
  },
  "write_locks": {
    "active": "implementer",
    "queue": []
  }
}
```

### Write Policy Enforcement

**Serial mode (default):**
1. Before dispatching a writing role, acquire global write lock
2. If lock held, queue the role
3. Release lock on role completion
4. Process queue FIFO

**Scoped mode (opt-in, v2):**
1. Before dispatching, collect `write_scope` for all candidate writers
2. Check pairwise disjointness (glob intersection check)
3. If disjoint: dispatch in parallel, each with scope-restricted sandbox
4. If overlap: fall back to serial for overlapping roles, parallel for non-overlapping

**Worktree mode (v3):**
1. Create git worktree per writing role
2. Each role works in isolation
3. On completion: human review + merge gate
4. Conflict detection before merge attempt

### Dispatch Logic

`codex-team-rt dispatch` does NOT launch subagents directly. It returns a
**dispatch plan** (JSON) that the calling skill interprets and executes using
Codex's native subagent mechanism. This keeps the runtime as a pure
config-resolver and policy-enforcer, while the skill layer owns execution.

```
codex-team-rt dispatch implement --task "Add auth" --run-id abc123

# Returns:
{
  "stage": "implement",
  "dispatch": [
    {
      "role": "implementer",
      "agent": ".codex/agents/implementer.toml",
      "mode": "write",
      "write_lock": true,
      "task": "Add auth"
    }
  ],
  "policy": "serial",
  "gate": "auto",
  "blocked": []
}
```

The skill then:
1. Reads the dispatch plan
2. Launches each agent as a Codex subagent (serial or parallel per policy)
3. Collects outputs
4. Calls `codex-team-rt` to update state and release locks
5. Evaluates gate (human pause or auto-approve)

## HOTL Adapter

### Integration Model

**Problem:** The previous design said "HOTL calls back into codex-team each
phase" but never defined how. HOTL has no plugin callback mechanism — it
orchestrates via skills and `hotl-rt`, not by calling external tools mid-phase.

**Decision: codex-team wraps HOTL in v1 (wrapper model).**

When `pipeline: hotl`, the `team-run` skill becomes the orchestrator:

1. `team-run` reads the task and resolves which roles participate per stage
2. For each stage, `team-run` invokes the corresponding HOTL skill
   (e.g., `hotl:brainstorming`) but injects the role's system instructions
   into the HOTL workflow file's step actions
3. HOTL owns execution mechanics (loops, verification, gates)
4. codex-team owns role selection and write policy
5. Between HOTL phases, `team-run` manages handoffs and state

**Concrete v1 flow:**

```
User: $team-run "Add user authentication"

team-run skill:
  1. codex-team-rt init --task "Add auth" --pipeline hotl
  2. codex-team-rt dispatch design -> {roles: [architect]}

  3. DESIGN PHASE:
     - Generate hotl-workflow with architect's instructions in step actions
     - Invoke hotl:brainstorming (HOTL drives the design conversation)
     - Collect design output

  4. codex-team-rt dispatch plan -> {roles: [architect]}

  5. PLAN PHASE:
     - Invoke hotl:writing-plans (HOTL generates workflow file)
     - Architect reviews plan via team-dispatch

  6. codex-team-rt dispatch implement -> {roles: [implementer]}
     codex-team-rt dispatch test -> {roles: [test_writer]}

  7. IMPLEMENT + TEST PHASE:
     - Invoke hotl:loop-execution or hotl:subagent-execution
     - HOTL executes steps; implementer/test_writer agents are the workers
     - Write policy enforced: implementer runs first (serial),
       test_writer runs after (or parallel if scoped policy)

  8. codex-team-rt dispatch review -> {roles: [reviewer]}

  9. REVIEW PHASE:
     - Invoke hotl:code-review with reviewer agent
     - Human gate: user approves or requests changes
```

**Key principle:** codex-team is the outer orchestrator; HOTL is the inner
execution engine. codex-team never modifies HOTL internals — it composes
HOTL skills from the outside, injecting role context through workflow files
and agent assignments.

### v2 Evolution: Formal Callback Contract

In v2, if HOTL adds a plugin extension point (e.g., `on_phase_start` hooks
in workflow files), codex-team can register as a phase listener instead of
wrapping. This would allow:

```yaml
# Future hotl-workflow-*.md frontmatter
plugins:
  codex-team:
    on_phase_start: codex-team-rt dispatch ${phase}
    on_phase_end: codex-team-rt complete ${phase}
```

Until then, the wrapper model is the cleanest integration that doesn't
require HOTL changes.

### Default Phase Mapping (internal, not user-facing in v1)

```
HOTL Phase     ->  codex-team Stage  ->  Default Roles
───────────        ────────────────      ──────────────
brainstorm     ->  design             ->  architect
plan           ->  plan               ->  architect
execute        ->  implement + test   ->  implementer, test_writer
review         ->  review             ->  reviewer + custom review roles
verify         ->  (HOTL owns)        ->  —
```

### HOTL Detection

The adapter checks for HOTL availability via:

```python
def hotl_available() -> bool:
    """Check if HOTL plugin is installed and accessible."""
    # Check common install locations
    paths = [
        Path.home() / ".codex" / "plugins" / "hotl",
        Path.home() / ".claude" / "plugins" / "cache" / "hotl-plugin",
    ]
    return any(p.exists() for p in paths)
```

This is called by `team-init` (to suggest `pipeline: hotl`) and by `team-run`
(to validate the pipeline mode). It never silently activates HOTL.

## Skills

All user-facing operations are skills (no commands/ directory).

### using-codex-team (Router)

Injected at session start (v2 via hooks, v1 via manual skill invocation).
Routes user intent to the appropriate skill:

- "Set up team" -> team-init
- "Run this task" -> team-run
- "Send to reviewer" -> team-dispatch
- "Show team status" -> team-status
- "Add a new role" -> team-add-role
- "Regenerate agents" -> team-generate

### team-init

1. Check for existing `codex-team.yaml`
2. If absent: copy template, prompt for customization
3. Run `codex-team-rt init` to validate
4. Run `codex-team-rt generate` to produce `.codex/agents/*.toml`
5. Detect HOTL and suggest `pipeline: hotl` if found

### team-run

1. Accept task description from user
2. Determine pipeline mode (standalone/hotl/dispatch-only)
3. If standalone: iterate through pipeline stages, dispatching roles at each
4. If hotl: act as outer orchestrator — for each stage, resolve roles via
   `codex-team-rt dispatch`, then invoke the corresponding HOTL skill
   (e.g., `hotl:brainstorming` for design, `hotl:loop-execution` for
   implement) with role agents as the workers. codex-team manages handoffs
   and write policy between phases; HOTL manages execution within each phase.
5. Enforce gates between stages

### team-dispatch

1. Accept role name + task
2. Validate role exists and is appropriate
3. Check write policy
4. Launch role as Codex subagent
5. Collect and present output

### team-status

1. Read `.codex-team/state/<run-id>.json`
2. Display: current stage, active roles, write locks, completed stages
3. Show gate status (pending/approved/rejected)

### team-add-role

1. Prompt for role fields (name, description, responsibilities, stages, write access)
2. Write to `codex-team.yaml` under `roles:`
3. Regenerate `.codex/agents/*.toml`

### team-generate

1. Read all role definitions (plugin defaults + project overrides)
2. Merge configs (project overrides win)
3. Generate `.codex/agents/*.toml` for each role
4. Validate generated TOML
5. Report what was generated/updated

## Versioned Delivery

### v1 (MVP)

- Plugin manifest + skills
- Built-in roles: architect, implementer, reviewer, test-writer
- `codex-team.yaml` with project-level overrides and custom roles
- Agent generation (`.codex/agents/*.toml`)
- Standalone pipeline (design -> plan -> implement -> test -> review)
- Serial write policy (default)
- HOTL adapter (explicit opt-in via `pipeline: hotl`)
- Smoke tests

### v2

- SessionStart hooks (with install step for hooks.json)
- Scoped parallel write policy
- `pipeline: auto` with HOTL suggestion
- Runtime state persistence and resume
- `team-status` with rich display

### v3

- Worktree isolation for parallel writers
- Runtime role overrides (ephemeral, promotable to config)
- Role marketplace / sharing
- Cross-repo team configs

## HOTL Contracts

### Intent Contract

```
intent: Build a Codex plugin that provides role-based team collaboration
        for AI-assisted development
constraints:
  - Must work as a standard Codex plugin (.codex-plugin/plugin.json)
  - Must work standalone without HOTL dependency
  - Must generate Codex-native custom agents (.codex/agents/*.toml)
  - One write-owner at a time by default (serial policy)
  - Runtime: Python 3.8+ with PyYAML + toml (lightweight, pre-installed base)
  - Skills are the only user-facing extension point (no commands/)
  - Runtime returns JSON dispatch plans; skills own subagent execution
  - HOTL integration via wrapper model (codex-team wraps HOTL skills)
  - Hooks deferred to v2
success_criteria:
  - Plugin installs via Codex plugin system
  - Default roles (architect, implementer, reviewer, test-writer) work out of box
  - codex-team.yaml allows project-level customization and custom roles
  - codex-team-rt generate produces valid .codex/agents/*.toml
  - Standalone pipeline runs design -> plan -> implement -> test -> review
  - HOTL integration activates only via explicit pipeline: hotl
  - Write policy enforcement prevents conflicting parallel writes
risk_level: medium
```

### Verification Contract

```
verify_steps:
  - run tests: bats test/smoke.bats
  - check: plugin.json is valid JSON with required fields
  - check: all SKILL.md files exist and are non-empty
  - check: codex-team-rt generate produces valid TOML for each built-in role
  - check: codex-team-rt init validates sample codex-team.yaml
  - check: codex-team-rt dispatch selects correct roles per stage
  - check: serial write policy blocks second writer
  - check: standalone pipeline transitions through all stages
  - check: HOTL adapter maps phases correctly
  - confirm: custom roles in codex-team.yaml appear in generated agents
```

### Governance Contract

```
approval_gates:
  - Design doc approval (this document)
  - codex-team.yaml schema finalized
  - Runtime engine core operations working
  - HOTL adapter integration tested
rollback: git revert; plugin is self-contained, no external side effects
ownership: user approves design and schema; implementation is autonomous
```
