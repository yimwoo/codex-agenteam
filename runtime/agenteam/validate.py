"""Config validation summary with no side effects."""

import json
import sys

from .config import load_config_layers, resolve_team_config
from .roles import resolve_roles
from .schema import validate_schema
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

    pipeline_dict = config.get("pipeline", {})
    profiles = pipeline_dict.get("profiles", {}) if isinstance(pipeline_dict, dict) else {}

    # Run structured validation with cross-reference checks
    schema_result = validate_schema(config, resolved_roles=roles)

    output_format = getattr(args, "format", "summary") or "summary"
    strict = getattr(args, "strict", False)

    if output_format == "diagnostics":
        result = schema_result.to_dict()
        result["pipeline_mode"] = summary_pipeline_mode
        result["isolation_mode"] = isolation_mode
        result["role_count"] = len(roles)
        result["stage_count"] = len(stages)
        result["profile_count"] = len(profiles)
        # Include config layer provenance
        try:
            cfg_arg = getattr(args, "config", None) or None
            layers = load_config_layers(cfg_arg)
            result["layers"] = layers
        except (FileNotFoundError, ValueError):
            result["layers"] = None
        print(json.dumps(result))
    else:
        # Backward-compatible summary format
        result = {
            "valid": schema_result.valid,
            "pipeline_mode": summary_pipeline_mode,
            "isolation_mode": isolation_mode,
            "role_count": len(roles),
            "stage_count": len(stages),
            "profile_count": len(profiles),
            "errors": [d.message for d in schema_result.errors],
            "warnings": [d.message for d in schema_result.warnings],
        }
        print(json.dumps(result))

    if not schema_result.valid:
        sys.exit(1)

    if strict and schema_result.warnings:
        print(
            json.dumps({"error": f"--strict: {len(schema_result.warnings)} warning(s) found"}),
            file=sys.stderr,
        )
        sys.exit(1)
