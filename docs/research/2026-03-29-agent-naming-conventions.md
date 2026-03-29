# Research: Human Names vs Functional Names for AI Agent Roles

**Date**: 2026-03-29
**Triggered by**: Design decision on whether AgenTeam roles should use human persona names (e.g., "Alice the Architect") or functional role names (e.g., "architect")
**Relevance**: AgenTeam currently uses functional role names (architect, implementer, reviewer, test-writer). This research evaluates whether adding human personas would improve adoption and usability.

## Key Findings

### Finding 1: The Industry Overwhelmingly Uses Functional Role Names for Developer Tools

Every major multi-agent framework targeting software development uses functional/professional role names as the primary identifier. No mainstream framework defaults to human personal names for developer-facing agents.

**CrewAI** -- the most popular multi-agent orchestration framework -- uses identifiers like `researcher`, `reporting_analyst`, and role descriptions like "Senior Data Researcher". The documentation explicitly states: "The names you use in your YAML files should match the method names in your Python code." All examples use functional descriptors, never personal names. ([CrewAI Docs](https://docs.crewai.com/en/concepts/agents))

**ChatDev** assigns corporate title roles: CEO, CTO, CPO, Programmer, Tester, Reviewer. These are organizational function titles, not personal names. The paper explicitly describes agents as role-instantiated through system prompts defining professional function. ([ChatDev paper](https://arxiv.org/html/2307.07924v5))

**LangGraph** uses snake_case functional names (`recipe_expert`, `math_expert`, `weather_expert`) and explicitly notes that some model providers reject names with spaces or special characters, making functional identifiers a practical necessity. ([LangGraph docs](https://www.langchain.com/langgraph))

**OpenAI Agents SDK** (successor to Swarm) uses simple descriptive names: `Agent(name="Assistant")`. No persona conventions. ([OpenAI Agents SDK](https://openai.github.io/openai-agents-python/agents/))

**Claude Code subagents ecosystem** -- the 100+ agent collection at VoltAgent/awesome-claude-code-subagents uses exclusively functional names: `backend-developer`, `code-reviewer`, `security-auditor`, `kubernetes-specialist`. Zero human names. ([VoltAgent collection](https://github.com/VoltAgent/awesome-claude-code-subagents))

**The agentic-dev-team project** (Claude Code team plugin, direct competitor) uses: Software Engineer, Architect, Product Manager, Security Engineer, QA Engineer, etc. All functional. ([bdfinst/agentic-dev-team](https://github.com/bdfinst/agentic-dev-team))

### Finding 2: MetaGPT Is the Exception -- and It Is Instructive

MetaGPT is the only major framework that assigns human names to agents. In their tutorials, `Alice` is the SimpleCoder, `Bob` is the SimpleTester, `Charlie` is the SimpleReviewer. The code uses a dual-naming system:

```python
name: str = "Alice"
profile: str = "SimpleCoder"
```

However, this appears to be a **tutorial convention** for readability, not a production recommendation. In MetaGPT's actual software company simulation, agents are referenced by role: Product Manager, Architect, Project Manager, Engineer. The human names appear only in getting-started examples to make multi-agent message passing easier to follow visually. ([MetaGPT docs](https://github.com/geekan/MetaGPT-docs/blob/main/src/en/guide/tutorials/multi_agent_101.md))

This is a key distinction: human names served **pedagogical clarity** (distinguishing "which agent said what" in chat logs), not UX preference.

### Finding 3: UX Research Shows Context-Dependent Effects, with B2B/Developer Contexts Favoring Functional Names

The evidence on human-named vs functionally-named agents is nuanced and domain-specific:

**Consumer-facing chatbots**: One cited study found chatbots with human-like names received 18% higher engagement rates. Hospitality businesses using human-like names report 23% higher guest satisfaction scores. This is the strongest evidence for human naming. ([SocialIntents](https://www.socialintents.com/blog/chatbot-names/))

**B2B and professional contexts**: Recruitment firms using descriptive names report 31% higher candidate response rates compared to generic or playful names. B2B industries "see better results with functional naming approaches that emphasize capability over personality." ([SocialIntents](https://www.socialintents.com/blog/chatbot-names/))

**Developer tools specifically**: The entire ecosystem (Copilot, Cursor, Devin, Claude Code, Codex) uses functional identifiers. GitHub Copilot Workspace names its agents "Plan Agent", "Brainstorm Agent", "Repair Agent" -- purely functional. Devin is positioned as a "junior engineer on your team" -- a role description, not a persona. ([GitHub Copilot docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent))

**The Shape of AI UX pattern library** identifies four naming categories: persona-based (Claude, Devin), company-branded, functional titles (Copilot, Assistant), and technical labels (AI). It warns: "names that overpromise human qualities can backfire when the system fails to live up to them." ([Shape of AI](https://www.shapeof.ai/patterns/name))

### Finding 4: Anthropomorphization Carries Real Risks in Agentic Contexts

A 2025 PNAS paper by Peter, Riemer, and West coined the term "anthropomorphic seduction" to describe how human-like interaction design creates false trust. Key findings:

- Users disclosed more personal information to human-named chatbots -- this is listed as both a benefit (engagement) and a **danger** (false trust leading to over-disclosure).
- When users cannot distinguish AI from human interlocutors, "threats emerge of deception, manipulation, and disinformation at scale."
- The researchers explicitly warn about the gap between perceived and actual capabilities when agents present as human-like.

([PNAS: Benefits and dangers of anthropomorphic agents](https://www.pnas.org/doi/10.1073/pnas.2415898122))

For a developer tool like AgenTeam, anthropomorphization is particularly risky because:
1. Agents make architectural decisions and write code. Users need to maintain appropriate skepticism.
2. A human-named agent that produces bad code creates a different failure mode than a functionally-named one -- users may be slower to question "Alice's" output than "the architect's" output.
3. Developers are a skeptical audience; perceived gimmickry hurts credibility.

### Finding 5: Cultural Bias in Name Selection Is a Real and Documented Problem

Research from the University of Washington shows AI systems exhibit significant bias based on names, with names perceived as belonging to certain racial or gender groups receiving systematically different treatment. ([UW study on AI bias](https://www.washington.edu/news/2024/10/31/ai-bias-resume-screening-race-gender/))

Western names dominate AI systems due to training data biases. Any set of human names chosen for agent personas would inevitably signal cultural assumptions. "Alice", "Bob", "Charlie" are Western/anglophone defaults. Using names from other cultures risks tokenism; using no culture-specific names requires invented names that feel artificial.

Functional names (architect, reviewer) are culturally neutral by nature.

### Finding 6: The Middle Ground -- User-Configurable Display Names -- Exists but Is Rarely Used

Enterprise platforms (Microsoft Dynamics, Zendesk, Genesys) support "agent alias" or "display name" configurations that let organizations customize what end-users see. A 2025 study in the Journal of Applied Behavioral Sciences found that naming AI agents increased users' sense of "psychological ownership." ([Taskade](https://help.taskade.com/en/articles/8958457-custom-ai-agents-the-intelligence-pillar))

However, in developer-facing multi-agent tools, no framework implements user-configurable display names as a feature. The pattern exists in customer service tooling, not in coding agents.

CrewAI does support a `backstory` field that enriches the agent persona (e.g., "10 years of experience in data science") without changing the functional name -- this is persona enrichment without human naming. ([CrewAI personas](https://docs.crewai.com/en/concepts/agents))

## Competitive Landscape

| Project | Naming Approach | Human Names? | Takeaway |
|---------|----------------|--------------|----------|
| **CrewAI** | Functional role + rich backstory | No | Persona depth through backstory, not naming |
| **ChatDev** | Corporate titles (CEO, CTO, Programmer) | No | Org-chart metaphor, still functional |
| **MetaGPT** | Dual: human name + role profile | Yes (tutorials only) | Used for tutorial clarity, not production UX |
| **AutoGen** | User-defined, typically functional | No defaults | Flexible but examples use "Agent A", "Agent B" |
| **OpenAI Agents SDK** | Simple descriptive names | No | Minimalist approach |
| **LangGraph** | snake_case functional | No | Practical: avoids provider name restrictions |
| **Claude Code subagents** | kebab-case functional | No | 100+ agents, all functional |
| **GitHub Copilot** | Functional ("Plan Agent") | No | Major platform validates functional approach |
| **Devin** | Single branded name | N/A (single agent) | Product-level branding, not per-role naming |
| **AgenTeam (ours)** | Functional (architect, implementer) | No | Aligned with industry standard |

## Recommendations

### 1. Keep functional role names as the primary identifiers
**Priority**: High | **Effort**: None (maintain status quo)

The evidence is clear: every developer-facing multi-agent tool uses functional names. AgenTeam's current approach (architect, implementer, reviewer, test-writer) is exactly aligned with industry convention. Switching to human names would be a departure from every comparable tool and would likely hurt credibility with the developer audience.

### 2. Consider adding an optional `display_name` field to role YAML (low priority)
**Priority**: Low | **Effort**: Small

If users want to personalize their team ("call the architect 'Archie'"), support it as an optional override in `agenteam.yaml`:

```yaml
roles:
  architect:
    display_name: "Archie"  # optional, shown in output only
```

This would appear in CLI output and logs but not affect the agent identifier or system behavior. This gives users the personalization option without the project taking a stance on naming. However, there is no evidence this would improve adoption for a developer tool, so it should be treated as a nice-to-have, not a priority.

### 3. Enrich role personas through backstory/instructions, not names
**Priority**: Medium | **Effort**: Small

CrewAI's approach is instructive: their agents have rich `backstory` fields that improve agent behavior without human naming. AgenTeam already has `system_instructions` in role YAML -- this is the right place to invest in persona depth. Consider expanding the `system_instructions` to include experience-level framing and working-style guidance, which CrewAI's research suggests improves output quality:

```yaml
system_instructions: |
  You are the **architect** on an AgenTeam. You bring 15 years of
  systems design experience. You are thorough but pragmatic...
```

This is persona enrichment that improves agent behavior without the downsides of human naming.

### 4. Do NOT default to human names
**Priority**: High (negative recommendation) | **Effort**: N/A

The risks outweigh benefits for this context:
- Cultural bias in any name set chosen
- Anthropomorphization risks in an agentic coding context where appropriate skepticism matters
- Misalignment with every competitor and community convention
- Developer audience is the demographic least receptive to perceived gimmickry

### 5. If logs need disambiguation, use role-prefixed output formatting
**Priority**: Medium | **Effort**: Small

MetaGPT's motivation for human names was log readability. If AgenTeam encounters the same problem (hard to tell which agent said what in output), solve it with formatting:

```
[architect] Proposing approach A: ...
[reviewer]  Found 2 issues in the implementation...
```

This is clearer than human names and matches how developer tools (loggers, CI systems) already work.

## Sources

- [CrewAI Agents Documentation](https://docs.crewai.com/en/concepts/agents) -- Defines functional role naming convention with backstory enrichment
- [ChatDev Paper](https://arxiv.org/html/2307.07924v5) -- Corporate title roles (CEO, CTO, Programmer), no human names
- [MetaGPT Multi-Agent 101](https://github.com/geekan/MetaGPT-docs/blob/main/src/en/guide/tutorials/multi_agent_101.md) -- Only framework using human names, in tutorial context only
- [VoltAgent awesome-claude-code-subagents](https://github.com/VoltAgent/awesome-claude-code-subagents) -- 100+ Claude Code agents, all functional names
- [bdfinst/agentic-dev-team](https://github.com/bdfinst/agentic-dev-team) -- Direct competitor uses functional role names
- [PNAS: Benefits and dangers of anthropomorphic agents](https://www.pnas.org/doi/10.1073/pnas.2415898122) -- "Anthropomorphic seduction" risks in human-like agent design
- [Shape of AI: Name Pattern](https://www.shapeof.ai/patterns/name) -- UX pattern library: warns names overpromising human qualities backfire
- [SocialIntents: Chatbot Names](https://www.socialintents.com/blog/chatbot-names/) -- B2B contexts favor functional names; 31% higher response rate
- [UW AI Bias Study](https://www.washington.edu/news/2024/10/31/ai-bias-resume-screening-race-gender/) -- Documented name-based bias in AI systems
- [GitHub Copilot Coding Agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent) -- Functional naming: "Plan Agent", "Brainstorm Agent"
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/agents/) -- Simple descriptive agent names
- [LangGraph](https://www.langchain.com/langgraph) -- snake_case functional names, practical constraints on naming
- [CrewAI Role-Based Guide (DigitalOcean)](https://www.digitalocean.com/community/tutorials/crewai-crash-course-role-based-agent-orchestration) -- Functional roles with rich persona backstories
- [IBM: Dangers of Anthropomorphizing AI](https://www.ibm.com/think/insights/anthropomorphizing-ai-danger-infosec-perspective) -- InfoSec perspective on anthropomorphization risks
