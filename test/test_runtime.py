"""Unit tests for agenteam_rt.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

# Add runtime to path
RUNTIME = Path(__file__).resolve().parent.parent / "runtime" / "agenteam_rt.py"
ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "agenteam.yaml.template"


def run_rt(*args, cwd=None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run agenteam-rt with given args."""
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
        env={**os.environ, **(env or {})},
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


def make_home_env(tmp_path: Path) -> dict[str, str]:
    """Return an isolated HOME override for subprocess tests."""
    home = tmp_path / "home"
    home.mkdir()
    return {"HOME": str(home)}


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
        assert "Invalid" in r.stderr and "pipeline" in r.stderr

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
        assert "Invalid" in r.stderr and "mode" in r.stderr

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


class TestValidateCommand:
    def test_validate_returns_summary_without_creating_state(self, tmp_path):
        make_config(tmp_path)

        r = run_rt("validate", cwd=str(tmp_path))

        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result == {
            "valid": True,
            "pipeline_mode": "standalone",
            "isolation_mode": "branch",
            "role_count": 6,
            "stage_count": 7,
            "profile_count": 0,
            "errors": [],
            "warnings": [],
        }
        assert not (tmp_path / ".agenteam" / "state").exists()

    def test_validate_preserves_dispatch_only_mode(self, tmp_path):
        make_config(tmp_path, overrides={"team": {"pipeline": "dispatch-only"}})

        r = run_rt("validate", cwd=str(tmp_path))

        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["pipeline_mode"] == "dispatch-only"


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
        assert "dev" in roles
        assert "reviewer" in roles
        assert "qa" in roles

    def test_role_override(self, tmp_path):
        make_config(tmp_path)
        # Add a model override for architect
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config.setdefault("roles", {})
        config["roles"].setdefault("architect", {})
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
        assert (agents_dir / "dev.toml").exists()
        assert (agents_dir / "reviewer.toml").exists()
        assert (agents_dir / "qa.toml").exists()

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

        agent = toml_lib.load(str(tmp_path / ".codex" / "agents" / "dev.toml"))
        assert agent.get("model") == "gpt-5.3-codex"
        assert agent.get("model_reasoning_effort") == "medium"
        assert agent.get("sandbox_mode") == "workspace-write"

    def test_built_in_roles_generate_codex_supported_models(self, tmp_path):
        import toml as toml_lib

        make_config(tmp_path)
        run_rt("generate", cwd=str(tmp_path))

        inherited_roles = {"architect", "pm", "researcher", "reviewer"}
        pinned_roles = {
            "dev": "gpt-5.3-codex",
            "qa": "gpt-5.3-codex",
        }

        for role_name in inherited_roles:
            agent = toml_lib.load(str(tmp_path / ".codex" / "agents" / f"{role_name}.toml"))
            assert "model" not in agent

        for role_name, expected_model in pinned_roles.items():
            agent = toml_lib.load(str(tmp_path / ".codex" / "agents" / f"{role_name}.toml"))
            assert agent.get("model") == expected_model

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
                    "model": "gpt-5.4",
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

    def test_path_traversal_run_id_rejected(self, tmp_path):
        """Run IDs with path traversal characters are rejected."""
        make_config(tmp_path)
        r = run_rt(
            "dispatch", "implement",
            "--run-id", "../../etc/passwd",
            "--task", "test",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Invalid run_id" in r.stderr

    def test_valid_run_id_accepted(self, tmp_path):
        """Normal run IDs with alphanumeric, hyphens, underscores pass."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]
        r = run_rt(
            "dispatch", "implement",
            "--run-id", run_id,
            "--task", "test",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0


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
        assert plan["policy"] == "branch"
        assert len(plan["dispatch"]) > 0
        assert plan["dispatch"][0]["role"] == "dev"
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
        # dev should be blocked because another writer holds the lock
        assert len(plan["blocked"]) > 0
        assert plan["blocked"][0]["role"] == "dev"

    def test_e2e_default_pipeline_dispatches_all_six_builtin_roles(self, tmp_path):
        """Walk the default pipeline and verify all built-in agents are dispatched."""
        make_config(tmp_path)

        generate_r = run_rt("generate", cwd=str(tmp_path))
        assert generate_r.returncode == 0

        init_r = run_rt("init", "--task", "ship a collaborative feature", cwd=str(tmp_path))
        assert init_r.returncode == 0
        state = json.loads(init_r.stdout)
        run_id = state["run_id"]

        dispatched_roles = set()
        stage_dispatch_counts = {}

        for stage_name in [
            "research",
            "strategy",
            "design",
            "plan",
            "implement",
            "test",
            "review",
        ]:
            r = run_rt(
                "dispatch",
                stage_name,
                "--task",
                "ship a collaborative feature",
                "--run-id",
                run_id,
                cwd=str(tmp_path),
            )
            assert r.returncode == 0, f"dispatch failed for stage {stage_name}: {r.stderr}"
            plan = json.loads(r.stdout)

            assert plan["stage"] == stage_name
            assert (
                plan["dispatch"] or plan["blocked"]
            ), f"expected dispatch or blocked entries for stage {stage_name}"

            stage_dispatch_counts[stage_name] = len(plan["dispatch"])
            for entry in plan["dispatch"]:
                dispatched_roles.add(entry["role"])
                assert (tmp_path / entry["agent"]).exists()
                assert entry["task"] == "ship a collaborative feature"
            # Collect blocked roles too (serial policy blocks extra writers)
            for entry in plan.get("blocked", []):
                dispatched_roles.add(entry["role"])

        assert dispatched_roles == {
            "researcher",
            "pm",
            "architect",
            "dev",
            "qa",
            "reviewer",
        }
        # Design stage: 3 writer roles, serial policy dispatches first + blocks rest
        assert stage_dispatch_counts["design"] >= 1


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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthCommand:
    def test_health_without_config(self, tmp_path):
        env = make_home_env(tmp_path)

        r = run_rt("health", cwd=str(tmp_path), env=env)

        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result == {
            "config_exists": False,
            "pipeline_mode": None,
            "hotl_available": False,
            "hotl_active_in_project": False,
            "generated_agents_exist": False,
            "latest_run_id": None,
        }

    def test_health_with_config_generated_agents_and_latest_run(self, tmp_path):
        make_config(tmp_path)
        env = make_home_env(tmp_path)

        generate_r = run_rt("generate", cwd=str(tmp_path), env=env)
        assert generate_r.returncode == 0

        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True)

        older_run_id = "20260329T235959Z"
        latest_run_id = "20260330T010805Z"
        for run_id in [older_run_id, latest_run_id]:
            with open(state_dir / f"{run_id}.json", "w") as f:
                json.dump({"run_id": run_id}, f)

        r = run_rt("health", cwd=str(tmp_path), env=env)

        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result == {
            "config_exists": True,
            "pipeline_mode": "standalone",
            "hotl_available": False,
            "hotl_active_in_project": False,
            "generated_agents_exist": True,
            "latest_run_id": latest_run_id,
        }

    def test_health_reports_malformed_config_errors_on_stderr(self, tmp_path):
        env = make_home_env(tmp_path)

        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            f.write("version: '1'\nteam: [\n")

        r = run_rt("health", cwd=str(tmp_path), env=env)

        assert r.returncode != 0
        error = json.loads(r.stderr)
        assert "error" in error
        assert error["error"]


# ---------------------------------------------------------------------------
# Standup
# ---------------------------------------------------------------------------


class TestStandup:
    def test_standup_no_active_run(self, tmp_path):
        """Standup with no runs should return health=no-active-run and run=null."""
        make_config(tmp_path)
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "no-active-run"
        assert result["run"] is None
        assert result["stages"] == {}
        assert result["dispatch_mode"] is False
        assert "roles" in result
        assert "artifact_paths" in result
        assert "output_path" in result
        assert result["output_path"].startswith("docs/meetings/")
        assert result["output_path"].endswith("-standup.md")
        assert result["warnings"] == []

    def test_standup_with_active_run(self, tmp_path):
        """Standup after init should include run state and on-track health."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "build feature X", cwd=str(tmp_path))
        assert init_r.returncode == 0
        run_id = json.loads(init_r.stdout)["run_id"]

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "on-track"
        assert result["run"] is not None
        assert result["run"]["run_id"] == run_id
        assert result["run"]["task"] == "build feature X"
        assert result["run"]["current_stage"] == "research"
        assert "design" in result["stages"]
        assert result["stages"]["design"]["status"] == "pending"

    def test_standup_returns_all_default_roles(self, tmp_path):
        """Standup should list all 6 built-in roles."""
        make_config(tmp_path)
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert set(result["roles"]) == {"researcher", "pm", "architect", "dev", "qa", "reviewer"}
        # roles should be sorted
        assert result["roles"] == sorted(result["roles"])

    def test_standup_dispatch_flag(self, tmp_path):
        """--dispatch flag sets dispatch_mode=true."""
        make_config(tmp_path)
        r = run_rt("standup", "--dispatch", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["dispatch_mode"] is True

    def test_standup_task_context(self, tmp_path):
        """--task flag adds task_context to output."""
        make_config(tmp_path)
        r = run_rt("standup", "--task", "focus on auth module", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["task_context"] == "focus on auth module"

    def test_standup_no_task_context_omitted(self, tmp_path):
        """Without --task, task_context key should not be present."""
        make_config(tmp_path)
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "task_context" not in result

    def test_standup_off_track_blocked(self, tmp_path):
        """A blocked stage triggers off-track health."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        state = json.loads(init_r.stdout)
        run_id = state["run_id"]

        # Set a stage to blocked
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        state["stages"]["implement"]["status"] = "blocked"
        with open(state_path, "w") as f:
            json.dump(state, f)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "off-track"
        assert any("blocked" in w for w in result["warnings"])

    def test_standup_off_track_failed(self, tmp_path):
        """A failed stage triggers off-track health."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        state = json.loads(init_r.stdout)
        run_id = state["run_id"]

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        state["stages"]["test"]["status"] = "failed"
        with open(state_path, "w") as f:
            json.dump(state, f)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "off-track"
        assert any("failed" in w for w in result["warnings"])

    def test_standup_at_risk_gate_rejection(self, tmp_path):
        """An in-progress stage with gate=rejected triggers at-risk health."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        state = json.loads(init_r.stdout)
        run_id = state["run_id"]

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        state["stages"]["design"]["status"] = "in-progress"
        state["stages"]["design"]["gate"] = "rejected"
        with open(state_path, "w") as f:
            json.dump(state, f)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "at-risk"
        assert any("gate rejection" in w for w in result["warnings"])

    def test_standup_includes_artifact_paths(self, tmp_path):
        """Standup should include artifact paths."""
        make_config(tmp_path)
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "researcher" in result["artifact_paths"]
        assert "architect" in result["artifact_paths"]
        assert "qa" in result["artifact_paths"]

    def test_standup_many_roles_warning(self, tmp_path):
        """More than 6 roles should trigger the thread warning."""
        config_path = tmp_path / "agenteam.yaml"
        roles = {}
        for i in range(8):
            roles[f"custom_role_{i}"] = {
                "description": f"Custom role {i}",
                "participates_in": ["review"],
                "can_write": False,
            }
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": roles,
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        # 6 built-in + 8 custom = 14 roles
        assert len(result["roles"]) == 14
        assert any("max_threads" in w for w in result["warnings"])
        assert any("above 12" in w for w in result["warnings"])

    def test_standup_dispatch_output_path_deepdive(self, tmp_path):
        """--dispatch produces output_path ending in -deepdive.md."""
        make_config(tmp_path)
        r = run_rt("standup", "--dispatch", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["output_path"].endswith("-deepdive.md")

    def test_standup_dispatch_includes_dispatch_list(self, tmp_path):
        """--dispatch includes a dispatch list with researcher, architect, pm."""
        make_config(tmp_path)
        r = run_rt("standup", "--dispatch", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "dispatch" in result
        role_names = [d["role"] for d in result["dispatch"]]
        assert set(role_names) == {"researcher", "architect", "pm"}
        for d in result["dispatch"]:
            assert d["agent"].endswith(".toml")

    def test_standup_no_dispatch_omits_dispatch_list(self, tmp_path):
        """Without --dispatch, dispatch key should not be present."""
        make_config(tmp_path)
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "dispatch" not in result

    def test_standup_dispatch_no_active_run(self, tmp_path):
        """--dispatch with no active run should succeed and still include a dispatch list."""
        make_config(tmp_path)
        r = run_rt("standup", "--dispatch", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "no-active-run"
        assert result["dispatch_mode"] is True
        assert "dispatch" in result
        assert len(result["dispatch"]) > 0

    def test_standup_output_path_ends_standup_md_after_init(self, tmp_path):
        """output_path ends in -standup.md even after an active run is present."""
        make_config(tmp_path)
        run_rt("init", "--task", "test", cwd=str(tmp_path))
        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["output_path"].startswith("docs/meetings/")
        assert result["output_path"].endswith("-standup.md")


# ---------------------------------------------------------------------------
# compute_health (unit-level via subprocess with crafted state files)
# ---------------------------------------------------------------------------


class TestComputeHealth:
    """Tests for compute_health code paths exercised via standup with crafted state."""

    def _write_state(self, tmp_path, state: dict) -> None:
        """Write a state JSON file so find_latest_state() picks it up."""
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        run_id = state.get("run_id", "20240101T000000Z")
        with open(state_dir / f"{run_id}.json", "w") as f:
            json.dump(state, f)

    def test_health_empty_stages_returns_on_track(self, tmp_path):
        """State with empty stages dict should return on-track (nothing to be wrong)."""
        make_config(tmp_path)
        state = {
            "run_id": "20240101T000000Z",
            "task": "empty stages test",
            "pipeline_mode": "standalone",
            "current_stage": None,
            "stages": {},
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "on-track"
        assert result["warnings"] == []

    def test_health_at_risk_long_running_stage(self, tmp_path):
        """Stage in-progress with started_at > 30 min ago triggers at-risk."""
        import time

        make_config(tmp_path)
        # started_at set to 31 minutes ago
        old_start = time.time() - (31 * 60)
        state = {
            "run_id": "20240101T000000Z",
            "task": "long running",
            "pipeline_mode": "standalone",
            "current_stage": "implement",
            "stages": {
                "implement": {
                    "status": "in-progress",
                    "roles": ["dev"],
                    "gate": "auto",
                    "started_at": old_start,
                }
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "at-risk"
        assert any("minutes" in w for w in result["warnings"])

    def test_health_not_at_risk_recent_stage(self, tmp_path):
        """Stage in-progress started recently (< 30 min) should remain on-track."""
        import time

        make_config(tmp_path)
        recent_start = time.time() - (5 * 60)
        state = {
            "run_id": "20240101T000000Z",
            "task": "recent run",
            "pipeline_mode": "standalone",
            "current_stage": "implement",
            "stages": {
                "implement": {
                    "status": "in-progress",
                    "roles": ["dev"],
                    "gate": "auto",
                    "started_at": recent_start,
                }
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "on-track"

    def test_health_malformed_started_at_ignored(self, tmp_path):
        """Non-numeric started_at (TypeError path) must not crash — stage stays on-track."""
        make_config(tmp_path)
        state = {
            "run_id": "20240101T000000Z",
            "task": "bad started_at",
            "pipeline_mode": "standalone",
            "current_stage": "implement",
            "stages": {
                "implement": {
                    "status": "in-progress",
                    "roles": ["dev"],
                    "gate": "auto",
                    "started_at": "not-a-timestamp",
                }
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        # TypeError path must be swallowed; no at-risk promotion
        assert result["health"] == "on-track"
        assert result["warnings"] == []

    def test_health_multiple_off_track_stages_all_warned(self, tmp_path):
        """All blocked/failed stages should each produce a warning entry."""
        make_config(tmp_path)
        state = {
            "run_id": "20240101T000000Z",
            "task": "multi off-track",
            "pipeline_mode": "standalone",
            "current_stage": "implement",
            "stages": {
                "design": {
                    "status": "blocked",
                    "roles": ["architect"],
                    "gate": "auto",
                },
                "implement": {
                    "status": "failed",
                    "roles": ["dev"],
                    "gate": "auto",
                },
                "test": {
                    "status": "pending",
                    "roles": ["qa"],
                    "gate": "auto",
                },
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "off-track"
        # One warning per off-track stage
        assert any("design" in w for w in result["warnings"])
        assert any("implement" in w for w in result["warnings"])

    def test_health_off_track_wins_over_at_risk(self, tmp_path):
        """When both off-track (blocked/failed) and at-risk (gate rejected) stages exist,
        off-track should take priority."""
        import time

        make_config(tmp_path)
        old_start = time.time() - (35 * 60)
        state = {
            "run_id": "20240101T000000Z",
            "task": "mixed health",
            "pipeline_mode": "standalone",
            "current_stage": "implement",
            "stages": {
                # This would produce at-risk (long-running)
                "design": {
                    "status": "in-progress",
                    "roles": ["architect"],
                    "gate": "auto",
                    "started_at": old_start,
                },
                # This produces off-track (blocked wins)
                "implement": {
                    "status": "blocked",
                    "roles": ["dev"],
                    "gate": "auto",
                },
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "off-track"
        # The off-track warning for implement must be present
        assert any("implement" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# cmd_generate warnings
# ---------------------------------------------------------------------------


class TestGenerateWarnings:
    def _make_config_with_n_roles(self, tmp_path: Path, n: int) -> None:
        """Create a config with exactly n custom roles (no built-ins)."""
        roles = {}
        for i in range(n):
            roles[f"role_{i}"] = {
                "description": f"Role number {i}",
                "participates_in": ["review"],
                "can_write": False,
            }
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": roles,
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_generate_no_warning_with_six_roles(self, tmp_path):
        """Exactly 6 roles should produce no warnings from generate."""
        # Use default config (6 built-in roles)
        make_config(tmp_path)
        r = run_rt("generate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "warnings" not in result

    def test_generate_warns_above_six_roles(self, tmp_path):
        """7+ roles should trigger the max_threads warning from generate."""
        # 6 built-in + 1 custom = 7 total
        make_config(tmp_path)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config.setdefault("roles", {})
        config["roles"]["extra_role"] = {
            "description": "Extra role",
            "participates_in": ["review"],
            "can_write": False,
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("generate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "warnings" in result
        assert any("max_threads" in w for w in result["warnings"])

    def test_generate_warns_above_twelve_roles(self, tmp_path):
        """13+ roles should trigger both the max_threads and >12 coordination warnings."""
        # 6 built-in + 7 custom = 13 total
        make_config(tmp_path)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config.setdefault("roles", {})
        for i in range(7):
            config["roles"][f"extra_role_{i}"] = {
                "description": f"Extra role {i}",
                "participates_in": ["review"],
                "can_write": False,
            }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("generate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "warnings" in result
        assert any("max_threads" in w for w in result["warnings"])
        assert any("above 12" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# cmd_artifact_paths
# ---------------------------------------------------------------------------


class TestArtifactPaths:
    def test_artifact_paths_standalone_mode(self, tmp_path):
        """pipeline=standalone should return standalone paths."""
        make_config(tmp_path)
        r = run_rt("artifact-paths", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "standalone"
        # architect uses docs/designs/ in standalone, docs/plans/ in HOTL
        assert result["paths"]["architect"] == "docs/designs/"

    def test_artifact_paths_hotl_mode_changes_paths(self, tmp_path):
        """pipeline=hotl should return HOTL-specific paths."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("artifact-paths", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "hotl"
        # architect path differs between modes
        assert result["paths"]["architect"] == "docs/plans/"
        # dev_plans at project root in HOTL
        assert result["paths"]["dev_plans"] == "./"

    def test_artifact_paths_auto_no_hotl_uses_standalone(self, tmp_path):
        """pipeline=auto with HOTL unavailable should use standalone paths."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "auto", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        # tmp_path has no .hotl dir and no hotl-workflow-*.md files
        # and HOTL plugin is almost certainly not installed in test env
        r = run_rt("artifact-paths", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        # If hotl is not available in this environment, expect standalone
        if not result["hotl_available"]:
            assert result["mode"] == "standalone"

    def test_artifact_paths_returns_all_expected_keys(self, tmp_path):
        """artifact-paths result should contain all role keys."""
        make_config(tmp_path)
        r = run_rt("artifact-paths", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        for key in ("researcher", "pm", "architect", "dev_plans", "dev_code", "qa"):
            assert key in result["paths"], f"missing key: {key}"

    def test_artifact_paths_hotl_active_in_project(self, tmp_path):
        """When .hotl/ directory exists and pipeline=auto, HOTL paths should be used
        (only if hotl plugin is also available; otherwise skip)."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "auto", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        # Create .hotl directory to simulate active HOTL project
        (tmp_path / ".hotl").mkdir()

        r = run_rt("artifact-paths", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["hotl_active_in_project"] is True
        # If hotl plugin is available in this environment, mode should be hotl
        if result["hotl_available"]:
            assert result["mode"] == "hotl"


# ---------------------------------------------------------------------------
# find_config: preferred .agenteam/config.yaml path
# ---------------------------------------------------------------------------


class TestFindConfig:
    def test_preferred_config_path(self, tmp_path):
        """find_config prefers .agenteam/config.yaml over agenteam.yaml."""
        # Create both files; preferred path should win
        config_dir = tmp_path / ".agenteam"
        config_dir.mkdir()
        preferred_config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": {
                "preferred_only_role": {
                    "description": "Only in preferred config",
                    "participates_in": ["review"],
                    "can_write": False,
                }
            },
            "pipeline": {"stages": []},
        }
        with open(config_dir / "config.yaml", "w") as f:
            yaml.dump(preferred_config, f)

        # Write a legacy agenteam.yaml that does NOT have this role
        legacy_config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(tmp_path / "agenteam.yaml", "w") as f:
            yaml.dump(legacy_config, f)

        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "preferred_only_role" in roles

    def test_legacy_config_used_when_no_preferred(self, tmp_path):
        """Without .agenteam/config.yaml, the legacy agenteam.yaml is used."""
        make_config(tmp_path)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "architect" in roles


# ---------------------------------------------------------------------------
# cmd_status with explicit run-id
# ---------------------------------------------------------------------------


class TestStatusById:
    def test_status_with_explicit_run_id(self, tmp_path):
        """status <run-id> should return that specific run's state."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "explicit id task", cwd=str(tmp_path))
        assert init_r.returncode == 0
        run_id = json.loads(init_r.stdout)["run_id"]

        r = run_rt("status", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["run_id"] == run_id
        assert state["task"] == "explicit id task"

    def test_status_nonexistent_run_id(self, tmp_path):
        """status with a run-id that doesn't exist should exit non-zero."""
        make_config(tmp_path)
        r = run_rt("status", "99991231T999999Z", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# cmd_dispatch without --run-id
# ---------------------------------------------------------------------------


class TestDispatchNoRunId:
    def test_dispatch_without_run_id(self, tmp_path):
        """dispatch without --run-id should succeed (no state loaded, no write lock)."""
        make_config(tmp_path)
        r = run_rt("dispatch", "implement", "--task", "ad-hoc task", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["stage"] == "implement"
        # With no state/lock, writers should be dispatched (not blocked)
        assert len(plan["dispatch"]) > 0
        assert plan["blocked"] == []


# ---------------------------------------------------------------------------
# Branch plan
# ---------------------------------------------------------------------------


class TestBranchPlan:
    def test_serial_mode_with_role(self, tmp_path):
        """Serial mode + --role returns create-branch with ateam/<role>/<slug>."""
        make_config(tmp_path)
        r = run_rt("branch-plan", "--task", "add user auth", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "branch"
        assert result["action"] == "create-branch"
        assert result["branch"] == "ateam/dev/add-user-auth"
        assert result["base_branch"] == "current"
        assert result["pipeline_mode"] == "standalone"

    def test_branch_mode_with_run_id(self, tmp_path):
        """Serial mode + --run-id returns create-branch with ateam/run/<id>."""
        make_config(tmp_path)
        r = run_rt(
            "branch-plan",
            "--task",
            "build feature",
            "--run-id",
            "20260330T150000Z",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["action"] == "create-branch"
        assert result["branch"] == "ateam/run/20260330T150000Z"
        assert result["base_branch"] == "main"

    def test_worktree_mode(self, tmp_path):
        """Worktree mode returns create-worktree with path."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "worktree"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("branch-plan", "--task", "fix bug", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "worktree"
        assert result["action"] == "create-worktree"
        assert result["branch"].startswith("ateam/dev/")
        assert "worktree_path" in result
        assert result["worktree_path"].startswith(".ateam-worktrees/")

    def test_scoped_mode(self, tmp_path):
        """Scoped mode returns use-current with warning."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "scoped"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("branch-plan", "--task", "test", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "none"
        assert result["action"] == "use-current"
        assert result["branch"] is None
        assert "warning" in result
        assert "NOT isolation" in result["warning"]

    def test_hotl_pipeline_with_run_id_defers(self, tmp_path):
        """HOTL pipeline + --run-id returns hotl-deferred."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("branch-plan", "--task", "test", "--run-id", "abc123", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "hotl-deferred"
        assert result["action"] == "none"

    def test_hotl_pipeline_with_role_still_isolates(self, tmp_path):
        """HOTL pipeline + --role (assign) still gets branch isolation."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
            "roles": {},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("branch-plan", "--task", "fix auth", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "branch"
        assert result["action"] == "create-branch"
        assert result["branch"] == "ateam/dev/fix-auth"

    def test_task_slug_special_chars(self, tmp_path):
        """Task slugs handle special characters correctly."""
        make_config(tmp_path)
        r = run_rt(
            "branch-plan",
            "--task",
            "Fix bug #42: handle NULL in user.email!!!",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        branch = result["branch"]
        # Should be safe for git branch names
        assert " " not in branch
        assert "#" not in branch
        assert "!" not in branch
        assert branch.startswith("ateam/dev/")

    def test_task_slug_long_task(self, tmp_path):
        """Long task descriptions are truncated to 40 chars in slug."""
        make_config(tmp_path)
        long_task = "a" * 100
        r = run_rt("branch-plan", "--task", long_task, "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        slug = result["branch"].replace("ateam/dev/", "")
        assert len(slug) <= 40


# ---------------------------------------------------------------------------
# Config simplification
# ---------------------------------------------------------------------------


class TestConfigSimplification:
    def test_minimal_config_works(self, tmp_path):
        """Config with just version loads and resolves roles."""
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump({"version": "1"}, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "architect" in roles
        assert "dev" in roles

    def test_new_isolation_worktree(self, tmp_path):
        """Flat isolation: worktree is read by branch-plan."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "isolation": "worktree", "pipeline": {"stages": []}}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "test", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "worktree"

    def test_new_isolation_none(self, tmp_path):
        """Flat isolation: none returns use-current."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "isolation": "none", "pipeline": {"stages": []}}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "test", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "none"
        assert result["action"] == "use-current"

    def test_legacy_pipeline_hotl_still_works(self, tmp_path):
        """Legacy team.pipeline: hotl maps correctly."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "t", "--run-id", "abc", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "hotl-deferred"

    def test_legacy_serial_maps_to_branch(self, tmp_path):
        """Legacy team.parallel_writes.mode: serial maps to branch."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "t", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "branch"

    def test_invalid_isolation_rejected(self, tmp_path):
        """Invalid isolation value is rejected."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "isolation": "invalid"}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "Invalid isolation" in r.stderr

    def test_invalid_top_level_pipeline_rejected(self, tmp_path):
        """Top-level pipeline: 'invalid' is rejected."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "pipeline": "invalid"}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "Invalid pipeline" in r.stderr

    def test_pipeline_hotl_top_level_accepted(self, tmp_path):
        """Top-level pipeline: hotl is valid."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "pipeline": "hotl"}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0

    def test_no_team_block_defaults_to_branch(self, tmp_path):
        """Config without team block defaults to branch isolation."""
        config_path = tmp_path / "agenteam.yaml"
        config = {"version": "1", "pipeline": {"stages": []}}
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "t", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "branch"

    def test_new_keys_win_over_legacy(self, tmp_path):
        """When both new and legacy keys exist, new keys win."""
        config_path = tmp_path / "agenteam.yaml"
        config = {
            "version": "1",
            "isolation": "worktree",
            "team": {"parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("branch-plan", "--task", "t", "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "worktree"

    def test_task_slug_long_task(self, tmp_path):
        """Long task descriptions are truncated to 40 chars in slug."""
        make_config(tmp_path)
        long_task = "a" * 100
        r = run_rt("branch-plan", "--task", long_task, "--role", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        slug = result["branch"].replace("ateam/dev/", "")
        assert len(slug) <= 40


# ---------------------------------------------------------------------------
# Verify plan
# ---------------------------------------------------------------------------


class TestVerifyPlan:
    def _make_verify_config(self, tmp_path, stages=None, extra=None):
        """Create a config with optional verify fields on stages."""
        if stages is None:
            stages = [
                {"name": "implement", "roles": ["dev"], "gate": "auto",
                 "verify": "python3 -m pytest tests/ -v", "max_retries": 2},
                {"name": "design", "roles": ["architect"], "gate": "human"},
            ]
        config = {
            "version": "1",
            "pipeline": {"stages": stages},
        }
        if extra:
            config.update(extra)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_verify_plan_from_config(self, tmp_path):
        """Stage with explicit verify returns config source and command."""
        self._make_verify_config(tmp_path)
        r = run_rt("verify-plan", "implement", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["stage"] == "implement"
        assert plan["verify"] == "python3 -m pytest tests/ -v"
        assert plan["source"] == "config"
        assert plan["max_retries"] == 2
        assert plan["attempt"] == 1
        assert "cwd" in plan

    def test_verify_plan_auto_detected(self, tmp_path):
        """Stage without verify auto-detects from repo signals."""
        self._make_verify_config(tmp_path)
        # Create a tests/ directory so auto-detection fires
        (tmp_path / "tests").mkdir()
        r = run_rt("verify-plan", "design", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["stage"] == "design"
        assert plan["verify"] == "python3 -m pytest -v"
        assert plan["source"] == "auto-detected"
        assert plan["attempt"] == 1
        assert "cwd" in plan

    def test_verify_plan_none_detected(self, tmp_path):
        """Stage without verify and no repo signals returns null verify."""
        self._make_verify_config(tmp_path)
        # No tests/ dir, no pytest.ini, etc. in tmp_path
        r = run_rt("verify-plan", "design", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["verify"] is None
        assert plan["source"] == "none"
        assert plan["max_retries"] == 0
        assert plan["attempt"] == 0
        assert "cwd" not in plan

    def test_verify_plan_nonexistent_stage(self, tmp_path):
        """Requesting verify-plan for a nonexistent stage returns error."""
        self._make_verify_config(tmp_path)
        r = run_rt("verify-plan", "nonexistent", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_verify_plan_attempt_increments_with_state(self, tmp_path):
        """Attempt number reflects existing verify_attempts in state."""
        self._make_verify_config(tmp_path)
        # Init a run to get state
        r_init = run_rt("init", "--task", "test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Record a verify attempt by writing state directly
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["implement"]["verify_attempts"] = [
            {"attempt": 1, "result": "fail", "output": "1 test failed"},
        ]
        with open(state_path, "w") as f:
            json.dump(state, f)

        r = run_rt("verify-plan", "implement", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["attempt"] == 2

    def test_verify_plan_cwd_is_project_root(self, tmp_path):
        """cwd should be the project root (tmp_path) in branch mode."""
        self._make_verify_config(tmp_path)
        r = run_rt("verify-plan", "implement", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["cwd"] == str(tmp_path)


# ---------------------------------------------------------------------------
# Record verify
# ---------------------------------------------------------------------------


class TestRecordVerify:
    def _setup_run(self, tmp_path):
        """Create a config and init a run, returning run_id."""
        config = {
            "version": "1",
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["dev"], "gate": "auto",
                     "verify": "python3 -m pytest -v", "max_retries": 2},
                    {"name": "test", "roles": ["qa"], "gate": "auto"},
                ]
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("init", "--task", "verify test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_record_pass(self, tmp_path):
        """Recording a pass result persists in state."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "implement", "--result", "pass",
            "--output", "all tests passed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["recorded"] is True
        assert result["attempt"] == 1
        assert result["result"] == "pass"

        # Verify state file
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        stage = state["stages"]["implement"]
        assert stage["verify_result"] == "pass"
        assert len(stage["verify_attempts"]) == 1
        assert stage["verify_attempts"][0]["output"] == "all tests passed"

    def test_record_fail(self, tmp_path):
        """Recording a fail result persists in state."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "implement", "--result", "fail",
            "--output", "2 tests failed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["result"] == "fail"

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert state["stages"]["implement"]["verify_result"] == "fail"

    def test_multiple_attempts(self, tmp_path):
        """Multiple record-verify calls increment attempt numbers."""
        run_id = self._setup_run(tmp_path)
        # First attempt: fail
        run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "implement", "--result", "fail",
            cwd=str(tmp_path),
        )
        # Second attempt: pass
        r = run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "implement", "--result", "pass",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["attempt"] == 2

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        attempts = state["stages"]["implement"]["verify_attempts"]
        assert len(attempts) == 2
        assert attempts[0]["result"] == "fail"
        assert attempts[1]["result"] == "pass"
        # verify_result reflects the latest
        assert state["stages"]["implement"]["verify_result"] == "pass"

    def test_record_verify_nonexistent_stage(self, tmp_path):
        """Recording verify for a stage not in state returns error."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "nonexistent", "--result", "pass",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_record_verify_nonexistent_run(self, tmp_path):
        """Recording verify for a nonexistent run returns error."""
        self._setup_run(tmp_path)
        r = run_rt(
            "record-verify", "--run-id", "99991231T999999Z",
            "--stage", "implement", "--result", "pass",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# Final verify plan
# ---------------------------------------------------------------------------


class TestFinalVerifyPlan:
    def test_final_verify_from_config(self, tmp_path):
        """Config with final_verify returns commands and policy."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
            "final_verify": ["python3 -m pytest -v", "ruff check ."],
            "final_verify_policy": "block",
            "final_verify_max_retries": 2,
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["commands"] == ["python3 -m pytest -v", "ruff check ."]
        assert plan["policy"] == "block"
        assert plan["max_retries"] == 2
        assert plan["source"] == "config"
        assert "cwd" in plan

    def test_final_verify_auto_detected(self, tmp_path):
        """Without final_verify config, auto-detects from repo signals."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        # Create a tests/ directory for auto-detection
        (tmp_path / "tests").mkdir()

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["commands"] == ["python3 -m pytest -v"]
        assert plan["source"] == "auto-detected"
        assert plan["policy"] == "block"
        assert "cwd" in plan

    def test_final_verify_nothing_found(self, tmp_path):
        """No config and no repo signals returns unverified policy."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["commands"] == []
        assert plan["policy"] == "unverified"
        assert plan["source"] == "none"
        assert "cwd" not in plan

    def test_final_verify_warn_policy(self, tmp_path):
        """Config with policy=warn returns warn."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
            "final_verify": ["python3 -m pytest -v"],
            "final_verify_policy": "warn",
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["policy"] == "warn"

    def test_final_verify_single_command_string(self, tmp_path):
        """A single string final_verify is normalized to a list."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
            "final_verify": "python3 -m pytest -v",
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["commands"] == ["python3 -m pytest -v"]
        assert plan["source"] == "config"

    def test_final_verify_defaults(self, tmp_path):
        """Default policy is block and max_retries is 1 when not specified."""
        config = {
            "version": "1",
            "pipeline": {"stages": []},
            "final_verify": ["make test"],
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("final-verify-plan", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["policy"] == "block"
        assert plan["max_retries"] == 1


# ---------------------------------------------------------------------------
# Record gate
# ---------------------------------------------------------------------------


class TestRecordGate:
    def _setup_run(self, tmp_path):
        """Create config with stages and init a run."""
        config = {
            "version": "1",
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["dev"], "gate": "reviewer"},
                    {"name": "design", "roles": ["architect"], "gate": "human"},
                    {"name": "test", "roles": ["qa"], "gate": "auto"},
                ]
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("init", "--task", "gate test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_record_gate_approved(self, tmp_path):
        """Recording an approved gate persists in state."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-gate", "--run-id", run_id,
            "--stage", "implement", "--gate-type", "reviewer",
            "--result", "approved",
            "--verdict", "PASS WITH WARNINGS: 2 WARN findings",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["recorded"] is True
        assert result["result"] == "approved"
        assert result["verdict"] == "PASS WITH WARNINGS: 2 WARN findings"

        # Check state file
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        stage = state["stages"]["implement"]
        assert stage["gate"] == "reviewer"
        assert stage["gate_result"] == "approved"
        assert stage["gate_agent"] == "reviewer"
        assert stage["gate_verdict"] == "PASS WITH WARNINGS: 2 WARN findings"

    def test_record_gate_rejected(self, tmp_path):
        """Recording a rejected gate persists in state."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-gate", "--run-id", run_id,
            "--stage", "implement", "--gate-type", "reviewer",
            "--result", "rejected",
            "--verdict", "BLOCK: missing error handling",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert state["stages"]["implement"]["gate_result"] == "rejected"

    def test_record_gate_human(self, tmp_path):
        """Human gate type does not set gate_agent."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-gate", "--run-id", run_id,
            "--stage", "design", "--gate-type", "human",
            "--result", "approved",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        stage = state["stages"]["design"]
        assert stage["gate"] == "human"
        assert stage["gate_result"] == "approved"
        assert "gate_agent" not in stage

    def test_record_gate_nonexistent_stage(self, tmp_path):
        """Recording a gate for a nonexistent stage returns error."""
        run_id = self._setup_run(tmp_path)
        r = run_rt(
            "record-gate", "--run-id", run_id,
            "--stage", "nonexistent", "--gate-type", "auto",
            "--result", "approved",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_record_gate_nonexistent_run(self, tmp_path):
        """Recording a gate for a nonexistent run returns error."""
        self._setup_run(tmp_path)
        r = run_rt(
            "record-gate", "--run-id", "99991231T999999Z",
            "--stage", "implement", "--gate-type", "reviewer",
            "--result", "approved",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# Writer group partitioning (pure function)
# ---------------------------------------------------------------------------


class TestWriterGroups:
    """Test partition_writer_groups pure function via dispatch output."""

    @staticmethod
    def _make_scoped_config(tmp_path, roles_dict, stage_roles):
        """Create a config with isolation:none and given roles/stage."""
        config = {
            "version": "1",
            "isolation": "none",
            "roles": roles_dict,
            "pipeline": {
                "stages": [{"name": "build", "roles": stage_roles, "gate": "auto"}],
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_three_non_overlapping_writers_one_group(self, tmp_path):
        """Three writers with disjoint scopes should all land in one group."""
        self._make_scoped_config(tmp_path, {
            "alpha": {"can_write": True, "write_scope": ["src/**"]},
            "beta": {"can_write": True, "write_scope": ["lib/**"]},
            "gamma": {"can_write": True, "write_scope": ["docs/**"]},
        }, ["alpha", "beta", "gamma"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "groups" in plan
        assert len(plan["groups"]) == 1
        role_names = [e["role"] for e in plan["groups"][0]["roles"]]
        assert sorted(role_names) == ["alpha", "beta", "gamma"]
        assert plan["groups"][0]["parallel"] is True

    def test_two_overlapping_writers_two_groups(self, tmp_path):
        """Two writers sharing a scope pattern should be in separate groups."""
        self._make_scoped_config(tmp_path, {
            "alpha": {"can_write": True, "write_scope": ["src/**"]},
            "beta": {"can_write": True, "write_scope": ["src/**", "lib/**"]},
        }, ["alpha", "beta"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert len(plan["groups"]) == 2
        assert plan["groups"][0]["roles"][0]["role"] == "alpha"
        assert plan["groups"][1]["roles"][0]["role"] == "beta"

    def test_mixed_overlapping_non_overlapping(self, tmp_path):
        """Mixed: alpha+gamma share no scopes, beta overlaps with alpha."""
        self._make_scoped_config(tmp_path, {
            "alpha": {"can_write": True, "write_scope": ["src/**"]},
            "beta": {"can_write": True, "write_scope": ["src/**"]},
            "gamma": {"can_write": True, "write_scope": ["docs/**"]},
        }, ["alpha", "beta", "gamma"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        # alpha + gamma in group 1 (no overlap), beta in group 2
        assert len(plan["groups"]) == 2
        g1_roles = sorted(e["role"] for e in plan["groups"][0]["roles"])
        g2_roles = sorted(e["role"] for e in plan["groups"][1]["roles"])
        assert g1_roles == ["alpha", "gamma"]
        assert g2_roles == ["beta"]

    def test_read_only_roles_in_read_only_list(self, tmp_path):
        """Read-only roles should appear in read_only, not in groups."""
        self._make_scoped_config(tmp_path, {
            "writer": {"can_write": True, "write_scope": ["src/**"]},
            "reader": {"can_write": False, "write_scope": []},
        }, ["writer", "reader"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["read_only"] == ["reader"]
        # writer should be in the groups
        all_group_roles = []
        for g in plan["groups"]:
            for e in g["roles"]:
                all_group_roles.append(e["role"])
        assert "writer" in all_group_roles
        assert "reader" not in all_group_roles

    def test_single_writer_one_group(self, tmp_path):
        """A single writer produces exactly one group."""
        self._make_scoped_config(tmp_path, {
            "solo": {"can_write": True, "write_scope": ["src/**"]},
        }, ["solo"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert len(plan["groups"]) == 1
        assert plan["groups"][0]["roles"][0]["role"] == "solo"

    def test_no_writers_zero_groups(self, tmp_path):
        """Stage with only read-only roles produces zero groups."""
        self._make_scoped_config(tmp_path, {
            "reader_a": {"can_write": False},
            "reader_b": {"can_write": False},
        }, ["reader_a", "reader_b"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["groups"] == []
        assert sorted(plan["read_only"]) == ["reader_a", "reader_b"]


# ---------------------------------------------------------------------------
# Grouped dispatch output format
# ---------------------------------------------------------------------------


class TestGroupedDispatch:
    """Test that cmd_dispatch returns correct format based on isolation mode."""

    @staticmethod
    def _make_config(tmp_path, isolation, roles_dict, stage_roles):
        config = {
            "version": "1",
            "isolation": isolation,
            "roles": roles_dict,
            "pipeline": {
                "stages": [{"name": "build", "roles": stage_roles, "gate": "human"}],
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_isolation_none_non_overlapping_returns_groups(self, tmp_path):
        """isolation:none with non-overlapping scopes returns groups key."""
        self._make_config(tmp_path, "none", {
            "w1": {"can_write": True, "write_scope": ["src/**"]},
            "w2": {"can_write": True, "write_scope": ["lib/**"]},
        }, ["w1", "w2"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "groups" in plan
        assert "dispatch" not in plan
        assert len(plan["groups"]) == 1
        assert plan["policy"] == "none"
        assert plan["gate"] == "human"
        assert plan["stage"] == "build"

    def test_isolation_none_overlapping_returns_multiple_groups(self, tmp_path):
        """isolation:none with overlapping scopes returns multiple groups."""
        self._make_config(tmp_path, "none", {
            "w1": {"can_write": True, "write_scope": ["src/**"]},
            "w2": {"can_write": True, "write_scope": ["src/**"]},
            "w3": {"can_write": True, "write_scope": ["docs/**"]},
        }, ["w1", "w2", "w3"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "groups" in plan
        assert len(plan["groups"]) == 2

    def test_isolation_branch_returns_flat_dispatch(self, tmp_path):
        """isolation:branch returns flat dispatch list, no groups key."""
        self._make_config(tmp_path, "branch", {
            "w1": {"can_write": True, "write_scope": ["src/**"]},
        }, ["w1"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "dispatch" in plan
        assert "groups" not in plan
        assert plan["policy"] == "branch"

    def test_isolation_worktree_returns_flat_dispatch(self, tmp_path):
        """isolation:worktree returns flat dispatch list, no groups key."""
        self._make_config(tmp_path, "worktree", {
            "w1": {"can_write": True, "write_scope": ["src/**"]},
        }, ["w1"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "dispatch" in plan
        assert "groups" not in plan
        assert plan["policy"] == "worktree"

    def test_read_only_present_in_grouped_dispatch(self, tmp_path):
        """Read-only roles appear in read_only list of grouped dispatch."""
        self._make_config(tmp_path, "none", {
            "writer": {"can_write": True, "write_scope": ["src/**"]},
            "auditor": {"can_write": False},
        }, ["writer", "auditor"])

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "auditor" in plan["read_only"]
        assert len(plan["groups"]) == 1

    def test_group_roles_have_correct_agent_paths(self, tmp_path):
        """Each role entry in groups has the correct agent path and mode."""
        self._make_config(tmp_path, "none", {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
            "qa": {"can_write": True, "write_scope": ["tests/**"]},
        }, ["dev", "qa"])

        r = run_rt("dispatch", "build", "--task", "build it", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        all_entries = []
        for g in plan["groups"]:
            all_entries.extend(g["roles"])
        for entry in all_entries:
            assert entry["agent"] == f".codex/agents/{entry['role']}.toml"
            assert entry["mode"] == "write"
            assert entry["task"] == "build it"


# ---------------------------------------------------------------------------
# Scope audit
# ---------------------------------------------------------------------------


class TestScopeAudit:
    """Test cmd_scope_audit with real git repos."""

    @staticmethod
    def _init_git_repo(path):
        """Initialize a git repo with an initial commit."""
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path), capture_output=True, check=True,
        )
        # Initial commit (empty)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path), capture_output=True, check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path), capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    @staticmethod
    def _commit_file(path, filepath, content="x"):
        """Create/write a file and commit it."""
        fpath = path / filepath
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        subprocess.run(
            ["git", "add", str(filepath)],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"add {filepath}"],
            cwd=str(path), capture_output=True, check=True,
        )

    @staticmethod
    def _make_audit_config(tmp_path, roles_dict, stage_roles):
        config = {
            "version": "1",
            "isolation": "none",
            "roles": roles_dict,
            "pipeline": {
                "stages": [{"name": "build", "roles": stage_roles, "gate": "auto"}],
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_all_files_in_scope_passed(self, tmp_path):
        """All changed files within declared scopes -> passed: true."""
        self._init_git_repo(tmp_path)
        baseline = self._get_head(tmp_path)

        self._make_audit_config(tmp_path, {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
        }, ["dev"])

        # Add a file within scope and commit
        self._commit_file(tmp_path, "src/main.py", "print('hello')")

        r = run_rt(
            "scope-audit", "--stage", "build",
            "--baseline", baseline,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is True
        assert result["unclaimed_files"] == []
        assert result["violations"] == []
        assert "src/**" in result["files_by_scope"]

    def test_file_outside_scope_fails(self, tmp_path):
        """A changed file outside all scopes -> passed: false."""
        self._init_git_repo(tmp_path)
        baseline = self._get_head(tmp_path)

        self._make_audit_config(tmp_path, {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
        }, ["dev"])

        # Add a file outside scope
        self._commit_file(tmp_path, "config/settings.yaml", "key: val")

        r = run_rt(
            "scope-audit", "--stage", "build",
            "--baseline", baseline,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "config/settings.yaml" in result["unclaimed_files"]
        assert len(result["violations"]) == 1
        assert result["violations"][0]["file"] == "config/settings.yaml"

    def test_no_changed_files_passed(self, tmp_path):
        """No changes since baseline -> passed: true."""
        self._init_git_repo(tmp_path)
        baseline = self._get_head(tmp_path)

        self._make_audit_config(tmp_path, {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
        }, ["dev"])

        r = run_rt(
            "scope-audit", "--stage", "build",
            "--baseline", baseline,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is True
        assert result["unclaimed_files"] == []
        assert result["files_by_scope"] == {}

    def test_mixed_in_and_out_of_scope_fails(self, tmp_path):
        """Mix of in-scope and out-of-scope files -> passed: false."""
        self._init_git_repo(tmp_path)
        baseline = self._get_head(tmp_path)

        self._make_audit_config(tmp_path, {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
            "qa": {"can_write": True, "write_scope": ["tests/**"]},
        }, ["dev", "qa"])

        # In-scope files
        self._commit_file(tmp_path, "src/app.py", "app code")
        self._commit_file(tmp_path, "tests/test_app.py", "test code")
        # Out-of-scope file
        self._commit_file(tmp_path, "README.md", "# Readme")

        r = run_rt(
            "scope-audit", "--stage", "build",
            "--baseline", baseline,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "README.md" in result["unclaimed_files"]
        # In-scope files should be classified
        assert "src/app.py" in result["files_by_scope"].get("src/**", [])
        assert "tests/test_app.py" in result["files_by_scope"].get("tests/**", [])

    def test_baseline_respected(self, tmp_path):
        """Only changes after the baseline should be audited."""
        self._init_git_repo(tmp_path)

        self._make_audit_config(tmp_path, {
            "dev": {"can_write": True, "write_scope": ["src/**"]},
        }, ["dev"])

        # Commit an out-of-scope file BEFORE baseline
        self._commit_file(tmp_path, "config/old.yaml", "old config")
        baseline = self._get_head(tmp_path)

        # Commit an in-scope file AFTER baseline
        self._commit_file(tmp_path, "src/new.py", "new code")

        r = run_rt(
            "scope-audit", "--stage", "build",
            "--baseline", baseline,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        # Only src/new.py should be checked (after baseline)
        # config/old.yaml was before baseline, so not included
        assert result["passed"] is True
        assert "config/old.yaml" not in result["unclaimed_files"]
        assert "src/new.py" in result["files_by_scope"].get("src/**", [])


# ---------------------------------------------------------------------------
# Run-level timestamps in init (v2.2)
# ---------------------------------------------------------------------------


class TestInitTimestamps:
    def test_init_includes_started_at(self, tmp_path):
        """init should include started_at ISO 8601 timestamp."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "timestamp test", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert "started_at" in state
        # ISO 8601 format check (YYYY-MM-DDTHH:MM:SSZ)
        assert "T" in state["started_at"]
        assert state["started_at"].endswith("Z")

    def test_init_includes_status_running(self, tmp_path):
        """init should set status to 'running'."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "status test", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["status"] == "running"

    def test_init_includes_branch_null(self, tmp_path):
        """init should set branch to null (populated later by skill)."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "branch test", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["branch"] is None


# ---------------------------------------------------------------------------
# Cross-stage rework (v2.2)
# ---------------------------------------------------------------------------


class TestCrossStageRework:
    """Test cross-stage rework in verify-plan and record-verify."""

    @staticmethod
    def _make_rework_config(tmp_path, stages=None):
        """Create a config with rework_to on test stage."""
        if stages is None:
            stages = [
                {"name": "implement", "roles": ["dev"], "gate": "auto",
                 "verify": "python3 -m pytest -v", "max_retries": 2},
                {"name": "test", "roles": ["qa"], "gate": "auto",
                 "verify": "python3 -m pytest -v", "max_retries": 2,
                 "rework_to": "implement"},
            ]
        config = {
            "version": "1",
            "roles": {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
                "qa": {"can_write": True, "write_scope": ["tests/**"]},
            },
            "pipeline": {"stages": stages},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_verify_plan_with_rework_to_returns_rework_roles(self, tmp_path):
        """verify-plan with rework_to returns rework_to and rework_roles."""
        self._make_rework_config(tmp_path)
        r = run_rt("verify-plan", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert plan["rework_to"] == "implement"
        assert "dev" in plan["rework_roles"]

    def test_verify_plan_without_rework_to_has_no_rework_fields(self, tmp_path):
        """verify-plan without rework_to has no rework_to/rework_roles fields."""
        self._make_rework_config(tmp_path)
        r = run_rt("verify-plan", "implement", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "rework_to" not in plan
        assert "rework_roles" not in plan

    def test_record_verify_with_rework_stage(self, tmp_path):
        """record-verify with --rework-stage stores it in verify_attempts."""
        self._make_rework_config(tmp_path)
        r_init = run_rt("init", "--task", "rework test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        r = run_rt(
            "record-verify", "--run-id", run_id,
            "--stage", "test", "--result", "fail",
            "--output", "2 tests failed",
            "--rework-stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

        # Check state
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        attempts = state["stages"]["test"]["verify_attempts"]
        assert len(attempts) == 1
        assert attempts[0]["rework_stage"] == "implement"

    def test_rework_to_nonexistent_stage_returns_error(self, tmp_path):
        """rework_to pointing to a nonexistent stage returns error."""
        stages = [
            {"name": "test", "roles": ["qa"], "gate": "auto",
             "verify": "python3 -m pytest -v", "max_retries": 2,
             "rework_to": "nonexistent"},
        ]
        self._make_rework_config(tmp_path, stages=stages)
        r = run_rt("verify-plan", "test", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "nonexistent" in r.stderr


# ---------------------------------------------------------------------------
# Per-stage rollback (v2.2)
# ---------------------------------------------------------------------------


class TestStageBaseline:
    """Test cmd_stage_baseline capture and rollback with temp git repos."""

    @staticmethod
    def _init_git_repo(path):
        """Initialize a git repo with an initial commit."""
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path), capture_output=True, check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path), capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    @staticmethod
    def _make_baseline_config(tmp_path, isolation="branch"):
        config = {
            "version": "1",
            "isolation": isolation,
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["dev"], "gate": "auto"},
                    {"name": "test", "roles": ["qa"], "gate": "auto"},
                ]
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_capture_stores_correct_sha(self, tmp_path):
        """stage-baseline capture stores the correct HEAD SHA."""
        self._init_git_repo(tmp_path)
        self._make_baseline_config(tmp_path)
        expected_sha = self._get_head(tmp_path)

        r_init = run_rt("init", "--task", "baseline test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        r = run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "capture",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["baseline"] == expected_sha
        assert result["action"] == "capture"

        # Verify state file
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert state["stages"]["implement"]["baseline"] == expected_sha

    def test_rollback_returns_stored_sha(self, tmp_path):
        """stage-baseline rollback returns the stored baseline SHA."""
        self._init_git_repo(tmp_path)
        self._make_baseline_config(tmp_path)

        r_init = run_rt("init", "--task", "rollback test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Capture first
        run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "capture",
            cwd=str(tmp_path),
        )

        # Rollback
        r = run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "rollback",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["action"] == "rollback"
        assert result["allowed"] is True
        assert len(result["baseline"]) == 40  # Full SHA

    def test_isolation_none_rollback_not_allowed(self, tmp_path):
        """Rollback in isolation:none returns allowed:false."""
        self._init_git_repo(tmp_path)
        self._make_baseline_config(tmp_path, isolation="none")

        r_init = run_rt("init", "--task", "none test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Capture
        run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "capture",
            cwd=str(tmp_path),
        )

        # Rollback should be disallowed
        r = run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "rollback",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["allowed"] is False
        assert "reason" in result

    def test_isolation_branch_rollback_allowed(self, tmp_path):
        """Rollback in isolation:branch returns allowed:true."""
        self._init_git_repo(tmp_path)
        self._make_baseline_config(tmp_path, isolation="branch")

        r_init = run_rt("init", "--task", "branch test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Capture
        run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "capture",
            cwd=str(tmp_path),
        )

        r = run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "rollback",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["allowed"] is True

    def test_no_baseline_returns_error(self, tmp_path):
        """Rollback with no captured baseline returns error."""
        self._init_git_repo(tmp_path)
        self._make_baseline_config(tmp_path)

        r_init = run_rt("init", "--task", "no baseline", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        r = run_rt(
            "stage-baseline", "--run-id", run_id,
            "--stage", "implement", "--action", "rollback",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "No baseline" in r.stderr


# ---------------------------------------------------------------------------
# Run report (v2.2)
# ---------------------------------------------------------------------------


class TestRunReport:
    """Test cmd_run_report JSON assembly."""

    @staticmethod
    def _write_state(tmp_path, state):
        """Write a state file for testing."""
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        run_id = state["run_id"]
        with open(state_dir / f"{run_id}.json", "w") as f:
            json.dump(state, f)

    @staticmethod
    def _make_report_config(tmp_path):
        config = {
            "version": "1",
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["dev"], "gate": "auto"},
                    {"name": "test", "roles": ["qa"], "gate": "auto"},
                ]
            },
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def test_completed_run_includes_all_stages(self, tmp_path):
        """Report for a completed run includes all stages."""
        self._make_report_config(tmp_path)
        state = {
            "run_id": "20260330T150000Z",
            "task": "Add auth",
            "status": "completed",
            "started_at": "2026-03-30T15:00:00Z",
            "completed_at": "2026-03-30T15:04:32Z",
            "branch": "ateam/run/20260330T150000Z",
            "stages": {
                "implement": {
                    "status": "passed",
                    "roles": ["dev"],
                    "gate": "auto",
                    "verify_result": "pass",
                    "verify_attempts": [{"attempt": 1, "result": "pass"}],
                    "gate_result": "approved",
                },
                "test": {
                    "status": "passed",
                    "roles": ["qa"],
                    "gate": "auto",
                    "verify_result": "pass",
                    "verify_attempts": [{"attempt": 1, "result": "pass"}],
                    "gate_result": "approved",
                },
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("run-report", "--run-id", "20260330T150000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        report = json.loads(r.stdout)
        assert report["run_id"] == "20260330T150000Z"
        assert report["task"] == "Add auth"
        assert report["status"] == "completed"
        assert len(report["stages"]) == 2
        stage_names = [s["name"] for s in report["stages"]]
        assert "implement" in stage_names
        assert "test" in stage_names

    def test_run_with_rework_includes_rework_history(self, tmp_path):
        """Report with rework attempts includes rework_history."""
        self._make_report_config(tmp_path)
        state = {
            "run_id": "20260330T160000Z",
            "task": "Add feature",
            "status": "completed",
            "started_at": "2026-03-30T16:00:00Z",
            "branch": None,
            "stages": {
                "implement": {
                    "status": "passed",
                    "roles": ["dev"],
                    "gate": "auto",
                },
                "test": {
                    "status": "passed",
                    "roles": ["qa"],
                    "gate": "auto",
                    "verify_result": "pass",
                    "verify_attempts": [
                        {"attempt": 1, "result": "fail", "rework_stage": "implement"},
                        {"attempt": 2, "result": "pass"},
                    ],
                },
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("run-report", "--run-id", "20260330T160000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        report = json.loads(r.stdout)
        assert len(report["rework_history"]) == 1
        assert report["rework_history"][0]["rework_stage"] == "implement"
        assert report["rework_history"][0]["stage"] == "test"

    def test_includes_final_verify_results(self, tmp_path):
        """Report includes final_verify_results from state."""
        self._make_report_config(tmp_path)
        state = {
            "run_id": "20260330T170000Z",
            "task": "Final verify test",
            "status": "completed",
            "started_at": "2026-03-30T17:00:00Z",
            "branch": None,
            "final_verify_results": [
                {"command": "python3 -m pytest -v", "passed": True},
                {"command": "ruff check .", "passed": True},
            ],
            "stages": {
                "implement": {"status": "passed", "roles": ["dev"], "gate": "auto"},
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("run-report", "--run-id", "20260330T170000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        report = json.loads(r.stdout)
        assert len(report["final_verify_results"]) == 2
        assert report["final_verify_results"][0]["command"] == "python3 -m pytest -v"
        assert report["final_verify_results"][0]["passed"] is True

    def test_report_path_under_agenteam_reports(self, tmp_path):
        """report_path should be under .agenteam/reports/."""
        self._make_report_config(tmp_path)
        state = {
            "run_id": "20260330T180000Z",
            "task": "Path test",
            "status": "completed",
            "started_at": "2026-03-30T18:00:00Z",
            "branch": None,
            "stages": {},
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("run-report", "--run-id", "20260330T180000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        report = json.loads(r.stdout)
        assert report["report_path"].startswith(".agenteam/reports/")
        assert report["report_path"].endswith(".md")

    def test_includes_criteria_override_details(self, tmp_path):
        """Report includes criteria override details from gate."""
        self._make_report_config(tmp_path)
        state = {
            "run_id": "20260330T190000Z",
            "task": "Criteria override test",
            "status": "completed",
            "started_at": "2026-03-30T19:00:00Z",
            "branch": None,
            "stages": {
                "implement": {
                    "status": "passed",
                    "roles": ["dev"],
                    "gate": "human",
                    "gate_result": "approved",
                    "gate_type": "criteria_override",
                    "criteria_failed": ["max_files_changed"],
                    "criteria_details": {"max_files_changed": {"configured": 15, "actual": 23}},
                    "override_reason": "Bulk rename",
                },
            },
            "write_locks": {"active": None, "queue": []},
        }
        self._write_state(tmp_path, state)

        r = run_rt("run-report", "--run-id", "20260330T190000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        report = json.loads(r.stdout)
        impl_stage = [s for s in report["stages"] if s["name"] == "implement"][0]
        assert impl_stage["gate"]["gate_type"] == "criteria_override"
        assert "max_files_changed" in impl_stage["gate"]["criteria_failed"]
        assert impl_stage["gate"]["override_reason"] == "Bulk rename"


# ---------------------------------------------------------------------------
# Gate criteria evaluation (v2.2)
# ---------------------------------------------------------------------------


class TestGateEval:
    """Test cmd_gate_eval with temp git repos."""

    @staticmethod
    def _init_git_repo(path):
        """Initialize a git repo with an initial commit."""
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path), capture_output=True, check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path), capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()

    @staticmethod
    def _commit_file(path, filepath, content="x"):
        """Create/write a file and commit it."""
        fpath = path / filepath
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        subprocess.run(
            ["git", "add", str(filepath)],
            cwd=str(path), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"add {filepath}"],
            cwd=str(path), capture_output=True, check=True,
        )

    @staticmethod
    def _make_gate_config(tmp_path, criteria=None):
        stages = [
            {"name": "implement", "roles": ["dev"], "gate": "auto"},
        ]
        if criteria is not None:
            stages[0]["criteria"] = criteria
        config = {
            "version": "1",
            "pipeline": {"stages": stages},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

    def _setup_run_with_baseline(self, tmp_path, criteria=None):
        """Init git repo, create config, init run, capture baseline.

        Returns (run_id, baseline_sha).
        """
        self._init_git_repo(tmp_path)
        self._make_gate_config(tmp_path, criteria=criteria)
        baseline_sha = self._get_head(tmp_path)

        r_init = run_rt("init", "--task", "gate test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Write baseline directly into state (stage-baseline capture needs git)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["implement"]["baseline"] = baseline_sha
        with open(state_path, "w") as f:
            json.dump(state, f)

        return run_id, baseline_sha

    def test_max_files_changed_exceeded(self, tmp_path):
        """max_files_changed exceeded returns failed_criteria."""
        run_id, _ = self._setup_run_with_baseline(
            tmp_path, criteria={"max_files_changed": 1}
        )

        # Create 2 files (exceeds max of 1)
        self._commit_file(tmp_path, "src/a.py", "a")
        self._commit_file(tmp_path, "src/b.py", "b")

        r = run_rt(
            "gate-eval", "--run-id", run_id,
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "max_files_changed" in result["failed_criteria"]
        assert result["criteria"]["max_files_changed"]["actual"] == 2
        assert result["criteria"]["max_files_changed"]["configured"] == 1

    def test_scope_paths_violation(self, tmp_path):
        """scope_paths violation returns failed_criteria."""
        run_id, _ = self._setup_run_with_baseline(
            tmp_path, criteria={"scope_paths": ["src/**"]}
        )

        # Create a file outside scope
        self._commit_file(tmp_path, "config/settings.yaml", "key: val")

        r = run_rt(
            "gate-eval", "--run-id", run_id,
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "scope_paths" in result["failed_criteria"]
        assert "config/settings.yaml" in result["criteria"]["scope_paths"]["actual_out_of_scope"]

    def test_requires_tests_with_no_test_files(self, tmp_path):
        """requires_tests with no test files returns failed_criteria."""
        run_id, _ = self._setup_run_with_baseline(
            tmp_path, criteria={"requires_tests": True}
        )

        # Create a non-test file only
        self._commit_file(tmp_path, "src/main.py", "code")

        r = run_rt(
            "gate-eval", "--run-id", run_id,
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "requires_tests" in result["failed_criteria"]
        assert result["criteria"]["requires_tests"]["test_files_found"] is False

    def test_all_criteria_met(self, tmp_path):
        """All criteria met returns passed:true."""
        run_id, _ = self._setup_run_with_baseline(
            tmp_path, criteria={
                "max_files_changed": 5,
                "scope_paths": ["src/**", "tests/**"],
                "requires_tests": True,
            }
        )

        # Create files within scope including a test file
        self._commit_file(tmp_path, "src/app.py", "app code")
        self._commit_file(tmp_path, "tests/test_app.py", "test code")

        r = run_rt(
            "gate-eval", "--run-id", run_id,
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is True
        assert result["failed_criteria"] == []
        assert result["criteria"]["max_files_changed"]["passed"] is True
        assert result["criteria"]["scope_paths"]["passed"] is True
        assert result["criteria"]["requires_tests"]["passed"] is True

    def test_no_criteria_configured_passes(self, tmp_path):
        """No criteria configured returns passed:true with empty criteria."""
        run_id, _ = self._setup_run_with_baseline(tmp_path, criteria=None)

        # Create some files
        self._commit_file(tmp_path, "src/anything.py", "stuff")

        r = run_rt(
            "gate-eval", "--run-id", run_id,
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is True
        assert result["criteria"] == {}
        assert result["failed_criteria"] == []

    def test_criteria_override_via_record_gate(self, tmp_path):
        """Criteria override via record-gate with gate_type:criteria_override."""
        self._init_git_repo(tmp_path)
        self._make_gate_config(tmp_path, criteria={"max_files_changed": 1})

        r_init = run_rt("init", "--task", "override test", cwd=str(tmp_path))
        assert r_init.returncode == 0
        run_id = json.loads(r_init.stdout)["run_id"]

        # Record a criteria_override gate
        r = run_rt(
            "record-gate", "--run-id", run_id,
            "--stage", "implement",
            "--gate-type", "criteria_override",
            "--result", "approved",
            "--verdict", "Criteria override: max_files_changed (23 > 15)",
            "--criteria-failed", '["max_files_changed"]',
            "--criteria-details", '{"max_files_changed": {"configured": 15, "actual": 23}}',
            "--override-reason", "Bulk rename across 23 files",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

        # Verify state
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        stage = state["stages"]["implement"]
        assert stage["gate_type"] == "criteria_override"
        assert stage["criteria_failed"] == ["max_files_changed"]
        assert stage["criteria_details"]["max_files_changed"]["configured"] == 15
        assert stage["override_reason"] == "Bulk rename across 23 files"


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


class TestEventLog:
    def test_event_append_creates_jsonl(self, tmp_path):
        r = run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "run_started",
            "--data", '{"task": "test task", "pipeline_mode": "standalone"}',
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["type"] == "run_started"
        assert result["run_id"] == "test-run"
        assert result["stage"] is None
        assert result["data"]["task"] == "test task"

        # Verify JSONL file exists
        jsonl = tmp_path / ".agenteam" / "events" / "test-run.jsonl"
        assert jsonl.exists()
        lines = jsonl.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["type"] == "run_started"

    def test_event_append_validates_type(self, tmp_path):
        r = run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "invalid_type",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Unknown event type" in r.stderr

    def test_event_append_validates_required_data(self, tmp_path):
        r = run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "run_started",
            "--data", '{"task": "test"}',
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "pipeline_mode" in r.stderr

    def test_event_list_returns_events(self, tmp_path):
        for i in range(3):
            run_rt(
                "event", "append",
                "--run-id", "test-run",
                "--type", "run_started",
                "--data", json.dumps({"task": f"task-{i}", "pipeline_mode": "standalone"}),
                cwd=str(tmp_path),
            )
        r = run_rt("event", "list", "--run-id", "test-run", cwd=str(tmp_path))
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 3

    def test_event_list_filters_by_type(self, tmp_path):
        run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "run_started",
            "--data", '{"task": "t", "pipeline_mode": "standalone"}',
            cwd=str(tmp_path),
        )
        run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "stage_dispatched",
            "--stage", "implement",
            "--data", '{"roles": ["dev"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        r = run_rt(
            "event", "list",
            "--run-id", "test-run",
            "--type", "run_started",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 1
        assert events[0]["type"] == "run_started"

    def test_event_list_filters_by_stage(self, tmp_path):
        run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "stage_dispatched",
            "--stage", "implement",
            "--data", '{"roles": ["dev"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        run_rt(
            "event", "append",
            "--run-id", "test-run",
            "--type", "stage_dispatched",
            "--stage", "review",
            "--data", '{"roles": ["reviewer"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        r = run_rt(
            "event", "list",
            "--run-id", "test-run",
            "--stage", "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 1
        assert events[0]["stage"] == "implement"

    def test_event_list_last_n(self, tmp_path):
        for i in range(5):
            run_rt(
                "event", "append",
                "--run-id", "test-run",
                "--type", "run_started",
                "--data", json.dumps({"task": f"task-{i}", "pipeline_mode": "standalone"}),
                cwd=str(tmp_path),
            )
        r = run_rt(
            "event", "list",
            "--run-id", "test-run",
            "--last", "2",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 2
        assert events[0]["data"]["task"] == "task-3"
        assert events[1]["data"]["task"] == "task-4"

    def test_event_list_empty_for_missing_file(self, tmp_path):
        r = run_rt(
            "event", "list",
            "--run-id", "nonexistent",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert events == []


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------


class TestTransitions:
    def _init_run(self, tmp_path):
        """Helper: init a run and return the run_id."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_valid_transition_pending_to_dispatched(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "transition",
            "--run-id", run_id,
            "--stage", "implement",
            "--to", "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["stage"] == "implement"
        assert result["from"] == "pending"
        assert result["to"] == "dispatched"
        assert "last_update" in result

    def test_invalid_transition_rejected(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "transition",
            "--run-id", run_id,
            "--stage", "implement",
            "--to", "completed",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Invalid transition" in r.stderr

    def test_transition_updates_last_update(self, tmp_path):
        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            old_state = json.load(f)
        old_update = old_state.get("last_update")

        import time
        time.sleep(0.01)

        r = run_rt(
            "transition",
            "--run-id", run_id,
            "--stage", "implement",
            "--to", "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        with open(state_path) as f:
            new_state = json.load(f)
        assert new_state["last_update"] >= old_update

    def test_v22_backward_compat(self, tmp_path):
        """v2.2 'in-progress' should be mapped to 'dispatched' for transition purposes."""
        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"

        # Manually set stage status to v2.2 'in-progress'
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["implement"]["status"] = "in-progress"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        # Should be able to transition to 'verifying' (valid from 'dispatched')
        r = run_rt(
            "transition",
            "--run-id", run_id,
            "--stage", "implement",
            "--to", "verifying",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["from"] == "in-progress"
        assert result["to"] == "verifying"

    def test_transition_missing_stage(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "transition",
            "--run-id", run_id,
            "--stage", "nonexistent",
            "--to", "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_dispatched_to_verifying(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_verifying_to_passed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "passed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_verifying_to_failed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "failed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_failed_to_dispatched(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "failed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_passed_to_gated(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "passed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "gated",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_gated_to_completed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "passed",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "gated",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "completed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_gated_to_rejected(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "passed",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "gated",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "rejected",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_completed_is_terminal(self, tmp_path):
        run_id = self._init_run(tmp_path)
        # Fast-track: pending -> dispatched -> completed
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "completed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition", "--run-id", run_id,
            "--stage", "implement", "--to", "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Invalid transition" in r.stderr


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class TestResume:
    def _init_run(self, tmp_path):
        """Helper: init a run and return the run_id."""
        make_config(tmp_path)
        r = run_rt("init", "--task", "resume test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def _make_stale(self, tmp_path, run_id, minutes_ago=15):
        """Set last_update to N minutes ago."""
        from datetime import datetime, timedelta, timezone
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        past = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        state["last_update"] = past.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

    def test_resume_detect_finds_stale_run(self, tmp_path):
        run_id = self._init_run(tmp_path)
        self._make_stale(tmp_path, run_id, 15)
        r = run_rt("resume-detect", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["resumable_runs"]) == 1
        assert result["resumable_runs"][0]["run_id"] == run_id

    def test_resume_detect_ignores_fresh_run(self, tmp_path):
        self._init_run(tmp_path)
        r = run_rt("resume-detect", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["resumable_runs"]) == 0

    def test_resume_detect_ignores_completed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["status"] = "completed"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
        self._make_stale(tmp_path, run_id, 15)
        r = run_rt("resume-detect", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["resumable_runs"]) == 0

    def test_resume_plan_returns_structure(self, tmp_path):
        run_id = self._init_run(tmp_path)
        self._make_stale(tmp_path, run_id, 15)
        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["run_id"] == run_id
        assert result["stale"] is True
        assert "interrupted_stage" in result
        assert "completed_stages" in result
        assert "remaining_stages" in result
        assert result["interrupted_stage"]["name"] == "research"

    def test_resume_plan_config_hash_match(self, tmp_path):
        run_id = self._init_run(tmp_path)
        self._make_stale(tmp_path, run_id, 15)
        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["config_hash_match"] is True

    def test_resume_plan_config_hash_mismatch(self, tmp_path):
        run_id = self._init_run(tmp_path)
        self._make_stale(tmp_path, run_id, 15)
        # Modify config after init
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "a") as f:
            f.write("\n# modified\n")
        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["config_hash_match"] is False

    def test_resume_plan_verify_safe_from_config(self, tmp_path):
        import yaml
        make_config(tmp_path)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        # Add verify_safe to research stage
        for stage in config["pipeline"]["stages"]:
            if stage["name"] == "research":
                stage["verify"] = "echo ok"
                stage["verify_safe"] = True
                break
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]
        self._make_stale(tmp_path, run_id, 15)

        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["interrupted_stage"]["verify_safe"] is True
        assert result["interrupted_stage"]["verify_safe_source"] == "config"

    def test_resume_plan_includes_pipeline_mode(self, tmp_path):
        run_id = self._init_run(tmp_path)
        self._make_stale(tmp_path, run_id, 15)
        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["pipeline_mode"] == "standalone"


# ---------------------------------------------------------------------------
# HOTL adapter
# ---------------------------------------------------------------------------


class TestHotlAdapter:
    def _init_run_with_hotl_skills(self, tmp_path, role_overrides=None):
        """Helper: create config with hotl_skills and init a run."""
        overrides = {"roles": role_overrides} if role_overrides else {}
        make_config(tmp_path, overrides)
        r = run_rt("init", "--task", "adapter test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_hotl_skills_no_hotl_installed(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(
            tmp_path,
            {"dev": {"hotl_skills": ["tdd"]}},
        )
        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "implement",
            "--role", "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["hotl_available"] is False
        # Eligibility still resolves even without HOTL
        assert len(result["eligible"]) == 1
        assert result["eligible"][0]["skill"] == "tdd"

    def test_hotl_skills_tdd_eligible(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(
            tmp_path,
            {"dev": {"hotl_skills": ["tdd", "systematic-debugging"]}},
        )
        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "implement",
            "--role", "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        eligible_skills = [e["skill"] for e in result["eligible"]]
        assert "tdd" in eligible_skills
        not_eligible_skills = [e["skill"] for e in result["not_eligible"]]
        assert "systematic-debugging" in not_eligible_skills

    def test_hotl_skills_tdd_not_eligible_wrong_stage(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(
            tmp_path,
            {"dev": {"hotl_skills": ["tdd"]}},
        )
        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "review",
            "--role", "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["eligible"]) == 0
        assert len(result["not_eligible"]) == 1
        assert result["not_eligible"][0]["skill"] == "tdd"

    def test_hotl_skills_code_review_eligible(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(
            tmp_path,
            {"reviewer": {"hotl_skills": ["code-review"]}},
        )
        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "review",
            "--role", "reviewer",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["eligible"]) == 1
        assert result["eligible"][0]["skill"] == "code-review"
        assert result["eligible"][0]["hotl_skill"] == "hotl:code-review"

    def test_hotl_skills_systematic_debugging_eligible_on_failed(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(
            tmp_path,
            {"dev": {"hotl_skills": ["systematic-debugging"]}},
        )
        # Manually set implement stage to failed
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["implement"]["status"] = "failed"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "implement",
            "--role", "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert len(result["eligible"]) == 1
        assert result["eligible"][0]["skill"] == "systematic-debugging"

    def test_hotl_skills_no_configured_skills(self, tmp_path):
        run_id = self._init_run_with_hotl_skills(tmp_path)
        env = make_home_env(tmp_path)
        r = run_rt(
            "hotl-skills",
            "--run-id", run_id,
            "--stage", "implement",
            "--role", "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["configured_skills"] == []
        assert result["eligible"] == []


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------


class TestProfileValidation:
    def _make_config_with_profiles(self, tmp_path, profiles, extra_stages=None):
        """Helper: create config with pipeline.profiles."""
        import yaml
        with open(TEMPLATE) as f:
            config = yaml.safe_load(f)
        if "pipeline" not in config or not isinstance(config["pipeline"], dict):
            config["pipeline"] = {"stages": []}
        config["pipeline"]["profiles"] = profiles
        if extra_stages:
            config["pipeline"]["stages"].extend(extra_stages)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    def test_valid_profiles_accepted(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0

    def test_unknown_stage_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "bad": {"stages": ["nonexistent"]},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "unknown stage" in r.stderr

    def test_duplicate_stage_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "bad": {"stages": ["implement", "implement"]},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "duplicate stage" in r.stderr

    def test_empty_stages_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "bad": {"stages": []},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "non-empty list" in r.stderr

    def test_hints_must_be_list_of_strings(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "bad": {"stages": ["implement"], "hints": 42},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "hints" in r.stderr

    def test_rework_to_outside_profile_rejected(self, tmp_path):
        # test stage has rework_to: implement, so a profile with test but not implement should fail
        self._make_config_with_profiles(tmp_path, {
            "bad": {"stages": ["test"]},
        })
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "rework_to" in r.stderr

    def test_no_profiles_key_is_valid(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0


# ---------------------------------------------------------------------------
# Profile init
# ---------------------------------------------------------------------------


class TestProfileInit:
    def _make_config_with_profiles(self, tmp_path, profiles):
        import yaml
        with open(TEMPLATE) as f:
            config = yaml.safe_load(f)
        if "pipeline" not in config or not isinstance(config["pipeline"], dict):
            config["pipeline"] = {"stages": []}
        config["pipeline"]["profiles"] = profiles
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    def test_init_with_profile_snapshots_subset(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["profile"] == "quick"
        assert state["stage_order"] == ["implement", "test"]
        assert set(state["stages"].keys()) == {"implement", "test"}

    def test_init_without_profile_uses_all_stages(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["profile"] is None
        assert len(state["stage_order"]) == 7
        assert len(state["stages"]) == 7

    def test_init_unknown_profile_fails(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "test", "--profile", "nonexistent", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "Unknown profile" in r.stderr

    def test_init_full_profile_implicit(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "full", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert len(state["stage_order"]) == 7

    def test_init_snapshots_full_stage_config(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        impl = state["stages"]["implement"]
        assert "verify" in impl
        assert "max_retries" in impl
        assert "rework_to" in impl
        assert "criteria" in impl
        assert impl["max_retries"] == 2  # from template

    def test_init_preserves_pipeline_order(self, tmp_path):
        # Profile lists stages out of pipeline order
        self._make_config_with_profiles(tmp_path, {
            "reversed": {"stages": ["test", "implement"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "reversed", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        # Pipeline order: implement comes before test
        assert state["stage_order"] == ["implement", "test"]

    def test_init_profile_stores_stage_order(self, tmp_path):
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert isinstance(state["stage_order"], list)
        assert state["stage_order"] == list(state["stages"].keys())


# ---------------------------------------------------------------------------
# resolve_stages_for_run (tested indirectly via dispatch)
# ---------------------------------------------------------------------------


class TestResolveStagesForRun:
    def _make_config_with_profiles(self, tmp_path, profiles):
        import yaml
        with open(TEMPLATE) as f:
            config = yaml.safe_load(f)
        if "pipeline" not in config or not isinstance(config["pipeline"], dict):
            config["pipeline"] = {"stages": []}
        config["pipeline"]["profiles"] = profiles
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    def test_with_run_id_returns_state_stages(self, tmp_path):
        """Init with quick profile, then dispatch should only see implement/test."""
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]

        # dispatch against a stage in the profile should work
        r = run_rt("dispatch", "implement", "--run-id", run_id, "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0

        # dispatch against a stage NOT in the profile should fail
        r = run_rt("dispatch", "research", "--run-id", run_id, "--task", "test", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_without_run_id_returns_config_stages(self, tmp_path):
        """Dispatch without run-id should use all config stages."""
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        # dispatch without --run-id should still find research (from config)
        r = run_rt("dispatch", "research", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0

    def test_state_stages_immune_to_config_change(self, tmp_path):
        """After init, changing config should not affect run-scoped commands."""
        import yaml
        self._make_config_with_profiles(tmp_path, {
            "quick": {"stages": ["implement", "test"]},
        })
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]

        # Read and modify config: change max_retries on implement
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        for s in config["pipeline"]["stages"]:
            if s["name"] == "implement":
                s["max_retries"] = 99
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        # verify-plan should use original max_retries from state (2), not config (99)
        r = run_rt("verify-plan", "implement", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["max_retries"] == 2


# ---------------------------------------------------------------------------
# Schema validation (v2.5)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Tests for the schema.py validation framework via validate --format diagnostics."""

    def _validate(self, tmp_path, config, fmt="diagnostics"):
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        args = ["validate", "--format", fmt]
        return run_rt(*args, cwd=str(tmp_path))

    def _diag_codes(self, result):
        data = json.loads(result.stdout)
        return [d["code"] for d in data.get("diagnostics", [])]

    def test_valid_new_format(self, tmp_path):
        """Version 2 config with no legacy keys validates cleanly."""
        config = {
            "version": "2",
            "isolation": "branch",
            "pipeline": {"stages": [
                {"name": "implement", "roles": ["dev"], "gate": "auto"},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["valid"] is True
        # No errors or warnings
        assert data["error_count"] == 0
        assert data["warning_count"] == 0

    def test_missing_version(self, tmp_path):
        """E001: missing version field."""
        r = self._validate(tmp_path, {"isolation": "branch"})
        assert r.returncode != 0
        assert "E001" in str(json.loads(r.stdout).get("diagnostics", []))

    def test_invalid_isolation(self, tmp_path):
        """E002: invalid isolation value."""
        r = self._validate(tmp_path, {"version": "1", "isolation": "invalid"})
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E002" in codes

    def test_invalid_pipeline_string(self, tmp_path):
        """E003: invalid top-level pipeline string."""
        r = self._validate(tmp_path, {"version": "1", "pipeline": "invalid"})
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E003" in codes

    def test_duplicate_stage_names(self, tmp_path):
        """E011: duplicate stage names in pipeline.stages."""
        config = {
            "version": "1",
            "pipeline": {"stages": [
                {"name": "test", "roles": ["qa"], "gate": "auto"},
                {"name": "test", "roles": ["dev"], "gate": "auto"},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E011" in codes

    def test_rework_to_missing_stage(self, tmp_path):
        """E008: rework_to references non-existent stage."""
        config = {
            "version": "1",
            "pipeline": {"stages": [
                {"name": "implement", "roles": ["dev"], "gate": "auto",
                 "rework_to": "nonexistent"},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E008" in codes

    def test_profile_unknown_stage(self, tmp_path):
        """E009: profile references unknown stage."""
        config = {
            "version": "1",
            "pipeline": {
                "stages": [{"name": "implement", "roles": ["dev"], "gate": "auto"}],
                "profiles": {"quick": {"stages": ["nonexistent"]}},
            },
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E009" in codes

    def test_stage_references_unknown_role(self, tmp_path):
        """E007: stage references role not in resolved roles."""
        config = {
            "version": "1",
            "pipeline": {"stages": [
                {"name": "implement", "roles": ["nonexistent_role"], "gate": "auto"},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E007" in codes

    def test_legacy_warnings(self, tmp_path):
        """W001/W002: legacy keys produce warnings."""
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode == 0
        codes = self._diag_codes(r)
        assert "W001" in codes
        assert "W002" in codes

    def test_final_verify_string_warning(self, tmp_path):
        """W004: final_verify as string emits warning."""
        config = {
            "version": "1",
            "final_verify": "python3 -m pytest -v",
            "pipeline": {"stages": []},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode == 0
        codes = self._diag_codes(r)
        assert "W004" in codes

    def test_strict_fails_on_warnings(self, tmp_path):
        """--strict treats warnings as errors."""
        config = {
            "version": "1",
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("validate", "--strict", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "strict" in r.stderr.lower()

    def test_invalid_gate_type(self, tmp_path):
        """E015: invalid gate value."""
        config = {
            "version": "1",
            "pipeline": {"stages": [
                {"name": "test", "roles": ["qa"], "gate": "manual"},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E015" in codes

    def test_invalid_max_retries(self, tmp_path):
        """E016: max_retries must be non-negative integer."""
        config = {
            "version": "1",
            "pipeline": {"stages": [
                {"name": "test", "roles": ["qa"], "gate": "auto", "max_retries": -1},
            ]},
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E016" in codes

    def test_unknown_top_level_key_suggestion(self, tmp_path):
        """Unknown key gets 'Did you mean?' suggestion."""
        config = {
            "version": "1",
            "pipline": "hotl",  # typo
        }
        r = self._validate(tmp_path, config)
        assert r.returncode == 0  # unknown keys are warnings not errors
        codes = self._diag_codes(r)
        assert "W005" in codes
        # Check suggestion is present
        diags = json.loads(r.stdout)["diagnostics"]
        w005 = [d for d in diags if d["code"] == "W005"][0]
        assert "pipeline" in w005["message"]

    def test_summary_format_backward_compat(self, tmp_path):
        """Default summary format includes core fields."""
        config = {"version": "1", "pipeline": {"stages": []}}
        r = self._validate(tmp_path, config, fmt="summary")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "valid" in data
        assert "pipeline_mode" in data
        assert "isolation_mode" in data
        assert "role_count" in data
        assert "stage_count" in data
        assert "profile_count" in data
        assert "errors" in data
        assert "warnings" in data

    def test_version_2_accepted(self, tmp_path):
        """Version 2 config validates cleanly."""
        config = {"version": "2", "isolation": "branch"}
        r = self._validate(tmp_path, config)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["valid"] is True

    def test_version_1_new_shape_info(self, tmp_path):
        """I003: version 1 config with new shape suggests version 2."""
        config = {"version": "1", "isolation": "branch", "pipeline": {"stages": []}}
        r = self._validate(tmp_path, config)
        assert r.returncode == 0
        diags = json.loads(r.stdout)["diagnostics"]
        codes = [d["code"] for d in diags]
        assert "I003" in codes
        i003 = [d for d in diags if d["code"] == "I003"][0]
        assert "version" in i003["message"].lower()


# ---------------------------------------------------------------------------
# Migration (v2.5)
# ---------------------------------------------------------------------------


class TestMigration:
    """Tests for the migrate.py migration engine via migrate CLI command."""

    def _make_legacy_config(self, tmp_path, overrides=None):
        config = {
            "version": "1",
            "team": {
                "pipeline": "standalone",
                "parallel_writes": {"mode": "serial"},
            },
            "roles": {},
            "pipeline": {"stages": []},
        }
        if overrides:
            config.update(overrides)
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path

    def test_migrate_legacy_to_current(self, tmp_path):
        """Full legacy config migrates to version 2 canonical format."""
        self._make_legacy_config(tmp_path)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["dry_run"] is False
        assert len(result["changes"]) > 0

        # Verify migrated file exists and is version 2
        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        assert migrated_path.exists()
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert str(migrated["version"]) == "2"
        assert "team" not in migrated
        assert migrated.get("isolation") == "branch"

    def test_migrate_dry_run(self, tmp_path):
        """--dry-run shows changes without writing files."""
        self._make_legacy_config(tmp_path)
        r = run_rt("migrate", "--dry-run", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["dry_run"] is True
        assert len(result["changes"]) > 0
        # No new file created
        assert not (tmp_path / ".agenteam" / "config.yaml").exists()
        # Original still exists
        assert (tmp_path / "agenteam.yaml").exists()

    def test_migrate_already_current(self, tmp_path):
        """Version 2 config is a no-op."""
        config = {"version": "2", "isolation": "branch", "pipeline": {"stages": []}}
        config_dir = tmp_path / ".agenteam"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["changes"] == []
        assert "canonical" in result["message"].lower()

    def test_migrate_mixed_format(self, tmp_path):
        """Config with both legacy and new keys: legacy removed, new preserved."""
        config = {
            "version": "1",
            "isolation": "worktree",
            "team": {"parallel_writes": {"mode": "serial"}},
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0

        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert migrated["isolation"] == "worktree"  # new key preserved
        assert "team" not in migrated

    def test_migrate_file_relocation(self, tmp_path):
        """agenteam.yaml is relocated to .agenteam/config.yaml, old renamed to .bak."""
        self._make_legacy_config(tmp_path)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0

        # Old file renamed to .bak
        assert not (tmp_path / "agenteam.yaml").exists()
        bak_files = list(tmp_path.glob("agenteam.yaml.bak-*"))
        assert len(bak_files) == 1

        # New file at correct location
        assert (tmp_path / ".agenteam" / "config.yaml").exists()

    def test_migrate_in_place(self, tmp_path):
        """.agenteam/config.yaml with legacy keys updates in place with backup."""
        config = {
            "version": "1",
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "worktree"}},
            "pipeline": {"stages": []},
        }
        config_dir = tmp_path / ".agenteam"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0

        # Backup created
        bak_files = list(config_dir.glob("config.yaml.bak-*"))
        assert len(bak_files) == 1

        # Migrated in place
        with open(config_path) as f:
            migrated = yaml.safe_load(f)
        assert str(migrated["version"]) == "2"
        assert migrated.get("pipeline") == "hotl"
        assert migrated.get("isolation") == "worktree"

    def test_migrate_hotl_pipeline(self, tmp_path):
        """team.pipeline: hotl -> pipeline: hotl."""
        self._make_legacy_config(tmp_path, overrides={
            "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
        })
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert migrated.get("pipeline") == "hotl"

    def test_migrate_serial_to_branch(self, tmp_path):
        """team.parallel_writes.mode: serial -> isolation: branch."""
        self._make_legacy_config(tmp_path)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert migrated.get("isolation") == "branch"

    def test_migrate_worktree_isolation(self, tmp_path):
        """team.parallel_writes.mode: worktree -> isolation: worktree."""
        self._make_legacy_config(tmp_path, overrides={
            "team": {"pipeline": "standalone", "parallel_writes": {"mode": "worktree"}},
        })
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert migrated.get("isolation") == "worktree"

    def test_migrate_idempotent(self, tmp_path):
        """Running migrate on version 2 config is a no-op."""
        config = {"version": "2", "isolation": "branch"}
        config_dir = tmp_path / ".agenteam"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["changes"] == []

    def test_migrate_final_verify_string_to_list(self, tmp_path):
        """final_verify string is normalized to list."""
        config = {
            "version": "1",
            "final_verify": "python3 -m pytest -v",
            "pipeline": {"stages": []},
        }
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        migrated_path = tmp_path / ".agenteam" / "config.yaml"
        with open(migrated_path) as f:
            migrated = yaml.safe_load(f)
        assert isinstance(migrated["final_verify"], list)
        assert migrated["final_verify"] == ["python3 -m pytest -v"]

    def test_migrate_backup_timestamped(self, tmp_path):
        """Backup filename contains timestamp pattern."""
        self._make_legacy_config(tmp_path)
        r = run_rt("migrate", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        backup = result["backup"]
        assert ".bak-" in backup
        # Pattern: .bak-YYYYMMDDTHHMMSSZ
        import re
        assert re.search(r"\.bak-\d{8}T\d{6}Z", backup)
