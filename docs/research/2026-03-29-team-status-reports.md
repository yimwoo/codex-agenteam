# Research: Team Status Reports and Multi-Agent Standups

**Date**: 2026-03-29
**Triggered by**: Designing a team standup / status report feature for AgenTeam
**Relevance**: AgenTeam already has a `status` skill showing run state; this research informs a richer cross-agent summary feature.

## Key Findings

### Finding 1: No multi-agent framework has a built-in "team standup" feature

None of the major multi-agent frameworks (CrewAI, AutoGen, MetaGPT, LangGraph) ship a dedicated "team standup" or "all agents report their perspective" feature. What they do offer:

- **CrewAI** provides `CrewOutput` (aggregates `TaskOutput` objects with raw/JSON/Pydantic results + token usage), `output_log_file` for persistent execution logs, step-level and task-level callbacks, and real-time streaming. The hierarchical process includes a "manager agent" that synthesizes final output, but it does not produce a status report across agents -- it delegates and collects results. The manager pattern is also buggy in practice (documented delegation failures in 2025).
- **AutoGen** returns a `TaskResult` containing all messages from all agents plus a `stop_reason`. The `Console()` utility formats these with speaker labels, token counts, and duration. There is no summary synthesis step -- just a chronological message log.
- **MetaGPT** uses a publish-subscribe shared message pool where agents post structured artifacts (PRDs, design docs, code) rather than status updates. Role-to-role communication is through formal document handoff, not informal reporting.
- **LangGraph** uses a shared state object that all agents read/write to with reducer-based merging. Status is implicitly shared through state fields, not explicitly reported.

**Implication for AgenTeam**: A team standup feature would be a differentiator. No existing framework does this. The closest analogue is MetaGPT's structured artifact handoff, but nobody synthesizes a "here's what the whole team thinks" view.

### Finding 2: Project management tools have converged on AI-generated summaries from activity data

- **Linear** auto-generates project status summaries by scanning completed issues, comments, and merged PRs. It produces health indicators (on-track / at-risk / off-track) and delivers summaries to inbox or Slack. It can flag "At Risk" projects by detecting scope creep.
- **GitHub Projects** offers burn-up charts, automated workflow triggers, and sub-issue progress roll-ups -- but no natural language summary generation.
- **ClickUp** has the most aggressive AI approach: its "Brain" scans tasks, milestones, comments, and Docs to produce structured status reports with customizable focus areas, length, and audience level (team detail vs. executive summary). Saves 4-8 hours/week of manual reporting per their claims.

**Pattern**: The most useful tools don't just dump activity logs -- they synthesize. Linear's health indicator + narrative summary is the gold standard. GitHub's charts are useful but lack the natural language explanation of "why" things are on/off track.

### Finding 3: AI standup tools collect three layers of data, but only the synthesis layer adds value

The market has many async standup tools. What they collect and how they report:

| Tool | Data Sources | Output Format | AI Features |
|------|-------------|---------------|-------------|
| **DailyBot** | Manual answers, Jira/Trello/GitHub activity | Compiled report per channel, CSV/PDF export | AI summaries, blocker detection |
| **Geekbot** | Manual answers via Slack DMs | Channel broadcasts, scheduled summaries | Participation/sentiment analysis |
| **Kollabe** | Manual answers, integrations | AI-generated summaries | Auto-highlights wins, blockers, focus areas, patterns |
| **Spinach** | Live meeting audio, Jira | Meeting summaries with action items | Auto-links Jira tickets, suggests new tickets, writes stakeholder reports |
| **Status Hero** | Manual check-ins + GitHub/Jira/Asana activity | Team dashboard with goals/activities/help requests | Activity correlation with check-ins |
| **Standup.so** | Git commits, task lists (paste-in) | Yesterday/Today/Blockers report | Commit-to-narrative transformation |

**What actually works**: The tools that combine automatic activity data (git, issues) with human context (blockers, priorities) produce the most useful output. Pure git-commit-to-summary tools (Standup.so) are a toy -- commits describe what changed, not why or what's blocked. Pure manual-input tools (basic Geekbot) are overhead. The sweet spot is automated activity + structured human input + AI synthesis.

### Finding 4: The "Yesterday/Today/Blockers" format is a scaffold, not a destination

The classic three-question standup format is widely used but widely criticized:

- It encourages **activity reporting** ("I worked on X") rather than **outcome reporting** ("X is now unblocked / shipped / at risk").
- Blockers without next steps create anxiety, not action. Best practice: report blockers as "problem + proposed next step + who needs to act."
- Many experienced teams abandon the three-question format entirely once they have the discipline to focus on goals.

