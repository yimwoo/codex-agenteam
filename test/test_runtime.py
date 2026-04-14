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


def _assert_decision_help(cwd: str) -> str:
    """Return decision help output and assert canonical command exists."""
    help_result = run_rt("decision", "--help", cwd=cwd)
    assert help_result.returncode == 0, help_result.stderr
    return help_result.stdout


def _run_decision_append(cwd: str, payload: dict) -> subprocess.CompletedProcess:
    """Append a decision record using the documented append interface."""
    append_help = run_rt("decision", "append", "--help", cwd=cwd)
    assert append_help.returncode == 0, append_help.stderr
    args = ["decision", "append"]
    flag_map = {
        "outcome": "--outcome",
        "role": "--role",
        "run_id": "--run-id",
        "stage": "--stage",
        "initiative": "--initiative",
        "phase": "--phase",
        "checkpoint": "--checkpoint",
        "artifact_type": "--artifact-type",
        "artifact_ref": "--artifact-ref",
        "decision_right": "--decision-right",
        "tripwire_id": "--tripwire-id",
        "summary": "--summary",
        "rationale": "--rationale",
        "human_disposition": "--human-disposition",
    }
    normalized = dict(payload)
    if "artifact" in payload and "artifact_ref" not in normalized:
        normalized["artifact_ref"] = payload["artifact"]
    if "rationale_ref" in payload and "rationale" not in normalized:
        normalized["rationale"] = payload["rationale_ref"]
    for key, flag in flag_map.items():
        if flag in append_help.stdout and key in normalized and normalized[key] is not None:
            args.extend([flag, str(normalized[key])])
    return run_rt(*args, cwd=cwd)


def _standup_governance_value(standup: dict, key: str):
    """Read a governance field from either standup.governance or standup.run."""
    governance = standup.get("governance")
    if isinstance(governance, dict) and key in governance:
        return governance.get(key)
    run = standup.get("run")
    if isinstance(run, dict) and key in run:
        return run.get(key)
    return None


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


def discoverable_state(run_id: str, **overrides) -> dict:
    """Build a minimal runtime-managed state payload for discovery tests."""
    state = {
        "run_id": run_id,
        "task": "test task",
        "pipeline_mode": "standalone",
        "current_stage": "research",
        "stage_order": ["research"],
        "started_at": "2026-03-30T00:00:00Z",
        "last_update": "2026-03-30T00:00:00Z",
        "status": "running",
        "branch": None,
        "stages": {"research": {"status": "pending", "roles": ["researcher"], "gate": "auto"}},
        "write_locks": {"active": None, "queue": []},
    }
    state.update(overrides)
    return state


