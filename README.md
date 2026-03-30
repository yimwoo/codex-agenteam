<p align="center">
  <img src="assets/agenteam-banner.png" alt="AgenTeam — Role-based AI team for Codex" width="100%">
</p>

<p align="center">
  <a href="https://github.com/yimwoo/codex-agenteam/releases"><img src="https://img.shields.io/github/v/release/yimwoo/codex-agenteam?color=2563EB&label=version&style=flat-square" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2563EB?style=flat-square" alt="MIT License"></a>
  <a href="https://github.com/yimwoo/codex-agenteam/stargazers"><img src="https://img.shields.io/github/stars/yimwoo/codex-agenteam?color=2563EB&style=flat-square" alt="Stars"></a>
  <a href="https://github.com/yimwoo/codex-agenteam/issues"><img src="https://img.shields.io/github/issues/yimwoo/codex-agenteam?color=2563EB&style=flat-square" alt="Issues"></a>
</p>

<p align="center">
  <strong>A full AI development team — researcher, PM, architect, dev, QA, and reviewer — as native Codex agents, orchestrated through a configurable pipeline.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> · <a href="#your-team">Meet the Team</a> · <a href="#pipeline">Pipeline</a> · <a href="#configuration">Configuration</a> · <a href="#cli-reference">CLI Reference</a>
</p>

---

## Why AgenTeam?

Most AI coding tools give you one agent. AgenTeam gives you a team.

Each role has a focused job, a scoped write area, and a place in the pipeline. The result: less context confusion, safer parallel execution, and a workflow that mirrors how real software teams operate.

```
You → @ATeam "add user authentication"
         ↓
   Researcher  →  PM  →  Architect  →  Dev  →  Qa  →  Reviewer
   (explore)    (spec)    (design)     (implement)  (test)   (sign off)
```

Every stage writes to its own directory. Nothing overlaps. Every gate is yours to approve.

---

## Quick Start

**1. Install:**

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

**2.** Restart Codex → **Plugins → Local Plugins** → install AgenTeam.

**3. Initialize your team:**

```
@ATeam build my team
```

AgenTeam creates your config, generates all six agents, and shows your roster. Done.

---

## Your Team

Once initialized, type `@` in Codex to see your full team roster:

| Role | Mention | Responsibility |
|------|---------|----------------|
| 🔍 Researcher | `@Researcher` | Investigates docs, GitHub, community trends, and prior art |
| 📋 PM | `@Pm` | Decides what to build, prioritizes work, writes specs |
| 🏗️ Architect | `@Architect` | Designs systems, critiques plans, identifies risks |
| 💻 Dev | `@Dev` | Translates designs into plans, writes production code |
| 🧪 Qa | `@Qa` | Writes unit and integration tests, catches regressions |
| 👁️ Reviewer | `@Reviewer` | Reviews for correctness, security, and code quality |

### Talk to any role directly

Skip the pipeline and go straight to the specialist you need:

```
@Architect review this API design
@Pm what should we build next?
@Researcher what are the best practices for error handling in this stack?
@Dev fix the race condition in src/queue.py
@Qa add a regression test for the queue race condition
@Reviewer review the queue fix and test
```

### Use @ATeam for team-level tasks

```
@ATeam let's have a standup meeting
@ATeam do a deep dive on this project
@ATeam add a security auditor that focuses on OWASP top 10
```

---

## Pipeline

When you give `@ATeam` a task, it runs the full development pipeline:

| Stage | Role(s) | Output | Gate |
|-------|---------|--------|------|
| Research | Researcher | `docs/research/` | auto |
| Strategy | PM | `docs/strategies/` | **human** |
| Design | Architect, PM, Researcher | `docs/designs/` | **human** |
| Plan | Dev | `docs/plans/` | **human** |
| Implement | Dev | `src/**`, `lib/**` | auto |
| Test | Qa | `tests/**` | auto |
| Review | Reviewer | verdict | **human** |

Each role writes to a scoped directory — no overlaps, safe for parallel execution. Human gates pause the pipeline until you approve.

### Collaborative Mode

