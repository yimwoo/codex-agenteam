# Setup Guide

## Prerequisites

- **Python 3.10+** (pre-installed on macOS and most Linux systems)
- **PyYAML** and **toml** Python packages
- **Codex CLI** or **Codex App**

## Installation

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/install.sh | bash
```

This clones the repo, installs Python dependencies, and registers the plugin in the Codex marketplace.

### Update

```bash
curl -fsSL https://raw.githubusercontent.com/yimwoo/codex-agenteam/main/update.sh | bash
```

### Local Install (for contributors)

```bash
git clone https://github.com/yimwoo/codex-agenteam.git
cd codex-agenteam
bash install.sh --local
```

## After Installation

1. Restart Codex
2. Go to **Plugins > Local Plugins** and install AgenTeam
3. Navigate to your project and run `@ATeam build my team`

If the role picker still does not show the new roles, confirm the project now
contains `.codex/agents/*.toml`, then open a new thread or restart Codex so it
reloads workspace agents from that folder.

**For teams:** If your repo already has `.agenteam.team/config.yaml` (committed
by a teammate), AgenTeam detects it automatically — no init needed. Your team's
pipeline, roles, and stages are shared. Create `.agenteam/config.yaml` only if
you need personal overrides (e.g., different model preferences).

## Next Steps

- Optional: scaffold governed-delivery foundations if your team wants
  lightweight decision tracking and tripwire checks for larger work
  - `agenteam-rt governed-bootstrap`
  - optional validation helpers:
    - `agenteam-rt decision render-log`
    - `agenteam-rt tripwire check --path src/auth/login.py`
- [Configuration Reference](configuration.md) -- customize roles, isolation, and pipeline
- [Pipeline & Profiles](pipeline.md) -- stages, gates, and task-sized profiles
- [CLI Reference](cli.md) -- all commands and skills
- [HOTL Integration](hotl.md) -- structured execution with the HOTL plugin