**Better alternatives from the research**:
- **Goal-focused**: "Progress toward [sprint goal]" + "Risks to [sprint goal]" -- ties everything to outcomes.
- **Action-oriented**: Each item must have an owner and a due date. No orphan blockers.
- **Health-indicator + narrative**: Linear's approach -- a single status emoji/label (on-track, at-risk, off-track) followed by 2-3 sentences of context. Fastest to scan, easiest to act on.

### Finding 5: The metrics that actually matter for dev team status reports

Based on the DX Core 4 framework (used by 300+ companies) and engineering management best practices:

**High signal (include)**:
- **Blockers requiring intervention** -- the single most actionable item; teams that surface blockers resolve them 2-3 days faster
- **Stage/milestone completion status** -- what's done, what's in progress, what's next
- **Health indicator** -- a single on-track / at-risk / off-track label, decided by evidence not gut
- **Risk items** -- scope changes, unresolved review comments, failing tests, dependency issues
- **Decisions made** -- what was decided and by whom, so the team has a shared record

**Medium signal (include if available)**:
- **Git activity summary** -- PRs merged, files changed, not raw commit lists
- **Test status** -- pass/fail counts, new failures
- **Code review state** -- open reviews awaiting action

**Low signal / noise (omit)**:
- Raw commit logs (activity, not outcomes)
- Lines of code changed (vanity metric)
- Deployment counts without quality context
- Individual time tracking
- Per-agent token usage (internal concern, not team status)

**Key principle**: Report accomplishments, not activities. Answer "What have we built/decided/unblocked?" not "What have we been busy with?"

## Competitive Landscape

| Project | Approach | Comparison to AgenTeam | Takeaway |
|---------|----------|----------------------|----------|
| **CrewAI** | Manager agent synthesizes final output; `CrewOutput` aggregates task results | AgenTeam has roles but no synthesizer role that produces a team-wide view | Add a synthesis step that collects per-role outputs |
| **MetaGPT** | Structured artifact handoff via shared message pool; publish-subscribe | AgenTeam uses state files + dispatch plans, similar concept | Status could read all role artifacts and summarize |
| **AutoGen** | `TaskResult` with chronological message log; `Console()` formatting | AgenTeam's status skill shows pipeline state, not agent perspectives | Richer than AutoGen's raw log, less than what's possible |
| **LangGraph** | Shared state object with reducer merging | AgenTeam's `.agenteam/state/` files serve a similar purpose | State is there; what's missing is the summary layer |
| **Linear** | AI scans activity, generates health + narrative summary | Closest to ideal; AgenTeam could do the same for agent runs | Model the output format on Linear's approach |
| **DailyBot/Kollabe** | Async collection + AI summary of wins/blockers/focus | Good UX pattern for team-facing output | Adapt the summary format for agent teams |

## Recommendations

### 1. Build a `standup` skill that synthesizes per-role perspectives into a single report

The existing `status` skill shows pipeline state (stages, locks, gates). A new `standup` skill should go further: for each active/completed role in the current run, read their output artifacts and state, then produce a synthesized team view.

**Format** (modeled on Linear + goal-focused standup best practices):
```
AgenTeam Standup: <team-name>
Run: <run-id> | Task: <short task description>
Health: [on-track | at-risk | off-track]

## Completed
- [architect] Design doc produced: <1-line summary>
- [implementer] 3 files changed, tests passing

## In Progress
- [reviewer] Reviewing implementation -- 2 comments open

## Blocked
- [qa] Waiting on review completion (owner: reviewer)

## Decisions
- Architecture: chose X over Y because Z (architect, stage: design)

## Next
- reviewer completes review -> qa begins test stage
```

**Why**: No framework does this. It's a genuine differentiator. The signal-to-noise ratio is high because it focuses on outcomes, blockers, and decisions rather than activity logs.

**Priority**: High
**Effort**: Medium -- reads existing state files and role outputs; the hard part is the synthesis prompt/logic.

### 2. Use a health indicator as the top-line signal

Every status report should open with a single health label: `on-track`, `at-risk`, or `off-track`. Determine this programmatically from:
- Are any stages blocked or failed?
- Has a stage been in-progress longer than expected?
- Are there unresolved gate rejections?
- Are there write-lock contention issues?

**Why**: Linear's adoption of this pattern shows it works. Decision-makers scan the health indicator first and only read details if it's not green. This is especially valuable when AgenTeam is running multiple concurrent tasks.

**Priority**: High
**Effort**: Small -- the data is already in the state file.

### 3. Report blockers as "problem + next step + owner"

Don't just list that something is blocked. Every blocker in the standup output should include what's blocked, why, and what needs to happen next (and who does it).

**Why**: Research shows teams that surface structured blockers resolve them 2-3 days faster. For an AI agent team, this means the orchestrator (or human) can immediately see what to unblock.

**Priority**: High
**Effort**: Small -- this is a formatting convention for the standup skill template.

