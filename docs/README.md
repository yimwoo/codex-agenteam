# Documentation Layout

This directory contains AgenTeam's public product references and its durable
design, decision, planning, review, prompt, and release-requirement documents.
This file is the tracked contributor map for deciding where new documentation
belongs.

Any human or AI contributor working on product or roadmap changes in this repo
should read this file first to understand:

- where new documentation belongs
- which workflow to use for major initiatives vs small changes
- which parts of the process are repo-specific documentation practice versus
  shipped AgenTeam product behavior

## Scope Of This Taxonomy

The internal-document taxonomy applies to **new work starting from 2026-04-14
onward**. Top-level product references such as setup, configuration, pipeline,
CLI, and HOTL documentation evolve with the shipped product.

Existing documents under `docs/plans/`, `docs/designs/`, `docs/research/`, and
other current locations stay where they are. Do not migrate old documents just
to fit this layout. This file governs what gets created next.

## Important Boundary

This documentation workflow is for **how we build AgenTeam in this repo**.
It is **not** the same thing as AgenTeam's current shipped runtime model.

AgenTeam's shipped product combines Codex-native roles and a configurable
run/stage executor with optional HOTL integration, governed-delivery controls,
diagnostic trace and evidence, benchmark conversion, compatibility checks, and
workspace-agent export. The repo may still use richer documentation and
planning practices for major work than the plugin enforces for users.

That means:

- use the fuller process for major roadmap items and design-doc-driven work
- use a lighter process for bugs, spikes, POCs, and small feature changes
- treat HOTL-specific steps as optional unless the initiative explicitly uses
  HOTL workflows

## Directory Layout

```text
docs/
├── README.md              ← this file
├── setup.md               ← installation, update, and compatibility checks
├── configuration.md       ← roles, profiles, model routing, and governance
├── pipeline.md            ← execution, verification, evidence, and handoffs
├── cli.md                 ← skills and runtime command reference
├── hotl.md                ← optional HOTL integration
├── designs/               ← strategic, multi-phase architecture docs
├── decisions/             ← ADRs and decision log
├── requirements/          ← release or phase requirements
├── plans/                 ← tactical design and execution plans
├── reviews/               ← review memos and triage memos
├── prompts/               ← reusable templates and playbooks
├── specs/                 ← structured reference specs and fixtures
├── strategies/            ← cross-cutting strategy notes and roadmap
├── research/              ← exploratory artifacts and landscape research
├── meetings/              ← meeting notes and summaries
└── ui/                    ← UI mocks and wireframes
```

Some directories may be created only when first needed. The taxonomy is the
target structure for new work, not a requirement that every folder already
exist.

Reproducible benchmark methodology, the core task suite, and sample fixtures
live under [`benchmarks/`](../benchmarks/README.md) so the guide and its inputs
remain versioned together.

## Directory Meanings

### `designs/`

Strategic, durable, multi-phase architecture documents.

Use this for:

- major initiative architecture
- long-lived system design
- cross-phase feature design

These are the "why and where we are going" documents. They change slowly and
are usually rewritten thoughtfully rather than patched casually.

Conventions:

- one primary design doc per major initiative
- descriptive filenames are preferred over dated names when the document is
  meant to remain the canonical reference
- design docs are human-approved, even if agents help draft them

### `decisions/`

Architecture Decision Records and the append-only decision log.

Use this for:

- ADRs that record expensive-to-reverse technical decisions
- `log.md` or equivalent projection of short autonomous or escalated decisions

Conventions:

- ADRs are numbered sequentially, for example `001-...`, `002-...`
- accepted ADRs are not edited in place to change history; a new ADR should
  supersede an older one when needed
- one ADR should capture one real decision, not a bundle of loosely related
  sub-decisions

Rule of thumb:

- if the decision is easy to reverse, it probably does not need an ADR
- if the rationale keeps getting repeated, it probably does

### `requirements/`

Requirements documents for releases, initiatives, or major phases.

Use this for:

- release requirements
- phase-scoped PM requirements
- user-visible acceptance and non-goals

Typical contents:

- target users and personas
- user stories
- acceptance criteria
- non-goals
- exit or release gate

For major work, requirements are the input to plan documents.

For small work, a full requirements document is optional.

### `plans/`

Tactical design and execution plans.

Use this for:

- phase plans
- implementation plans
- scoped design plans for a release

