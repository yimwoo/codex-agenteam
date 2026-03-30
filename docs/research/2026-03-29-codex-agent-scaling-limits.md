# Research: Codex Agent Scaling Limits

**Date**: 2026-03-29
**Triggered by**: Need to understand how many team members (custom agents) our AgenTeam plugin can realistically generate and run
**Relevance**: AgenTeam generates `.codex/agents/*.toml` files -- we need to know the scaling ceiling

## Executive Summary

There is **no documented or coded limit** on the number of `.codex/agents/*.toml` definition files. The practical ceiling is determined by two runtime constraints: `agents.max_threads` (default 6 concurrent threads) and `agents.max_depth` (default 1 level of nesting). Both are user-configurable. The true hard ceiling is the OpenAI API rate limit, which triggers HTTP 429 errors when too many agents make concurrent model requests.

---

## Key Findings

### Finding 1: No Limit on Agent Definition Files

The Codex CLI source code (`codex-rs/core/src/config/agent_roles.rs`) loads all TOML files from `.codex/agents/` recursively using `collect_agent_role_files_recursive()`. The files are collected into a `BTreeMap<String, AgentRoleConfig>` with **no size cap, no file count validation, and no resource exhaustion protection**. Duplicate role names within a layer trigger warnings but do not prevent loading. There is no documented or hardcoded maximum on definition files.

**Implication for AgenTeam**: We can generate as many `.codex/agents/*.toml` files as we want. A team of 4, 8, 20, or 50 role definitions will all load without issue.

Source: [GitHub - codex-rs/core/src/config/agent_roles.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/config/agent_roles.rs)

### Finding 2: Concurrent Thread Limit Defaults to 6 (Configurable)

The `agents.max_threads` config key controls how many agent threads can run simultaneously. The default is 6, defined as `DEFAULT_AGENT_MAX_THREADS = Some(6)` in `codex-rs/core/src/config/mod.rs`. This is configurable in `config.toml`:

```toml
[agents]
max_threads = 12  # or any number
```

When `max_threads` is reached, new spawn requests **queue** until a thread completes -- they do not fail.

An OpenAI engineer (@etraut-openai) confirmed on GitHub issue #11965: *"The agents.max_threads config key allows you to configure this value. If you don't specify the config key, it defaults to DEFAULT_AGENT_MAX_THREADS (6)."* They also warned: *"Note that if you go significantly above 6, you might trigger a 429 error."*

A user reported successfully running 12 parallel agents for an application build.

