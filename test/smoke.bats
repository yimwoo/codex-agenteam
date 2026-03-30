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

@test "using-ateam SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/using-ateam/SKILL.md" ]
}

@test "init SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/init/SKILL.md" ]
}

@test "run SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/run/SKILL.md" ]
}

@test "assign SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/assign/SKILL.md" ]
}

@test "status SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/status/SKILL.md" ]
}

@test "add-member SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/add-member/SKILL.md" ]
}

@test "generate SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/generate/SKILL.md" ]
}

@test "standup SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/standup/SKILL.md" ]
}

@test "deepdive SKILL.md exists and is non-empty" {
  [ -s "$PLUGIN_DIR/skills/deepdive/SKILL.md" ]
}

# -----------------------------------------------------------------------
# Role templates
# -----------------------------------------------------------------------

@test "researcher.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/researcher.yaml'))"
  [ "$status" -eq 0 ]
}

@test "pm.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/pm.yaml'))"
  [ "$status" -eq 0 ]
}

@test "architect.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/architect.yaml'))"
  [ "$status" -eq 0 ]
}

@test "dev.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/dev.yaml'))"
  [ "$status" -eq 0 ]
}

@test "reviewer.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/reviewer.yaml'))"
  [ "$status" -eq 0 ]
}

@test "qa.yaml exists and is valid YAML" {
  run python3 -c "import yaml; yaml.safe_load(open('$PLUGIN_DIR/roles/qa.yaml'))"
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

@test "git-isolate.sh exists and is executable" {
  [ -x "$PLUGIN_DIR/scripts/git-isolate.sh" ]
}

@test "git-isolate.sh --help prints usage" {
  run bash "$PLUGIN_DIR/scripts/git-isolate.sh" invalid-cmd
  [ "$status" -ne 0 ]
}

@test "verify-stage.sh exists and is executable" {
  [ -x "$PLUGIN_DIR/scripts/verify-stage.sh" ]
}

@test "verify-stage.sh without args prints usage" {
  run bash "$PLUGIN_DIR/scripts/verify-stage.sh" invalid-cmd
  [ "$status" -ne 0 ]
}

@test "update.sh --local refreshes Codex plugin cache" {
  local tmp_home
  tmp_home="$(mktemp -d "${BATS_TEST_TMPDIR}/ateam-update-home.XXXXXX")"
  local cache_dir="$tmp_home/.codex/plugins/cache/codex-plugins/ateam/stable"

  mkdir -p "$cache_dir"
  echo "stale" > "$cache_dir/OLD_MARKER.txt"

  run env HOME="$tmp_home" bash "$PLUGIN_DIR/update.sh" --local
  [ "$status" -eq 0 ]
  [ -f "$cache_dir/.codex-plugin/plugin.json" ]
  [ ! -e "$cache_dir/OLD_MARKER.txt" ]
}

@test "smoke_playground.py fallback smoke test passes" {
  run python3 "$PLUGIN_DIR/scripts/smoke_playground.py" --json
  [ "$status" -eq 0 ]
}
