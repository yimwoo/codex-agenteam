# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What This Is

AgenTeam (`codex-agenteam`) is a Codex plugin that provides role-based team collaboration for AI-assisted development. Roles (architect, dev, reviewer, qa) are defined as YAML templates, materialized into Codex-native custom agents (`.codex/agents/*.toml`), and orchestrated through a configurable pipeline.

## Commands

### Install dependencies
```bash
pip install -r runtime/requirements.txt
```

### Run unit tests (pytest)
```bash
python3 -m pytest test/test_runtime.py -v
```

### Run a single test
```bash
python3 -m pytest test/test_runtime.py::TestRoleResolution::test_role_override -v
```

### Run smoke tests (bats)
```bash
bats test/smoke.bats
```

### Run the runtime CLI directly
```bash
python3 runtime/agenteam_rt.py --help
python3 runtime/agenteam_rt.py roles list          # requires agenteam.yaml in cwd
python3 runtime/agenteam_rt.py generate             # generates .codex/agents/*.toml
python3 runtime/agenteam_rt.py init --task "desc"   # creates run state
python3 runtime/agenteam_rt.py dispatch <stage> --task "desc" --run-id <id>
python3 runtime/agenteam_rt.py policy check
python3 runtime/agenteam_rt.py hotl check           # no config needed
```

## Architecture

### Separation of concerns

- **Runtime (`runtime/agenteam_rt.py`)** — Pure config-resolver and policy-enforcer. Single-file Python CLI that outputs JSON. It never launches subagents or executes skills.
- **Skills (`skills/*/SKILL.md`)** — User-facing operations. Skills read runtime JSON output and own subagent execution via Codex's native mechanism.
- **Roles (`roles/*.yaml`)** — Built-in role templates in YAML. These are the plugin's internal authoring format.
- **Generated agents (`.codex/agents/*.toml`)** — Codex-native agent format produced by `agenteam_rt.py generate`. YAML roles go through a Python generation step to become flat TOML.

### Config resolution flow

```
roles/*.yaml (plugin defaults)
         \
          deep_merge  -->  resolved role  -->  generate_agent_toml()  -->  .codex/agents/*.toml
         /
agenteam.yaml roles: (project overrides)
```

Project overrides win on leaf values. Custom roles (not in defaults) are taken as-is from `agenteam.yaml`.

### Pipeline and dispatch

The runtime returns JSON **dispatch plans** — it does not execute anything. The skill layer (`run`, `assign`) reads the plan and launches Codex subagents.

Pipeline modes: `standalone` (built-in stages), `hotl` (wraps HOTL skills), `dispatch-only` (ad-hoc), `auto` (detects HOTL, never silently activates).

Write policy modes: `serial` (one writer at a time, default), `scoped` (parallel with disjoint write_scope, v2), `worktree` (git worktree isolation, v3).

### HOTL integration

When `pipeline: hotl`, AgenTeam is the outer orchestrator and HOTL is the inner execution engine. AgenTeam manages role selection and write policy; HOTL manages phase execution (loops, verification, gates). AgenTeam wraps HOTL skills, injecting role context — it never modifies HOTL internals.

### Key conventions

- Runtime dependencies: Python 3.10+, PyYAML, toml
- All runtime output is JSON (stdout for data, stderr for errors)
- Valid pipeline values: `standalone`, `hotl`, `dispatch-only`, `auto`
- Valid write modes: `serial`, `scoped`, `worktree`
- State files live in `.agenteam/state/<run-id>.json`
- Tests invoke the runtime as a subprocess via `python3 runtime/agenteam_rt.py` with a temp directory containing a generated `agenteam.yaml`

## Releasing

When bumping the version for a release, update **all three** locations:

1. `.codex-plugin/plugin.json` — `"version": "X.Y.Z"` (source of truth)
2. `runtime/agenteam/__init__.py` — `__version__ = "X.Y.Z"`
3. `pyproject.toml` — `version = "X.Y.Z"`

All three must match. Then commit, push, and create a GitHub release with `gh release create vX.Y.Z`.

## Git Workflow

- **Always work on feature branches**, not main. Use `feature/<short-description>` for new features and `fix/<short-description>` for bug fixes.
- Create the branch before starting work. Push and create a PR when ready to merge.
- Main branch should only receive merges via PR.
- When creating commits, do NOT include `Co-Authored-By` trailers. The only committer and author should be `yimwoo <yiming.wu@outlook.com>`.