When using a `collaborative` profile, discovery roles (researcher, architect, PM) run in parallel and produce a convergence summary before handing off to implementation. You see what each specialist found, approve the handoff, then dev/qa/reviewer execute serially with per-role visibility.

---

## Add Team Members

Need a specialist that isn't in the default roster? Just ask:

```
@ATeam add a security auditor that focuses on auth and data leaks
@ATeam add a performance engineer to profile API response times
@ATeam add a docs writer that maintains README and API docs
```

AgenTeam infers the config, confirms with you, and generates the agent. Then `@` them directly.

---

## Configuration

AgenTeam works out of the box with zero config. Customize when you're ready.

Config lives at `.agenteam/config.yaml` in your project root:

```yaml
version: "1"

# isolation: branch          # branch (default) | worktree | none
# pipeline: hotl             # omit for auto-detect

roles:
  dev:
    write_scope:
      - "src/**"
      - "lib/**"
      - "docs/plans/**"

  # Add custom roles:
  security_auditor:
    description: "Reviews code for security vulnerabilities"
    participates_in: [review]
    can_write: false
    system_instructions: |
      Focus on OWASP top 10, auth/authz logic, and hardcoded secrets.

pipeline:
  stages:
    - name: research
      roles: [researcher]
      gate: auto
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

  # Pipeline profiles (optional) — right-size the pipeline to the task
  profiles:
    quick:
      stages: [implement, test]
      hints: [typo, one-line fix, config change, version bump]
    standard:
      stages: [design, plan, implement, test, review]
      hints: [new endpoint, refactor, add feature, fix bug]
```

Use profiles with `@ATeam --profile quick fix the typo in README`. Without `--profile`, the full pipeline runs.

### Branch Isolation

Writing agents are automatically isolated on dedicated branches — they never touch your current branch directly.

| Mode | Behavior |
|------|----------|
| `branch` *(default)* | Creates `ateam/<role>/<task>` branch per assignment |
| `worktree` | Creates an isolated git worktree per writer |
| `none` | Stays on current branch (relies on non-overlapping write scopes) |

### HOTL Integration

AgenTeam auto-detects the [HOTL plugin](https://github.com/yimwoo/hotl). When present, roles can optionally use HOTL execution skills for stronger development discipline:

| HOTL Skill | Used by | When |
|------------|---------|------|
| `tdd` | Dev | Implementation stages — TDD workflow |
| `systematic-debugging` | Dev | On verify failure or rework |
| `code-review` | Reviewer | Review stages — structured review |

Enable per role in config:

```yaml
roles:
  dev:
    hotl_skills: [tdd, systematic-debugging]
  reviewer:
    hotl_skills: [code-review]
```

Without HOTL installed, roles use their default behavior — no degradation, just less ceremony.

### Resume

Interrupted runs are detected automatically at session start. Resume with verify-first strategy:

```
@ATeam resume <run-id>
```

The runtime re-verifies the last incomplete stage before continuing, and asks before re-dispatching expensive work.

---

## CLI Reference

For Codex CLI users:

| Command | Purpose |
|---------|---------|
| `$ateam:init` | Set up team config and generate agents |
| `$ateam:run "task"` | Run the full pipeline on a task |
| `$ateam:resume` | Resume an interrupted run |
| `$ateam:status` | Show team status and current config |
| `$ateam:add-member` | Add a custom team member |
| `$ateam:generate` | Regenerate agents after config changes |
| `$ateam:standup` | Quick project status report |

---

## Install & Update

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash

# Update
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/update.sh | bash

# Local install (for contributors)
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

`install.sh` keeps the marketplace entry synced with the plugin manifest, and `update.sh` refreshes both the local checkout and marketplace metadata before you restart Codex.

**Requirements:** Python 3.10+, Codex App or Codex CLI.

---

## Contributing

Found a bug or have a role idea? [Open an issue](https://github.com/yimwoo/codex-agenteam/issues) or submit a PR. Custom role configs and pipeline presets are especially welcome.

If AgenTeam is useful to you, a ⭐ goes a long way.

---

## License

MIT © [Yiming Wu](https://github.com/yimwoo)
