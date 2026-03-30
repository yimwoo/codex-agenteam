# Config Simplification Design

**Date:** 2026-03-30
**Status:** Approved

## Problem

The current config is 72 lines and exposes internal concepts (pipeline modes,
parallel_writes nesting) that confuse users. Options like `hotl`, `auto`, and
`dispatch-only` are meaningless to users without context. New users should see
a 1-3 line config that just works.

## Decision

### Minimal config (all you need)

```yaml
version: "1"
```

Everything else is inferred from defaults and auto-detection.

### Customized config (only what you override)

```yaml
version: "1"
isolation: worktree       # branch (default) | worktree | none
roles:
  dev:
    write_scope: ["src/**", "lib/**"]
pipeline:
  stages:
    - name: implement
      roles: [dev]
      gate: auto
```

### Schema changes

| Before | After | Default |
|--------|-------|---------|
| `team.pipeline: standalone \| hotl \| dispatch-only \| auto` | `pipeline: hotl` (top-level, optional) | Auto-detect: HOTL if available + active, else standalone |
| `team.parallel_writes.mode: serial \| scoped \| worktree` | `isolation: branch \| worktree \| none` | `branch` |
| `team.name` | removed | Not used by runtime |
| `team:` block | removed | -- |

### Key decisions

- **`auto` becomes the default behavior**, not a setting. Runtime auto-detects
  HOTL at dispatch time. Only `pipeline: hotl` exists as an explicit override.
- **`dispatch-only` is eliminated.** It's just "no stages defined."
- **`scoped` renamed to `none`.** Honest: it does not isolate.
- **`serial` renamed to `branch`.** Describes what actually happens.
- **Legacy schema accepted** with deprecation warning. `team.pipeline` and
  `team.parallel_writes.mode` still work but emit a stderr warning.

### $ateam:init behavior

- **HOTL not detected:** generate minimal config (no HOTL references)
- **HOTL detected:** add a commented-out line: `# pipeline: hotl  # HOTL plugin detected`
- **Never show `auto` or `dispatch-only` to users**

## Backward Compatibility

Runtime accepts both schemas via `resolve_team_config()`:

```python
def resolve_team_config(config: dict) -> tuple[str, str]:
    # New schema (flat keys)
    isolation = config.get("isolation")
    pipeline = config.get("pipeline")  # only "hotl" is valid

    # Legacy schema (nested team block)
    team = config.get("team", {})
    if not pipeline:
        legacy_pipeline = team.get("pipeline")
        if legacy_pipeline == "hotl":
            pipeline = "hotl"
    if not isolation:
        pw = team.get("parallel_writes", {})
        legacy_mode = pw.get("mode")
        ISOLATION_MAP = {"serial": "branch", "scoped": "none", "worktree": "worktree"}
        isolation = ISOLATION_MAP.get(legacy_mode)

    # Defaults
    isolation = isolation or "branch"
    # pipeline: None means auto-detect at runtime
    return pipeline, isolation
```

## Implementation Slices

```
Slice 1: Extract resolve_team_config() helper (pure refactor, no behavior change)
Slice 2: Accept new flat keys alongside legacy nested keys
Slice 3: Rewrite template to minimal form
Slice 4: Update tests to new schema
Slice 5: Update skill docs
Slice 6: Deprecation warning for legacy keys (optional)
```

## Research

- docs/research/2026-03-29-config-complexity-patterns.md
- PM analysis: kill team.pipeline enum, HOTL options only when detected
- Architect analysis: runtime needs only `version`, everything else defaultable
