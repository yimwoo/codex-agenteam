# Research: Codex Plugin Compliance Audit for codex-agenteam

**Date**: 2026-03-29
**Triggered by**: Request to verify codex-agenteam meets all Codex plugin requirements
**Relevance**: The plugin cannot be installed or discovered by Codex users unless its structure matches the Codex plugin specification.

---

## Key Findings

### Finding 1: plugin.json Is Minimal but Missing Several Important Fields

The current `.codex-plugin/plugin.json` contains only four fields:

```json
{
  "name": "codex-agenteam",
  "version": "1.0.0",
  "description": "AgenTeam: Role-based team collaboration...",
  "skills": "skills/"
}
```

**What is missing compared to the spec and the lore reference plugin:**

| Field | Required? | Current State | Lore Reference | Impact |
|-------|-----------|---------------|----------------|--------|
| `name` | Required | Present | Present | OK |
| `version` | Required | Present | Present | OK |
| `description` | Required | Present | Present | OK |
| `skills` | Optional | `"skills/"` | `"./skills/"` | **Path format wrong** -- spec requires `./` prefix |
| `author` | Optional | **Missing** | `{ "name": ..., "url": ... }` | Needed for marketplace display |
| `homepage` | Optional | **Missing** | Present | Low priority |
| `repository` | Optional | **Missing** | Present | Low priority |
| `license` | Optional | **Missing** | `"MIT"` | Should be specified |
| `keywords` | Optional | **Missing** | Present (12 entries) | Helps plugin discovery |
| `hooks` | Optional | **Missing** | `"./hooks/hooks.json"` | See Finding 3 |
| `mcpServers` | Optional | **Missing** | `"./.mcp.json"` | N/A for this plugin currently |
| `interface` | Optional | **Missing** | Extensive block | **Critical for marketplace visibility** |

The `skills` path should use `"./skills/"` (dot-slash prefix) per the spec: "Paths must be relative to plugin root and start with `./`."

The `interface` block is technically optional but practically required for any plugin that wants to appear properly in the Codex plugin browser. Without it, the plugin has no display name, no description in the installer, no icon, no category, and no starter prompts.

### Finding 2: No Install Script -- Manual Installation Is Unnecessarily Hard

The codex-agenteam plugin has **no install.sh**. The lore reference plugin provides a full installer that:

1. Clones the repo to `~/.codex/plugins/lore-source`
2. Installs dependencies (`npm install`)
3. Reads plugin.json to build a marketplace entry
4. Registers the plugin in `~/.agents/plugins/marketplace.json` (or repo-scoped equivalent)
5. Seeds/refreshes the Codex plugin cache at `~/.codex/plugins/cache/codex-plugins/lore/`
6. Supports `--local` mode for contributors

codex-agenteam's `docs/setup.md` tells users to `git clone` and `pip install -r runtime/requirements.txt`, then vaguely says "add the plugin to your Codex configuration as a local plugin" with no concrete steps.

**What the installer must do for codex-agenteam:**

1. Clone to `~/.codex/plugins/codex-agenteam-source` (or use local mode)
2. Run `pip install -r runtime/requirements.txt` to install PyYAML and toml
3. Read `.codex-plugin/plugin.json` to extract name/version/description
4. Create/update `~/.agents/plugins/marketplace.json` with the plugin entry
5. Seed the Codex plugin cache at `~/.codex/plugins/cache/codex-plugins/codex-agenteam/`
6. Print next-step instructions

Since this plugin is Python-based (not Node), the installer must adapt the dependency installation step. The lore plugin uses `npm install`; codex-agenteam should use `pip install`.

### Finding 3: No Hooks Infrastructure

The lore reference plugin ships `hooks/hooks.json` with three hooks:
- `SessionStart` -- loads shared knowledge at session open
- `UserPromptSubmit` -- whispers context before each prompt
- `Stop` -- runs observer on session end

codex-agenteam has **no hooks directory and no hooks.json**. This is not strictly required -- hooks are optional per the spec -- but certain functionality would benefit from hooks:

