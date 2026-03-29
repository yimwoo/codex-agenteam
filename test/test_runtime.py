"""Unit tests for agenteam_rt.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Add runtime to path
RUNTIME = Path(__file__).resolve().parent.parent / "runtime" / "agenteam_rt.py"
ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "agenteam.yaml.template"


def run_rt(*args, cwd=None) -> subprocess.CompletedProcess:
    """Run agenteam-rt with given args."""
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
    )


def make_config(tmp_path: Path, overrides: dict | None = None) -> Path:
    """Create a agenteam.yaml in tmp_path from template, with optional overrides."""
    with open(TEMPLATE) as f:
        config = yaml.safe_load(f)
    if overrides:
        config.update(overrides)
    config_path = tmp_path / "agenteam.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


# ---------------------------------------------------------------------------
# Config loading & validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    def test_valid_config(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "architect" in roles

    def test_missing_config(self, tmp_path):
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0

    def test_invalid_pipeline_mode(self, tmp_path):
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "invalid", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "Invalid pipeline" in r.stderr

    def test_invalid_write_mode(self, tmp_path):
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "invalid"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "Invalid parallel_writes.mode" in r.stderr

    def test_missing_version(self, tmp_path):
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "version" in r.stderr


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

class TestRoleResolution:
    def test_default_roles_loaded(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "researcher" in roles
        assert "pm" in roles
        assert "architect" in roles
        assert "implementer" in roles
        assert "reviewer" in roles
        assert "test_writer" in roles

    def test_role_override(self, tmp_path):
        make_config(tmp_path)
        # Add a model override for architect
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["roles"]["architect"]["model"] = "o4-mini"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("roles", "show", "architect", cwd=str(tmp_path))
        assert r.returncode == 0
        role = json.loads(r.stdout)
        assert role["model"] == "o4-mini"
        # Original fields should still be present
        assert "design" in role["participates_in"]

    def test_custom_role(self, tmp_path):
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": {
                "security_auditor": {
                    "description": "Security reviewer",
                    "participates_in": ["review"],
                    "can_write": False,
                    "parallel_safe": True,
                }
            },
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "security_auditor" in roles

    def test_show_nonexistent_role(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("roles", "show", "nonexistent", cwd=str(tmp_path))
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# TOML generation
# ---------------------------------------------------------------------------

class TestTomlGeneration:
    def test_generates_all_roles(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("generate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["generated"]) == 6  # 6 built-in roles

        agents_dir = tmp_path / ".codex" / "agents"
        assert (agents_dir / "architect.toml").exists()
        assert (agents_dir / "implementer.toml").exists()
        assert (agents_dir / "reviewer.toml").exists()
        assert (agents_dir / "test_writer.toml").exists()

    def test_toml_has_flat_structure(self, tmp_path):
        import toml as toml_lib

        make_config(tmp_path)
        run_rt("generate", cwd=str(tmp_path))

        agent = toml_lib.load(str(tmp_path / ".codex" / "agents" / "architect.toml"))
        assert agent["name"] == "architect"
        assert "developer_instructions" in agent
        assert isinstance(agent["developer_instructions"], str)
        # Should be flat — no nested [config] or [developer_instructions] tables
        assert "description" in agent

    def test_toml_includes_model_fields(self, tmp_path):
        import toml as toml_lib

        make_config(tmp_path)
        run_rt("generate", cwd=str(tmp_path))

        agent = toml_lib.load(str(tmp_path / ".codex" / "agents" / "architect.toml"))
        assert agent.get("model") == "o3"
        assert agent.get("model_reasoning_effort") == "high"
        assert agent.get("sandbox_mode") == "workspace-write"

    def test_custom_role_generates_toml(self, tmp_path):
        import toml as toml_lib

        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": {
                "security_auditor": {
                    "description": "Security reviewer",
                    "participates_in": ["review"],
                    "can_write": False,
                    "model": "o3",
                    "system_instructions": "You are a security auditor.",
                }
            },
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("generate", cwd=str(tmp_path))
        assert r.returncode == 0

        agent_path = tmp_path / ".codex" / "agents" / "security_auditor.toml"
        assert agent_path.exists()
        agent = toml_lib.load(str(agent_path))
        assert agent["name"] == "security_auditor"


# ---------------------------------------------------------------------------
# Init & state
# ---------------------------------------------------------------------------

class TestInitAndState:
    def test_init_creates_state(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "test task", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert "run_id" in state
        assert state["task"] == "test task"
        assert state["stages"]["design"]["status"] == "pending"
        assert state["stages"]["implement"]["status"] == "pending"

        # State file should exist
        state_dir = tmp_path / ".agenteam" / "state"
        assert state_dir.exists()
        state_files = list(state_dir.glob("*.json"))
        assert len(state_files) == 1

    def test_status_returns_latest(self, tmp_path):
        make_config(tmp_path)
        run_rt("init", "--task", "task 1", cwd=str(tmp_path))
        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["task"] == "task 1"

    def test_status_no_runs(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_dispatch_implement(self, tmp_path):
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        run_id = json.loads(init_r.stdout)["run_id"]

        r = run_rt("dispatch", "implement", "--task", "test", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["stage"] == "implement"
        assert plan["policy"] == "serial"
        assert len(plan["dispatch"]) > 0
        assert plan["dispatch"][0]["role"] == "implementer"
        assert plan["dispatch"][0]["mode"] == "write"

    def test_dispatch_review_readonly(self, tmp_path):
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        run_id = json.loads(init_r.stdout)["run_id"]

        r = run_rt("dispatch", "review", "--task", "test", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["stage"] == "review"
        for entry in plan["dispatch"]:
            assert entry["mode"] == "read"

    def test_dispatch_nonexistent_stage(self, tmp_path):
        make_config(tmp_path)
        run_rt("init", "--task", "test", cwd=str(tmp_path))
        r = run_rt("dispatch", "nonexistent", "--task", "test", cwd=str(tmp_path))
        assert r.returncode != 0

    def test_serial_policy_blocks_second_writer(self, tmp_path):
        """When a write lock is active, additional writers should be blocked."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        state = json.loads(init_r.stdout)
        run_id = state["run_id"]

        # Simulate active write lock by modifying state
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        state["write_locks"]["active"] = "other_writer"
        with open(state_path, "w") as f:
            json.dump(state, f)

        r = run_rt("dispatch", "implement", "--task", "test", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        # implementer should be blocked because another writer holds the lock
        assert len(plan["blocked"]) > 0
        assert plan["blocked"][0]["role"] == "implementer"


# ---------------------------------------------------------------------------
# Policy check
# ---------------------------------------------------------------------------

class TestPolicyCheck:
    def test_no_overlaps(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("policy", "check", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["safe_for_parallel"] is True

    def test_detects_overlap(self, tmp_path):
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "scoped"}},
            "roles": {
                "writer_a": {"can_write": True, "write_scope": ["src/**"]},
                "writer_b": {"can_write": True, "write_scope": ["src/**", "lib/**"]},
            },
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("policy", "check", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["safe_for_parallel"] is False
        assert len(result["overlaps"]) > 0


# ---------------------------------------------------------------------------
# HOTL detection
# ---------------------------------------------------------------------------

class TestHotlDetection:
    def test_hotl_check_returns_json(self):
        r = run_rt("hotl", "check")
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "available" in result
        assert "path" in result