Typical contents:

- intent
- scope and non-scope
- verification plan
- governance or approval notes
- sequencing and rollout

Plans are more transient than `designs/`, but more durable than chat output.

### `reviews/`

Review memos, kickoff reviews, plan reviews, and triage memos.

Use this for:

- structured review findings
- kickoff review outputs
- plan review outputs
- triage decisions that accept, defer, or reject findings

These are audit-friendly but usually less durable than design docs or ADRs.

### `prompts/`

Reusable templates and playbooks.

Use this for:

- initiative playbooks
- review templates
- design-doc templates
- plan templates
- operating-model references

Conventions:

- prompt templates should stay agent-neutral
- playbooks may be initiative-specific
- shared templates should not hardcode one agent/tool unless the file is
  explicitly tool-specific

### `specs/`

Structured specification artifacts, fixtures, or reference materials that are
not best represented as narrative design docs.

Use this for:

- YAML specs
- reference PDFs
- structured input/output examples

### `strategies/`

Cross-cutting product or engineering strategy notes.

Use this for:

- roadmap documents
- rollout strategy
- testing strategy
- adoption strategy

### `research/`

Exploratory artifacts and landscape analysis.

Use this for:

- competitive research
- tool comparisons
- ecosystem scans
- early exploration before design stabilizes

### `meetings/`

Meeting notes, working sessions, and standups that are worth preserving.

### `ui/`

UI mocks, wireframes, and other interface artifacts.

## Which Workflow To Use

There are two valid workflows in this repo.

## Workflow A: Major Initiative / Major Feature

Use this for:

- strategic features
- design-doc-driven initiatives
- multi-session or multi-phase work
- releases with new governance or architecture surfaces

Recommended flow:

```text
designs/ → kickoff review → triage → doc fixes and ADRs → requirements/ → optional brainstorming → plans/ → plan review → execution
```

Step-by-step:

1. Confirm the relevant `designs/` baseline exists and is internally
   consistent.
2. Write a kickoff review memo in `reviews/`.
3. Write a triage memo in `reviews/` that accepts, defers, or rejects findings.
4. Split accepted findings into:
   - doc fixes to existing docs
   - new ADRs in `decisions/` when a real decision must be recorded
5. Write a requirements document in `requirements/`.
6. Run brainstorming only if there is a real open design question.
7. Write a plan document in `plans/`.
8. Review the plan in `reviews/`.
9. Execute from the approved plan.

Notes:

- HOTL brainstorming and `hotl write-plan` are allowed, but not mandatory for
  every initiative
- for major work, requirements-before-plan is the preferred pattern

## Workflow B: Small Change / Bug / POC

Use this for:

- bug fixes
- small refactors
- spikes
- prototypes
- low-risk docs or config changes

Recommended flow:

```text
brief context note or issue → optional plan note → implementation → review if needed
```

For this workflow:

- a full requirements doc is usually unnecessary
- a new ADR is usually unnecessary
- a full kickoff review / triage cycle is usually unnecessary
- keep documentation proportional to the change

The goal is to preserve AgenTeam's lightweight usability for small work.

## Conventions

- Do not conflate doc fixes and ADRs.
- Use dated filenames for transient artifacts such as reviews, meetings, and
  many plans.
- Use stable descriptive filenames for durable artifacts such as canonical
  design docs, ADRs, and shared prompt templates.
- Keep prompt templates agent-neutral unless a file is explicitly tool-specific.
- One ADR should capture one real decision whenever possible.
- Major work should prefer requirements before detailed planning.
- Small work should prefer minimal ceremony.

## Relationship To The Product Roadmap

This taxonomy is intentionally ahead of some current AgenTeam runtime
capabilities.

That is acceptable.

We may use stronger documentation discipline inside this repo than the plugin
currently enforces for end users. When adding new product features, prefer to
lift proven pieces of this process into the roadmap gradually rather than
assuming the full workflow is already part of the shipped product.

Examples of process elements that may inform the roadmap:

- decision log conventions
- requirements documents for major work
- review and triage memo patterns
- playbook structure
- minimal phase/checkpoint vocabulary

## Practical Rule

If the work is large enough that multiple people or multiple agent sessions
could lose context, use the major-initiative workflow.

If the work is small enough that a short plan and one execution path are
enough, use the lightweight workflow.
