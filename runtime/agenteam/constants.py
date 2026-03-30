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

# Map legacy write mode values to new isolation schema
ISOLATION_MAP = {"serial": "branch", "scoped": "none", "worktree": "worktree"}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
ROLES_DIR = PLUGIN_DIR / "roles"
