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
