"""Prompt-contract tests for AgenTeam skills."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_skill(path: str) -> str:
    return (ROOT / path).read_text()


def test_using_ateam_auto_init_continues_original_request():
    text = read_skill("skills/using-ateam/SKILL.md")
    assert "continue to Step 2 and route the original request in the same turn" in text
    assert "Do not stop after setup." in text
    assert "Do not run `init --task` during team setup" in text
    assert 'if [ -d "$PLUGIN_DIR/local" ]; then PLUGIN_DIR="$PLUGIN_DIR/local"; fi' in text
    assert "If Step 1 already handled a first-time team-setup request, do not invoke" in text


def test_using_ateam_routes_build_project_requests_to_run():
    text = read_skill("skills/using-ateam/SKILL.md")
    assert '"build a new project called X"' in text
    assert "| `$ateam:run` |" in text


def test_run_skill_requires_real_dispatch_and_full_pipeline():
    text = read_skill("skills/run/SKILL.md")
    assert "Creating the run state is bookkeeping only." in text
    assert "research -> strategy -> design -> plan -> implement -> test -> review" in text
    assert "You must launch actual Codex subagents." in text
    assert "Do not mark the run complete after `implement`." in text


def test_run_skill_requires_dynamic_role_context_injection():
    text = read_skill("skills/run/SKILL.md")
    assert "Build a role-context block" in text
    assert "verify-plan" in text
    assert "roles show <role>" in text
    assert "handoff_contract" in text


def test_run_skill_requires_hotl_aware_artifact_discovery():
    text = read_skill("skills/run/SKILL.md")
    assert "artifact-paths" in text
    assert "Do NOT hardcode directory paths" in text


def test_researcher_role_has_citation_format():
    text = (ROOT / "roles" / "researcher.yaml").read_text()
    assert "Citation Format" in text
    assert "[Title](URL)" in text


def test_assign_skill_passes_handoff_and_role_context():
    text = read_skill("skills/assign/SKILL.md")
    assert "roles show <role-name>" in text
    assert "handoff" in text


def test_init_skill_prefers_validate_over_dummy_init():
    text = read_skill("skills/init/SKILL.md")
    assert "python3 <plugin-dir>/runtime/agenteam_rt.py validate" in text
    assert "python3 <plugin-dir>/runtime/agenteam_rt.py --help" in text
    assert "Do not create a dummy run just to validate config." in text


def test_status_and_standup_docs_use_current_role_names():
    status_text = read_skill("skills/status/SKILL.md")
    standup_text = read_skill("skills/standup/SKILL.md")
    assert "dev" in status_text
    assert "implement" in status_text
    assert "review" in status_text
    assert "implementer" not in status_text
    assert "test_writer" not in status_text
    assert "test-writer" not in status_text
    assert "| dev |" in standup_text
    assert "| qa |" in standup_text
    assert "| reviewer |" in standup_text
    assert "implementer" not in standup_text
    assert "test_writer" not in standup_text
    assert "test-writer" not in standup_text


def test_ci_repair_skill_has_required_elements():
    text = read_skill("skills/ci-repair/SKILL.md")
    # Commit-keyed run selection (not branch-keyed)
    assert "headRefOid" in text
    # Safe git model with baseline
    assert "REPAIR_BASELINE" in text
    # Verify before push
    assert "final-verify-plan" in text
    # Failure log fetching
    assert "log-failed" in text
    # Git safety preflight
    assert "git-isolate" in text or "preflight" in text
    # HOTL adapter NOT used for standalone repair
    assert "hotl-skills" not in text or "NOT used" in text