### 4. Include git and artifact summaries, not raw logs

When git activity is available, summarize it at the PR/changeset level ("3 files changed in runtime/, tests passing") rather than listing individual commits. When role artifacts exist (design docs, test reports), include a one-line summary rather than the full content.

**Why**: Raw commit logs are the top source of noise in automated status reports (confirmed by research on Standup.so, Status Hero, and engineering metrics best practices). Summaries are signal; logs are noise.

**Priority**: Medium
**Effort**: Medium -- requires reading git state and summarizing, which may need an LLM call or heuristic.

### 5. Support audience-tailored output

ClickUp's approach of adjustable "focus areas, report length, and style" for different audiences is worth borrowing. A standup for the human operator should be concise (the format above). A standup for another agent (e.g., the PM role reviewing team progress) could include more structured data.

Consider two output modes:
- `--format brief` (default): The concise human-readable format above
- `--format json`: Machine-readable structured output for programmatic consumption by other agents/skills

**Why**: AgenTeam's architecture already separates runtime (JSON output) from skills (human-facing). The standup should follow the same pattern.

**Priority**: Medium
**Effort**: Small -- the runtime already outputs JSON; add a standup subcommand.

### 6. Do not build a "meeting" or "conversation" feature

Some frameworks (AutoGen's group chat, CrewAI's hierarchical manager) simulate multi-agent conversations where agents talk to each other. The research shows these are:
- Expensive in tokens
- Prone to hallucination and circular reasoning
- Not more informative than structured artifact exchange

MetaGPT explicitly rejected unconstrained natural language dialogue in favor of structured communication, and their results were better. AgenTeam's dispatch-plan architecture is already on the right side of this tradeoff. Don't add a "team meeting" simulation.

**Why**: The evidence from MetaGPT's paper and CrewAI's documented hierarchical process failures shows that unstructured multi-agent dialogue produces worse outcomes than structured handoff. AgenTeam's current architecture (dispatch plans + state files + role artifacts) is the right foundation.

**Priority**: N/A (anti-recommendation)
**Effort**: N/A

## Sources

- [CrewAI Docs - Crews](https://docs.crewai.com/en/concepts/crews) -- CrewOutput structure, callbacks, output_log_file, manager agent
- [AutoGen Teams Tutorial](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/teams.html) -- TaskResult, RoundRobinGroupChat, Console formatting
- [MetaGPT Paper](https://arxiv.org/html/2308.00352v6) -- Shared message pool, structured communication protocol, role-based artifact handoff
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/) -- Shared state architecture, reducer merging
- [LangGraph Production Multi-Agent Communication](https://www.marktechpost.com/2026/03/01/how-to-design-a-production-grade-multi-agent-communication-system-using-langgraph-structured-message-bus-acp-logging-and-persistent-shared-state-architecture/) -- Structured message bus, persistent shared state
- [Linear AI Workflows](https://linear.app/ai) -- AI-generated project summaries, health indicators
- [Linear Initiative and Project Updates](https://linear.app/docs/initiative-and-project-updates) -- Health indicator + narrative format
- [ClickUp AI Status Report Generator](https://clickup.com/p/features/ai/status-report-generator) -- Audience-tailored automated reports, 4-8hr/week savings
- [GitHub Projects Insights](https://docs.github.com/en/issues/planning-and-tracking-with-projects/viewing-insights-from-your-project/about-insights-for-projects) -- Burn-up charts, automated workflows
- [DailyBot](https://www.dailybot.com/) -- Async standup with AI summaries, multi-tool integration
- [Geekbot](https://geekbot.com/) -- Slack-native async standups, participation tracking
- [Kollabe](https://kollabe.com/standups) -- AI-generated standup summaries highlighting wins/blockers/focus
- [Spinach AI](https://www.spinach.ai/) -- Meeting AI with Jira auto-linking, stakeholder reports
- [Status Hero](https://runsteady.com/integrations/github/) -- Git+issue activity correlated with manual check-ins
- [Standup.so](https://standup-so.vercel.app/) -- Git commits to standup report (minimal, toy-level)
- [DX Core 4 Engineering Metrics](https://getdx.com/blog/engineering-metrics-top-teams/) -- Speed/Effectiveness/Quality/Business Impact framework, 300+ companies
- [CrewAI Hierarchical Process Issues](https://towardsdatascience.com/why-crewais-manager-worker-architecture-fails-and-how-to-fix-it/) -- Documented delegation failures in manager-worker pattern
- [Async Standup Guide](https://fullscale.io/blog/guide-to-async-daily-standups/) -- Goal-focused alternatives to Yesterday/Today/Blockers
- [Project Status Report Best Practices](https://plane.so/blog/project-status-report-how-to-write-one-and-what-to-include) -- Accomplishments vs activity, blocker formatting
