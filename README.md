<p align="center">
  <img src="assets/agenteam-banner.png" alt="AgenTeam -- Research, Design, Build, Review" width="100%">
</p>

<p align="center">
  <strong>Specialist AI agents orchestrated as a configurable team pipeline for Codex.</strong>
</p>

---

## Quick Start

**Install:**

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

Restart Codex, go to **Plugins > Local Plugins**, and install AgenTeam.

**Use it:**

```
@ATeam build my team
```

That's it. AgenTeam creates your config, generates the agents, and shows your team.

---

## Your Team

After setup, type `@` in Codex to see your team:

| Role | @ Mention | What They Do |
|------|-----------|-------------|
| Researcher | `@Researcher` | Investigates web, GitHub, docs, community trends |
| PM | `@Pm` | Decides what to build, prioritizes, writes specs |
| Architect | `@Architect` | Designs systems, critiques plans, identifies risks |
| Dev | `@Dev` | Translates designs into plans, writes production code |
| QA | `@Qa` | Writes unit and integration tests |
| Reviewer | `@Reviewer` | Reviews for correctness, security, and regressions |

Talk to any role directly:

```
@Architect review this API design
@Pm what should we build next?
@Researcher what are the best practices for error handling in this stack?
@Dev fix the race condition in src/queue.py
@Qa add a regression test for the queue race condition
@Reviewer review the queue fix and test
```

Use `@ATeam` for team-level operations:

```
@ATeam refactor this codebase to be more maintainable
@ATeam show team status
@ATeam add a security auditor that focuses on OWASP top 10
```

---

## Pipeline

When you give `@ATeam` a task, it orchestrates the full pipeline:

```
research --> strategy --> design --> plan --> implement --> test --> review
   |            |           |          |          |           |         |
   v            v           v          v          v           v         v
  docs/      docs/       docs/     docs/      src/**      tests/**  (verdict)
  research/  strategies/ designs/   plans/     lib/**
```

Each role writes to a scoped directory -- no overlaps, safe for parallel execution.

---

## Add Team Members

Need a specialist? Just ask:

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

  # Add custom roles
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
```

### Branch Isolation

Writing agents are automatically isolated on dedicated branches -- they never work directly on your current branch.

| Isolation | What Happens |
|-----------|-------------|
| `branch` (default) | Creates `ateam/<role>/<task>` branch per assignment |
| `worktree` | Creates isolated git worktree per writer |
| `none` | Stays on current branch (trusts non-overlapping write scopes) |

### HOTL Integration

AgenTeam auto-detects the [HOTL plugin](https://github.com/yimwoo/hotl). When available, AgenTeam is the outer orchestrator (who does what, write policy) and HOTL is the inner engine (loops, verification, gates). Force it with `pipeline: hotl`.

---

## CLI Reference

For Codex CLI users:

| Command | Purpose |
|---------|---------|
| `$ateam:init` | Set up team config and generate agents |
| `$ateam:run "task"` | Run the full pipeline |
| `$ateam:status` | Show team status |
| `$ateam:add-member` | Add a custom team member |
| `$ateam:generate` | Regenerate agents after config changes |
| `$ateam:standup` | Quick project status report |

---

## Install / Update

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash

# Update
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/update.sh | bash

# Local install (contributors)
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

**Requirements:** Python 3.10+, Codex App or Codex CLI.

---

## License

MIT