def write_history_entry(
    tmp_path: Path, run_id: str, lessons: dict, task: str = "prior task"
) -> None:
    """Write a synthetic history entry for visible-memory tests."""
    history_dir = tmp_path / ".agenteam" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": run_id,
        "task": task,
        "status": "completed",
        "profile": None,
        "stages": [],
        "rework_history": [],
        "lessons": {
            "verify_failures": [],
            "rework_edges": [],
            "gate_rejections": [],
            "gate_overrides": [],
            "skipped_stages": [],
            "final_verify_passed": True,
            "total_stages": 7,
            "completed_stages": 7,
            "profile_used": None,
            **lessons,
        },
    }
    with open(history_dir / f"{run_id}.json", "w") as f:
        json.dump(entry, f, indent=2)


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

    def test_generate_uses_config_project_root_when_config_flag_is_set(self, tmp_path):
        config_dir = tmp_path / ".agenteam"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        with open(TEMPLATE) as f:
            config = yaml.safe_load(f)
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        other_cwd = tmp_path / "outside"
        other_cwd.mkdir()

        r = run_rt("--config", str(config_path), "generate", cwd=str(other_cwd))
        assert r.returncode == 0

        assert (tmp_path / ".codex" / "agents" / "architect.toml").exists()
        assert not (other_cwd / ".codex" / "agents" / "architect.toml").exists()


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

    def test_status_skips_incompatible_latest_state(self, tmp_path):
        """status without run-id skips latest discoverable run with unknown roles."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        compatible = {
            "run_id": "20260401T000001Z",
            "task": "compatible run",
            "status": "running",
            "last_update": "2026-04-01T00:00:01Z",
            "stages": {"implement": {"status": "pending", "roles": ["dev"], "gate": "auto"}},
        }
        incompatible = {
            "run_id": "20260401T000002Z",
            "task": "legacy run",
            "status": "running",
            "last_update": "2026-04-01T00:00:02Z",
            "stages": {
                "implement": {"status": "pending", "roles": ["implementer"], "gate": "auto"}
            },
        }

        with open(state_dir / f"{compatible['run_id']}.json", "w") as f:
            json.dump(compatible, f)
        with open(state_dir / f"{incompatible['run_id']}.json", "w") as f:
            json.dump(incompatible, f)

        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["run_id"] == compatible["run_id"]
        assert state["task"] == "compatible run"

    def test_status_incompatible_only_returns_actionable_error(self, tmp_path):
        """status without run-id returns an actionable error when only legacy runs exist."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        incompatible = {
            "run_id": "20260401T000002Z",
            "task": "legacy run",
            "status": "running",
            "last_update": "2026-04-01T00:00:02Z",
            "stages": {
                "implement": {"status": "pending", "roles": ["implementer"], "gate": "auto"}
            },
        }
        with open(state_dir / f"{incompatible['run_id']}.json", "w") as f:
            json.dump(incompatible, f)

        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode != 0
        error = json.loads(r.stderr)
        assert "No compatible runs found" in error["error"]

    def test_status_ignores_legacy_scratch_state_without_run_id(self, tmp_path):
        """Implicit status should ignore incomplete legacy scratch state files."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        with open(state_dir / "20260330T000000Z.json", "w") as f:
            json.dump({"run_id": "20260330T000000Z", "stages": {}}, f)

        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "No runs found" in r.stderr

    def test_status_includes_visible_memory_from_compatible_history(self, tmp_path):
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "current task", cwd=str(tmp_path))
        assert init_r.returncode == 0
        current_run_id = json.loads(init_r.stdout)["run_id"]

        prior_run_id = "20260401T000001Z"
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / f"{prior_run_id}.json", "w") as f:
            json.dump(
                discoverable_state(
                    prior_run_id,
                    task="prior task",
                    status="completed",
                    stages={"implement": {"status": "completed", "roles": ["dev"], "gate": "auto"}},
                ),
                f,
            )
        write_history_entry(
            tmp_path,
            prior_run_id,
            {
                "verify_failures": [
                    {"stage": "implement", "attempts": 2, "final_result": "pass"},
                ]
            },
        )

        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["run_id"] == current_run_id
        assert "memory" in result
        assert len(result["memory"]["items"]) == 1
        assert result["memory"]["items"][0]["type"] == "verify_failure"
        assert result["memory"]["items"][0]["source_run_id"] == prior_run_id
        assert result["memory"]["items"][0]["stage"] == "implement"

    def test_status_memory_ignores_incompatible_history_state(self, tmp_path):
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "current task", cwd=str(tmp_path))
        assert init_r.returncode == 0

        prior_run_id = "20260401T000001Z"
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / f"{prior_run_id}.json", "w") as f:
            json.dump(
                discoverable_state(
                    prior_run_id,
                    task="legacy task",
                    status="completed",
                    stages={
                        "implement": {
                            "status": "completed",
                            "roles": ["implementer"],
                            "gate": "auto",
                        }
                    },
                ),
                f,
            )
        write_history_entry(
            tmp_path,
            prior_run_id,
            {
                "gate_rejections": [
                    {"stage": "review", "gate_type": "human"},
                ]
            },
            task="legacy task",
        )

        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["memory"]["items"] == []
        assert result["memory"]["summary"] == "No compatible prior memory."

    def test_status_no_runs(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("status", cwd=str(tmp_path))
        assert r.returncode != 0

    def test_path_traversal_run_id_rejected(self, tmp_path):
        """Run IDs with path traversal characters are rejected."""
        make_config(tmp_path)
        r = run_rt(
            "dispatch",
            "implement",
            "--run-id",
            "../../etc/passwd",
            "--task",
            "test",
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
            "dispatch",
            "implement",
            "--run-id",
            run_id,
            "--task",
            "test",
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
                json.dump(discoverable_state(run_id), f)

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

    def test_health_ignores_legacy_scratch_state(self, tmp_path):
        make_config(tmp_path)
        env = make_home_env(tmp_path)

        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True)
        with open(state_dir / "20260330T010805Z.json", "w") as f:
            json.dump({"run_id": "20260330T010805Z", "stages": {}}, f)

        r = run_rt("health", cwd=str(tmp_path), env=env)

        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["latest_run_id"] is None

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
        assert result["memory"]["items"] == []
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

    def test_standup_includes_visible_memory(self, tmp_path):
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "current task", cwd=str(tmp_path))
        assert init_r.returncode == 0

        prior_run_id = "20260401T000001Z"
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / f"{prior_run_id}.json", "w") as f:
            json.dump(
                discoverable_state(
                    prior_run_id,
                    task="prior task",
                    status="completed",
                    stages={"test": {"status": "completed", "roles": ["qa"], "gate": "auto"}},
                ),
                f,
            )
        write_history_entry(
            tmp_path,
            prior_run_id,
            {
                "rework_edges": [
                    {"from_stage": "test", "to_stage": "implement"},
                ]
            },
        )

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "memory" in result
        assert len(result["memory"]["items"]) == 1
        assert result["memory"]["items"][0]["type"] == "rework_edge"
        assert result["memory"]["items"][0]["source_run_id"] == prior_run_id
        assert result["memory"]["items"][0]["stage"] == "test"

    def test_standup_ignores_legacy_scratch_state(self, tmp_path):
        """Standup should ignore incomplete legacy scratch state files."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "20260330T045144Z.json", "w") as f:
            json.dump(
                {
                    "run_id": "20260330T045144Z",
                    "task": "team initialization",
                    "current_stage": "research",
                    "stages": {"research": {"status": "pending", "roles": ["researcher"]}},
                },
                f,
            )

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["health"] == "no-active-run"
        assert result["run"] is None
        assert result["stages"] == {}

    def test_standup_ignores_incompatible_latest_state(self, tmp_path):
        """standup should ignore latest discoverable run if it references unknown roles."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        compatible = {
            "run_id": "20260401T000001Z",
            "task": "compatible run",
            "current_stage": "implement",
            "status": "running",
            "last_update": "2026-04-01T00:00:01Z",
            "stages": {"implement": {"status": "pending", "roles": ["dev"], "gate": "auto"}},
        }
        incompatible = {
            "run_id": "20260401T000002Z",
            "task": "legacy run",
            "current_stage": "implement",
            "status": "running",
            "last_update": "2026-04-01T00:00:02Z",
            "stages": {
                "implement": {"status": "pending", "roles": ["implementer"], "gate": "auto"}
            },
        }

        with open(state_dir / f"{compatible['run_id']}.json", "w") as f:
            json.dump(compatible, f)
        with open(state_dir / f"{incompatible['run_id']}.json", "w") as f:
            json.dump(incompatible, f)

        r = run_rt("standup", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["run"] is not None
        assert result["run"]["run_id"] == compatible["run_id"]
        assert any("Ignored stale local run state" in warning for warning in result["warnings"])

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

    def test_standup_uses_config_roles_when_demo_state_has_legacy_role_names(self, tmp_path):
        """Legacy role names in stale/demo state must not leak into standup role output."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "20260330T045144Z.json", "w") as f:
            json.dump(
                {
                    "run_id": "20260330T045144Z",
                    "task": "demo run",
                    "pipeline_mode": "standalone",
                    "current_stage": "implement",
                    "stages": {
                        "implement": {"status": "pending", "roles": ["implementer"]},
                        "test": {"status": "pending", "roles": ["test_writer"]},
                    },
                },
                f,
            )

        r = run_rt("standup", "--dispatch", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert set(result["roles"]) == {"researcher", "pm", "architect", "dev", "qa", "reviewer"}
        assert "implementer" not in result["roles"]
        assert "test_writer" not in result["roles"]
        assert {item["role"] for item in result["dispatch"]} == {"researcher", "architect", "pm"}


# ---------------------------------------------------------------------------
# Governed Delivery Foundations (v3.3)
# ---------------------------------------------------------------------------


class TestGovernedDeliveryFoundations:
    def test_governance_bootstrap_creates_expected_assets(self, tmp_path):
        make_config(tmp_path)

        result = run_rt("governed-bootstrap", cwd=str(tmp_path))
        assert result.returncode == 0, result.stderr

        assert (tmp_path / ".agenteam" / "governance" / "operating-model.yaml").exists()
        assert (tmp_path / ".agenteam" / "governance" / "tripwires.yaml").exists()
        assert (tmp_path / ".agenteam" / "governance" / "lifecycle.json").exists()
        assert (tmp_path / ".agenteam" / "governance" / "decisions.jsonl").exists()
        assert (tmp_path / ".agenteam" / "governance" / "playbooks" / "README.md").exists()
        assert (tmp_path / "docs" / "decisions" / "log.md").exists()
        tripwires_text = (tmp_path / ".agenteam" / "governance" / "tripwires.yaml").read_text()
        assert "public-api-change" in tripwires_text
        assert "auth-surface-change" in tripwires_text

    def test_governance_bootstrap_is_idempotent(self, tmp_path):
        make_config(tmp_path)

        first = run_rt("governed-bootstrap", cwd=str(tmp_path))
        assert first.returncode == 0, first.stderr
        second = run_rt("governed-bootstrap", cwd=str(tmp_path))
        assert second.returncode == 0, second.stderr
        payload = json.loads(second.stdout)
        assert payload["created"] == []

    def test_decision_append_list_and_render_log(self, tmp_path):
        make_config(tmp_path)
        init = run_rt("init", "--task", "decision-flow", cwd=str(tmp_path))
        assert init.returncode == 0
        run_id = json.loads(init.stdout)["run_id"]

        decision_one = {
            "outcome": "autonomous",
            "role": "architect",
            "run_id": run_id,
            "stage": "design",
            "initiative": "governed-delivery-foundations",
            "phase": "v3.3",
            "checkpoint": "kickoff",
            "escalation_status": "none",
            "artifact": "docs/plans/2026-04-14-v33-governed-delivery-foundations-design.md",
            "summary": "Use JSONL as canonical decision storage.",
            "rationale_ref": (
                "docs/requirements/2026-04-14-" "governed-delivery-foundations-requirements.md"
            ),
        }
        decision_two = {
            "outcome": "escalated",
            "role": "pm",
            "run_id": run_id,
            "stage": "plan",
            "initiative": "governed-delivery-foundations",
            "phase": "v3.3",
            "checkpoint": "plan-review",
            "escalation_status": "open",
            "summary": "Escalate scope expansion beyond foundations release boundary.",
            "rationale_ref": "docs/designs/2026-04-14-governed-delivery-release-recommendation.md",
        }

        append_one = _run_decision_append(str(tmp_path), decision_one)
        assert append_one.returncode == 0, append_one.stderr
        append_two = _run_decision_append(str(tmp_path), decision_two)
        assert append_two.returncode == 0, append_two.stderr

        help_text = _assert_decision_help(str(tmp_path))
        assert "append" in help_text
        assert "list" in help_text
        assert "render-log" in help_text

        listed = run_rt("decision", "list", cwd=str(tmp_path))
        assert listed.returncode == 0, listed.stderr
        payload = json.loads(listed.stdout)
        if isinstance(payload, list):
            entries = payload
        else:
            entries = (
                payload.get("entries")
                or payload.get("decisions")
                or payload.get("items")
                or payload.get("records")
                or []
            )
        summaries = {entry.get("summary") for entry in entries if isinstance(entry, dict)}
        assert "Use JSONL as canonical decision storage." in summaries
        assert "Escalate scope expansion beyond foundations release boundary." in summaries

        rendered = run_rt("decision", "render-log", cwd=str(tmp_path))
        assert rendered.returncode == 0, rendered.stderr
        log_path = tmp_path / "docs" / "decisions" / "log.md"
        assert log_path.exists()
        log_text = log_path.read_text()
        assert "Use JSONL as canonical decision storage." in log_text
        assert "Escalate scope expansion beyond foundations release boundary." in log_text

    def test_decision_append_rejects_invalid_outcome(self, tmp_path):
        make_config(tmp_path)
        init = run_rt("init", "--task", "decision-validation", cwd=str(tmp_path))
        assert init.returncode == 0
        run_id = json.loads(init.stdout)["run_id"]

        invalid_decision = {
            "outcome": "maybe",
            "role": "architect",
            "run_id": run_id,
            "stage": "design",
            "summary": "Invalid outcome should be rejected.",
        }
        append_invalid = _run_decision_append(str(tmp_path), invalid_decision)
        assert append_invalid.returncode != 0
        error_text = (append_invalid.stderr or append_invalid.stdout).lower()
        assert "outcome" in error_text or "invalid" in error_text

    def test_decision_append_rejects_unknown_run_id(self, tmp_path):
        make_config(tmp_path)

        append_invalid = _run_decision_append(
            str(tmp_path),
            {
                "outcome": "autonomous",
                "role": "architect",
                "run_id": "20260414T999999Z",
                "stage": "design",
                "summary": "Unknown run should be rejected.",
            },
        )
        assert append_invalid.returncode != 0
        error_text = (append_invalid.stderr or append_invalid.stdout).lower()
        assert "run" in error_text and "not found" in error_text

    def test_decision_append_rejects_invalid_human_disposition(self, tmp_path):
        make_config(tmp_path)
        init = run_rt("init", "--task", "decision-validation", cwd=str(tmp_path))
        assert init.returncode == 0
        run_id = json.loads(init.stdout)["run_id"]

        append_invalid = run_rt(
            "decision",
            "append",
            "--outcome",
            "escalated",
            "--role",
            "architect",
            "--run-id",
            run_id,
            "--stage",
            "design",
            "--summary",
            "Disposition should be validated.",
            "--human-disposition",
            "maybe",
            cwd=str(tmp_path),
        )
        assert append_invalid.returncode != 0
        error_text = (append_invalid.stderr or append_invalid.stdout).lower()
        assert "human-disposition" in error_text or "invalid" in error_text

    def test_decision_list_rejects_malformed_jsonl(self, tmp_path):
        make_config(tmp_path)
        decisions_path = tmp_path / ".agenteam" / "governance" / "decisions.jsonl"
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        decisions_path.write_text('{"ok": true}\nnot-json\n')

        listed = run_rt("decision", "list", cwd=str(tmp_path))
        assert listed.returncode != 0
        error_text = (listed.stderr or listed.stdout).lower()
        assert "malformed decision log" in error_text

    def test_governance_metadata_absent_by_default_and_visible_when_present(self, tmp_path):
        make_config(tmp_path)
        init = run_rt("init", "--task", "governance-optional", cwd=str(tmp_path))
        assert init.returncode == 0
        run_id = json.loads(init.stdout)["run_id"]

        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            default_state = json.load(f)
        assert "initiative" not in default_state
        assert "phase" not in default_state
        assert "checkpoint" not in default_state
        assert "escalation_status" not in default_state

        status_default = run_rt("status", run_id, cwd=str(tmp_path))
        assert status_default.returncode == 0
        status_default_payload = json.loads(status_default.stdout)
        assert "initiative" not in status_default_payload
        assert "phase" not in status_default_payload
        assert "checkpoint" not in status_default_payload
        assert "escalation_status" not in status_default_payload

        standup_default = run_rt("standup", cwd=str(tmp_path))
        assert standup_default.returncode == 0
        standup_default_payload = json.loads(standup_default.stdout)
        assert _standup_governance_value(standup_default_payload, "initiative") is None
        assert _standup_governance_value(standup_default_payload, "phase") is None
        assert _standup_governance_value(standup_default_payload, "checkpoint") is None
        assert _standup_governance_value(standup_default_payload, "escalation_status") is None

        default_state["initiative"] = "governed-delivery-foundations"
        default_state["phase"] = "v3.3"
        default_state["checkpoint"] = "plan-review"
        default_state["escalation_status"] = "open"
        with open(state_path, "w") as f:
            json.dump(default_state, f, indent=2)

        status_with_meta = run_rt("status", run_id, cwd=str(tmp_path))
        assert status_with_meta.returncode == 0
        status_payload = json.loads(status_with_meta.stdout)
        assert status_payload["initiative"] == "governed-delivery-foundations"
        assert status_payload["phase"] == "v3.3"
        assert status_payload["checkpoint"] == "plan-review"
        assert status_payload["escalation_status"] == "open"

        standup_with_meta = run_rt("standup", cwd=str(tmp_path))
        assert standup_with_meta.returncode == 0
        standup_payload = json.loads(standup_with_meta.stdout)
        assert _standup_governance_value(standup_payload, "initiative") == (
            "governed-delivery-foundations"
        )
        assert _standup_governance_value(standup_payload, "phase") == "v3.3"
        assert _standup_governance_value(standup_payload, "checkpoint") == "plan-review"
        assert _standup_governance_value(standup_payload, "escalation_status") == "open"

    def test_init_rejects_invalid_burn_estimate(self, tmp_path):
        make_config(tmp_path)

        init = run_rt(
            "init",
            "--task",
            "bad-burn-estimate",
            "--burn-estimate",
            "many",
            cwd=str(tmp_path),
        )
        assert init.returncode != 0
        error_text = (init.stderr or init.stdout).lower()
        assert "burn-estimate" in error_text or "numeric" in error_text

    def test_governed_bootstrap_honors_global_config_outside_repo_root(self, tmp_path):
        config_path = make_config(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()

        result = run_rt(
            "--config",
            str(config_path),
            "governed-bootstrap",
            cwd=str(outside),
        )
        assert result.returncode == 0, result.stderr

        assert (tmp_path / ".agenteam" / "governance" / "operating-model.yaml").exists()
        assert (tmp_path / "docs" / "decisions" / "log.md").exists()
        assert not (outside / ".agenteam" / "governance" / "operating-model.yaml").exists()

    def test_decision_commands_honor_global_config_outside_repo_root(self, tmp_path):
        config_path = make_config(tmp_path)
        init = run_rt("init", "--task", "outside-root-decision", cwd=str(tmp_path))
        assert init.returncode == 0
        run_id = json.loads(init.stdout)["run_id"]

        outside = tmp_path / "outside"
        outside.mkdir()

        append = run_rt(
            "--config",
            str(config_path),
            "decision",
            "append",
            "--outcome",
            "autonomous",
            "--role",
            "architect",
            "--run-id",
            run_id,
            "--stage",
            "design",
            "--summary",
            "Append from outside repo root.",
            cwd=str(outside),
        )
        assert append.returncode == 0, append.stderr

        listed = run_rt(
            "--config",
            str(config_path),
            "decision",
            "list",
            "--run-id",
            run_id,
            cwd=str(outside),
        )
        assert listed.returncode == 0, listed.stderr
        payload = json.loads(listed.stdout)
        assert any(entry.get("summary") == "Append from outside repo root." for entry in payload)

    def test_tripwire_check_matches_warn_and_block_rules(self, tmp_path):
        make_config(tmp_path)
        run_rt("governed-bootstrap", cwd=str(tmp_path))

        check = run_rt(
            "tripwire",
            "check",
            "--path",
            "src/auth/login.py",
            "--path",
            "src/api/public.py",
            cwd=str(tmp_path),
        )
        assert check.returncode == 0, check.stderr
        payload = json.loads(check.stdout)
        assert "auth-surface-change" in payload["block"]
        assert "public-api-change" in payload["warn"]

    def test_tripwire_check_matches_decision_right_rule(self, tmp_path):
        make_config(tmp_path)
        run_rt("governed-bootstrap", cwd=str(tmp_path))

        check = run_rt(
            "tripwire",
            "check",
            "--artifact-type",
            "adr",
            "--decision-right",
            "schema-change",
            cwd=str(tmp_path),
        )
        assert check.returncode == 0, check.stderr
        payload = json.loads(check.stdout)
        assert "adr-required" in payload["warn"]
        assert payload["block"] == []

    def test_tripwire_check_rejects_malformed_config(self, tmp_path):
        make_config(tmp_path)
        tripwires_path = tmp_path / ".agenteam" / "governance" / "tripwires.yaml"
        tripwires_path.parent.mkdir(parents=True, exist_ok=True)
        tripwires_path.write_text("tripwires: [\n")

        check = run_rt("tripwire", "check", cwd=str(tmp_path))
        assert check.returncode != 0
        error_text = (check.stderr or check.stdout).lower()
        assert "malformed tripwires config" in error_text

    def test_tripwire_check_honors_global_config_outside_repo_root(self, tmp_path):
        config_path = make_config(tmp_path)
        run_rt("governed-bootstrap", cwd=str(tmp_path))
        outside = tmp_path / "outside"
        outside.mkdir()

        check = run_rt(
            "--config",
            str(config_path),
            "tripwire",
            "check",
            "--path",
            "src/auth/session.py",
            cwd=str(outside),
        )
        assert check.returncode == 0, check.stderr
        payload = json.loads(check.stdout)
        assert "auth-surface-change" in payload["block"]


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
        merged = discoverable_state(run_id)
        merged.update(state)
        with open(state_dir / f"{run_id}.json", "w") as f:
            json.dump(merged, f)

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

    def test_status_with_explicit_legacy_run_id_still_returns_state(self, tmp_path):
        """Explicit run-id lookup remains backward compatible for legacy state files."""
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "20260330T000000Z.json", "w") as f:
            json.dump({"run_id": "20260330T000000Z", "stages": {}}, f)

        r = run_rt("status", "20260330T000000Z", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["run_id"] == "20260330T000000Z"

    def test_status_nonexistent_run_id(self, tmp_path):
        """status with a run-id that doesn't exist should exit non-zero."""
        make_config(tmp_path)
        r = run_rt("status", "99991231T999999Z", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_status_run_id_is_stable_with_newer_demo_state_present(self, tmp_path):
        """Explicit run-id lookup should ignore unrelated newer state files."""
        make_config(tmp_path)
        init_r = run_rt("init", "--task", "real task", cwd=str(tmp_path))
        assert init_r.returncode == 0
        real_run_id = json.loads(init_r.stdout)["run_id"]

        state_dir = tmp_path / ".agenteam" / "state"
        with open(state_dir / "99991231T999999Z.json", "w") as f:
            json.dump(
                {
                    "run_id": "99991231T999999Z",
                    "task": "demo task",
                    "status": "running",
                    "stages": {},
                },
                f,
            )

        r = run_rt("status", real_run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["run_id"] == real_run_id
        assert state["task"] == "real task"


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
                {
                    "name": "implement",
                    "roles": ["dev"],
                    "gate": "auto",
                    "verify": "python3 -m pytest tests/ -v",
                    "max_retries": 2,
                },
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
                    {
                        "name": "implement",
                        "roles": ["dev"],
                        "gate": "auto",
                        "verify": "python3 -m pytest -v",
                        "max_retries": 2,
                    },
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
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--result",
            "pass",
            "--output",
            "all tests passed",
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
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--result",
            "fail",
            "--output",
            "2 tests failed",
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
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--result",
            "fail",
            cwd=str(tmp_path),
        )
        # Second attempt: pass
        r = run_rt(
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--result",
            "pass",
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
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "nonexistent",
            "--result",
            "pass",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_record_verify_nonexistent_run(self, tmp_path):
        """Recording verify for a nonexistent run returns error."""
        self._setup_run(tmp_path)
        r = run_rt(
            "record-verify",
            "--run-id",
            "99991231T999999Z",
            "--stage",
            "implement",
            "--result",
            "pass",
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
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--gate-type",
            "reviewer",
            "--result",
            "approved",
            "--verdict",
            "PASS WITH WARNINGS: 2 WARN findings",
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
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--gate-type",
            "reviewer",
            "--result",
            "rejected",
            "--verdict",
            "BLOCK: missing error handling",
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
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "design",
            "--gate-type",
            "human",
            "--result",
            "approved",
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
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "nonexistent",
            "--gate-type",
            "auto",
            "--result",
            "approved",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_record_gate_nonexistent_run(self, tmp_path):
        """Recording a gate for a nonexistent run returns error."""
        self._setup_run(tmp_path)
        r = run_rt(
            "record-gate",
            "--run-id",
            "99991231T999999Z",
            "--stage",
            "implement",
            "--gate-type",
            "reviewer",
            "--result",
            "approved",
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
        self._make_scoped_config(
            tmp_path,
            {
                "alpha": {"can_write": True, "write_scope": ["src/**"]},
                "beta": {"can_write": True, "write_scope": ["lib/**"]},
                "gamma": {"can_write": True, "write_scope": ["docs/**"]},
            },
            ["alpha", "beta", "gamma"],
        )

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
        self._make_scoped_config(
            tmp_path,
            {
                "alpha": {"can_write": True, "write_scope": ["src/**"]},
                "beta": {"can_write": True, "write_scope": ["src/**", "lib/**"]},
            },
            ["alpha", "beta"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert len(plan["groups"]) == 2
        assert plan["groups"][0]["roles"][0]["role"] == "alpha"
        assert plan["groups"][1]["roles"][0]["role"] == "beta"

    def test_mixed_overlapping_non_overlapping(self, tmp_path):
        """Mixed: alpha+gamma share no scopes, beta overlaps with alpha."""
        self._make_scoped_config(
            tmp_path,
            {
                "alpha": {"can_write": True, "write_scope": ["src/**"]},
                "beta": {"can_write": True, "write_scope": ["src/**"]},
                "gamma": {"can_write": True, "write_scope": ["docs/**"]},
            },
            ["alpha", "beta", "gamma"],
        )

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
        self._make_scoped_config(
            tmp_path,
            {
                "writer": {"can_write": True, "write_scope": ["src/**"]},
                "reader": {"can_write": False, "write_scope": []},
            },
            ["writer", "reader"],
        )

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
        self._make_scoped_config(
            tmp_path,
            {
                "solo": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["solo"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert len(plan["groups"]) == 1
        assert plan["groups"][0]["roles"][0]["role"] == "solo"

    def test_no_writers_zero_groups(self, tmp_path):
        """Stage with only read-only roles produces zero groups."""
        self._make_scoped_config(
            tmp_path,
            {
                "reader_a": {"can_write": False},
                "reader_b": {"can_write": False},
            },
            ["reader_a", "reader_b"],
        )

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
        self._make_config(
            tmp_path,
            "none",
            {
                "w1": {"can_write": True, "write_scope": ["src/**"]},
                "w2": {"can_write": True, "write_scope": ["lib/**"]},
            },
            ["w1", "w2"],
        )

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
        self._make_config(
            tmp_path,
            "none",
            {
                "w1": {"can_write": True, "write_scope": ["src/**"]},
                "w2": {"can_write": True, "write_scope": ["src/**"]},
                "w3": {"can_write": True, "write_scope": ["docs/**"]},
            },
            ["w1", "w2", "w3"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "groups" in plan
        assert len(plan["groups"]) == 2

    def test_isolation_branch_returns_flat_dispatch(self, tmp_path):
        """isolation:branch returns flat dispatch list, no groups key."""
        self._make_config(
            tmp_path,
            "branch",
            {
                "w1": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["w1"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "dispatch" in plan
        assert "groups" not in plan
        assert plan["policy"] == "branch"

    def test_isolation_worktree_returns_flat_dispatch(self, tmp_path):
        """isolation:worktree returns flat dispatch list, no groups key."""
        self._make_config(
            tmp_path,
            "worktree",
            {
                "w1": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["w1"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "dispatch" in plan
        assert "groups" not in plan
        assert plan["policy"] == "worktree"

    def test_read_only_present_in_grouped_dispatch(self, tmp_path):
        """Read-only roles appear in read_only list of grouped dispatch."""
        self._make_config(
            tmp_path,
            "none",
            {
                "writer": {"can_write": True, "write_scope": ["src/**"]},
                "auditor": {"can_write": False},
            },
            ["writer", "auditor"],
        )

        r = run_rt("dispatch", "build", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0
        plan = json.loads(r.stdout)
        assert "auditor" in plan["read_only"]
        assert len(plan["groups"]) == 1

    def test_group_roles_have_correct_agent_paths(self, tmp_path):
        """Each role entry in groups has the correct agent path and mode."""
        self._make_config(
            tmp_path,
            "none",
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
                "qa": {"can_write": True, "write_scope": ["tests/**"]},
            },
            ["dev", "qa"],
        )

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
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        # Initial commit (empty)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
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
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"add {filepath}"],
            cwd=str(path),
            capture_output=True,
            check=True,
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

        self._make_audit_config(
            tmp_path,
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["dev"],
        )

        # Add a file within scope and commit
        self._commit_file(tmp_path, "src/main.py", "print('hello')")

        r = run_rt(
            "scope-audit",
            "--stage",
            "build",
            "--baseline",
            baseline,
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

        self._make_audit_config(
            tmp_path,
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["dev"],
        )

        # Add a file outside scope
        self._commit_file(tmp_path, "config/settings.yaml", "key: val")

        r = run_rt(
            "scope-audit",
            "--stage",
            "build",
            "--baseline",
            baseline,
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

        self._make_audit_config(
            tmp_path,
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["dev"],
        )

        r = run_rt(
            "scope-audit",
            "--stage",
            "build",
            "--baseline",
            baseline,
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

        self._make_audit_config(
            tmp_path,
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
                "qa": {"can_write": True, "write_scope": ["tests/**"]},
            },
            ["dev", "qa"],
        )

        # In-scope files
        self._commit_file(tmp_path, "src/app.py", "app code")
        self._commit_file(tmp_path, "tests/test_app.py", "test code")
        # Out-of-scope file
        self._commit_file(tmp_path, "README.md", "# Readme")

        r = run_rt(
            "scope-audit",
            "--stage",
            "build",
            "--baseline",
            baseline,
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

        self._make_audit_config(
            tmp_path,
            {
                "dev": {"can_write": True, "write_scope": ["src/**"]},
            },
            ["dev"],
        )

        # Commit an out-of-scope file BEFORE baseline
        self._commit_file(tmp_path, "config/old.yaml", "old config")
        baseline = self._get_head(tmp_path)

        # Commit an in-scope file AFTER baseline
        self._commit_file(tmp_path, "src/new.py", "new code")

        r = run_rt(
            "scope-audit",
            "--stage",
            "build",
            "--baseline",
            baseline,
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
                {
                    "name": "implement",
                    "roles": ["dev"],
                    "gate": "auto",
                    "verify": "python3 -m pytest -v",
                    "max_retries": 2,
                },
                {
                    "name": "test",
                    "roles": ["qa"],
                    "gate": "auto",
                    "verify": "python3 -m pytest -v",
                    "max_retries": 2,
                    "rework_to": "implement",
                },
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
            "record-verify",
            "--run-id",
            run_id,
            "--stage",
            "test",
            "--result",
            "fail",
            "--output",
            "2 tests failed",
            "--rework-stage",
            "implement",
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
            {
                "name": "test",
                "roles": ["qa"],
                "gate": "auto",
                "verify": "python3 -m pytest -v",
                "max_retries": 2,
                "rework_to": "nonexistent",
            },
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
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
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
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "capture",
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
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "capture",
            cwd=str(tmp_path),
        )

        # Rollback
        r = run_rt(
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "rollback",
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
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "capture",
            cwd=str(tmp_path),
        )

        # Rollback should be disallowed
        r = run_rt(
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "rollback",
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
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "capture",
            cwd=str(tmp_path),
        )

        r = run_rt(
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "rollback",
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
            "stage-baseline",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--action",
            "rollback",
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
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=str(path),
            capture_output=True,
            check=True,
        )

    @staticmethod
    def _get_head(path):
        """Get HEAD sha."""
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
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
            cwd=str(path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"add {filepath}"],
            cwd=str(path),
            capture_output=True,
            check=True,
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
        run_id, _ = self._setup_run_with_baseline(tmp_path, criteria={"max_files_changed": 1})

        # Create 2 files (exceeds max of 1)
        self._commit_file(tmp_path, "src/a.py", "a")
        self._commit_file(tmp_path, "src/b.py", "b")

        r = run_rt(
            "gate-eval",
            "--run-id",
            run_id,
            "--stage",
            "implement",
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
        run_id, _ = self._setup_run_with_baseline(tmp_path, criteria={"scope_paths": ["src/**"]})

        # Create a file outside scope
        self._commit_file(tmp_path, "config/settings.yaml", "key: val")

        r = run_rt(
            "gate-eval",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["passed"] is False
        assert "scope_paths" in result["failed_criteria"]
        assert "config/settings.yaml" in result["criteria"]["scope_paths"]["actual_out_of_scope"]

    def test_requires_tests_with_no_test_files(self, tmp_path):
        """requires_tests with no test files returns failed_criteria."""
        run_id, _ = self._setup_run_with_baseline(tmp_path, criteria={"requires_tests": True})

        # Create a non-test file only
        self._commit_file(tmp_path, "src/main.py", "code")

        r = run_rt(
            "gate-eval",
            "--run-id",
            run_id,
            "--stage",
            "implement",
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
            tmp_path,
            criteria={
                "max_files_changed": 5,
                "scope_paths": ["src/**", "tests/**"],
                "requires_tests": True,
            },
        )

        # Create files within scope including a test file
        self._commit_file(tmp_path, "src/app.py", "app code")
        self._commit_file(tmp_path, "tests/test_app.py", "test code")

        r = run_rt(
            "gate-eval",
            "--run-id",
            run_id,
            "--stage",
            "implement",
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
            "gate-eval",
            "--run-id",
            run_id,
            "--stage",
            "implement",
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
            "record-gate",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--gate-type",
            "criteria_override",
            "--result",
            "approved",
            "--verdict",
            "Criteria override: max_files_changed (23 > 15)",
            "--criteria-failed",
            '["max_files_changed"]',
            "--criteria-details",
            '{"max_files_changed": {"configured": 15, "actual": 23}}',
            "--override-reason",
            "Bulk rename across 23 files",
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
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "run_started",
            "--data",
            '{"task": "test task", "pipeline_mode": "standalone"}',
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
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "invalid_type",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Unknown event type" in r.stderr

    def test_event_append_validates_required_data(self, tmp_path):
        r = run_rt(
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "run_started",
            "--data",
            '{"task": "test"}',
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "pipeline_mode" in r.stderr

    def test_event_list_returns_events(self, tmp_path):
        for i in range(3):
            run_rt(
                "event",
                "append",
                "--run-id",
                "test-run",
                "--type",
                "run_started",
                "--data",
                json.dumps({"task": f"task-{i}", "pipeline_mode": "standalone"}),
                cwd=str(tmp_path),
            )
        r = run_rt("event", "list", "--run-id", "test-run", cwd=str(tmp_path))
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 3

    def test_event_list_filters_by_type(self, tmp_path):
        run_rt(
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "run_started",
            "--data",
            '{"task": "t", "pipeline_mode": "standalone"}',
            cwd=str(tmp_path),
        )
        run_rt(
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "stage_dispatched",
            "--stage",
            "implement",
            "--data",
            '{"roles": ["dev"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        r = run_rt(
            "event",
            "list",
            "--run-id",
            "test-run",
            "--type",
            "run_started",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 1
        assert events[0]["type"] == "run_started"

    def test_event_list_filters_by_stage(self, tmp_path):
        run_rt(
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "stage_dispatched",
            "--stage",
            "implement",
            "--data",
            '{"roles": ["dev"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        run_rt(
            "event",
            "append",
            "--run-id",
            "test-run",
            "--type",
            "stage_dispatched",
            "--stage",
            "review",
            "--data",
            '{"roles": ["reviewer"], "isolation": "branch"}',
            cwd=str(tmp_path),
        )
        r = run_rt(
            "event",
            "list",
            "--run-id",
            "test-run",
            "--stage",
            "implement",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 1
        assert events[0]["stage"] == "implement"

    def test_event_list_last_n(self, tmp_path):
        for i in range(5):
            run_rt(
                "event",
                "append",
                "--run-id",
                "test-run",
                "--type",
                "run_started",
                "--data",
                json.dumps({"task": f"task-{i}", "pipeline_mode": "standalone"}),
                cwd=str(tmp_path),
            )
        r = run_rt(
            "event",
            "list",
            "--run-id",
            "test-run",
            "--last",
            "2",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        events = json.loads(r.stdout)
        assert len(events) == 2
        assert events[0]["data"]["task"] == "task-3"
        assert events[1]["data"]["task"] == "task-4"

    def test_event_list_empty_for_missing_file(self, tmp_path):
        r = run_rt(
            "event",
            "list",
            "--run-id",
            "nonexistent",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "completed",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
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
            "--run-id",
            run_id,
            "--stage",
            "nonexistent",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_dispatched_to_verifying(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_verifying_to_passed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "passed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_verifying_to_failed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "failed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_failed_to_dispatched(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "failed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_passed_to_gated(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "passed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "gated",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_gated_to_completed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "passed",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "gated",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "completed",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_gated_to_rejected(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "verifying",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "passed",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "gated",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "rejected",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_completed_is_terminal(self, tmp_path):
        run_id = self._init_run(tmp_path)
        # Fast-track: pending -> dispatched -> completed
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "completed",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
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
        # Modify effective config after init
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config.setdefault("roles", {})
        config["roles"].setdefault("architect", {})
        config["roles"]["architect"]["model"] = "o3-pro"
        with open(config_path, "w") as f:
            yaml.dump(config, f)
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

    def test_resume_plan_rejects_legacy_scratch_state(self, tmp_path):
        make_config(tmp_path)
        state_dir = tmp_path / ".agenteam" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(state_dir / "20260330T045144Z.json", "w") as f:
            json.dump({"run_id": "20260330T045144Z", "stages": {}}, f)

        r = run_rt("resume-plan", "--run-id", "20260330T045144Z", cwd=str(tmp_path))
        assert r.returncode != 0
        error = json.loads(r.stderr)
        assert "not resumable" in error["error"]

    def test_resume_plan_layered_config_hash_uses_effective_config(self, tmp_path):
        with open(TEMPLATE) as f:
            team_config = yaml.safe_load(f)

        team_dir = tmp_path / ".agenteam.team"
        team_dir.mkdir(parents=True, exist_ok=True)
        with open(team_dir / "config.yaml", "w") as f:
            yaml.dump(team_config, f)

        personal_dir = tmp_path / ".agenteam"
        personal_dir.mkdir(parents=True, exist_ok=True)
        with open(personal_dir / "config.yaml", "w") as f:
            yaml.dump({"roles": {"architect": {"model": "o3-pro"}}}, f)

        r = run_rt("init", "--task", "layered resume", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]
        self._make_stale(tmp_path, run_id, 15)

        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["config_hash_match"] is True


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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
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
            "--run-id",
            run_id,
            "--stage",
            "review",
            "--role",
            "dev",
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
            "--run-id",
            run_id,
            "--stage",
            "review",
            "--role",
            "reviewer",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
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
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0

    def test_unknown_stage_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "bad": {"stages": ["nonexistent"]},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "unknown stage" in r.stderr

    def test_duplicate_stage_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "bad": {"stages": ["implement", "implement"]},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "duplicate stage" in r.stderr

    def test_empty_stages_in_profile_rejected(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "bad": {"stages": []},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "non-empty list" in r.stderr

    def test_hints_must_be_list_of_strings(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "bad": {"stages": ["implement"], "hints": 42},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode != 0
        assert "hints" in r.stderr

    def test_rework_to_outside_profile_rejected(self, tmp_path):
        # test stage has rework_to: implement, so a profile with test but not implement should fail
        self._make_config_with_profiles(
            tmp_path,
            {
                "bad": {"stages": ["test"]},
            },
        )
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
        r = run_rt("init", "--task", "test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert state["profile"] == "quick"
        assert state["stage_order"] == ["implement", "test"]
        assert set(state["stages"].keys()) == {"implement", "test"}

    def test_init_without_profile_uses_all_stages(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
        r = run_rt("init", "--task", "test", "--profile", "full", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        assert len(state["stage_order"]) == 7

    def test_init_snapshots_full_stage_config(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "reversed": {"stages": ["test", "implement"]},
            },
        )
        r = run_rt("init", "--task", "test", "--profile", "reversed", cwd=str(tmp_path))
        assert r.returncode == 0
        state = json.loads(r.stdout)
        # Pipeline order: implement comes before test
        assert state["stage_order"] == ["implement", "test"]

    def test_init_profile_stores_stage_order(self, tmp_path):
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
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
        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
        # dispatch without --run-id should still find research (from config)
        r = run_rt("dispatch", "research", "--task", "test", cwd=str(tmp_path))
        assert r.returncode == 0

    def test_state_stages_immune_to_config_change(self, tmp_path):
        """After init, changing config should not affect run-scoped commands."""
        import yaml

        self._make_config_with_profiles(
            tmp_path,
            {
                "quick": {"stages": ["implement", "test"]},
            },
        )
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
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["dev"], "gate": "auto"},
                ]
            },
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
            "pipeline": {
                "stages": [
                    {"name": "test", "roles": ["qa"], "gate": "auto"},
                    {"name": "test", "roles": ["dev"], "gate": "auto"},
                ]
            },
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E011" in codes

    def test_rework_to_missing_stage(self, tmp_path):
        """E008: rework_to references non-existent stage."""
        config = {
            "version": "1",
            "pipeline": {
                "stages": [
                    {
                        "name": "implement",
                        "roles": ["dev"],
                        "gate": "auto",
                        "rework_to": "nonexistent",
                    },
                ]
            },
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
            "pipeline": {
                "stages": [
                    {"name": "implement", "roles": ["nonexistent_role"], "gate": "auto"},
                ]
            },
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
            "pipeline": {
                "stages": [
                    {"name": "test", "roles": ["qa"], "gate": "manual"},
                ]
            },
        }
        r = self._validate(tmp_path, config)
        assert r.returncode != 0
        codes = self._diag_codes(r)
        assert "E015" in codes

    def test_invalid_max_retries(self, tmp_path):
        """E016: max_retries must be non-negative integer."""
        config = {
            "version": "1",
            "pipeline": {
                "stages": [
                    {"name": "test", "roles": ["qa"], "gate": "auto", "max_retries": -1},
                ]
            },
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
        self._make_legacy_config(
            tmp_path,
            overrides={
                "team": {"pipeline": "hotl", "parallel_writes": {"mode": "serial"}},
            },
        )
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
        self._make_legacy_config(
            tmp_path,
            overrides={
                "team": {"pipeline": "standalone", "parallel_writes": {"mode": "worktree"}},
            },
        )
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


# ---------------------------------------------------------------------------
# History (cross-run context)
# ---------------------------------------------------------------------------


class TestHistory:
    def _init_run(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "history test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_history_append_creates_file(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["run_id"] == run_id
        assert result["task"] == "history test"
        assert "lessons" in result

        history_path = tmp_path / ".agenteam" / "history" / f"{run_id}.json"
        assert history_path.exists()

    def test_history_append_includes_profile(self, tmp_path):
        import yaml

        with open(TEMPLATE) as f:
            config = yaml.safe_load(f)
        config["pipeline"]["profiles"] = {"quick": {"stages": ["implement", "test"]}}
        config_path = tmp_path / "agenteam.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        r = run_rt("init", "--task", "profile test", "--profile", "quick", cwd=str(tmp_path))
        assert r.returncode == 0
        run_id = json.loads(r.stdout)["run_id"]

        r = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["profile"] == "quick"

    def test_history_append_lessons_structure(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        lessons = result["lessons"]
        assert "verify_failures" in lessons
        assert "rework_edges" in lessons
        assert "gate_rejections" in lessons
        assert "gate_overrides" in lessons
        assert "final_verify_passed" in lessons
        assert "total_stages" in lessons
        assert "completed_stages" in lessons
        assert "profile_used" in lessons

    def test_history_append_idempotent(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r1 = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r1.returncode == 0
        r2 = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r2.returncode == 0
        # Both should produce identical output
        assert json.loads(r1.stdout)["run_id"] == json.loads(r2.stdout)["run_id"]

    def test_history_append_captures_verify_failures(self, tmp_path):
        run_id = self._init_run(tmp_path)
        # Manually add verify attempts with a failure
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["implement"]["verify_attempts"] = [
            {"attempt": 1, "result": "fail"},
            {"attempt": 2, "result": "pass"},
        ]
        state["stages"]["implement"]["verify_result"] = "pass"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        r = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        failures = result["lessons"]["verify_failures"]
        assert len(failures) == 1
        assert failures[0]["stage"] == "implement"
        assert failures[0]["attempts"] == 2
        assert failures[0]["final_result"] == "pass"

    def _create_synthetic_history(self, tmp_path, count):
        """Helper: create N history entries with distinct IDs."""
        history_dir = tmp_path / ".agenteam" / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        run_ids = []
        for i in range(count):
            rid = f"2026033{i}T{10 + i:02d}0000Z"
            entry = {
                "run_id": rid,
                "task": f"task-{i}",
                "status": "completed",
                "profile": None,
                "stages": [],
                "rework_history": [],
                "lessons": {
                    "verify_failures": [],
                    "rework_edges": [],
                    "gate_rejections": [],
                    "gate_overrides": [],
                    "final_verify_passed": True,
                    "total_stages": 7,
                    "completed_stages": 7,
                    "profile_used": None,
                },
            }
            with open(history_dir / f"{rid}.json", "w") as f:
                json.dump(entry, f)
            run_ids.append(rid)
        return run_ids

    def test_history_list_returns_entries(self, tmp_path):
        self._create_synthetic_history(tmp_path, 3)
        r = run_rt("history", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        entries = json.loads(r.stdout)
        assert len(entries) == 3

    def test_history_list_reverse_chronological(self, tmp_path):
        run_ids = self._create_synthetic_history(tmp_path, 3)
        r = run_rt("history", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        entries = json.loads(r.stdout)
        # Most recent (highest timestamp) first
        assert entries[0]["run_id"] == run_ids[-1]
        assert entries[-1]["run_id"] == run_ids[0]

    def test_history_list_last_n(self, tmp_path):
        self._create_synthetic_history(tmp_path, 5)

        r = run_rt("history", "list", "--last", "2", cwd=str(tmp_path))
        assert r.returncode == 0
        entries = json.loads(r.stdout)
        assert len(entries) == 2

    def test_history_list_empty_when_no_history(self, tmp_path):
        r = run_rt("history", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        entries = json.loads(r.stdout)
        assert entries == []


# ---------------------------------------------------------------------------
# Two-layer config (team + personal)
# ---------------------------------------------------------------------------


class TestTwoLayerConfig:
    """Tests for .agenteam.team/ + .agenteam/ config merge."""

    def _make_team_config(self, tmp_path, config_dict):
        team_dir = tmp_path / ".agenteam.team"
        team_dir.mkdir(parents=True, exist_ok=True)
        config_path = team_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_dict, f)
        return config_path

    def _make_personal_config(self, tmp_path, config_dict):
        personal_dir = tmp_path / ".agenteam"
        personal_dir.mkdir(parents=True, exist_ok=True)
        config_path = personal_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_dict, f)
        return config_path

    def test_team_only(self, tmp_path):
        """Team config only, no personal — works as full config."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "branch",
                "pipeline": {"stages": []},
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "architect" in roles

    def test_personal_only(self, tmp_path):
        """Personal only, no team — backward compatible."""
        make_config(tmp_path)
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        roles = json.loads(r.stdout)
        assert "architect" in roles

    def test_both_merge(self, tmp_path):
        """Team + personal: personal model override applied."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "branch",
                "roles": {"dev": {"model": "team-model"}},
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "roles": {"dev": {"model": "personal-model"}},
            },
        )
        r = run_rt("roles", "show", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        role = json.loads(r.stdout)
        assert role["model"] == "personal-model"

    def test_blocked_override(self, tmp_path):
        """Personal write_scope override is blocked."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "roles": {
                    "dev": {"write_scope": ["src/**"]},
                },
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "roles": {
                    "dev": {"write_scope": ["everything/**"]},
                },
            },
        )
        r = run_rt("roles", "show", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        role = json.loads(r.stdout)
        assert role["write_scope"] == ["src/**"]
        assert "blocked" in r.stderr.lower()

    def test_unknown_role_in_personal(self, tmp_path):
        """Personal config with unknown role emits warning."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "roles": {
                    "mystery_role": {"model": "fast"},
                },
            },
        )
        r = run_rt("roles", "list", cwd=str(tmp_path))
        assert r.returncode == 0
        assert "unknown role" in r.stderr.lower() or "mystery_role" in r.stderr

    def test_system_instructions_append(self, tmp_path):
        """Personal system_instructions appends, not replaces."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "roles": {
                    "dev": {"system_instructions": "Team instructions."},
                },
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "roles": {
                    "dev": {"system_instructions": "Personal addendum."},
                },
            },
        )
        r = run_rt("roles", "show", "dev", cwd=str(tmp_path))
        assert r.returncode == 0
        role = json.loads(r.stdout)
        instructions = role.get("system_instructions", "")
        assert "Team instructions." in instructions
        assert "Personal addendum." in instructions

    def test_allow_personal_override_escape_hatch(self, tmp_path):
        """Team allows personal isolation override via escape hatch."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "branch",
                "allow_personal_override": ["isolation"],
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "worktree",
            },
        )
        r = run_rt(
            "branch-plan",
            "--task",
            "t",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["mode"] == "worktree"

    def test_validate_uses_merged(self, tmp_path):
        """validate --format diagnostics reflects merged state."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "branch",
                "pipeline": {"stages": []},
            },
        )
        self._make_personal_config(
            tmp_path,
            {
                "version": "2",
                "roles": {"dev": {"model": "fast-model"}},
            },
        )
        r = run_rt(
            "validate",
            "--format",
            "diagnostics",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["valid"] is True
        # Layers info should be present
        layers = data.get("layers")
        assert layers is not None
        assert layers["team_config"] is not None
        assert layers["personal_config"] is not None
        assert layers["effective_source"] == "merged"

    def test_config_hash_effective(self, tmp_path):
        """config_hash changes when either layer changes."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "pipeline": {"stages": []},
            },
        )
        r1 = run_rt("init", "--task", "t1", cwd=str(tmp_path))
        assert r1.returncode == 0
        hash1 = json.loads(r1.stdout)["config_hash"]

        # Change team config
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "isolation": "worktree",
                "pipeline": {"stages": []},
            },
        )
        r2 = run_rt("init", "--task", "t2", cwd=str(tmp_path))
        assert r2.returncode == 0
        hash2 = json.loads(r2.stdout)["config_hash"]
        assert hash1 != hash2

    def test_find_config_fallback_to_team(self, tmp_path):
        """When no personal config, find_config returns team path."""
        self._make_team_config(
            tmp_path,
            {
                "version": "2",
                "pipeline": {"stages": []},
            },
        )
        r = run_rt("validate", cwd=str(tmp_path))
        assert r.returncode == 0


# ---------------------------------------------------------------------------
# Smart stage skipping
# ---------------------------------------------------------------------------


class TestSkippedStatus:
    def _init_run(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "skip test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_pending_to_skipped(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "test",
            "--to",
            "skipped",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["from"] == "pending"
        assert result["to"] == "skipped"

    def test_skipped_is_terminal(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "test",
            "--to",
            "skipped",
            cwd=str(tmp_path),
        )
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "test",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "Invalid transition" in r.stderr

    def test_skipped_does_not_break_dispatched(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_set_stage_field_updates_state(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "set-stage-field",
            "--run-id",
            run_id,
            "--stage",
            "test",
            "--field",
            "skip_reason",
            "--value",
            "docs_only_change",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        # Verify in state file
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert state["stages"]["test"]["skip_reason"] == "docs_only_change"

    def test_resume_excludes_skipped_from_remaining(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        # Mark test as skipped, implement as completed
        state["stages"]["test"]["status"] = "skipped"
        state["stages"]["test"]["skip_reason"] = "docs_only_change"
        state["stages"]["implement"]["status"] = "completed"
        # Make stale
        past = datetime.now(timezone.utc) - timedelta(minutes=15)
        state["last_update"] = past.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        r = run_rt("resume-plan", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "test" not in result["remaining_stages"]
        assert "test" in result["skipped_stages"]
        assert "implement" in result["completed_stages"]
        assert "test" not in result["completed_stages"]

    def test_history_lessons_include_skipped_stages(self, tmp_path):
        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["test"]["status"] = "skipped"
        state["stages"]["test"]["skip_reason"] = "docs_only_change"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        r = run_rt("history", "append", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        skipped = result["lessons"]["skipped_stages"]
        assert len(skipped) == 1
        assert skipped[0]["stage"] == "test"
        assert skipped[0]["reason"] == "docs_only_change"

    def test_report_includes_skip_reason(self, tmp_path):
        run_id = self._init_run(tmp_path)
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        state["stages"]["test"]["status"] = "skipped"
        state["stages"]["test"]["skip_reason"] = "docs_only_change"
        state["stages"]["test"]["skipped_at"] = "2026-04-09T12:00:00Z"
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        r = run_rt("run-report", "--run-id", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        test_stage = [s for s in result["stages"] if s["name"] == "test"][0]
        assert test_stage["status"] == "skipped"
        assert test_stage["skip_reason"] == "docs_only_change"
        assert test_stage["skipped_at"] == "2026-04-09T12:00:00Z"


# ---------------------------------------------------------------------------
# Run observability (v3.0)
# ---------------------------------------------------------------------------


class TestTransitionTimestamps:
    def _init_run(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "timestamp test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_transition_to_dispatched_sets_started_at(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert "started_at" in state["stages"]["implement"]
        assert state["stages"]["implement"]["started_at"].endswith("Z")

    def test_transition_to_dispatched_advances_current_stage(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert state["current_stage"] == "implement"

    def test_transition_to_completed_sets_completed_at(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "completed",
            cwd=str(tmp_path),
        )
        state_path = tmp_path / ".agenteam" / "state" / f"{run_id}.json"
        with open(state_path) as f:
            state = json.load(f)
        assert "completed_at" in state["stages"]["implement"]


class TestStatusProgress:
    def _init_run(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "progress test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_status_progress_returns_compact_view(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        r = run_rt("status", run_id, "--progress", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "elapsed" in result
        assert "current_stage" in result
        assert "stages" in result
        assert result["current_stage"]["name"] == "implement"

    def test_status_progress_includes_last_event(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt("status", run_id, "--progress", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["last_event"] is not None
        assert result["last_event"]["type"] == "run_started"

    def test_status_without_progress_unchanged(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt("status", run_id, cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        # Raw state has stages as a dict, not a list
        assert isinstance(result["stages"], dict)
        assert "run_id" in result

    def test_status_progress_stage_elapsed(self, tmp_path):
        run_id = self._init_run(tmp_path)
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "dispatched",
            cwd=str(tmp_path),
        )
        run_rt(
            "transition",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--to",
            "completed",
            cwd=str(tmp_path),
        )
        r = run_rt("status", run_id, "--progress", cwd=str(tmp_path))
        assert r.returncode == 0
        result = json.loads(r.stdout)
        impl = [s for s in result["stages"] if s["name"] == "implement"][0]
        assert "elapsed" in impl


class TestEventTail:
    def test_event_tail_exits_on_run_finished(self, tmp_path):
        # Create a JSONL file with events including run_finished
        events_dir = tmp_path / ".agenteam" / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        events_file = events_dir / "test-tail.jsonl"
        events = [
            '{"ts":"2026-04-10T12:00:00Z","type":"run_started","run_id":"test-tail","stage":null,"data":{"task":"t","pipeline_mode":"standalone"}}',
            '{"ts":"2026-04-10T12:01:00Z","type":"stage_dispatched","run_id":"test-tail","stage":"implement","data":{"roles":["dev"],"isolation":"branch"}}',
            '{"ts":"2026-04-10T12:02:00Z","type":"run_finished","run_id":"test-tail","stage":null,"data":{"status":"completed"}}',
        ]
        events_file.write_text("\n".join(events) + "\n")

        r = run_rt("event", "tail", "--run-id", "test-tail", cwd=str(tmp_path))
        assert r.returncode == 0
        lines = [line for line in r.stdout.strip().split("\n") if line]
        assert len(lines) == 3
        assert "run_finished" in lines[-1]


# ---------------------------------------------------------------------------
# Prompt build (v3.2)
# ---------------------------------------------------------------------------


class TestPromptBuild:
    def _init_run(self, tmp_path):
        make_config(tmp_path)
        r = run_rt("init", "--task", "prompt build test", cwd=str(tmp_path))
        assert r.returncode == 0
        return json.loads(r.stdout)["run_id"]

    def test_prompt_build_returns_schema(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["schema_version"] == "1"
        assert result["run_id"] == run_id
        assert result["stage"] == "implement"
        assert result["role"] == "dev"
        assert "agent" in result
        assert "task" in result
        assert "prompt_sections" in result
        assert "prompt" in result

    def test_prompt_build_developer_instructions_match_role(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        instructions = result["agent"]["developer_instructions"]
        assert "dev" in instructions.lower()
        assert len(instructions) > 50  # Should have real content

    def test_prompt_build_task_separates_raw_and_effective(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["task"]["raw"] == "prompt build test"
        assert "prompt build test" in result["task"]["effective"]

    def test_prompt_build_prompt_sections_ordered(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        section_ids = [s["id"] for s in result["prompt_sections"]]
        assert section_ids[0] == "developer_instructions"
        assert section_ids[1] == "task"

    def test_prompt_build_artifacts_has_search_paths(self, tmp_path):
        run_id = self._init_run(tmp_path)
        env = make_home_env(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert "search_paths" in result["artifacts"]
        assert len(result["artifacts"]["search_paths"]) > 0

    def test_prompt_build_hotl_graceful_without_plugin(self, tmp_path):
        run_id = self._init_run(tmp_path)
        env = make_home_env(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
            env=env,
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert result["hotl"]["available"] is False

    def test_prompt_build_prompt_is_nonempty_string(self, tmp_path):
        run_id = self._init_run(tmp_path)
        r = run_rt(
            "prompt-build",
            "--run-id",
            run_id,
            "--stage",
            "implement",
            "--role",
            "dev",
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        result = json.loads(r.stdout)
        assert isinstance(result["prompt"], str)
        assert len(result["prompt"]) > 100  # Should have substantial content


# ---------------------------------------------------------------------------
# Non-interactive runner (v3.3)
# ---------------------------------------------------------------------------


class TestRunner:
    def test_parse_codex_args_handles_shell_quoting_and_bare_flags(self):
        from runtime.agenteam.runner import _parse_codex_args

        assert _parse_codex_args('--config model="gpt-5.2" skip-git-repo-check') == [
            "--config",
            "model=gpt-5.2",
            "--skip-git-repo-check",
        ]

    def test_run_missing_codex_binary_fails(self, tmp_path):
        make_config(tmp_path)
        r = run_rt(
            "run",
            "--task",
            "test",
            "--codex-bin",
            "/nonexistent/codex-binary-xyz",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_run_resume_missing_state_fails(self, tmp_path):
        make_config(tmp_path)
        r = run_rt(
            "run",
            "--run-id",
            "nonexistent-run-id",
            "--codex-bin",
            "codex",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0
        assert "not found" in r.stderr

    def test_run_cli_accepts_all_flags(self, tmp_path):
        """Verify the CLI parser accepts all documented flags."""
        make_config(tmp_path)
        # Parse only — will fail at codex binary check, but shouldn't fail at parse
        r = run_rt(
            "run",
            "--task",
            "test task",
            "--profile",
            "quick",
            "--codex-bin",
            "/nonexistent/bin",
            "--codex-args",
            "skip-git-repo-check",
            "--auto-approve-gates",
            "--output-dir",
            str(tmp_path / "out"),
            cwd=str(tmp_path),
        )
        # Should fail at codex binary check, not at arg parsing
        assert r.returncode != 0
        assert "not found" in r.stderr  # codex binary error, not parse error

    def test_run_role_uses_stdin_prompt_and_normalized_codex_args(self, tmp_path, monkeypatch):
        from runtime.agenteam import runner

        captured = {}

        monkeypatch.setattr(runner, "build_prompt", lambda *args, **kwargs: {"prompt": "hello"})
        monkeypatch.setattr(runner, "_emit_event", lambda *args, **kwargs: None)

        def fake_run(cmd, input, capture_output, text, cwd, timeout):
            captured["cmd"] = cmd
            captured["input"] = input
            return subprocess.CompletedProcess(cmd, 0, '{"type":"turn.completed"}', "")

        monkeypatch.setattr(runner.subprocess, "run", fake_run)

        result = runner._run_role(
            run_id="run-123",
            stage="research",
            role_name="researcher",
            config={},
            codex_bin="codex",
            codex_args=runner._parse_codex_args("skip-git-repo-check"),
            output_dir=tmp_path,
            events_file=tmp_path / "events.jsonl",
        )

        assert captured["cmd"] == [
            "codex",
            "exec",
            "--json",
            "--full-auto",
            "--skip-git-repo-check",
        ]
        assert captured["input"] == "hello"
        assert result["exit_code"] == 0

    def test_run_no_task_fails(self, tmp_path):
        make_config(tmp_path)
        r = run_rt(
            "run",
            "--codex-bin",
            "codex",
            cwd=str(tmp_path),
        )
        assert r.returncode != 0

    def test_run_creates_output_directory(self, tmp_path):
        """Test that _setup_output_dir creates the directory."""
        from runtime.agenteam.runner import _setup_output_dir

        out = _setup_output_dir(str(tmp_path / "custom-out"), "test-run")
        assert out.exists()
        assert out == tmp_path / "custom-out"
