# AgenTeam -- Specialist AI Agents as Your Team for Codex

**AgenTeam** is a [Codex](https://codex.ai) plugin that turns a single AI session into a team of specialists. Define roles like architect, dev, qa, and reviewer -- then orchestrate them through a configurable pipeline. Each role becomes a Codex-native custom agent (`.codex/agents/*.toml`) with its own model, permissions, and write scope.

> Design. Plan. Implement. Test. Review. -- All in one session.

## Quick Start

### 1. Install AgenTeam

Requirements: Python 3.10+ and Codex App or Codex CLI.

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

After the installer finishes:

- In the **Codex App**, restart Codex, open **Plugins > Local Plugins**, and install AgenTeam.
- In the **Codex CLI**, restart the session if needed so `$ateam:*` skills are available.

### 2. Choose Your Entry Point

Use **Codex App** if you want chat-first orchestration with `@` mentions.
Use **Codex CLI** if you want command-style skill invocation.

#### Codex App (`@ATeam`, `@Role`)

Open any project in Codex and ask AgenTeam to set itself up:

```
@ATeam build my team
```

On first run, AgenTeam will create `.agenteam/config.yaml` (preferred; legacy `agenteam.yaml` still works), generate the role agents,
and show the available team members.

Use `@ATeam` for setup, status, and pipeline runs.
Use `@Architect`, `@Dev`, `@Reviewer`, and other roles for focused work after setup.

Team-level:

```
@ATeam refactor this codebase to be more maintainable
@ATeam show team status
```

Role-level:

```
@Architect    -- system design, risk analysis
@Reviewer     -- correctness, security, regressions
@Dev          -- write production code
@Pm           -- strategy, priorities, specs
@Researcher   -- web, GitHub, docs, community
@Qa           -- unit and integration tests
```

Examples:

```
@Architect review this API design
@Pm what should we build next?
@Researcher investigate caching strategies for our use case
@Reviewer check the auth logic in src/auth.py
```

#### Codex CLI (`$ateam:*`)

From a project root:

```
$ateam:init
$ateam:run "refactor this codebase to be more maintainable"
$ateam:status
$ateam:add-member
$ateam:generate
```

Run `$ateam:init` once per project to create `.agenteam/config.yaml` and `.codex/agents/*.toml`.
After that, use `$ateam:run` to start work and `$ateam:status` to inspect the current run.

### 3. First 5 Minutes

1. Install plugin and open your project.
2. Initialize once with `@ATeam build my team` (App) or `$ateam:init` (CLI).
3. Verify setup:
   `.agenteam/config.yaml` exists in your project root (or legacy `agenteam.yaml`)
   `.codex/agents/*.toml` exists for the built-in roles
   `@ATeam build my team` lists the built-in roles in the app
4. Start with a real task:

```
@ATeam build a REST API for managing tasks
```

```bash
$ateam:run "build a REST API for managing tasks"
```

5. Customize roles, models, and pipeline behavior in `.agenteam/config.yaml` when ready.

> Install, initialize once, then orchestrate with `@ATeam` or `$ateam:*`, and `@` roles directly whenever you want specialist focus.

## Usage Examples

### Talk to Individual Roles

In the Codex App, `@` any team member directly:

```
@Architect propose an approach for caching
@Dev implement the caching layer per the approved plan
@Qa add integration tests for the cache
@Reviewer review the caching implementation
@Pm prioritize the backlog for next sprint
@Researcher what are the best practices for error handling in this stack?
```

### Team Operations via @ATeam

Use `@ATeam` for team-level operations:

```
@ATeam write tests for the untested parts of this project
@ATeam show team status
@ATeam add a security auditor that focuses on OWASP top 10
@ATeam add a performance engineer to profile API response times
```

### Codex CLI

In the CLI, use skill invocations:

```bash
# Run the full pipeline
$ateam:run "Refactor the database layer to use connection pooling"

# Check team status
$ateam:status

# Add a custom role
$ateam:add-member

# Regenerate agent TOML files after config changes
$ateam:generate
```

### Real-World Scenarios

**Bug fix with review:**
```
@Dev fix the race condition in src/queue.py -- see issue #42
@Qa add a regression test for the queue race condition
@Reviewer review the queue fix and test
```

**Architecture decision:**
```
@Architect we need to choose between REST and GraphQL for the new API. Analyze trade-offs.
```

**Add a specialist:**
```
@ATeam add a security auditor that focuses on auth and data leaks
```
AgenTeam infers the role config, confirms with you, writes to `.agenteam/config.yaml` (or legacy `agenteam.yaml`), and generates the agent. Then `@` them directly:
```
@Security Auditor audit the authentication module
```

## Built-in Roles

| Role | Pipeline Stages | Writes To | Default Model | Purpose |
|------|----------------|-----------|---------------|---------|
| **researcher** | research, design | `docs/research/` | Inherits user default | Investigate web, GitHub, docs, community |
| **pm** | strategy, design | `docs/strategies/` | Inherits user default | Decide what to build, prioritize, write specs |
| **architect** | design, review | `docs/designs/` | Inherits user default | Design systems, critique plans, identify risks |
| **dev** | plan, implement | `docs/plans/`, `src/**`, `lib/**` | gpt-5.3-codex | Translate designs into plans, then write code |
| **qa** | test | `tests/**`, `*.test.*` | gpt-5.3-codex | Write unit and integration tests |
| **reviewer** | review | Read-only | Inherits user default | Review for correctness, security, and regressions |

Each role writes to a scoped directory -- no overlaps, safe for parallel execution.

All roles are customizable via `.agenteam/config.yaml` (preferred; legacy `agenteam.yaml` still works). You can override models, write scopes, system instructions, and add entirely new roles.

## Configuration

AgenTeam is configured through `.agenteam/config.yaml` in your project root (or legacy `agenteam.yaml`):

```yaml
version: "1"

# isolation: branch          # branch (default) | worktree | none
# pipeline: hotl             # omit for auto-detect

roles:
  # Analysis/review roles inherit the user's default Codex model
  dev:
    model: gpt-5.3-codex
    write_scope:
      - "src/**"
      - "lib/**"
      - "docs/plans/**"

  # Add custom roles
  security_auditor:
    description: "Reviews code for security vulnerabilities"
    participates_in: [review]
    model: gpt-5.4
    can_write: false
    system_instructions: |
      Focus on OWASP top 10, auth/authz logic, and hardcoded secrets.

pipeline:
  stages:
    - name: research
      roles: [researcher]
      gate: auto              # auto = continue, human = pause for approval
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
    - name: test
      roles: [qa]
      gate: auto
    - name: review
      roles: [reviewer]
      gate: human
```

### Pipeline Execution

By default, AgenTeam auto-detects HOTL and uses it if available. Otherwise it
runs the built-in standalone pipeline. To force HOTL, add `pipeline: hotl` to
your config. To skip the pipeline entirely, just use `$ateam:assign` or `@` roles directly.

### Write Policy & Branch Isolation

AgenTeam enforces write safety so agents don't step on each other. Writing
agents (`@Dev`, `@Qa`, custom writers) are automatically isolated on dedicated
branches or worktrees -- they never work directly on your current branch.

| Mode | Branch Behavior | Concurrency |
|------|----------------|-------------|
| `serial` (default) | Creates `ateam/<role>/<task>` branch per assignment, `ateam/run/<id>` per pipeline run | One writer at a time. Others queue. |
| `scoped` | Stays on current branch (trusts non-overlapping `write_scope`) | Parallel writes within scope boundaries |
| `worktree` | Creates isolated git worktree per writer | Full parallel isolation |

Preflight checks block on dirty worktree and detached HEAD before any git
mutation. Worktrees with uncommitted changes are preserved (never auto-deleted).

## How It Works

```
                        @ateam "Add user auth"
                               |
  research ──► strategy ──► design ──► plan ──► implement ──► test ──► review
     │            │           │          │          │           │         │
     ▼            ▼           ▼          ▼          ▼           ▼         ▼
  docs/        docs/       docs/     docs/      src/**      tests/**   (verdict)
  research/  strategies/  designs/   plans/     lib/**
```

1. **Researcher** looks outward -- web, GitHub, docs, community -> `docs/research/`
2. **PM** decides what to build based on research and strategy -> `docs/strategies/`
3. **Architect** (with PM + researcher input) designs the solution -> `docs/designs/`
4. **Implementer** translates design into a step-by-step plan -> `docs/plans/`, then writes code
5. **Qa** creates test coverage
6. **Reviewer** checks for correctness, security, and regressions

## Installation

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

### Local Install (contributors)

```bash
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

### Update

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/update.sh | bash
```

Or from a local clone:

```bash
bash update.sh --local
```

### Requirements

- Python 3.10+
- Codex CLI or Codex App

The installer handles Python dependencies (PyYAML, toml) automatically.

## HOTL Integration

AgenTeam can integrate with the [HOTL plugin](https://github.com/yimwoo/hotl) for structured workflow execution:

```yaml
team:
  pipeline: hotl
```

In HOTL mode, AgenTeam is the outer orchestrator (who does what, write policy) and HOTL is the inner engine (loops, verification, gates). They compose cleanly -- AgenTeam wraps HOTL skills with role context.

## License

MIT
