"""Shared constants and type aliases for the AgenTeam runtime."""

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Type aliases (gradual — used at function boundaries, not strictly enforced)
# ---------------------------------------------------------------------------

ConfigDict = dict[str, Any]
RoleDict = dict[str, Any]
StateDict = dict[str, Any]

# ---------------------------------------------------------------------------
# Valid enum values
# ---------------------------------------------------------------------------

VALID_PIPELINES = {"standalone", "hotl", "dispatch-only", "auto"}  # legacy
VALID_WRITE_MODES = {"serial", "scoped", "worktree"}  # legacy
VALID_ISOLATION = {"branch", "worktree", "none"}
VALID_VERSIONS = {"1", "2"}
VALID_GATE_TYPES = {"auto", "human", "reviewer", "qa"}
VALID_FINAL_VERIFY_POLICIES = {"block", "warn"}
VALID_REASONING_EFFORT = {"low", "medium", "high"}
KNOWN_TOP_LEVEL_KEYS = {
    "version",
    "isolation",
    "pipeline",
    "roles",
    "team",
    "final_verify",
    "final_verify_policy",
    "final_verify_max_retries",
    "allow_personal_override",
}

# Two-layer config: personal override allowlist (role-level fields)
PERSONAL_OVERRIDE_ALLOWLIST = {"model", "reasoning_effort", "system_instructions"}

# Role-level fields that are NEVER personally overridable
NON_OVERRIDABLE_ROLE_FIELDS = {"write_scope", "can_write"}

# Directory names
TEAM_CONFIG_DIR = ".agenteam.team"
PERSONAL_CONFIG_DIR = ".agenteam"

# Map legacy write mode values to new isolation schema
ISOLATION_MAP = {"serial": "branch", "scoped": "none", "worktree": "worktree"}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
ROLES_DIR = PLUGIN_DIR / "roles"
