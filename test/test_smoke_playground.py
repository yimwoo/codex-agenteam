"""Tests for the standalone smoke playground runner."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "smoke_playground.py"
TEMPLATE = ROOT / "templates" / "agenteam.yaml.template"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_smoke_runner_creates_fallback_playground_and_succeeds():
    result = run_script("--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["used_fallback_playground"] is True
    assert payload["generated_agents"] >= 6
    assert "researcher" in payload["roles"]
    assert payload["verify_command"] == "npm test"


def test_smoke_runner_can_target_existing_project(tmp_path):
    project = tmp_path / "demo-project"
    project.mkdir()
    (project / ".agenteam").mkdir()
    (project / ".agenteam" / "config.yaml").write_text(TEMPLATE.read_text())
    (project / "package.json").write_text(
        json.dumps(
            {
                "name": "demo-project",
                "private": True,
                "scripts": {"test": "node -e \"console.log('ok')\""},
            },
            indent=2,
        )
        + "\n"
    )

    result = run_script("--project", str(project), "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["used_fallback_playground"] is False
    assert payload["project_dir"] == str(project.resolve())
