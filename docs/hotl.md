# HOTL Integration

AgenTeam auto-detects the [HOTL plugin](https://github.com/yimwoo/hotl-plugin). When present, roles can use HOTL execution skills for stronger development discipline.

## How It Works

AgenTeam is the **outer orchestrator** — it manages role selection, write policy, and pipeline flow. HOTL is the **inner execution engine** — it manages phase execution (loops, verification, gates).

```
AgenTeam (roles, isolation, pipeline)
    |
    +-- HOTL (tdd, debugging, code-review)
```

AgenTeam wraps HOTL skills and injects role context. It never modifies HOTL internals.

## Enable HOTL

Set the pipeline mode in your config:

```yaml
pipeline: hotl
```

Or let AgenTeam auto-detect: if HOTL is installed and the config omits `pipeline`, AgenTeam will suggest HOTL integration during `$ateam:init`.

## Skill Mapping

| HOTL Skill | Used by | When |
|------------|---------|------|
| `tdd` | Dev | Implementation stages — TDD workflow |
| `systematic-debugging` | Dev | On verify failure or rework |
| `code-review` | Reviewer | Review stages — structured review |

## Per-Role Configuration

Enable specific HOTL skills per role:

```yaml
roles:
  dev:
    hotl_skills: [tdd, systematic-debugging]
  reviewer:
    hotl_skills: [code-review]
```

## Graceful Fallback

Without HOTL installed, roles use their default behavior — no degradation, just less ceremony. The `hotl_skills` config is silently ignored if HOTL is not available.

Check HOTL availability:

```bash
agenteam-rt hotl check
```

## Runtime Commands

```bash
# Check HOTL availability
agenteam-rt hotl check

# Resolve HOTL skill eligibility for a role in a run
agenteam-rt hotl-skills --run-id <id> --stage implement --role dev
```
