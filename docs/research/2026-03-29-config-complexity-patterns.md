# Research: Configuration Complexity Patterns in Developer Tools

**Date**: 2026-03-29
**Triggered by**: Need to decide how AgenTeam's `agenteam.yaml` / generated `.codex/agents/*.toml` should handle simple vs advanced config
**Relevance**: AgenTeam's config surface (pipeline modes, write policies, HOTL integration, role overrides) risks overwhelming new users

## Key Findings

### Finding 1: The "Sensible-Defaults-Plus-Layers" Pattern Dominates

Every successful tool uses the same core strategy: **zero required config beyond identity, with commented-out templates for everything else**.

**Codex itself** is the clearest example. A valid `config.toml` is one line:
```toml
model = "gpt-5.4"
```
Everything else -- sandbox mode, approval policy, MCP servers, profiles, OTEL -- exists as commented-out blocks in the sample config with inline `# Default: ...` annotations. The official docs split this into separate pages: "Config basics" (4 keys) vs "Advanced Configuration" (profiles, providers, OTEL, hooks).

**ESLint flat config** went through the same evolution. The old `.eslintrc` system grew organically complex; the flat config replacement (`eslint.config.js`) was designed so `export default []` is valid. The 2025 addition of `defineConfig()` + `extends` further reduced boilerplate -- you go from 1 line to N lines only as your needs grow, never all-at-once.

**Helm** is the cautionary tale. Mandatory `values.yaml` files that routinely hit 100+ lines are a known pain point in the ecosystem. Helm docs explicitly recommend flat keys over nested ones because nested values require existence checks at every level. The community consensus: commented-out sections in `values.yaml` are documentation, not configuration.

### Finding 2: Docker Compose "Profiles" Is the Best Pattern for Optional Integrations

Docker Compose solves the "HOTL-like" problem cleanly: **services without a `profiles` attribute always start; services with `profiles` are hidden until explicitly activated**.

```yaml
services:
  backend:          # always starts
    image: backend
  phpmyadmin:       # only with --profile debug
    image: phpmyadmin
    profiles: [debug]
```

Key design decisions:
- Core services have NO profile tag (zero config for the common case)
- Optional services are visible in the file but inert by default
- Activation is explicit: `--profile debug` or `COMPOSE_PROFILES=debug`
- Targeting a profiled service directly auto-activates it (escape hatch)

This maps directly to AgenTeam's HOTL question: the `pipeline: hotl` mode should be present in the config file as a commented-out option with a note like `# Requires HOTL plugin installed`, not hidden entirely.

### Finding 3: Claude Code Subagents Use "Required 2, Optional 15" Pattern

Claude Code's `.claude/agents/*.md` frontmatter has **2 required fields** (`name`, `description`) and **15 optional fields** (`tools`, `model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`, `background`, `effort`, `isolation`, `initialPrompt`, `disallowedTools`). The minimal valid agent is:

```markdown
---
name: reviewer
description: Reviews code for quality
---
You are a code reviewer.
```

Everything else layers on. This is the pattern Codex agent TOML files also follow -- `name` and `description` are the only truly required fields; `model`, `sandbox_mode`, `developer_instructions` are optional with sane defaults.

### Finding 4: "List Unavailable Options" Beats "Hide Them"

Across tools, the winning pattern for optional/unavailable integrations is **visible but inactive** rather than hidden:

| Tool | Pattern | Example |
|------|---------|---------|
| Docker Compose | `profiles: [debug]` -- visible, inactive | Service defined but doesn't start |
| Codex sample config | Commented blocks with `# Default: unset` | MCP servers, OTEL, custom providers |
| Helm | Commented sections with docs | `# ingress.enabled: false` |
| ESLint | `extends` accepts missing plugins gracefully | Plugin not installed = clear error, not silent |

Hiding options creates two problems: (1) users don't know they exist, (2) when they discover them, they have no template to copy. Listing them commented-out with a one-line explanation solves both.

## Competitive Landscape

