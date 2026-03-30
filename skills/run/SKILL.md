---
name: run
description: Run a full pipeline for a task. Orchestrates roles through stages (standalone or HOTL-integrated).
---

# AgenTeam Run

Orchestrate a full team pipeline for a task. This is the main entry point
for collaborative AI-assisted development. You are the lead; AgenTeam
dispatches your specialists.

## Process

### 1. Auto-Init Guard

Check for `.agenteam/config.yaml` (or legacy `agenteam.yaml`) in the project root. If missing:
- Create config dir: `mkdir -p .agenteam`
- Copy the template: `cp <plugin-dir>/templates/agenteam.yaml.template .agenteam/config.yaml`
- Set the team name to the project directory name
- Generate agents: `python3 <runtime>/agenteam_rt.py generate`
- Tell the user: "AgenTeam auto-initialized with default roles. Edit `.agenteam/config.yaml` to customize."

### 2. Accept Task

Get the task description from the user. If not provided, ask:
"What task should the team work on?"

### 3. Initialize Run

```bash
python3 <runtime>/agenteam_rt.py init --task "<task description>"
```

Capture the run state (run_id, pipeline_mode, stages).

### 4. Determine Pipeline Mode

Read `pipeline_mode` from the run state:

- **standalone** -> Run the built-in pipeline (step 4)
- **hotl** -> Run the HOTL wrapper pipeline (step 5)
- **dispatch-only** -> Tell the user: "Pipeline is dispatch-only. Use
  `$ateam:assign <role> <task>` to assign tasks to specific roles."
- **auto** -> Check HOTL availability. If available, ask the user:
  "HOTL detected. Run with HOTL integration? (yes/no)". If yes, use HOTL
  mode. If no, use standalone mode.

### 5. Standalone Pipeline

Iterate through each stage in order:

```
For each stage in [design, plan, implement, test, review]:

  a. Get dispatch plan:
     python3 <runtime>/agenteam_rt.py dispatch <stage> \
       --task "<task>" --run-id <run_id>

  b. Read the dispatch plan (JSON):
     - dispatch: list of roles to launch
     - blocked: roles waiting for write lock
     - gate: human or auto

  c. Launch agents:
     - For each role in dispatch list:
       - If mode is "read": launch as Codex subagent (can run in parallel
         with other readers)
       - If mode is "write": launch as Codex subagent (serial by default)
     - The agent file is at the path in the dispatch plan (e.g.,
       .codex/agents/architect.toml)
     - Pass the task description and any outputs from previous stages
       as context to the agent

  d. Collect outputs:
     - Gather each role's output
     - Store as context for subsequent stages

  e. Gate check:
     - If gate is "human": pause and show the user a summary of the
       stage output. Ask: "Approve this stage? (yes/no/details)"
     - If gate is "auto": continue to next stage

  f. Handoff:
     - Pass the collected outputs as context to the next stage
     - Design output feeds into plan stage
     - Plan output feeds into implement stage
     - Implement output feeds into test stage
     - All outputs feed into review stage
```

### 6. HOTL Wrapper Pipeline

When pipeline mode is `hotl`, AgenTeam acts as the outer orchestrator
and composes HOTL skills for each stage:

```
a. DESIGN STAGE:
   - Resolve roles: agenteam-rt dispatch design -> {architect}
   - Invoke HOTL brainstorming skill with architect's system instructions
     injected as context
   - HOTL drives the design conversation
   - Collect design output

b. PLAN STAGE:
   - Resolve roles: agenteam-rt dispatch plan -> {architect}
   - Invoke HOTL writing-plans skill
   - HOTL generates the workflow file
   - Gate: human approval of the plan

c. IMPLEMENT + TEST STAGE:
   - Resolve roles: agenteam-rt dispatch implement -> {dev}
   - Resolve roles: agenteam-rt dispatch test -> {qa}
   - Invoke HOTL loop-execution or subagent-execution
   - HOTL executes workflow steps
   - Implementer and qa agents are the workers
   - Write policy enforced: serial by default

d. REVIEW STAGE:
   - Resolve roles: agenteam-rt dispatch review -> {reviewer}
   - Invoke HOTL code-review skill with reviewer agent
   - Gate: human approval
```

**Key principle:** AgenTeam manages role selection and write policy
between phases. HOTL manages execution within each phase. AgenTeam
never modifies HOTL internals.

### 7. Completion

After all stages complete:
- Show a summary of what each role produced
- Show the final state: `python3 <runtime>/agenteam_rt.py status`
- Suggest next steps (commit, create PR, etc.)

## Error Handling

- If a stage fails, stop the pipeline and show the error
- If a role agent fails, report which role failed and at what stage
- If write policy blocks a role, show the block reason and wait
- If HOTL is configured but not available, fall back to standalone
  with a warning

## Runtime Path Resolution

Resolve the AgenTeam runtime:
1. If running from the plugin directory: `./runtime/agenteam_rt.py`
2. If installed as a Codex plugin: `<plugin-install-path>/runtime/agenteam_rt.py`