- **SessionStart hook**: Could auto-detect `agenteam.yaml` in the project and inject team context at session start. Could run the version check (`scripts/check-update.sh`) silently.
- **UserPromptSubmit hook**: Could inject role context or write-policy warnings before prompts that would trigger multi-agent workflows.

Without a SessionStart hook, the plugin relies entirely on users explicitly invoking `$ateam-init` or `$using-agenteam`. A startup hook that detects an existing `agenteam.yaml` and surfaces the team's status would make the plugin feel "alive" automatically.

Hooks currently require `codex_hooks = true` in `config.toml` and remain experimental. This means hooks are a "nice to have" rather than a blocker, but planning for them now is wise.

### Finding 4: Skill Directory Structure Is Correct

The skills follow the Codex convention properly:

```
skills/
  ateam-generate/SKILL.md
  ateam-dispatch/SKILL.md
  ateam-run/SKILL.md
  ateam-init/SKILL.md
  ateam-status/SKILL.md
  ateam-add-role/SKILL.md
  using-agenteam/SKILL.md
```

Each SKILL.md has the required frontmatter (`name`, `description`) and instruction body. This matches the Codex spec exactly. The `using-agenteam` skill serves as a router skill, which is a good pattern.

**One minor issue**: The skill SKILL.md files reference `<runtime>` and `<plugin-dir>` as placeholder paths. While this is reasonable (the skill instructions are for the AI agent, not for literal execution), there is no mechanism to resolve these paths at runtime. The lore plugin solves this differently -- its MCP server handles path resolution internally. For codex-agenteam, the skills need a concrete path resolution strategy. The `ateam-init` skill says to resolve by checking `./runtime/agenteam_rt.py` first, then `<plugin-install-path>/runtime/agenteam_rt.py`. This heuristic is fragile -- the plugin install path varies depending on install mode.

### Finding 5: No .mcp.json and No .app.json (Not Currently Needed)

The plugin does not provide MCP servers or app connectors. This is fine -- the plugin's architecture is skill-driven with a Python CLI backend. MCP and app connectors are optional per the spec.

However, if the plugin evolves to support real-time state queries (e.g., "what stage is the team on?"), an MCP server could provide tools like `agenteam_status`, `agenteam_dispatch`, etc. that are callable as tools rather than requiring the AI to invoke Python subprocesses. This is a future consideration, not a gap.

### Finding 6: Missing marketplace.json for Repo-Scoped Distribution

Per the Codex plugin spec, plugins are discovered through marketplace files at:
- `$REPO_ROOT/.agents/plugins/marketplace.json` (repo-scoped)
- `~/.agents/plugins/marketplace.json` (personal)

codex-agenteam provides neither. For the plugin to be installable from within a project (repo-scoped), or globally (personal), a marketplace entry is required. The install.sh should generate this, but there should also be a template or example in the repo.

---

## Competitive Landscape

