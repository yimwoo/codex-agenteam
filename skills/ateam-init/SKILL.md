---
name: ateam-init
description: Initialize AgenTeam config for a project. Creates agenteam.yaml and generates .codex/agents/*.toml.
---

# AgenTeam Init

Set up AgenTeam for the current project.

## Process

### 1. Check Prerequisites

Verify Python 3.8+ is available:
```bash
python3 --version
```

Check for required dependencies:
```bash
python3 -c "import yaml; import toml; print('OK')"
```

If dependencies are missing, offer to install:
```bash
pip install pyyaml toml
```

### 2. Check for Existing Config

Look for `agenteam.yaml` in the project root.

- **If exists:** Ask the user if they want to reconfigure or keep existing config.
  If keeping, skip to step 4.
- **If absent:** Continue to step 3.

### 3. Create Config

Copy the template and prompt for customization:

```bash
cp <plugin-dir>/templates/agenteam.yaml.template agenteam.yaml
```

Ask the user (one question at a time):

1. **Team name:** "What should I name this team?" (default: project directory name)
2. **Pipeline mode:**
   - `standalone` — Built-in pipeline (design -> plan -> implement -> test -> review)
   - `hotl` — Integrate with HOTL plugin for structured workflows
   - `dispatch-only` — No pipeline, dispatch roles ad-hoc
3. **Write scope customization:** "Do the default write scopes work?
   (implementer: src/**, lib/** | test_writer: tests/**, *.test.*)"
4. **Custom roles:** "Do you want to add any custom roles? (e.g., security_auditor, docs_writer)"

Update `agenteam.yaml` with the user's choices.

### 4. Validate Config

```bash
python3 <plugin-dir>/runtime/agenteam_rt.py init --task "team initialization"
```

If validation fails, show the error and help the user fix it.

### 5. Generate Agents

```bash
python3 <plugin-dir>/runtime/agenteam_rt.py generate
```

This creates `.codex/agents/*.toml` for each role. Show the user what was generated.

### 6. HOTL Detection

```bash
python3 <plugin-dir>/runtime/agenteam_rt.py hotl check
```

If HOTL is available and pipeline is not already set to `hotl`:
- Inform the user: "HOTL plugin detected. You can set `pipeline: hotl` in
  agenteam.yaml to integrate with HOTL workflows."
- Do not change the config automatically.

### 7. Summary

Show:
- Config file location
- Generated agent files
- Available skills (`$ateam-run`, `$ateam-assign`, etc.)
- Next step suggestion: "Run `$ateam-run` to start a task with your team."

## Runtime Path Resolution

Resolve the AgenTeam runtime:
1. If running from the plugin directory: `./runtime/agenteam_rt.py`
2. If installed as a Codex plugin: `<plugin-install-path>/runtime/agenteam_rt.py`
