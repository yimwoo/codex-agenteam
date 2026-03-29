# AgenTeam -- Role-Based AI Team Collaboration for Codex

**AgenTeam** is a [Codex](https://codex.ai) plugin that turns a single AI session into a team of specialists. Define roles like architect, implementer, test-writer, and reviewer -- then orchestrate them through a configurable pipeline. Each role becomes a Codex-native custom agent (`.codex/agents/*.toml`) with its own model, permissions, and write scope.

> Design. Plan. Implement. Test. Review. -- All in one session.

## Quick Start

### 1. Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh)
```

Restart Codex, open **Plugins > Local Plugins**, and install AgenTeam.

### 2. Use It

Open any project in Codex and go -- no setup required:

```
@ateam add user authentication
```

AgenTeam auto-initializes with default roles on first use, then orchestrates the full pipeline:

1. **Architect** designs the approach and creates a plan
2. **Implementer** writes the production code
3. **Test Writer** creates test coverage
4. **Reviewer** checks for correctness and security

That's it. Two steps: install, use.

> Want to customize roles, models, or the pipeline? Edit `agenteam.yaml` in your project root, or run `$ateam-init` for guided setup.

## Usage Examples

### Codex App

In the Codex App, use `@ateam` to talk to the plugin directly:

```
@ateam set up a team for this project

@ateam ask architect to review this API design

@ateam ask reviewer to check the auth logic in src/auth.py

@ateam ask pm what we should build next

@ateam run the full pipeline on: add rate limiting to the API

@ateam show team status

@ateam add a performance tuning engineer to my team

@ateam add a security auditor that focuses on auth and data leaks
```

The plugin routes your intent to the right role -- you don't need to remember skill names.

### Codex CLI

In the CLI, use skill invocations directly:

```bash
# Run the full design-plan-implement-test-review pipeline
$ateam-run "Refactor the database layer to use connection pooling"

# Dispatch a single role for a focused task
$ateam-assign architect "Propose an approach for caching"
$ateam-assign implementer "Implement the caching layer per the approved plan"
$ateam-assign test_writer "Add integration tests for the cache"
$ateam-assign reviewer "Review the caching implementation"

# Check what the team is working on
$ateam-status

# Add a custom role
$ateam-add-role

# Regenerate agent TOML files after config changes
$ateam-generate
```

### Real-World Scenarios

**Bug fix with review:**
```
$ateam-assign implementer "Fix the race condition in src/queue.py -- see issue #42"
$ateam-assign test_writer "Add a regression test for the queue race condition"
$ateam-assign reviewer "Review the queue fix and test"
```

**Architecture decision:**
```
$ateam-assign architect "We need to choose between REST and GraphQL for the new API. Analyze trade-offs for our use case."
```

**Add a specialist to your team:**
```
@ateam add a security auditor that focuses on OWASP top 10 and auth logic
```
AgenTeam infers the role config, confirms with you, writes to `agenteam.yaml`, and generates the agent. Then use it immediately:
```
@ateam ask security_auditor to audit the authentication module
```

**More examples of custom roles:**
```
@ateam add a performance engineer to profile API response times
@ateam add a docs writer that maintains README and API documentation
@ateam add a DevOps engineer for CI/CD pipeline work
```

## Built-in Roles

| Role | Pipeline Stages | Writes To | Default Model | Purpose |
|------|----------------|-----------|---------------|---------|
| **researcher** | research, design | `docs/research/` | o3 | Investigate web, GitHub, docs, community |
| **pm** | strategy, design | `docs/strategies/` | o3 | Decide what to build, prioritize, write specs |
| **architect** | design, review | `docs/designs/` | o3 | Design systems, critique plans, identify risks |
| **implementer** | plan, implement | `docs/plans/`, `src/**`, `lib/**` | o3-mini | Translate designs into plans, then write code |
| **test_writer** | test | `tests/**`, `*.test.*` | o3-mini | Write unit and integration tests |
| **reviewer** | review | Read-only | o3 | Review for correctness, security, and regressions |

Each role writes to a scoped directory -- no overlaps, safe for parallel execution.

All roles are customizable via `agenteam.yaml`. You can override models, write scopes, system instructions, and add entirely new roles.

## Configuration

AgenTeam is configured through `agenteam.yaml` in your project root:

```yaml
version: "1"

team:
  name: my-project-team
  pipeline: standalone        # standalone | hotl | dispatch-only | auto
  parallel_writes:
    mode: serial              # serial | scoped (v2) | worktree (v3)

roles:
  # Override built-in roles
  architect:
    model: o3
    reasoning_effort: high
  implementer:
    write_scope:
      - "src/**"
      - "lib/**"
      - "docs/plans/**"

  # Add custom roles
  security_auditor:
    description: "Reviews code for security vulnerabilities"
    participates_in: [review]
    model: o3
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
      roles: [implementer]
      gate: human
    - name: implement
      roles: [implementer]
      gate: auto
    - name: test
      roles: [test_writer]
      gate: auto
    - name: review
      roles: [reviewer]
      gate: human
```

### Pipeline Modes

| Mode | Behavior |
|------|----------|
| `standalone` | Built-in pipeline: design -> plan -> implement -> test -> review |
| `hotl` | Integrates with [HOTL plugin](https://github.com/yimwoo/hotl) for structured workflow execution |
| `dispatch-only` | No pipeline -- invoke roles ad-hoc via `$ateam-assign` |
| `auto` | Detects HOTL availability and suggests integration; falls back to standalone |

### Write Policy

AgenTeam enforces write safety so agents don't step on each other:

| Mode | Behavior |
|------|----------|
| `serial` (default) | One writer at a time. Others queue. Safe for any project. |
| `scoped` (v2) | Parallel writes with non-overlapping `write_scope` per role |
| `worktree` (v3) | Each writer gets an isolated git worktree |

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
5. **Test Writer** creates test coverage
6. **Reviewer** checks for correctness, security, and regressions

## Installation

### One-Line Install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh)
```

### Local Install (contributors)

```bash
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

### Update

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/update.sh)
```

Or from a local clone:

```bash
bash update.sh --local
```

### Requirements

- Python 3.8+
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