Sources:
- [GitHub Issue #11965 - Make MAX_THREADS Configurable](https://github.com/openai/codex/issues/11965)
- [Config Reference](https://developers.openai.com/codex/config-reference)

### Finding 3: Nesting Depth Defaults to 1 (Configurable)

The `agents.max_depth` config key defaults to 1, meaning the root session can spawn child agents, but those children cannot spawn grandchildren. This prevents recursive fan-out. It is also configurable:

```toml
[agents]
max_depth = 2  # allow grandchildren
```

The docs explicitly warn: *"Raising this value can turn broad delegation instructions into repeated fan-out, which increases token usage, latency, and local resource consumption."*

**Implication for AgenTeam**: Our plugin dispatches agents from the skill layer (depth 0 -> 1), so the default `max_depth = 1` is sufficient. Our agents do not need to spawn sub-sub-agents.

Source: [Subagents Documentation](https://developers.openai.com/codex/subagents)

### Finding 4: API Rate Limits Are the True Ceiling

The real constraint on concurrent agent execution is the OpenAI API rate limit. Multiple concurrent agents each make independent model and tool calls, multiplying token consumption. Key facts:

- Rate limits are measured in RPM (requests/min), TPM (tokens/min), RPD, TPD
- Plans have 5-hour rolling windows: Plus/Business gets 10-60 cloud tasks per window; Pro gets 50-400
- Going above ~6 concurrent agents risks triggering HTTP 429 (Too Many Requests)
- Codex CLI has built-in retry logic (up to 5 retries, 15s delay) for 429 errors
- Enterprise/Edu plans have no fixed limits (usage scales with credits)

Source: [Codex Pricing](https://developers.openai.com/codex/pricing)

### Finding 5: Multi-Agent v2 (March 2026) Improves Scalability

The latest CLI release (0.117.0, March 26, 2026) introduced multi-agent v2 with:
- Path-based agent addresses (`/root/agent_a`) replacing UUIDs
- Structured inter-agent messaging
- Agent listing for multi-agent workflows
- Better recovery from stale turn-steering races

This suggests OpenAI is actively investing in multi-agent scalability. The path-based addressing scheme scales better than the previous UUID system and has no documented ceiling.

Source: [Codex Changelog](https://developers.openai.com/codex/changelog)

### Finding 6: project_doc_max_bytes Affects Instructions, Not Agent Count

The `project_doc_max_bytes` limit (default 32 KiB) controls how much of AGENTS.md is loaded into context. This does **not** affect the number of `.codex/agents/*.toml` files. Agent TOML files have their own `developer_instructions` field that is loaded per-agent. However, if our generated TOML files have very large `developer_instructions` strings, there may be practical token-budget constraints per session.

Source: [AGENTS.md Guide](https://developers.openai.com/codex/guides/agents-md)

---

## Limit Summary Table

| Constraint | Default | Configurable? | Hard Max |
|---|---|---|---|
| Number of `.codex/agents/*.toml` definition files | Unlimited | N/A | No limit found in code or docs |
| Concurrent agent threads (`max_threads`) | 6 | Yes, via config.toml | No hard max; API rate limits apply |
| Agent nesting depth (`max_depth`) | 1 | Yes, via config.toml | No hard max; cost/latency concerns |
| Per-worker timeout (CSV jobs) | 1800s | Yes | N/A |
| Cloud tasks per 5-hour window (Plus) | 10-60 | Upgrade plan | Varies by plan |
| Cloud tasks per 5-hour window (Pro) | 50-400 | Buy credits | Varies by plan |
| Cloud tasks per 5-hour window (Enterprise) | No fixed limit | Credits | Credits-based |

---

## Competitive Landscape

| Project | Approach | Comparison to AgenTeam | Takeaway |
|---|---|---|---|
| Codex built-in subagents | 3 built-in agents (default, worker, explorer) + custom TOML | AgenTeam adds structured roles on top | We complement rather than compete |
| Claude Code agents | AGENTS.md with agent orchestration | Similar concept, different format | TOML approach aligns with Codex native format |
| Cursor/Windsurf | IDE-integrated agents | No plugin/TOML extensibility | AgenTeam's file-based approach is more portable |
| Codex + Agents SDK | SDK-level multi-agent | Heavier integration than plugin | Our plugin approach is lighter-weight |

---

## Recommendations

1. **Default to 4-6 team roles; document how to scale beyond**
   Our current built-in roles (architect, implementer, reviewer, test-writer) plus a few custom roles fit comfortably within the default `max_threads = 6`. For users with more roles, document that they should increase `max_threads` in their config.toml.
   Priority: high
   Effort: small

2. **Add a `max_threads` recommendation to generated output**
   When `agenteam_rt.py generate` produces more than 6 agent TOML files, emit a warning or suggestion to the user: "You have N agents defined. Consider setting agents.max_threads = N in your .codex/config.toml for full parallelism."
   Priority: medium
   Effort: small

3. **Keep developer_instructions concise in generated TOML**
   Since each agent session independently loads its instructions, bloated instructions multiply token costs. Keep the `system_instructions` in role YAML lean and specific.
   Priority: medium
   Effort: small

4. **Do not artificially cap the number of roles**
   Since Codex imposes no limit on definition files, AgenTeam should not either. Let users define as many custom roles as they want. The runtime constraint (max_threads) is self-regulating -- excess agents simply queue.
   Priority: high
   Effort: none (current behavior is already correct)

5. **Monitor multi-agent v2 path-based addressing**
   The March 2026 multi-agent v2 release introduces path-based agent addresses and structured messaging. This may enable more sophisticated AgenTeam orchestration patterns in the future (e.g., direct agent-to-agent communication instead of dispatch plans).
   Priority: low
   Effort: medium (future work)

6. **Consider serial dispatch for cost management**
   For users on Plus/Business plans with tight cloud-task budgets (10-60 per 5-hour window), recommend serial pipeline execution over parallel dispatch. Document this as a cost optimization strategy.
   Priority: medium
   Effort: small

---

## Sources

- [Codex Config Reference](https://developers.openai.com/codex/config-reference) -- Complete config parameter list including agents.max_threads, max_depth
- [Codex Subagents Documentation](https://developers.openai.com/codex/subagents) -- Agent definition format, concurrency model, best practices
- [Codex Sample Configuration](https://developers.openai.com/codex/config-sample) -- Full sample config.toml with [agents] section
- [GitHub Issue #11965 - Make MAX_THREADS Configurable](https://github.com/openai/codex/issues/11965) -- Confirmed max_threads is already configurable; 429 risk above 6
- [GitHub Issue #13964 - Schema says max_threads unbounded](https://github.com/openai/codex/issues/13964) -- Clarified that unset defaults to 6 (not unlimited); fixed in docs
- [GitHub - codex-rs/core/src/config/agent_roles.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/config/agent_roles.rs) -- Source code showing no file count limits on agent definitions
- [GitHub - codex-rs/core/src/config/mod.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs) -- DEFAULT_AGENT_MAX_THREADS = Some(6)
- [Codex Changelog](https://developers.openai.com/codex/changelog) -- Multi-agent v2 with path-based addressing (March 26, 2026)
- [Codex Pricing](https://developers.openai.com/codex/pricing) -- Plan-based usage limits and cloud task quotas
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced) -- Profile management, MCP servers, observability
- [Codex CLI Features](https://developers.openai.com/codex/cli/features) -- Custom agent overview and subagent spawning behavior
- [Build Codex Plugins](https://developers.openai.com/codex/plugins/build) -- Plugin manifest structure and capabilities
