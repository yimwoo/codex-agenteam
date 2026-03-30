# AgenTeam (codex-agenteam) Setup Guide

## Prerequisites

- **Python 3.8+** (pre-installed on macOS and most Linux systems)
- **PyYAML** and **toml** Python packages
- **Codex CLI** or **Codex App**

Install Python dependencies:

```bash
pip install pyyaml toml
```

## Installation

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

This clones the repo, installs Python dependencies, and registers the plugin in the Codex marketplace.

### Local Install (for contributors)

```bash
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

## Quick Start

### 1. Initialize

Navigate to your project directory and run:

```
$ateam:init
```

This will:
- Create `agenteam.yaml` in your project root
- Generate `.codex/agents/*.toml` for each role
- Detect HOTL plugin and suggest integration

### 2. Run a Task

```
$ateam:run "Add user authentication"
```

This orchestrates the full pipeline:
1. **Design** — Architect analyzes requirements and proposes approaches
2. **Plan** — Architect creates an implementation plan
3. **Implement** — Implementer writes the code
4. **Test** — Qa creates test coverage
5. **Review** — Reviewer checks for correctness and security

### 3. Dispatch a Role Directly

```
$ateam:assign architect "Review this API design"
$ateam:assign reviewer "Check auth logic in src/auth.py"
```

## Configuration Reference

### agenteam.yaml

```yaml
version: "1"

team:
  name: my-project-team       # Team identifier
  pipeline: standalone         # auto | standalone | hotl | dispatch-only
  parallel_writes:
    mode: serial               # serial | scoped (v2) | worktree (v3)

roles:
  # Analysis/review roles inherit the user's default Codex model.
  dev:
    model: gpt-5.3-codex
    can_write: true
    write_scope:
      - "src/**"
      - "lib/**"

  # Add custom roles
  security_auditor:
    base_agent: default
    description: "Reviews code for security vulnerabilities"
    responsibilities:
      - "Check for OWASP top 10"
    participates_in:
      - review
    can_write: false

pipeline:
  stages:
    - name: design
      roles: [architect]
      gate: human
    - name: plan
      roles: [architect]
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

### Pipeline Modes

| Mode | Description |
|------|-------------|
| `standalone` | Built-in pipeline: design -> plan -> implement -> test -> review |
| `hotl` | Integrates with HOTL plugin for structured workflow execution |
| `dispatch-only` | No pipeline. Invoke roles ad-hoc via `$ateam:assign` |
| `auto` | Detects HOTL and suggests integration. Falls back to standalone. |

### Write Policy

| Mode | Behavior |
|------|----------|
| `serial` (default) | One writer at a time. Others queue. |
| `scoped` (v2) | Parallel writers with non-overlapping write_scope |
| `worktree` (v3) | Each writer gets a git worktree |

## HOTL Integration

To use AgenTeam with the HOTL plugin:

1. Install the HOTL plugin
2. Set `pipeline: hotl` in `agenteam.yaml`
3. Run `$ateam:run` — AgenTeam will wrap HOTL skills with role context

In HOTL mode:
- AgenTeam manages role selection and write policy
- HOTL manages phase execution (loops, verification, gates)
- AgenTeam is the outer orchestrator; HOTL is the inner engine

## Available Skills

| Skill | Invocation | Purpose |
|-------|-----------|---------|
| init | `$ateam:init` | Set up team config |
| run | `$ateam:run` | Run full pipeline |
| assign | `$ateam:assign` | Assign a task to a role |
| status | `$ateam:status` | Show team state |
| add-member | `$ateam:add-member` | Add custom role |
| generate | `$ateam:generate` | Regenerate agents |

## Built-in Roles

| Role | Stages | Writes | Purpose |
|------|--------|--------|---------|
| architect | design, plan, review | No | Design and critique |
| dev | implement | Yes (src/, lib/) | Write production code |
| qa | test | Yes (tests/) | Write tests |
| reviewer | review | No | Check correctness and security |
