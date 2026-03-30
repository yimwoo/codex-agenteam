"""Config validation summary with no side effects."""

import json

from .config import resolve_team_config
from .roles import resolve_roles
from .state import get_pipeline_stages


def cmd_validate(args, config: dict) -> None:
    """Validate config and return a small summary without creating run state."""
    pipeline_mode, isolation_mode = resolve_team_config(config)
    team = config.get("team", {}) if isinstance(config.get("team"), dict) else {}
    legacy_pipeline = team.get("pipeline")
    roles = resolve_roles(config)
    stages = get_pipeline_stages(config)

    # resolve_team_config intentionally collapses legacy standalone/auto/dispatch-only
    # into None for runtime auto-detection. Preserve dispatch-only in the user-facing
    # validation summary so setup tools don't misreport that supported mode.
    if pipeline_mode is None and legacy_pipeline == "dispatch-only":
        summary_pipeline_mode = "dispatch-only"
    else:
        summary_pipeline_mode = pipeline_mode or "standalone"

    result = {
        "valid": True,
        "pipeline_mode": summary_pipeline_mode,
        "isolation_mode": isolation_mode,
        "role_count": len(roles),
        "stage_count": len(stages),
    }
    print(json.dumps(result))