| Tool | Config approach | Progressive disclosure | Optional integrations |
|------|----------------|----------------------|----------------------|
| Codex | TOML, 1 required key | Separate basic/advanced doc pages | Commented blocks in sample |
| Claude Code agents | Markdown+YAML, 2 required fields | Optional fields ignored if absent | Not applicable (tools inherited) |
| ESLint flat config | JS module, 0 required config | `defineConfig()` wraps complexity | `extends` normalizes plugin access |
| Docker Compose | YAML, profiles for optional | Core services profile-free | `profiles:` tag hides until activated |
| Helm | YAML values, all keys listed | Flat > nested recommended | Commented with `enabled: false` |

## Recommendations for AgenTeam

### 1. Make `agenteam.yaml` work with 3 lines

**Current state**: The config file is 72 lines. A new user sees pipeline stages, write policies, role overrides, and model selections all at once.

**Target**: A minimal valid config should be:
```yaml
version: "1"
team:
  name: my-project
```

Everything else should have defaults baked into the runtime. `pipeline: standalone`, `parallel_writes.mode: serial`, default roles with default models -- all derived if absent.

Priority: **high** | Effort: **small** (runtime already deep-merges; just make top-level keys optional)

### 2. Ship a "full" config as a separate reference file, not the default

Follow the Codex pattern: `agenteam init` should generate the 3-line minimal config. Provide a `agenteam init --full` or a `docs/agenteam-reference.yaml` with every option commented out and annotated. The current 72-line config should be that reference file, not what users get by default.

Priority: **high** | Effort: **small**

### 3. Use the Docker Compose profiles pattern for HOTL

Don't hide `pipeline: hotl` -- list it as a commented option with a clear note:

```yaml
team:
  # pipeline: hotl       # Requires HOTL plugin. See docs/hotl-integration.md
  pipeline: standalone    # Default: built-in stage pipeline
```

If someone sets `pipeline: hotl` without HOTL installed, `agenteam_rt.py` should fail fast with a specific error message naming what's missing. The `auto` mode already does detection, which is correct.

Priority: **medium** | Effort: **small**

### 4. Keep generated TOML files minimal

The generated `.codex/agents/*.toml` files should contain only the fields that differ from Codex defaults. Currently `architect.toml` has 5 fields -- that's fine. Don't add fields "for documentation" in generated files; those are machine output, not human-authored config. The role YAML files are the human-readable source of truth.

Priority: **medium** | Effort: **none** (current behavior is already correct)

### 5. Adopt the "required 2, optional N" convention for role YAML

Currently role YAML files have ~15 fields all populated. Consider marking which are truly required (`name`, `description`) vs optional-with-defaults. This matters when users define custom roles in `agenteam.yaml` -- they shouldn't need to specify `parallel_safe: false` or `reasoning_effort: medium` if those are the defaults.

Priority: **low** | Effort: **small**

## Sources

- [Codex Config Basics](https://developers.openai.com/codex/config-basic) -- Minimal config is 1 line; hierarchy resolves user > project > system > defaults
- [Codex Config Reference](https://developers.openai.com/codex/config-reference) -- Full schema showing required vs optional keys with defaults
- [Codex Sample Configuration](https://developers.openai.com/codex/config-sample) -- Progressive disclosure via commented blocks with inline defaults
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced) -- Profiles, providers, OTEL separated into advanced tier
- [ESLint Flat Config: defineConfig + extends](https://eslint.org/blog/2025/03/flat-config-extends-define-config-global-ignores/) -- defineConfig() normalizes plugin composition, extends reduces boilerplate
- [Docker Compose Profiles](https://docs.docker.com/compose/how-tos/profiles/) -- Services without profiles always start; profiled services hidden until activated
- [Docker Compose Profiles: Underrated Feature](https://event-driven.io/en/docker_compose_profiles/) -- Practical patterns for optional service management
- [Helm Values Best Practices](https://helm.sh/docs/chart_best_practices/values/) -- Flat > nested; comments as documentation for optional sections
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents) -- 2 required fields, 15 optional; frontmatter-based progressive config
- [Progressive Disclosure of Complexity](https://jason.energy/progressive-disclosure-of-complexity/) -- "Opt out of defaults incrementally, not all-or-nothing"
- [Syntasso: Progressive Disclosure in Developer Platforms](https://www.syntasso.io/post/why-implement-progressive-disclosure-in-your-internal-developer-platform-and-portal) -- Sensible defaults grouped into layers; expose layers through appropriate interfaces