| Project | Approach | Comparison to codex-agenteam | Takeaway |
|---------|----------|------------------------------|----------|
| [Lore](https://github.com/yimwoo/lore) (reference plugin) | Node.js MCP server + hooks + skills, full install.sh, rich plugin.json with interface block | More complete plugin packaging; automated installation; hooks for passive behavior; MCP for tool-based access | codex-agenteam needs parity on packaging (install.sh, interface block, marketplace registration) |
| Codex built-in skills | First-party skills bundled with Codex | No install needed; always available; uses $skill-name invocation | codex-agenteam correctly uses the same $skill-name convention |
| Claude Code agents (.codex/agents/*.toml) | Native agent definition format | codex-agenteam generates these as output; good alignment with Codex native format | Generation approach is sound |

---

## Gap Summary

| Gap | Severity | Blocks Installation? |
|-----|----------|---------------------|
| `skills` path missing `./` prefix | Medium | Possibly -- Codex may not resolve the path |
| No `interface` block in plugin.json | High | No, but plugin is invisible/ugly in marketplace |
| No `author` field in plugin.json | Low | No |
| No `keywords` in plugin.json | Low | No |
| No `install.sh` | **Critical** | Yes -- no automated way to install and register |
| No marketplace.json template | High | Yes -- Codex cannot discover the plugin |
| No hooks directory | Low | No -- hooks are optional and experimental |
| No concrete runtime path resolution in skills | Medium | No, but skills may fail to find the runtime |
| `scripts/check-update.sh` references wrong GitHub repo name | Low | No -- best-effort check, fails silently |

---

## Recommendations

### 1. Fix the `skills` path in plugin.json
Change `"skills/"` to `"./skills/"` to match the spec's path convention.

**Priority**: High
**Effort**: Small (one-character edit)

### 2. Add `interface` block to plugin.json
Add display metadata so the plugin renders properly in the Codex plugin browser:

```json
"interface": {
  "displayName": "AgenTeam",
  "shortDescription": "Role-based team collaboration -- architect, implement, test, review.",
  "longDescription": "AgenTeam organizes AI-assisted development into specialist roles...",
  "developerName": "Yiming Wu",
  "category": "Productivity",
  "capabilities": ["Interactive", "Read", "Write"],
  "defaultPrompt": [
    "Set up a development team for this project",
    "Run the full pipeline on: add user authentication",
    "Dispatch the reviewer to check recent changes"
  ],
  "websiteURL": "https://github.com/yimwoo/codex-agenteam",
  "brandColor": "#2563EB"
}
```

**Priority**: High
**Effort**: Small

### 3. Create install.sh
Build an installer modeled on lore's install.sh but adapted for Python:
- Clone to `~/.codex/plugins/codex-agenteam-source`
- `pip install -r runtime/requirements.txt`
- Read plugin.json and register in `~/.agents/plugins/marketplace.json`
- Seed Codex plugin cache
- Support `--local` flag for development
- Print clear next-step instructions

**Priority**: Critical
**Effort**: Medium

### 4. Add `author`, `keywords`, `repository`, and `license` to plugin.json
Fill in metadata fields for discoverability and attribution.

**Priority**: Medium
**Effort**: Small

### 5. Add a SessionStart hook (optional, forward-looking)
Create `hooks/hooks.json` with a `SessionStart` hook that:
- Detects `agenteam.yaml` in the project
- If found, injects a brief team-status summary as additional context
- Optionally runs the version check

Register in plugin.json as `"hooks": "./hooks/hooks.json"`.

**Priority**: Low (hooks are experimental)
**Effort**: Medium

### 6. Solve runtime path resolution
The skills reference `<runtime>/agenteam_rt.py` without a reliable way to resolve this. Options:
- A) At install time, write a small shim script (e.g., `~/.codex/plugins/cache/.../agenteam-rt`) that knows its own absolute path
- B) Have the install.sh create a symlink or wrapper at a well-known location
- C) Use an environment variable set by a SessionStart hook
- D) The most practical approach: have the install.sh write a small `.agenteam-plugin-path` marker file into the plugin cache, and have the skill instructions check for it

**Priority**: Medium
**Effort**: Medium

### 7. Provide a marketplace.json template
Include a `marketplace.json.template` or have install.sh generate it. For repo-scoped use, provide instructions to create `.agents/plugins/marketplace.json` pointing to the local plugin.

**Priority**: High
**Effort**: Small

---

## Sources
- [Codex Plugin Build Guide](https://developers.openai.com/codex/plugins/build) -- Official plugin.json spec, marketplace format, path conventions
- [Codex Plugins Overview](https://developers.openai.com/codex/plugins) -- Plugin discovery, installation flow, components
- [Codex Agent Skills](https://developers.openai.com/codex/skills) -- SKILL.md format, frontmatter fields, discovery hierarchy
- [Codex Hooks](https://developers.openai.com/codex/hooks) -- hooks.json format, supported events, experimental status
- [Lore plugin (yimwoo/lore)](https://github.com/yimwoo/lore) -- Reference implementation: install.sh, plugin.json with full interface block, hooks, MCP server
- [Lore install.sh](https://raw.githubusercontent.com/yimwoo/lore/main/install.sh) -- Complete installer with marketplace registration, cache seeding, local mode support
