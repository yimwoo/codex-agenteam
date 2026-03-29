#!/usr/bin/env bats
# Smoke tests for codex-agenteam (AgenTeam) plugin structure

PLUGIN_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"

# -----------------------------------------------------------------------
# Plugin manifest
# -----------------------------------------------------------------------

@test "plugin.json exists and is valid JSON" {
  run python3 -c "import json; json.load(open('$PLUGIN_DIR/.codex-plugin/plugin.json'))"
  [ "$status" -eq 0 ]
}

@test "plugin.json has required fields" {
  run python3 -c "
import json
d = json.load(open('$PLUGIN_DIR/.codex-plugin/plugin.json'))
assert 'name' in d, 'missing name'
assert 'version' in d, 'missing version'
assert 'skills' in d, 'missing skills'
print('OK')
"
  [ "$status" -eq 0 ]
}

# -----------------------------------------------------------------------
# Skills
# -----------------------------------------------------------------------

@test "using-agenteam SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/using-agenteam/SKILL.md" ]
}

@test "ateam-init SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-init/SKILL.md" ]
}

@test "ateam-run SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-run/SKILL.md" ]
}

@test "ateam-assign SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-assign/SKILL.md" ]
}

@test "ateam-status SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-status/SKILL.md" ]
}

@test "ateam-add-role SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-add-role/SKILL.md" ]
}

@test "ateam-generate SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/ateam-generate/SKILL.md" ]
}

# -----------------------------------------------------------------------
# Role templates
# -----------------------------------------------------------------------

@test "architect.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/architect.yaml'))"
  [ "$status" -eq 0 ]
}

@test "implementer.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/implementer.yaml'))"
  [ "$status" -eq 0 ]
}

@test "reviewer.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/reviewer.yaml'))"
  [ "$status" -eq 0 ]
}

@test "test-writer.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/test-writer.yaml'))"
  [ "$status" -eq 0 ]
}

# -----------------------------------------------------------------------
# Config template
# -----------------------------------------------------------------------

@test "agenteam.yaml.template exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/templates/agenteam.yaml.template'))"
  [ "$status" -eq 0 ]
}

# -----------------------------------------------------------------------
# Runtime
# -----------------------------------------------------------------------

@test "agenteam_rt.py --help returns 0" {
  run python3 "$PLUGIN_DIR/runtime/agenteam_rt.py" --help
  [ "$status" -eq 0 ]
}

@test "requirements.txt exists" {
  [ -f "$PLUGIN_DIR/runtime/requirements.txt" ]
}
