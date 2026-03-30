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


def test_init_skill_prefers_validate_over_dummy_init():
    text = read_skill("skills/init/SKILL.md")
    assert "python3 <plugin-dir>/runtime/agenteam_rt.py validate" in text
    assert "python3 <plugin-dir>/runtime/agenteam_rt.py --help" in text
    assert "Do not create a dummy run just to validate config." in text
